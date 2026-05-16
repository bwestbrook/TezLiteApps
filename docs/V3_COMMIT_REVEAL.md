# RandomOracle v3 — Commit-Reveal with User-Contributed Entropy

This document is the design spec for the v3 randomness layer. v2 trusted
the oracle key to pick fair values; v3 removes that trust by combining
THREE independent inputs into the final seed, none of which any single
party controls.

```
finalSeed = sha256( preimage  ||  userNonce  ||  pack(requestId) )
```

  - `preimage`  : revealed by the oracle AFTER the request was bound to
    a commit. The preimage MUST hash to a value the oracle published
    BEFORE the request, so the oracle has no degrees of freedom at
    reveal time.
  - `userNonce` : 32 bytes the player attaches at request time. Defeats
    any attempt by the oracle to pre-compute favorable preimages, because
    the oracle didn't know `userNonce` when it committed.
  - `requestId` : the contract's monotonic counter. Defeats replay across
    multiple requests bound to the same commit.

Anyone watching the chain can re-derive the final seed and the values,
so disputes are objectively resolvable.

---

## Sequence

```
                  oracle worker            on-chain RandomOracle           player
                  =============            =====================           ======

  every N blocks:
    p = random(32)
    h = sha256(p)
    journal.append(commitId=C, p)
    ─── postCommit(h) ────────────▶  commitLog[C] = (h, level, '')
                                     emit commitPosted

                                                                     prepare op:
                                                                     read oracle.commitLog
                                                                     pick latest C with
                                                                       postedAtBlock ≤ L-1
                                                                       and revealedPreimage==''
                                                                     userNonce = random(32)
                                                                     callbackContext = pack(gameId, phase)

                                     ◀────────── requestRandom(callback, nRandoms,    bet() entrypoint
                                                  maxValue, userNonce, C,             on game contract
                                                  callbackContext)                    forwards request
                                     assert C is age-eligible
                                     assert C not yet revealed
                                     requests[R] = (...,
                                                    commitId=C,
                                                    userNonce,
                                                    callbackContext,
                                                    requestBlock=L)
                                     emit randomRequested(R, n, max, C)

  poll: see commitPosted for C, no    ── revealCommit(C, p) ──▶  assert sha256(p) == h
  reveal yet → wait until any                                    commitLog[C].revealedPreimage = p
  request binds to it → reveal                                   emit commitRevealed

  poll: see randomFulfilled?          ── fulfillRandom(R) ──▶    seed = sha256(p || userNonce || pack(R))
  if not, anyone may call                                        for k in 0..n-1:
  (we do it as a bridge)                                           chunk = sha256(seed || pack(k))
                                                                   value[k] = bytes_to_nat(chunk) mod (maxValue+1)
                                                                 invoke callback.onRandomFulfilled(R, values, ctx)
                                                                 emit randomFulfilled
                                                                                                    ─────────────▶
                                                                                                    game contract
                                                                                                    settles via ctx
```

---

## Threat model

### What an adversarial oracle CAN do, even in v3

  - **Censor specific requests.** The oracle can simply refuse to
    reveal a commit if it dislikes the outcome a given request would
    produce. This is observable on chain (commit posted but never
    revealed; bound requests stuck pending) and the operator can be
    publicly named + rotated by admin. Defense: monitor reveal latency
    per commit and alert on outliers.

  - **Pick which commit to use at reveal time.** No — once a request
    binds to commitId C, the seed is fully determined by `(commit[C].preimage,
    request.userNonce, R)`, all of which are immutable post-binding. The
    oracle's only choice is to reveal-or-not for C as a whole (above
    point). It can't selectively rebind.

  - **Pre-compute preimages and pick favorable ones.** No: the user
    nonce is unknown when the commit is posted, so any pre-computation
    is doing brute-force search over a 256-bit space for an unknown
    target. Computationally infeasible.

