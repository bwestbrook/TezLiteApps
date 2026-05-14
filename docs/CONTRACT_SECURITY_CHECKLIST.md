# Contract Security Checklist

A pattern-based rubric for auditing SmartPy/Michelson entrypoints in
this codebase. Designed to be referenced by Claude Code (or any
reviewer) when writing or reviewing any new `@sp.entrypoint` —
particularly ones that move tez, mutate per-game state, or accept
oracle input.

**How to use:**

When you write or modify an entrypoint, walk down this list and for
each item answer "PASS / N/A / FAIL". If anything is FAIL or unclear,
fix before committing. The first three sections (auth, amount,
storage) catch ~80% of real Tezos security incidents.

The reference fixes for past incidents are in `docs/SECURITY_FIXES.md` —
each rule below cites the case that motivated it, so you can see what
"wrong" looks like.

---

## §1 — Authorization

### §1.1 Every privileged entrypoint asserts `sp.sender`

Any entrypoint that:
- Touches admin-only state (oracle/txl/admin/fee/bounds updates)
- Resolves randomness (oracle-only)
- Settles a game (admin or player-only)

…must start with `assert sp.sender == self.data.<role>, "<reason>"`.

**Example PASS:**
```python
@sp.entrypoint()
def updateFee(self, params):
    assert sp.sender == self.data.admin, "not admin"
    self.data.fee = params.fee
```

**Example FAIL** (no auth check):
```python
@sp.entrypoint()
def updateFee(self, params):
    self.data.fee = params.fee   # anyone can call!
```

### §1.2 The admin key itself must be rotatable

Every contract holding funds needs `updateAdmin(newAdmin)`. The
update path itself is the failsafe if the deployer key is ever
compromised or lost. See AD-4 / PLINKO-6 in `SECURITY_FIXES.md`.

### §1.3 Role checks use the CURRENT storage value, not a cached one

```python
# PASS — re-reads each call
assert sp.sender == self.data.oracle, "not oracle"

# FAIL — caches at __init__, would freeze the oracle address
ORACLE_ADDR = sp.address("tz1...")
assert sp.sender == ORACLE_ADDR, "not oracle"
```

### §1.4 Sender vs. payer

`sp.sender` and `sp.source` differ when one contract calls another.
For human-only entrypoints, prefer `sp.sender`. For entrypoints that
the oracle contract is supposed to call back into (e.g. callbacks),
`sp.sender` is still the right check — it's the *immediate* caller.
Never assert against `sp.source` unless you specifically want to
identify the originating EOA.

---

## §2 — Amount Validation

### §2.1 Entrypoints that take payment MUST validate `sp.amount` exactly

The motivating bug — `AD-1` in `SECURITY_FIXES.md`:

```python
# FAIL — tautology, attaches no constraint on sp.amount
assert sp.amount == sp.amount, "..."

# FAIL — only enforces a floor, not the actual price
assert sp.amount >= self.data.fee, "..."

# PASS — exact match
assert sp.amount == self.data.ante + self.data.fee, "must send ante + fee"

# PASS — range with clear semantics (e.g. Plinko's variable bet)
assert sp.amount >= self.data.minBet, "bet too small"
assert sp.amount <= self.data.maxBet, "bet too big"
```

### §2.2 Mutez arithmetic never goes negative

`sp.mutez` is unsigned. `a - b` where `b > a` raises `SUB_MUTEZ` and
the op reverts. Guard before subtracting:

```python
# FAIL — reverts if reserve is light
self.data.potReserve -= deficit

# PASS — explicit precondition + graceful fallback
assert self.data.potReserve >= deficit, "reserve too low"
self.data.potReserve -= deficit
```

…or, where the goal is to keep settling without bricking the game,
cap the payout at what's available (see PLINKO-2 in `SECURITY_FIXES.md`).

### §2.3 No silent unit confusion

