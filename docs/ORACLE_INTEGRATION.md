# RandomOracle Integration Guide (v3 — commit-reveal)

A drop-in trustless randomness service for Tezos dApps. v3 replaces v2's
"trust the operator's key" model with a commit-reveal scheme + caller-
contributed entropy, so an adversarial operator can be detected (and
slashed by anyone watching the chain). See docs/V3_COMMIT_REVEAL.md for
the full cryptographic spec.

- **Mainnet address**: _TBD — populated after first mainnet deploy_
- **Shadownet address**: see `ORACLE_CONTRACT_SHADOWNET` in `src/constants.js`
- **Fee**: read live from `oracle.storage().fee` — currently `0.1 ꜩ`
- **Caps**: 1 to 32 random values per request; each in `[0, maxValue]`
- **Status**: experimental; integrations welcome

## How it works

```
                                                ┌──────────────────┐
              every N blocks                    │   RandomOracle   │
              ────────────────                  │   v3 (KT1…)      │
              ┌──────────┐                      │                  │
              │ off-chain│ ── postCommit ─────▶ │  commitLog[C] =  │
              │  oracle  │                      │  (hash, level,   │
              │  worker  │                      │   '0x')          │
              └──────────┘                      │                  │
                   ▲                            │  requests[R] =   │
                   │ revealCommit               │  (callback,      │
                   │                            │   nRandoms,      │
                   │                            │   userNonce,     │
┌─────────────────┐│ ── requestRandom ────────▶ │   commitId,      │
│ your contract   ││    (forwards player's      │   callbackContext│
│ + UI            ││     userNonce + commitId)  │   …)             │
│                 ││                            │                  │
│ onRandomFulfilled│◀── (callback invoked) ──── │  derives values  │
└─────────────────┘ │   with (requestId,        │  via finalSeed = │
                    │   randomValues,           │  sha256(preimage │
                    │   callbackContext)        │  ||userNonce||R) │
                    │                            └──────────────────┘
                                                         ▲
                                                         │ fulfillRandom
                                                         │ (PERMISSIONLESS)
                                                  ┌──────────────────┐
                                                  │ anyone (worker   │
                                                  │ does it as a     │
                                                  │ bridge for       │
                                                  │ latency)         │
                                                  └──────────────────┘
```

Three phases:

1. **Commit** (rolling, oracle-driven).  Every ~N blocks the off-chain
   worker posts `sha256(preimage)` to `commitLog`. Each commit is sealed
   — the preimage stays in the worker's local journal until reveal time.
2. **Request.**  Your contract calls `requestRandom` with the player's
   32-byte `userNonce`, a `commitId` that's already on chain and at least
   `minCommitAge` blocks old, and an opaque `callbackContext` you'll
   receive back in the callback.
3. **Reveal + fulfill.**  Worker calls `revealCommit(commitId, preimage)`;
   the contract verifies `sha256(preimage) == hash`.  Then ANYONE can
   call `fulfillRandom(requestId)`, which deterministically computes
   the values from on-chain inputs alone and invokes your callback.

If your callback fails, the whole fulfillment op reverts and the request
stays pending — make sure your callback can't revert under normal
conditions.

## Contract interface

### `requestRandom`

```
%requestRandom record (
  callback         : address;       // your KT1 — must expose onRandomFulfilled
  nRandoms         : nat;           // 1..32
  maxValue         : nat;           // each value in [0, maxValue] inclusive
  userNonce        : bytes;         // 32 bytes recommended — player entropy
  commitId         : nat;           // existing, age-eligible, unrevealed
  callbackContext  : bytes;         // echoed back in the callback
)
```

Attach `sp.amount >= oracle.fee`. Anything above the fee is also
collected by the operator (a tip).