### What an adversarial PLAYER can do

  - **Choose `userNonce` adaptively after seeing the commit hash.** Yes,
    but this doesn't help — the player picks a nonce, the contract folds
    it into sha256 with the (still-unknown to player) preimage. The
    player has no way to bias the output of the hash; they could iterate
    over nonces but every nonce produces an unpredictable result until
    the oracle reveals.

  - **Front-run another player's bet to grab a specific commitId.**
    Pointless — every request binds to whichever commit it chooses
    (almost always the latest unrevealed one), and the value depends on
    (preimage, userNonce, requestId). Two different players picking the
    same commitId still get different seeds because their nonces and
    requestIds differ.

### What an adversarial THIRD PARTY can do

  - **Call fulfillRandom for someone else's request after reveal.**
    Yes — this is by design. fulfillRandom is permissionless. The values
    are deterministic from on-chain inputs, so it doesn't matter who
    submits the op. Worst case: a griefer pays gas to settle someone
    else's request (saving the oracle worker a tx).

  - **Forge a preimage to bias a result.** Computationally infeasible —
    they'd need to find a preimage that hashes to a specific committed
    hash AND produces a specific seed when combined with a specific
    user nonce. That's a second-preimage attack on SHA-256.

### Saturation attack (monitored, not enforced on chain)

If one commit binds to a very large number of requests, the oracle
effectively chose a single preimage that determines many outcomes. While
the player nonces still randomize each result individually, an oracle
with a *biased* preimage selection algorithm could in principle steer
its commit choices to favor itself across many games.

The brief calls for **off-chain monitoring** of binding histograms per
commitId rather than on-chain enforcement, to keep the contract simple.
Alert if any single commit binds > N requests (e.g. N=100). The fix
when this fires is to bump the commit posting cadence so fresh capacity
is always available, or to enforce a per-commit binding cap in a v3.1
contract upgrade.

### What happens if the preimage leaks early

If the oracle's local journal at `~/.tezliteapps/commits.json` is
compromised before the oracle reveals, an attacker can compute the seed
for any commit they have the preimage of — but only for *already-bound*
requests, because the attacker still doesn't know what `userNonce` future
players will pick. The attack window is "between commit-post and reveal,
for the specific requests bound during that window."

Mitigations:
  - Don't run the oracle worker on a multi-user machine.
  - Encrypt the journal at rest.
  - Tighten commit cadence so leaked preimages have fewer bound
    requests under them.
  - In a future upgrade, sign the preimage with a hardware key so
    journal exfiltration doesn't yield the raw bytes.

---

## Value-derivation choice

The brief sketches:

  - `value[0] = bytes_to_nat(finalSeed) mod (maxValue+1)`
  - `value[k] = bytes_to_nat(sha256(finalSeed || pack(k))) mod (maxValue+1)` for k≥1

The shipped contract uses a **uniform** variant:

  - `value[k] = bytes_to_nat(sha256(finalSeed || pack(k))) mod (maxValue+1)` for **all** k

**Why:** SmartPy's compile-time `if k == 0:` branching inside an unrolled
loop didn't constant-fold cleanly — the `chunk` variable failed to
resolve. Going uniform (always hash) costs 1 extra SHA-256 per request
(negligible gas) and keeps the loop one straight-line block. Same
security properties — both variants are unbiased to within ~2⁻²⁵⁶ for
any practical maxValue+1.

**Alternative** that was considered:

  - Submit values off-chain and verify by recomputing — fails the
    "permissionless fulfillRandom" requirement because the verification
    step needs bytes→nat too.
  - Push value derivation onto each consumer — viable but burdens every
    integrator to write the same byte-loop. Bad ergonomics.

**bytes→nat helper:** SmartPy 0.21 has no primitive for "interpret 32
bytes as a big-endian nat", so the contract carries a 256-entry byte
lookup table at `__init__` and unrolls a 32-iteration inner loop to
walk each SHA-256 byte. Costs ~8 kB of one-time storage. If a future
SmartPy / Tezos protocol adds a `BYTES_TO_NAT` opcode, this entire
section gets one helper call instead.

---

## Callback API constraint

The oracle invokes the requester's callback via:

```
sp.contract(record_type, callbackAddress, entrypoint="onRandomFulfilled")
```