If a parameter is in mutez, type it `sp.mutez`. If it's tez, use
`sp.tez(N)` literals and only mix into mutez via well-named helpers.
Don't let a `params.amount: sp.nat` mean "this number of mutez" by
convention — explicit types only.

---

## §3 — Storage Growth

### §3.1 Every entrypoint that appends to a map must have a counterpart that prunes

Any `self.data.games[k] = ...` / `self.data.rounds[k] = ...` needs an
admin-gated `prune<X>(k)` that removes entries after their terminal
state. See AD-3 / PLINKO-3.

### §3.2 Unbounded inputs are gas-griefing surfaces

If an entrypoint accepts a `sp.list` or `sp.map` from a non-admin
caller, cap the size. The motivating threat: a single op pinning the
mempool by submitting a 10,000-element map.

```python
# PASS — cap at the maximum domain size
count = sp.nat(0)
for _ in params.values.keys():
    count += 1
assert count <= 17, "too many entries"
```

If the entrypoint is admin-only, document the size assumption in a
comment so a future admin-multi-sig change doesn't open the door.

### §3.3 Empty maps must be type-cast at `__init__`

```python
# FAIL — SmartPy fails with "unknown type variable"
self.data.games = {}

# PASS
self.data.games = sp.cast({}, sp.map[sp.nat, sp.record(...)])
```

This bit TTT (`TTT-1`); also bit Plinko in an earlier revision.

---

## §4 — Reentrancy & Call Ordering

### §4.1 Update state BEFORE sending tez out

Tezos doesn't have Ethereum-style synchronous reentrancy (calls are
deferred to end-of-tx), but writing state first is still defense in
depth:

```python
# PASS — record settled, THEN pay out
self.data.games[gid].gameStatus = 3
sp.send(winner, payout)

# FAIL — send first, then record
sp.send(winner, payout)
self.data.games[gid].gameStatus = 3
```

### §4.2 Don't trust callbacks to be benign

When you `sp.transfer(record, amount, callbackContract)`, the callee
runs *after* your op (deferred). If your contract emits a callback
and then does more state changes, those changes happen AFTER the
external code returns. Don't structure logic around the callback
having already run.

### §4.3 No raw `sp.contract` lookups for external dependencies

Use `sp.contract(...).unwrap_some(error="…")` (or `.open_some()`),
never bare. A missing entrypoint or wrong type silently failing
during a callback can leave the game in a half-settled state.

---

## §5 — Arithmetic Safety

### §5.1 Divisions never hit zero

`sp.split_tokens(amount, num, den)` panics if `den == 0`. Guard or
structure so `den > 0` by construction.

```python
# PASS — spread > 0 by branch condition (lowCard < cardValue < highCard
# implies spread >= 1)
assert highCard > lowCard, "invalid bounds"
spread = sp.as_nat(highCard - lowCard - 1)
```

### §5.2 Off-by-one near range boundaries

The AD pair-detection off-by-2 bug (storage `+2` shift vs. raw
`cardValue` compare) bit us in March 2026 — a card and its 11-rank
sibling registered as a pair. Whenever an entrypoint compares two
fields that *should* be in the same unit space, **explicitly state
in a comment what the units are**:

```python
# All ranks in [2, 14] (face value). handValue[1..3] also stored as
# face value (= cardValue + 2). Comparisons must be face-vs-face.
spread = highCard - lowCard - 1  # both face value → spread in [0, 12]
```

### §5.3 `sp.as_nat` only converts proven-non-negative ints

If you `sp.as_nat(x - y)` and there's any path where `x < y`, you'll
panic. Add an `assert x >= y` first, or use `sp.is_nat(x - y).open_some(error=...)`.

---

## §6 — Randomness & Oracle Trust

### §6.1 Document the trust model explicitly

If an entrypoint accepts a value from `self.data.oracle` and that
value is the only thing standing between a player and a payout, the
contract's trust model is "this single key is honest". Say so in a
comment near the entrypoint:

```python
# TRUST MODEL: a malicious oracle can pick `bits` to favor specific
# players. The seed parameter is for audit, NOT for randomness-as-
# fairness. See docs/ORACLE_INTEGRATION.md §Auditability.
```

### §6.2 Replay-proof oracle calls

If the oracle's payload is independent of the on-chain state (e.g.
just a random nat), an attacker who captured one oracle signature
could replay it on a future round. Mitigations:
- Bind to the requestId (the AD/Plinko/TTT pattern — entrypoints
  take `gameId`/`roundId` and the contract enforces state machine
  transitions).
- Include a per-request commit hash (the v2 commit-reveal scheme).

### §6.3 Don't use timestamp / hash / address / exchange rate as a
"random" source

The Tezos randomness doc is canonical
(https://docs.tezos.com/developing/security/randomness). All of these
are biasable.

---

## §7 — Game-Logic Defense

### §7.1 Validate "coordinate" / "id" parameters before lookup

```python
# FAIL — out-of-range params.move panics
g.grid[params.move] == 0

# PASS
assert g.grid.contains(params.move), "invalid move coord"
g.grid[params.move] == 0
```

This bit TTT (`TTT-2`). Same applies to slot indices, row indices,
card values — anywhere the contract reads a map by a player-provided key.

### §7.2 Validate state-machine transitions

Every entrypoint that advances game state must check the current
state with `assert g.gameStatus == EXPECTED, "..."`. The motivating
bug class: a player calling `secondCard` on a game still at status 0
and ending up with `hand[1] == -1`.

### §7.3 Settlement is idempotent or one-shot

A function like `lastCard` that pays out must transition to a
terminal state (3/4/5) atomically. Re-entering it on the same game
must fail with `"bad game Status"`.

### §7.4 Don't use contract-level fields as per-call scratch

```python
# FAIL — gameWon, setSum lives on `self.data`, costs storage and
# leaks cross-call state if a tx ever splits into sub-ops.
self.data.gameWon = 0
self.data.setSum = 0

# PASS — local variables
gameWon = sp.int(0)
setSum = sp.int(0)
```

This bit TTT (`TTT-3`).

---

## §8 — Gas / Resource Constraints

### §8.1 Bound any loop's iteration count

```python
# FAIL — iterates 75 win-sets every move
for ws in self.data.game_winners.values():
    ...

# PASS — index lookup to ~9 sets touching the placed cell
for setIdx in self.data.cell_to_winsets[params.move]:
    ws = self.data.game_winners[setIdx]
    ...
```

See TTT-4 in `SECURITY_FIXES.md`.

### §8.2 Big map vs. map

For maps that grow unbounded (e.g. all-time games index), use
`sp.big_map` instead of `sp.map`. Big maps are lazy-loaded so reading
one key doesn't pay for the rest. For small bounded maps (winDict,
multipliers, initialBoard) regular `sp.map` is fine.

### §8.3 Emit events for off-chain indexers

Anywhere off-chain code (oracle worker, UI, audit script) needs to
know about an outcome, emit it: `sp.emit(payload, tag='eventName')`.
Don't make watchers diff storage to learn what happened.

---

## §9 — Cross-Contract Wiring

### §9.1 Update inter-contract addresses via admin entrypoints, never
hardcoded redeploys

Every contract that references another (`txlContract`, `adContract`,
`oracleContract`, etc.) must expose an admin-gated `update<X>` that
takes the new address. Hardcoding means a future address change
requires a full redeploy — annoying — and worse, contracts that
reference *each other* form a redeploy cascade.

### §9.2 The address-resolution side (UI / worker / scripts) reads
from `src/constants.js`

Never hardcode a `KT1...` in JS / Python — always import from
`src/constants.js`. The deploy script patches that file
automatically; consumers stay in sync.

---

## §10 — Off-Chain Integration

### §10.1 The oracle worker must be deterministic given storage

`oracle_worker.py`'s `decide()` function (per-game handler) should be
a pure function from storage → list of Actions. No external state,
no clock-dependent behavior. Tests can call it directly without RPC.