| Param | Why it's there |
|-------|----------------|
| `userNonce` | Mixes into `finalSeed` so the oracle's commit choice can't favor any specific request. The oracle didn't know what nonce you'd attach when it committed. |
| `commitId` | Binds this request to a still-sealed commit. The dApp queries `oracle.storage().commitLog` and picks the newest unrevealed commitId whose `postedAtBlock <= sp.level - minCommitAge` (so it was visible on chain before the player's signing op). |
| `callbackContext` | Opaque bytes echoed back to your callback. Lets you correlate the response with your own state (gameId + phase, roundId, etc.) without having to read the oracle's auto-incremented requestId at submit time. |

### Your callback entrypoint

**Must be named exactly `onRandomFulfilled`** — SmartPy requires a
compile-time string literal for `sp.contract(..., entrypoint=…)`, so the
oracle invokes a hardcoded name. Signature:

```python
@sp.entrypoint
def onRandomFulfilled(self, params):
    sp.cast(params.requestId, sp.nat)
    sp.cast(params.randomValues, sp.list[sp.nat])
    sp.cast(params.callbackContext, sp.bytes)
    assert sp.sender == self.data.oracleContract, "not oracle"
    # unpack callbackContext to dispatch:
    ctx = sp.unpack(params.callbackContext, sp.record(gameId=sp.nat, phase=sp.nat)).unwrap_some(...)
    # ... use params.randomValues, dispatch on ctx ...
```

**Always assert `sp.sender == oracleContract`** — without it, anyone
could spoof a result.

### Events you can index

- `commitPosted` — `{commitId, hash, postedAtBlock}`
- `commitRevealed` — `{commitId, preimage}`
- `randomRequested` — `[requestId, nRandoms, maxValue, commitId]`
- `randomFulfilled` — `{requestId, randomValues}`

## Drop-in example

`src/services/smart_contract_oracle_reference.py` is the ~80-line
CoinFlip dApp that wires up both sides for v3. Compile it via
`./scripts/compile.sh oracle`, deploy via `./scripts/deploy.py oracle
--network shadownet`, then call `flip(userNonce, commitId)` and watch
your contract storage update via the oracle callback in ~30 seconds.

## Cost & latency

- **Gas/storage**: a `requestRandom` op writes one storage row (~150
  mutez storage cost); `fulfillRandom` updates that row, derives values
  on chain via SHA-256 + bytes-to-nat (an 8 kB byte lookup table built
  once at origination keeps the per-call cost bounded), and invokes
  your callback. End-to-end ~0.01 ꜩ in gas on shadownet.
- **Latency**: typically 1–3 blocks. The commit was already on chain
  when you submitted (1 block to confirm your request). The worker
  reveals the bound commit (≤ 1 block of polling) and then calls
  fulfillRandom (1 block to confirm). Mainnet is similar.
- **Reliability**: the worker is a single daemon today. For production
  use cases we recommend either (a) running your own worker against
  the same RandomOracle contract, or (b) waiting for the planned
  multi-operator quorum (see V3 doc §Open TODOs).

## Auditability

The v3 oracle is **trustless-by-construction within the bounds of the
documented threat model**. Every fulfilled request stores enough on-chain
data to let any third party independently re-derive the result:

```
finalSeed   = sha256( preimage  ||  userNonce  ||  pack(requestId) )
value[k]    = bytes_to_nat( sha256(finalSeed || pack(k)) ) mod (maxValue+1)
```

The `preimage` is what `revealCommit` published (verified by the
contract against the committed hash). The `userNonce` is what the
requester attached. The `requestId` is the contract's auto-incremented
counter. All three live in chain storage and are emitted in events.

**Fairness property.**  At commit time the oracle didn't know what
userNonce the next request would carry — so it couldn't search for
preimages that favor any specific request. At request time the bound
commit was already on chain (`postedAtBlock + minCommitAge <= sp.level`)
so its hash was visible to the player before they signed. Neither side
can adaptively pick to favor any outcome.

**What an adversarial operator CAN still do** (see V3 doc §Threat model
for the full enumeration):

  - **Censor specific requests** by refusing to call `revealCommit` for
    a commit it dislikes. This is observable on chain — bound requests
    stuck pending while the commit ages → name + slash the operator.
  - **Cause griefing** by withholding commits altogether (no fresh
    `commitId` for new requests). Same observability + remedy.

**What an adversarial operator CANNOT do:**

  - Pick *any* result after seeing the request. The reveal must match
    the committed hash; the value is then fully determined by inputs
    the operator can't change post-commit.
  - Pre-compute a preimage that favors specific player nonces. At
    commit time it doesn't know what nonce will bind.
  - Re-bind a request to a different commit. Once `requestRandom`
    succeeds, the commitId is immutable on the request record.

If a single oracle key is compromised, the worst the attacker can do is
*censor* (which is loud) or *substitute a tampered preimage* (which the
contract's `sha256(preimage) == hash` assertion rejects). They cannot
bias a game's outcome in their favor.

For applications that need an even stronger guarantee — explicit
defense against a malicious-operator-with-bias-budget across many
requests — see V3 doc §Saturation attack and §Open TODOs (multi-operator
quorum).

## Running your own worker

If you don't trust the default operator (fair), point a copy of
`scripts/oracle_worker.py` at the same RandomOracle contract. The worker
has two coordinated handlers:

```bash
# Commits + reveal + fulfill bridge (the full v3 daemon)
./scripts/oracle-worker.sh --game oracle-committer --network shadownet
./scripts/oracle-worker.sh --game randomness       --network shadownet

# Or run both at once with --game all (the default)
./scripts/oracle-worker.sh
```

You'll need:
- A funded tz1 key matching `oracle.storage().oracle` (for postCommit /
  revealCommit; fulfillRandom is permissionless and any key can do it)
- Python 3.10+ with pytezos installed
- An always-on machine

The commit-reveal preimages are persisted to
`~/.tezliteapps/commits-<network>.json` so a worker restart doesn't
strand any pending commits. Encrypt the file at rest if your operator
machine is shared — leaking the journal lets an attacker pre-compute
finalSeeds for any bound requests in the leak window.

## Questions / bug reports

Open an issue on the TezLiteApps repo or DM `@jamin_b` on
Telegram/Discord. Fee revenue from your contract's usage helps fund
ongoing oracle uptime.