SmartPy requires the `entrypoint=` argument to be a compile-time string
literal — dynamic strings fail with `sp.contract is undefined or wrong
number of arguments`. **The callback entrypoint name is therefore
hardcoded to `onRandomFulfilled`.** Every integrating contract must
expose:

```python
@sp.entrypoint
def onRandomFulfilled(self, params):
    sp.cast(params.requestId, sp.nat)
    sp.cast(params.randomValues, sp.list[sp.nat])
    sp.cast(params.callbackContext, sp.bytes)
    assert sp.sender == self.data.oracleContract, "not oracle"
    # ... use params.randomValues, dispatch on callbackContext ...
```

`callbackContext` is opaque bytes the integrator stuffs into the
request (typically `pack((gameId, phase))`) and echoes back in the
callback. This sidesteps the "how does the game know its requestId at
submit time" problem — the integrator doesn't need to read the oracle's
auto-incremented counter; it just packs whatever state it needs to
correlate the response.

---

## Migration plan from v2

The v3 contract is **not** storage-compatible with v2. The migration is
a one-shot redeploy:

  1. Deploy the new oracle contract; capture its KT1 address.
  2. Update `ORACLE_CONTRACT_SHADOWNET` in `src/constants.js`.
  3. Redeploy each game contract (AD, Plinko, TTT) — they now embed
     calls to the oracle and need the new address in their storage.
  4. Restart `oracle_worker.py` with the new commit + reveal loops.
  5. The old v2 contract becomes inert; its pending requests (if any)
     will never be fulfilled. Drain them via v2's admin path before
     swap-over, OR accept that v2 was experimental and any orphaned
     requests are dust.

There is **no in-place upgrade** path. Tezos contracts are immutable;
v3 lives at a new address.

---

## Off-chain monitoring (what the operator should watch)

  - **Reveal latency.** Time between `commitPosted` and `commitRevealed`.
    Median should be ≤ 5 blocks; outliers ≥ 60 blocks suggest the
    worker is stuck or the oracle key is being held back.

  - **Per-commit binding count.** Histogram of how many requests bind
    to each commitId. Alert if any single commit binds more than N
    requests (default N=100). See "Saturation attack" above.

  - **Per-commit derived-value distribution.** For Plinko-style
    boolean outputs, histogram of finalX/finalZ per commitId. A commit
    showing strong bias (e.g. >75% one-side) across many requests is
    a fingerprint of preimage tampering OR a flagrant oracle key
    compromise.

  - **Unrevealed-commit age.** Any commit with bound requests and
    `revealedPreimage == ''` for more than M blocks (default M=20) is
    a censorship signal. Page the operator.

  - **Fulfillment latency.** Time between `commitRevealed` (commit
    becomes fulfillable) and the actual `randomFulfilled` event for
    each bound request. Should be ≤ 2 blocks for the worker's own
    bridge; longer means the worker is overloaded.

The grafana dashboards live at `grafana.internal/d/oracle-v3` (TBD —
build alongside the first mainnet deploy).

---

## Open TODOs (deferred from initial v3 ship)

  - **On-chain saturation cap.** Add `maxBindingsPerCommit` to oracle
    storage; requestRandom asserts `commitLog[C].bindingCount < cap`.
    Trades contract complexity for explicit defense vs. the saturation
    attack — currently we trust off-chain monitoring.

  - **Cancel pending request after timeout.** A requester whose bound
    commit is never revealed has no recovery path today. Add
    `cancelRequest(requestId)` requester-gated, claimable after the
    bound commit is N blocks old without reveal, refunding feePaid.

  - **Multi-operator quorum.** Have *several* oracle keys post commits;
    a request binds to a commit from a randomly-rotated subset and the
    final seed mixes preimages from k-of-n revealers. Properly removes
    the single-key trust assumption. Significantly more design work —
    out of scope for this commit batch.

  - **Hardware-key signing for preimages.** Today the worker's local
    journal is a flat-file disk artifact. A YubiKey-stored signing key
    that releases a signature over the preimage would prevent
    journal-exfiltration attacks even if the worker host is compromised.