### §10.2 Auth check fails should drop the handler, not the worker

If one game's storage.oracle is misconfigured, the worker should
warn + skip that handler, not exit. Other contracts keep being served.

### §10.3 Idempotent submission

`adapter.submit(action)` must be safe to call twice (e.g. on retry
after a network blip). Either the contract rejects re-submission via
state-machine guards (`assert g.gameStatus == 0`), or the worker
de-dupes via op-hash tracking.

---

## §11 — Frontend / UI Trust

### §11.1 Never trust contract storage for what the player CAN do

The UI shows buttons based on chain state ("DROP BALL is enabled
because wallet is connected + pot is healthy"), but the actual
preventing is on chain. UI guards are UX, not security.

### §11.2 Show the exact entrypoint params before signing

Beacon shows the user what they're signing. Make sure the dApp logs
the entrypoint + args to the console pre-`.send()` so debugging is
easy. The aceyDuecey/plinkoGame components already do this — keep
the pattern.

### §11.3 Sanitize seed / hash strings rendered into HTML

Oracle-supplied strings come from random hex but are still attacker-
controllable if the oracle is compromised. Render with text bindings
(`{{ seed }}`), never `v-html`.

---

## §12 — Operational

### §12.1 Per-fix commit hygiene

One security fix per commit, message format
`fix(<contract>): <one-line summary>`. The audit log reads cleanly
and reverts are surgical.

### §12.2 Redeploy implies a re-exercise

After redeploying, run `scripts/exercise_contracts.py --game <id>`
on shadownet before announcing the new address. The harness exits 0
on full happy-path success; treat that as the merge gate.

### §12.3 Oracle key rotation cadence

Rotate the `self.data.oracle` key on each contract at least quarterly
(or after any operational incident on the worker machine). See
`docs/SECURITY_FIXES.md` §XC-3 for the helper script outline.

---

## Reviewer's worksheet

For a NEW entrypoint, copy this skeleton into the commit description
and fill in:

```
## Security review

§1.1 Auth check on sender:           [PASS/FAIL/N/A] — <which role>
§2.1 sp.amount exactly validated:    [PASS/FAIL/N/A] — <expected value>
§2.2 No silent SUB_MUTEZ underflow:  [PASS/FAIL/N/A]
§3.1 Map growth bounded or pruned:   [PASS/FAIL/N/A]
§3.3 Empty maps type-cast:           [PASS/FAIL/N/A]
§4.1 State before sp.send:           [PASS/FAIL/N/A]
§5.1 No /0 divisions:                [PASS/FAIL/N/A]
§5.2 Units explicit in comments:     [PASS/FAIL/N/A]
§6.1 Trust model stated:             [PASS/FAIL/N/A]
§7.1 Player params validated:        [PASS/FAIL/N/A]
§7.2 State-machine transition gated: [PASS/FAIL/N/A]
§8.1 Loop iteration bounded:         [PASS/FAIL/N/A]
§8.3 Events emitted for indexers:    [PASS/FAIL/N/A]
§9.1 Cross-contract addr is update-able: [PASS/FAIL/N/A]

Risk summary: <one paragraph>
```

If you can answer PASS or N/A to every line, the entrypoint is
mergeable. Anything else gets a fix-or-justify treatment.

---

## Tying it together

When you (or Claude Code) write a new entrypoint:

1. Sketch the entrypoint.
2. Walk down §1 → §11 ticking each rule. Anything ambiguous, comment
   in the source: `# SECURITY: §6.1 — trust model: oracle picks slot`.
3. Open the worksheet block in your commit message. Fill it out
   honestly.
4. If any FAIL, fix or escalate.
5. Run the contract through `python <file>.py` to verify it compiles.
6. Add a scenario to `scripts/exercise_contracts.py` exercising the
   new entrypoint's happy path AND at least one failure path
   (`assert ... FAIL`).
7. Commit with the §XX worksheet in the message.

This way every contract change passes through the same lens.
