# TezLiteApps — Security Fix Backlog

This document lists every issue surfaced in the May 2026 security audit of
`smart_contractAD.py`, `smart_contractPlinko.py`, and `smart_contract_TTT.py`,
plus the cross-cutting items applicable to all three.

**For Claude Code (or any human working through this):**

- Work through items in the listed order. Higher-numbered fixes assume
  earlier ones are in place.
- Every fix has: (a) the exact file + region to edit, (b) the proposed
  before/after, (c) why, (d) an acceptance test you can run with
  `scripts/exercise_contracts.py`.
- After each fix, run the compile (via `pip install smartpy-tezos`'s
  `python <contract>.py`), copy the produced `.tz` + `.json` into
  `contracts/<id>/`, redeploy via `./scripts/deploy.py <id> --network shadownet`,
  and exercise via `.venv/bin/python scripts/exercise_contracts.py --game <id>`.
- Commit per fix with `git commit -m "fix(<contract>): <summary>"` so the
  history reads as a clean security-fix sequence.
- Don't bundle multiple fixes into one commit unless they're trivially
  dependent (e.g. "add `updateAdmin` AND wire it into the UI").

The fixes are grouped by contract and ordered HIGH → MED → LOW within each.
The Plinko commit-reveal redesign is at the end as its own section because
it's a v2-shape change, not a hotfix.

---

## Status

The hotfix batch — AD-1, AD-1.5, AD-2, AD-3, AD-4, PLINKO-2..6,
TTT-1..6, XC-1/2/3 — has been implemented and compile-verified locally
(`./scripts/compile.sh <contract> --no-deploy`), one commit per fix in
`fix(<contract>): …` form. The TTT contract additionally has an in-file
play-through test covering the win path, invalid-move rejection, and
claim-by-timeout.

**Still required before this is live** (see the Verification matrix at
the bottom):

- Redeploy each changed contract to shadownet, copy artifacts into
  `contracts/<id>/`, restart the oracle worker.
- Run `scripts/exercise_contracts.py --game {ad,plinko,ttt}` against
  the redeployed addresses.
- The human-only sanity checks (AD pair handling, Plinko payout math,
  TTT timeout window).

AD-5 and PLINKO-1 are intentionally **not** in this batch — they are
v2 commit-reveal work (see the redesign section at the bottom).

---

## AD (`src/services/smart_contractAD.py`)

### AD-1 [HIGH] — `bet()` tautology lets caller underpay the ante

**File**: `src/services/smart_contractAD.py`, inside the `bet` entrypoint
(around line 65-70 of the SmartPy source).

**Find**:

```python
@sp.entrypoint()
def bet(self, params):
    '''
    '''
    amount = self.data.ante + self.data.fee
    assert sp.amount == sp.amount
    sp.cast(sp.sender, sp.address)
```

The assertion `sp.amount == sp.amount` is a tautology. Caller can attach
any amount ≥ fee and still create a game.

**Replace with**:

```python
@sp.entrypoint()
def bet(self, params):
    '''
    Player creates a game by paying ante + fee.
    '''
    sp.cast(params.aceHigh, sp.int_or_nat)
    sp.cast(sp.sender, sp.address)
    sp.cast(sp.amount, sp.mutez)
    assert sp.amount == self.data.ante + self.data.fee, "must send ante + fee"
```

You can also delete the now-unused `amount = self.data.ante + self.data.fee`
line above the assert.

**Acceptance**: after redeploy, calling `bet(1)` with `0.15 ꜩ` must fail
with `"must send ante + fee"`. Only `0.3 ꜩ` (ante 0.2 + fee 0.1) succeeds.
The `--game ad` scenario in `scripts/exercise_contracts.py` already sends
exactly `0.3 ꜩ` and should still pass. (Note: the in-file `test()`
scenario's `tzMutezBet` was bumped from `250000` to `300000` for the
same reason — `bet()` now rejects anything but the exact price.)

---

### AD-1.5 [HIGH] — `updateOracle` / `updateTxlContract` wired to the wrong field + gate

**File**: `src/services/smart_contractAD.py`, the admin section.

Surfaced while implementing AD-1, not in the original audit list.
`updateOracle` wrote to `self.data.txlContract` (not
`self.data.oracle`), so the AD oracle key could **never** actually be
rotated — which silently undermines AD-4 and checklist §9.1.
`updateTxlContract` was gated on `self.data.oracle` instead of
`self.data.admin`. Both used `if sp.sender == …:` rather than `assert`,
so an unauthorized call was a silent no-op instead of a hard failure.

**Find**:

```python
@sp.entrypoint()
def updateTxlContract(self, params):
    if sp.sender == self.data.oracle:
        self.data.txlContract = params.newContract

@sp.entrypoint()
def updateOracle(self, params):
    if sp.sender == self.data.admin:
        self.data.txlContract = params.newContract
```

**Replace with**:

```python
@sp.entrypoint()
def updateTxlContract(self, params):
    assert sp.sender == self.data.admin, "not admin"
    self.data.txlContract = params.newContract

@sp.entrypoint()
def updateOracle(self, params):
    assert sp.sender == self.data.admin, "not admin"
    self.data.oracle = params.newOracle
```

This is the same bug class the TTT rewrite already called out in its
header changelog ("Fixed updateOracle — used to write to txlContract
under an oracle gate"). Checklist §1.1, §1.3, §9.1.

**Acceptance**: redeploy. `updateOracle(newOracle=tz1other…)` from the
admin key must actually change `storage.oracle` (poll it); a
subsequent oracle-gated call from the OLD oracle key must fail.
`updateTxlContract` must fail for any sender other than the admin.

---

### AD-2 [MED] — Pot auto-refill can brick `lastCard`

**File**: `src/services/smart_contractAD.py`, near the end of `lastCard`.

**Find**:

```python
sp.emit(self.data.pot)
if self.data.pot < sp.mutez(124999):
    self.data.pot += sp.mutez(125000)
    self.data.potReserve -= sp.mutez(125000)
```

If `potReserve < 125000 mutez`, `SUB_MUTEZ` panics → entire `lastCard` op
reverts → game stuck at status 2 forever.

**Replace with**:

```python
sp.emit(self.data.pot, tag='postSettlePot')
if self.data.pot < sp.mutez(124999) and self.data.potReserve >= sp.mutez(125000):
    self.data.pot += sp.mutez(125000)
    self.data.potReserve -= sp.mutez(125000)
```

**Acceptance**: redeploy with reserve = 0, run `--game ad` to settlement.
Game must reach status 3/4/5 without reverting at the refill step.

---

### AD-3 [MED] — `pruneGame` admin entrypoint to bound storage growth

**File**: `src/services/smart_contractAD.py`, anywhere in the admin section
(near `updateOracle` / `updateTxlContract`).

**Add**:

```python
@sp.entrypoint()
def pruneGame(self, params):
    '''Admin-only: delete a finished game record (status 3/4/5) to
    reclaim storage. Emits the full pre-prune record so off-chain
    indexers can keep history.'''
    sp.cast(params.gameId, sp.nat)
    assert sp.sender == self.data.admin, "not admin"
    g = self.data.games[params.gameId]
    assert g.gameStatus >= 3, "game not finished"
    sp.emit(g, tag='gamePruned')
    del self.data.games[params.gameId]
```

**Acceptance**: redeploy. From an exercise script (or manually via
pytezos): finish a game, then `contract.pruneGame(gameId=N).send()`.
Storage poll afterward must show `games[N]` absent.

---

### AD-4 [LOW] — Add `updateAdmin` so the admin key is rotatable

**File**: `src/services/smart_contractAD.py`, top of the admin section.

**Add**:

```python
@sp.entrypoint()
def updateAdmin(self, params):
    '''Two-step would be safer; for now, single-step. If the admin key
    is lost or compromised, this is the only path to recovery, so be
    very deliberate when calling it.'''
    sp.cast(params.newAdmin, sp.address)
    assert sp.sender == self.data.admin, "not admin"
    self.data.admin = params.newAdmin
```

**Acceptance**: redeploy. Call `updateAdmin(newAdmin=tz1other...)` from
the admin key; subsequent admin-gated calls must fail from the OLD key.

---

### AD-5 [LOW, v2 feature] — Commit-reveal for card randomness

See the cross-cutting "Commit-reveal redesign" section at the bottom of
this doc. Don't ship as a hotfix.

---

## AD v3 — re-audit (post-v3)

Re-pass before the mainnet origination of `smart_contractAD.py` (v3
commit-reveal consumer). The May 2026 audit covered the v2 surface;
this section re-verifies that the v2 hotfixes (AD-1..AD-4) carried
forward into the v3 rewrite, and adds checks specific to the v3
oracle-callback / commit-reveal flow. Line numbers refer to
`src/services/smart_contractAD.py` at the v3 source level
(no `pot`/`potReserve` literal edits shift anything in this region).

### AD-1 [HIGH, carried] — `bet()` strict-equality amount check

**Status**: ✓ retained in v3. Line 162:

```python
assert sp.amount == self.data.ante + self.data.fee + self.data.oracleFee, "must send ante + fee + oracleFee"
```

Strict `==`, all three terms required. The v2 tautology
(`sp.amount == sp.amount`) is gone. Underpay no longer creates a game;
overpay reverts before any state change.

### AD-2 [MED, carried] — Reserve-guarded pot refill

**Status**: ✓ retained in v3, moved to the `onRandomFulfilled` last-card
branch. Lines 343-345:

```python
if self.data.pot < sp.mutez(124999) and self.data.potReserve >= sp.mutez(125000):
    self.data.pot += sp.mutez(125000)
    self.data.potReserve -= sp.mutez(125000)
```

Both sides of the conjunction are required. `potReserve >= 125000`
guards the SUB_MUTEZ panic that would otherwise brick the oracle's
last-card settlement (callback would revert → game stuck in status 2
permanently). The 124999 / 125000 boundary is intentional — see the
inline comment.

### AD-3 [MED, carried] — `pruneGame`

**Status**: ✓ retained in v3 with the v3 record shape. Lines 131-141.
Admin-gated; requires `gameStatus >= 3` (3/4/5 = finished); emits the
record pre-delete for indexers; then `del self.data.games[gameId]`.

### AD-4 [LOW, carried] — `updateAdmin`

**Status**: ✓ retained in v3. Lines 99-105. Admin-gated, `sp.cast` on
`newAdmin`, single-step rotation. Same shape as v2.

### AD-5 [LOW, v2 feature] — Commit-reveal randomness

**Status**: ✓ subsumed by v3. The whole v3 rewrite *is* AD-5: cards now
come from `requestRandom` → `revealCommit` → `onRandomFulfilled` against
a v3 RandomOracle KT1, with player-controlled `userNonce` mixed into
the seed. No trusted-tz1-oracle key remains. AD-5 should be marked
DONE in the verification matrix.

### v3-specific checks

**V3-1 [HIGH check]** — `onRandomFulfilled` callback authentication.

Line 254:

```python
assert sp.sender == self.data.oracleContract, "not oracle"
```

Strict equality against the storage value. `sp.sender` is the immediate
caller, set by the protocol from the operation source — it can't be
spoofed at the SmartPy level. The only way to deliver a fulfillment is
to BE `self.data.oracleContract` (i.e. control that KT1). Admin can
rotate via `updateOracleContract` if the oracle is compromised.

**Finding**: ✓ correctly gated. No spoofing path under the Tezos protocol's
sender semantics.

**V3-2 [MED check]** — Replay of `onRandomFulfilled`.

The oracle could theoretically deliver the same `requestId` twice (retry
loop, or malicious double-fulfill). Mitigation lives in the gameStatus
state machine:

- Phase 0 asserts `g.gameStatus == 0` (line 261). After successful
  phase-0 fulfillment, status → 1 (or 5 on pair). A replay with phase=0
  hits `g.gameStatus in {1,5}`, assert reverts.
- Phase 1 asserts `g.gameStatus == 2` (line 293). After successful
  phase-1, status → 3 or 4. Replay reverts.

**Finding**: ✓ no double-settlement window. The state-machine guard is
sufficient because `gameStatus` is updated inside the same callback
that consumes it.

**V3-3 [MED check]** — `continueBet` accepts `sp.amount >= fee + oracleFee` (not `==`).

Lines 213-214:

```python
assert sp.amount >= self.data.fee + self.data.oracleFee, "must cover fee + oracleFee"
bet = sp.amount - self.data.fee - self.data.oracleFee
```

This is intentional and asymmetric to `bet()`: the bet size is a player
choice, not a fixed price. The spread-aware ceiling at line 225
(`maxPayout <= self.data.pot + bet`) is the actual safety bound — any
bet that would let the worst-case payout exceed the pot reverts.

**Concern checked**: can a "stray top-up" path bypass the spread
ceiling? E.g. player sends a massive amount, the bet is huge, but the
ceiling clamps the spread-implied payout. The ceiling check is
unconditional and runs before any state change, so no — overpayment
either fits the spread or reverts. ✓

**Finding**: ✓ asymmetry is correct. The `>=` is load-bearing for the
variable-bet UX; the ceiling check is what enforces solvency.

**V3-4 [HIGH check]** — Reentrancy / state-before-send in win branch.

Lines 322-329:

```python
spread = sp.as_nat(highCard - lowCard - 1)
winAmount = sp.split_tokens(g.finalBet, 1235, spread * 100)
if winAmount > self.data.pot:
    winAmount = self.data.pot
# §4.1: terminal state before sp.send.
self.data.games[ctx.gameId].gameStatus = 3
self.data.pot -= winAmount
sp.send(g.player, winAmount)
```

`gameStatus = 3` is written BEFORE `sp.send(g.player, winAmount)`. A
malicious player contract that re-enters via its `default()` would find
`gameStatus = 3`, and any callback that asserts `gameStatus == 0` or
`== 2` would revert. The pot is also debited before the send, so the
re-entered code sees a consistent (smaller) pot.

**Finding**: ✓ checks-effects-interactions order preserved from AD-5.

**V3-5 [LOW check]** — Cross-game / pruned-game callback safety.

Line 256: `assert ctx.gameId in self.data.games`. If a game was pruned
between `requestRandom` and the oracle's eventual fulfillment, the
fulfillment reverts cleanly rather than mis-applying to a different
gameId. Note: AD only allows `pruneGame` on `gameStatus >= 3`, and
those games have no outstanding oracle requests, so this is a defensive
check rather than a regular path. ✓

**V3-6 [LOW check]** — `handHashes` is a v2 leftover in storage.

Lines 78, 172, 176 initialize and populate `handHashes` to empty
strings, but no entrypoint ever writes a non-empty value (the v2
commit-reveal that needed them is gone). Pure storage waste, not a
security issue. **Not a fix in this batch** — leave as-is so the
mainnet storage shape matches what `aceyDuecey.vue` already reads.
Worth a follow-up cleanup commit post-mainnet.

**V3-7 [LOW check]** — Pot underflow envelope around `cv3 == lowCard` / `cv3 == highCard`.

Lines 313-314 / 332-333: `self.data.pot -= g.finalBet + self.data.ante;
sp.send(self.data.txlContract, g.finalBet + self.data.ante)`. Could
`pot < g.finalBet + self.data.ante` and trip SUB_MUTEZ?

- `bet()` adds `ante` to pot. `continueBet()` adds `bet` (=finalBet) to
  pot, then deducts `fee` via the auto-rake when `pot > 2 ꜩ`.
- At settle: net pot delta since this game started is roughly
  `+ante + finalBet - fee_or_zero`. Subtracting `ante + finalBet`
  leaves `pot >= -fee_or_zero` for *this game's contribution*, but pot
  started non-zero (5 ꜩ seed), so the cumulative balance stays
  positive.
- Worst case attempted: spread-1 max bet against the dust pot. Spread
  ceiling caps bet at ~8.8% of pot. With 5 ꜩ seed, max bet ~0.44 ꜩ,
  pot post-bet-and-rake ~5.54 ꜩ, settle subtracts 0.64 ꜩ → 4.9 ꜩ. No
  underflow.

**Finding**: ✓ no realistic underflow under the seeded mainnet pot.
The spread ceiling is the load-bearing constraint; if seeded pot ever
drops below `ante + maxBet` we'd revisit, but the auto-refill branch
(V3-2's AD-2-carry) prevents that.

### Summary

No HIGH findings. AD-1..AD-4 are correctly carried forward; AD-5 is
subsumed by the v3 commit-reveal flow. V3-specific checks all pass:
callback gate is sound, state machine prevents double-settlement,
checks-effects-interactions order preserved in the win branch. The
only non-trivial residual is V3-6 (unused `handHashes` field) — leave
for a post-mainnet cleanup so the storage shape stays predictable for
`aceyDuecey.vue`.

**Clear to proceed past task 10.**

---

## Plinko (`src/services/smart_contractPlinko.py`)

### PLINKO-1 [HIGH, v2 feature] — Oracle bias is the trust model

The current design lets the operator pick any bit string. Mitigation
options span from per-round commit-reveal to a quorum of operators —
all are v2 work. Document this in `docs/ORACLE_INTEGRATION.md` (the
oracle service doc already mentions it briefly; expand). Don't ship
a code change for this in the security batch.

---

### PLINKO-2 [MED] — Pot deficit pulls a hard assert

**File**: `src/services/smart_contractPlinko.py`, inside `resolve`.

**Find**:

```python
if payout > sp.mutez(0):
    if payout > self.data.pot:
        deficit = payout - self.data.pot
        assert self.data.potReserve >= deficit, "pot + reserve too low"
        self.data.potReserve -= deficit
        self.data.pot += deficit
    self.data.pot -= payout
    sp.send(r.player, payout)
```

If pot + reserve can't cover, the entire `resolve` op fails and the
oracle worker burns fees retrying forever.

**Replace with**:

```python
if payout > sp.mutez(0):
    # Cap payout at whatever pot + reserve can actually pay. The round
    # still settles (status flips off 0), the worker doesn't loop, and
    # an off-chain alert can prompt the admin to top up.
    available = self.data.pot + self.data.potReserve
    actualPayout = payout
    if payout > available:
        actualPayout = available
    if actualPayout > self.data.pot:
        deficit = actualPayout - self.data.pot
        self.data.potReserve -= deficit
        self.data.pot += deficit
    self.data.pot -= actualPayout
    sp.send(r.player, actualPayout)
    # Bookkeep what we actually paid vs. what was owed.
    self.data.rounds[params.roundId].payout = actualPayout
```

You'll also want to emit a `payoutShortfall` event with the gap if
`actualPayout < payout`, so off-chain alerting can notice underpayment.

**Acceptance**: redeploy with a manually drained pot+reserve, place a
high-multiplier play (e.g. rows=16 risk=2). `resolve` must succeed,
the player receives whatever was available, and the storage records
the smaller actual payout.

---

### PLINKO-3 [MED] — `pruneRound` admin entrypoint

Identical pattern to `AD-3`. Add to the admin section of
`smart_contractPlinko.py`:

```python
@sp.entrypoint()
def pruneRound(self, params):
    sp.cast(params.roundId, sp.nat)
    assert sp.sender == self.data.admin, "not admin"
    r = self.data.rounds[params.roundId]
    assert r.roundStatus != 0, "round not settled"
    sp.emit(r, tag='roundPruned')
    del self.data.rounds[params.roundId]
```

Same acceptance pattern as AD-3.

---

### PLINKO-4 [LOW] — Cap `setMultiplierRow` input size

**File**: `src/services/smart_contractPlinko.py`, in `setMultiplierRow`.

**Find** the `for slot in params.values.keys():` loop and prepend a size
guard. Modern SmartPy doesn't have a direct `len()` on maps inside
entrypoints; do a manual count:

```python
@sp.entrypoint()
def setMultiplierRow(self, params):
    assert sp.sender == self.data.admin, "not admin"
    sp.cast(params.rows, sp.nat)
    sp.cast(params.risk, sp.nat)
    sp.cast(params.values, sp.map[sp.nat, sp.nat])
    # Cap entry count to defeat gas-balloon griefing if the admin key
    # is ever compromised.
    count = sp.nat(0)
    for _k in params.values.keys():
        count += 1
    assert count <= 17, "too many entries (max 17 = 16-row slot count)"
    base = params.rows * 1000 + params.risk * 100
    for slot in params.values.keys():
        self.data.multipliers[base + slot] = params.values[slot]
```

**Acceptance**: admin-call `setMultiplierRow` with a 50-entry map must
fail with `"too many entries"`.

---

### PLINKO-5 [LOW] — `topUpPot` positivity + naming

**File**: `src/services/smart_contractPlinko.py`, in `topUpPot`.

**Find**:

```python
@sp.entrypoint()
def topUpPot(self, params):
    assert sp.sender == self.data.admin, "not admin"
    sp.cast(params.amount, sp.mutez)
    self.data.potReserve -= params.amount
    self.data.pot += params.amount
```

Two issues: (a) takes from reserve, gives to pot — directional, but the
name doesn't constrain the sign, (b) `mutez` is always non-negative so
this is structurally fine — but if you later switch to a signed type,
this'd drain in reverse silently.

**Replace with**:

```python
@sp.entrypoint()
def topUpPot(self, params):
    '''Move `amount` from reserve into the playable pot.'''
    sp.cast(params.amount, sp.mutez)
    assert sp.sender == self.data.admin, "not admin"
    assert params.amount > sp.mutez(0), "amount must be positive"
    assert self.data.potReserve >= params.amount, "reserve too low"
    self.data.potReserve -= params.amount
    self.data.pot += params.amount
    sp.emit([params.amount, self.data.pot, self.data.potReserve], tag='potToppedUp')

@sp.entrypoint()
def withdrawToReserve(self, params):
    '''Move `amount` from the playable pot back to the reserve.'''
    sp.cast(params.amount, sp.mutez)
    assert sp.sender == self.data.admin, "not admin"
    assert params.amount > sp.mutez(0), "amount must be positive"
    assert self.data.pot >= params.amount, "pot too low"
    self.data.pot -= params.amount
    self.data.potReserve += params.amount
    sp.emit([params.amount, self.data.pot, self.data.potReserve], tag='potDrained')
```

**Acceptance**: positive amounts both ways succeed; zero or oversized
amounts fail with the expected message.

---

### PLINKO-6 [LOW] — Add `updateAdmin` (mirror of AD-4)

Same code as AD-4 with `sp.cast` paths. Put it in the admin block of
`smart_contractPlinko.py`.

---

## Plinko v3 — re-audit (post-v3 commit-reveal)

Re-pass before the mainnet origination of `smart_contractPlinko.py`
(v3 commit-reveal consumer, commit `920e227`). The original audit
covered the v2 surface; this section re-verifies that PLINKO-1..6
carry forward into the v3 rewrite and adds v3-specific checks for
the commit-reveal / `requestRandom` / `onRandomFulfilled` flow. Line
numbers refer to `src/services/smart_contractPlinko.py` at the
v3 source level (mainnet `__init__` literal swap doesn't shift any
of the cited regions).

### PLINKO-1 [HIGH, v2 feature] — Oracle bias is the trust model

**Status**: ✓ subsumed by v3. Plinko now consumes the v3 RandomOracle
via `play()` forwarding `userNonce` + `commitId` (line 244) and
settling in `onRandomFulfilled` (line 248). The seed is derived
on-chain in the oracle from the commit-revealed preimage + the
player's `userNonce` + the requestId — see `smart_contract_oracle.py:352`.
The operator cannot bias outcomes by picking the seed after seeing
the request, because the preimage is committed before any request is
bound to it (verified against the oracle's commit lifecycle).
PLINKO-1 should be marked DONE in the verification matrix.

### PLINKO-2 [MED, carried] — Pot deficit pulls a hard assert

**Status**: ✓ retained in v3 as a clamp-and-emit pattern, not the
hard revert that the v2 audit flagged. Lines 310-323:

```python
if payout > sp.mutez(0):
    available = self.data.pot + self.data.potReserve
    actualPayout = payout
    if payout > available:
        actualPayout = available
        deficit = payout - self.data.pot
        self.data.potReserve -= deficit
        self.data.pot += deficit
    ...
    if actualPayout < payout:
        sp.emit(sp.record(roundId=roundId, owed=payout, paid=actualPayout), tag='payoutShortfall')
```

Cap-at-available means the oracle callback never reverts on under-funded
pots — settlement always completes, the shortfall is emitted as an
event for off-chain reconciliation, and round storage records the
actual paid amount. The on-chain bookkeeping (`pot`/`potReserve`)
moves consistently with the L1 send.

### PLINKO-3 [MED, carried] — `pruneRound`

**Status**: ✓ retained in v3 with the v3 round shape. Lines 156-164.
Admin-gated, requires `roundStatus != 0` (i.e. not still pending
oracle fulfillment), emits the record pre-delete for indexers, then
`del self.data.rounds[roundId]`. The "must be settled" guard prevents
the admin from pruning a round mid-flight and orphaning a callback.

### PLINKO-4 [LOW, carried] — Cap `setMultiplierRow` entry count

**Status**: ✓ retained in v3. Lines 178-186. Count iterated via a
loop (the SmartPy stdlib doesn't surface `len()` on `sp.map` in
this version), capped at 17 to fit the legitimate ring domain
(0..16 for rows=16) with one slot of headroom. Defeats the
gas-balloon vector if the admin key is ever compromised.

### PLINKO-5 [LOW, carried] — `topUpPot` positivity + naming

**Status**: ✓ retained in v3. Lines 329-337. Admin-gated; asserts
`params.amount > sp.mutez(0)` (positivity) and
`self.data.potReserve >= params.amount` (no underflow), then moves
the amount from reserve to pot and emits `potToppedUp`.

### PLINKO-6 [LOW, carried] — `updateAdmin`

**Status**: ✓ retained in v3. Lines 101-106. Admin-gated, `sp.cast`
on `newAdmin`, single-step rotation. Mirrors AD-4 exactly.

### v3-specific checks

**V3-1 [HIGH check]** — `onRandomFulfilled` callback authentication.

Line 257:

```python
assert sp.sender == self.data.oracleContract, "not oracle"
```

Strict equality against the storage value. `sp.sender` is the
immediate caller, set by the protocol — un-spoofable at the SmartPy
level. Admin can rotate the oracle KT1 via `updateOracleContract`
(line 109) if it's ever compromised.

**Finding**: ✓ correctly gated. Same shape as AD V3-1.

**V3-2 [MED check]** — Replay of `onRandomFulfilled`.

Line 261: `assert r.roundStatus == 0, "already resolved"`. After a
successful fulfillment, `roundStatus` flips to 1/2/3 (line 311). A
replayed callback with the same `requestId`/`callbackContext` would
revert at this assertion.

**Finding**: ✓ no double-settlement window.

**V3-3 [MED check]** — `play()` amount arithmetic.

Lines 213-216:

```python
assert sp.amount >= self.data.minBet + self.data.fee + self.data.oracleFee, "bet too small"
assert sp.amount <= self.data.maxBet + self.data.fee + self.data.oracleFee, "bet too big"
betAfterFees = sp.amount - self.data.fee - self.data.oracleFee
```

Both bounds use `>=` / `<=` (not strict-eq), which is intentional and
asymmetric to AD's `bet()` because plinko's bet size is a player
choice within the band. The `betAfterFees` calculation cannot
underflow under the `>=` lower bound. `sp.send(txlContract, fee)`
on line 218 is unconditional and the `oracleFee` is included in the
`sp.transfer` payload to the oracle on line 244 — both routes consume
the fee components before the callback can fire.

**Finding**: ✓ arithmetic is sound under SmartPy's mutez semantics.

**V3-4 [HIGH check]** — State-before-send in the win branch.

Lines 306-321:

```python
self.data.rounds[roundId] = sp.record(... roundStatus=newStatus ...)
...
if payout > sp.mutez(0):
    available = self.data.pot + self.data.potReserve
    actualPayout = payout
    if payout > available:
        ...
        self.data.potReserve -= deficit
        self.data.pot += deficit
    self.data.pot -= actualPayout
    sp.send(r.player, actualPayout)
```

`roundStatus` is written before `sp.send`. The pot is also debited
before the send. A malicious player contract that re-enters via its
`default()` finds `roundStatus != 0`, so a replay would revert at
V3-2's assertion (line 261). The default() entrypoint of Plinko itself
(line 96-98) only adds to `potReserve` — it does not mutate any
round state — so reentry through default() can't desync round state.

**Finding**: ✓ checks-effects-interactions order preserved.

**V3-5 [MED check]** — Oracle nRandoms / maxValue parameters.

Line 241: `nRand = sp.mul(sp.nat(2), params.rows)` with `rows ∈ {8,12,16}` →
`nRand ∈ {16, 24, 32}`. The mainnet oracle's `maxRandomsPerRequest`
is 32 (verified via tzkt /v1/contracts/<oracle>/storage). Exactly
fits the worst case; no padding bug. Line 244 forwards
`maxValue=sp.nat(1)` (each value is a bit). Line 279 defensively
asserts the oracle returned exactly `2*rows` values — protects
against a malicious / buggy oracle delivering a different count.

**Finding**: ✓ bounded and defensively validated.

**V3-6 [LOW check]** — Pruned-round callback safety.

Line 259: `assert roundId in self.data.rounds, "no such round"`. If
a round was pruned between `play()` and the eventual fulfillment, the
fulfillment reverts cleanly. `pruneRound` only allows settled rounds
(`roundStatus != 0`), so this can't be hit in practice — defensive
only.

**Finding**: ✓ defensive, no path to mis-apply a fulfillment to the
wrong round.

**V3-7 [LOW check]** — Mainnet pot seed bookkeeping.

`__init__` literals: `self.data.pot = sp.tez(5); self.data.potReserve = sp.tez(10)`.
`scripts/deploy.py` plinko spec has `initial_balance_tez=15.0`. The
two must agree because `default()` is NOT triggered by origination
(comment: smart_contractPlinko.py:96-98) — origination credits the
L1 balance directly without going through `default()`. The contract's
internal counters and the L1 balance therefore both start at 15 ꜩ.

**Finding**: ✓ bookkeeping consistent. If `initial_balance_tez` were
ever changed without updating the `__init__` literals (or vice versa),
on-chain bookkeeping would drift from L1 balance and the first
`topUpPot` to mainnet would be off. Worth a comment, which is in
place at both ends.

### Summary

No HIGH findings. PLINKO-1 is subsumed by v3; PLINKO-2..6 are correctly
carried forward. V3-specific checks all pass: callback gate is sound,
state machine prevents double-settlement, checks-effects-interactions
order preserved, oracle parameters bounded and defensively validated.
Mainnet pot-seed bookkeeping is consistent end-to-end (`__init__`
literals ↔ `deploy.py initial_balance_tez`).

**Clear to proceed to mainnet origination** (pending deployer-wallet
funding + explicit go-ahead).

---

## TTT (`src/services/smart_contract_TTT.py`)

### TTT-1 [HIGH] — `games = {}` untyped → compile failure

**File**: `src/services/smart_contract_TTT.py`, inside `__init__`.

**Find**:

```python
self.data.games = {}
self.data.currentGameIndex = 0
```

SmartPy raises `unknown type variable` for an empty dict with no
downstream entry constraining the type. Fix:

**Replace with**:

```python
self.data.games = sp.cast({}, sp.map[sp.int, sp.record(
    grid=sp.map[sp.int, sp.int],
    players=sp.map[sp.int, sp.address],
    metaData=sp.map[sp.string, sp.int],
    tzGameBet=sp.mutez,
    houseCutBps=sp.nat,
)])
self.data.currentGameIndex = sp.int(0)
```

Same treatment for `game_winners`: the non-empty dict literal SHOULD
infer cleanly, but if compile complains, wrap it in `sp.cast(...,
sp.map[sp.int, sp.list[sp.int]])`.

**Acceptance**: `python src/services/smart_contract_TTT.py` produces
the `TTT_gambling_+_house_cut/` output folder with `.tz` + `.json`
artifacts and no compile errors.

---

### TTT-2 [MED] — `makeMove` doesn't validate the move coord

**File**: `src/services/smart_contract_TTT.py`, near the top of `makeMove`.

**Find**:

```python
assert sp.sender == g.players[playerTurn], "not your turn"
assert g.grid[params.move] == 0, "cell occupied"
```

If `params.move` isn't one of the 64 valid coords (111..444 with each
digit 1..4), `g.grid[params.move]` panics. Not exploitable for funds
but useful as a defensive guard.

**Replace with**:

```python
assert sp.sender == g.players[playerTurn], "not your turn"
assert g.grid.contains(params.move), "invalid move coord"
assert g.grid[params.move] == 0, "cell occupied"
```

**Acceptance**: an exercise op with `move=999` fails with
`"invalid move coord"` rather than a Michelson-level panic.

---

### TTT-3 [MED] — Move per-move scratch state from `self.data.*` to locals

**File**: `src/services/smart_contract_TTT.py`, `__init__` and `makeMove`.

The fields `gameWon`, `setSum`, `lastCoord`, `hasRemainingWinners`,
`winnerHasZero`, `winnerHasOne`, `winnerHasTwo` are stored in contract
storage but only used as scratch space within a single `makeMove` call.
They cost storage forever and obscure intent.

**In `__init__`**: delete these lines:

```python
self.data.setSum = 0
self.data.gameWon = 0
self.data.lastCoord = 0
self.data.hasRemainingWinners = 0
self.data.winnerHasZero = 0
self.data.winnerHasOne = 0
self.data.winnerHasTwo = 0
```

**In `makeMove`**: replace `self.data.X` accesses with local variables:

```python
@sp.entrypoint()
def makeMove(self, params):
    sp.cast(params.gameId, sp.int)
    sp.cast(params.move, sp.int)
    g = self.data.games[params.gameId]
    assert g.metaData["gameStatus"] == 2, "game not active"
    assert g.metaData["firstMoveDecided"] == 1, "awaiting first-move flip"
    playerTurn = g.metaData["playerTurn"]
    assert sp.sender == g.players[playerTurn], "not your turn"
    assert g.grid.contains(params.move), "invalid move coord"
    assert g.grid[params.move] == 0, "cell occupied"

    # Place + flip turn.
    self.data.games[params.gameId].grid[params.move] = playerTurn
    nextTurn = 2
    if playerTurn == 2:
        nextTurn = 1
    self.data.games[params.gameId].metaData["playerTurn"] = nextTurn

    # Re-evaluate the board — all locals.
    gameWon = sp.int(0)
    hasRemainingWinners = sp.int(0)
    for gameWinningSet in self.data.game_winners.values():
        setSum = sp.int(0)
        winnerHasZero = sp.int(0)
        winnerHasOne = sp.int(0)
        winnerHasTwo = sp.int(0)
        for coord in gameWinningSet:
            owner = self.data.games[params.gameId].grid[coord]
            if owner == 0:
                winnerHasZero = 1
            if owner == 1:
                setSum += owner
                winnerHasOne = 1
            if owner == 2:
                setSum += owner
                winnerHasTwo = 1
        if setSum <= 2:
            hasRemainingWinners += 1
        if setSum == 3:
            if winnerHasTwo == 0:
                hasRemainingWinners += 1
        if setSum == 4:
            if winnerHasZero != 1 and winnerHasTwo != 1:
                gameWon = 1
                self.data.games[params.gameId].metaData["winningPlayer"] = 1
            else:
                hasRemainingWinners += 1
        if setSum == 6:
            if winnerHasOne == 0:
                hasRemainingWinners += 1
        if setSum == 8:
            gameWon = 2
            self.data.games[params.gameId].metaData["winningPlayer"] = 2

    # Settlement (unchanged logic, just uses the local `gameWon` /
    # `hasRemainingWinners` instead of self.data.*).
    if gameWon > 0:
        ...
    if gameWon == 0 and hasRemainingWinners == 0:
        ...
```

**Acceptance**: redeploy, play a full game to win-or-cat, exercise
script reports the right winner.

---

### TTT-4 [MED] — Index win sets per cell to cut 75-set scan

**File**: `src/services/smart_contract_TTT.py`, `__init__`.

Currently every `makeMove` re-evaluates all 75 win-sets even though
only the ~9 win-sets touching the just-placed cell could have changed.
Add an index:

```python
# After self.data.game_winners is built, also build:
#   self.data.cell_to_winsets[cellCoord] = list of winset indices that include it
self.data.cell_to_winsets = {}
for set_idx, ws in self.data.game_winners.items():
    for coord in ws:
        if coord not in self.data.cell_to_winsets:
            self.data.cell_to_winsets[coord] = []
        self.data.cell_to_winsets[coord].append(set_idx)
```

Then in `makeMove`, instead of iterating *all* `game_winners.values()`,
iterate only `self.data.cell_to_winsets[params.move]` and look up each
set from `self.data.game_winners[set_idx]`. ~9× speedup per move on
average, much more predictable gas cost.

This is the largest fix in TTT — defer if time is short. Acceptance:
same play-a-game test as TTT-3, gas cost (visible in `tzkt`) on
makeMove drops noticeably.

---

### TTT-5 [LOW] — Pick a surrender split policy

The current 30/70 is unusually generous to the surrenderer. Two
options, pick whichever matches the game narrative:

- **Pure forfeit**: surrenderer gets 0, opponent gets `pot − houseCut`.
- **Even split**: each side gets `(pot − houseCut)/2`.

Edit the `surrenderGame` entrypoint accordingly. Update
`AD_GAME_INFO`'s TTT analogue (`TTT_GAME_INFO` in `src/constants.js`)
to reflect whatever you pick.

---

### TTT-6 [LOW] — Add `claimByTimeout` (mirror of Chess)

**File**: `src/services/smart_contract_TTT.py`.

Mirror the Chess pattern:

```python
self.data.staleBlocks = sp.nat(120)
```

Then a new entrypoint:

```python
@sp.entrypoint()
def claimByTimeout(self, params):
    '''If your opponent has been idle for >= staleBlocks since their
    last move, you can claim the game.'''
    sp.cast(params.gameId, sp.int)
    g = self.data.games[params.gameId]
    assert g.metaData["gameStatus"] == 2, "game not active"
    assert sp.level - g.metaData["lastMoveBlock"] >= self.data.staleBlocks, "not stale yet"
    playerTurn = g.metaData["playerTurn"]
    assert sp.sender != g.players[playerTurn], "you owe the move"
    assert sp.sender == g.players[1] or sp.sender == g.players[2], "not a player"
    # Pay the claimant; mirror the makeMove win-settlement logic.
    pot = sp.mul(g.tzGameBet, sp.nat(2))
    houseAmt = sp.split_tokens(pot, g.houseCutBps, 10000)
    payout = pot - houseAmt
    sp.send(self.data.houseAddress, houseAmt)
    sp.send(sp.sender, payout)
    self.data.games[params.gameId].metaData["gameStatus"] = 3
    if sp.sender == g.players[1]:
        self.data.games[params.gameId].metaData["winningPlayer"] = 1
    else:
        self.data.games[params.gameId].metaData["winningPlayer"] = 2
    sp.emit(params.gameId, tag='claimedByTimeout')
```

Also requires adding `lastMoveBlock: sp.int` to the per-game record
type and setting it on `joinGame` and at the end of every `makeMove`.

**Acceptance**: simulate a 120-block timeout (or temporarily lower
`staleBlocks` to 5 for testing), claim succeeds; before-timeout claim
fails with `"not stale yet"`.

---

## Cross-cutting

### XC-1 — Update `docs/ORACLE_INTEGRATION.md` with bias warning

Expand the **Auditability** section. State explicitly that the current
v2 oracle gives clients NO defense against a malicious operator
choosing biased values — the seed proves *what* was chosen, not that
it was chosen fairly. A v3 commit-reveal scheme is on the roadmap.

### XC-2 — Document `default()` semantics

Every contract's `default()` entrypoint accepts anonymous tez. AD and
Plinko credit it to `potReserve`; TTT discards (no body). Document
this in each `*_GAME_INFO` block in `src/constants.js`.

### XC-3 — Add a `scripts/rotate_oracle.sh` helper

Operational, not contract code. Wrap the per-contract `updateOracle`
calls so the user can rotate the off-chain oracle key in one command:

```bash
#!/usr/bin/env bash
# rotate_oracle.sh — rotate the oracle address on every game contract.
# Usage: ./scripts/rotate_oracle.sh <new_tz1>
set -euo pipefail
NEW="$1"
for game in acey-duecey plinko war reversi chess ttt squares; do
  .venv/bin/python -c "
from pytezos import pytezos
from scripts.deploy import load_dotenv, NETWORK_RPCS, load_key
import os, re
load_dotenv()
# ... look up address from constants.js, call updateOracle($game, NEW)
"
done
```

(Stub — fill in per-contract logic as you write it.)

---

## Plinko commit-reveal redesign (v2, not in the hotfix batch)

The current resolve flow:

```
play() ─────────────────────► roundStatus=0
                                │
oracle.resolve(bits, seed) ────► roundStatus=1/2/3, slot=sum(bits)
```

Replace with two-phase commit:

```
play(commitHash) ──────────────► roundStatus=0, oracleCommit=hash
                                  │
oracle.commit(roundId, hash) ──► oracleCommit=hash    (after some delay)
                                  │
oracle.resolve(bits, nonce) ───► verify(hash == sha256(bits||nonce))
                                  if valid: settle as before.
```

The oracle commits to a hash *before* seeing the player's bet (or
after, but with a delay long enough that the player can verify the
hash was published independently). Reveal must match the hash —
otherwise the oracle has burned their key's credibility forever.

Design notes for the spec doc you'd write later:
- Use `sp.sha256` and `sp.pack` for the hash.
- `nonce` is `sp.bytes` so the bit-vector can pack into it for
  efficient hashing.
- Allow a `timeout` on the reveal: if oracle doesn't reveal within
  N blocks, the player can refund themselves.

Don't implement this in the current security batch. File as
`v2: plinko commit-reveal` and revisit after the hotfix deploys
ship and bake on shadownet.

---

## Squares (`src/services/smart_contract_squares_v2.py`)

Audit pass added May 2026 ahead of mainnet origination (the May 2026
batch above only covered AD / Plinko / TTT). Severities are HIGH (block
mainnet), MED (track + plan a follow-up), LOW (acknowledged), INFO
(reference). **No HIGH findings.** Squares is clear to ship on the v2
trust model — `SQ-1` and `SQ-2` are the items to watch first.

### SQ-1 [MED] — `setAxes` trusts the daemon to emit a real permutation

**File**: `src/services/smart_contract_squares_v2.py`, the `setAxes`
entrypoint (around lines 272-289).

Validation is only `0 in axisHome / 9 in axisHome` (same for `axisAway`).
A malformed or malicious permutation gets accepted as-is. Two failure
modes:

1. **Stuck game** — admin sends a map missing some 0..9 keys, e.g.
   `{0: 5, 9: 5}`. `reportQuarter`'s `for i in range(10):
   if game.axisHome[i] == homeDigit:` does a direct lookup that raises
   when the key is absent. The game wedges in `PHASE_AXES_SET` with no
   refund path (refundUnsold rejects `GameTooFar`). Players' tez is
   stranded.
2. **Insider win** — admin colludes by issuing a permutation
   correlated with their own pre-buys. Admin sees the full
   `squares` map before calling `setAxes`, so they can deterministically
   route quarter winners to squares they own.

This is the *documented* trust model for v2 — the off-chain daemon
(`scripts/oracle_worker.py` `SquaresHandler`) holds the admin key and
is trusted to (a) generate the permutation from entropy uncorrelated
with the buys, and (b) actually send a valid `[0..9]` permutation. The
contract already plumbs `rngOracle` through storage so a future v3 can
move to commit-reveal axis randomisation behind an admin updater
(`updateRngOracle`) without a redeploy.

**Mitigation track** (post-mainnet, not blocking):
- Tighten `setAxes` on-chain: require all 10 keys present + values are
  a permutation of 0..9 (cheap; two unrolled 10-iteration loops).
- Move to commit-reveal: admin commits `hash(salt || permutation)`
  before `closeSales`; reveals after with `(salt, permutation)`; the
  hash binds them to a permutation chosen before they could see the
  full buy list. Same pattern as the Plinko v2 redesign at the bottom
  of this doc.


## TXL v2 (`src/services/smart_contract_txl.py`)

First audit pass for the TXL holder-reward contract — v1 was never
audited. v2 was redesigned from scratch around the accumulator pattern;
findings below are vs. that design, not the v1 codebase.

### Fixed in v2 (vs v1 known issues)

- **HIGH — `default()` O(N) gas.** v1 wrote to all 271 ledger entries on
  every deposit. With the game suite live, every bet forwarded a holder
  fee → 271 storage writes per game op. v2 uses a single `accPerToken`
  accumulator; deposits are O(1).
- **HIGH — silent-no-op auth on oracle entrypoints.** v1's
  `updateOwner` used `if sp.sender == oracle:` followed by `sp.emit
  'not Oracle Error'` — non-oracle calls succeeded (wasted gas, no
  revert). v2 uses `assert sp.sender == self.data.oracle, "notOracle"`.
- **HIGH — no admin rotation.** v1's oracle was permanent. v2 adds
  two-step `proposeAdmin`/`acceptAdmin` and `updateOracle`.
- **HIGH — no circuit breaker.** v1 had no pause path. v2 has
  `pause`/`unpause` gating deposits, settle, push, and claim. Oracle
  ops + admin role ops bypass pause by design.
- **HIGH — public oracle seed.** v1's oracle mnemonic was committed
  in `src/services/oracle_TXL.py` — anyone could call `updateOwner`.
  v2 ships with a fresh, gitignored `TXL_ORACLE_MNEMONIC` in `.env`,
  separate from the deploy key.
- **MED — sp.map vs big_map.** v1 stored 271 owner entries in
  `sp.map`, serialized whole on every read. v2 uses `big_map`,
  paying per-key gas only. Combined with lazy creation, this also
  makes the contract storage-rent-friendly.
- **MED — untracked dust.** v1's `sp.split_tokens(amount, 1, 271)`
  silently dropped `amount mod 271` mutez per deposit. v2 tracks
  dust in storage and exposes `sweepDust(recipient)` to admin.
- **LOW — UI/contract drift.** v1's `NFT_INFO` copy promised "inverse
  weight against rank"; contract distributed flat. v2 keeps the flat
  distribution AND updates `constants.js:NFT_INFO` to match.

### v2 audit findings (informational)

- **`default()` division by zero guarded.** `sp.ediv(amount, activeSupply)`
  is wrapped in `unwrap_some` after an `assert activeSupply > 0`
  guard — so the contract reverts cleanly on a deposit before the
  oracle reconciles any holders (no panic, no silent loss).
- **Claim settles `lastSeenAcc` BEFORE `sp.send`.** Reentrancy belt-
  and-suspenders: even though Tezos's transfer semantics make a real
  reentrancy unlikely here, the storage write happens first.
- **Push-payout failure mode.** `pushPayouts` does multiple `sp.send`s
  in one op. If any recipient rejects tez, the whole op reverts and
  none of the listed addresses get paid. Mitigations:
    - Operator script splits the address list into smaller batches
      to isolate a bad address.
    - For a contract-holder that rejects tez and can't `claim()`
      either, the oracle can reassign that token to the burn
      sentinel — the share stops moving and the loss is contained
      to that single NFT until it changes hands.
  Considered routing failed sends back to a `pending` queue
  programmatically, but Michelson has no try/catch — the only way
  to "catch" is to pre-check via `sp.contract(unit, addr)` and skip
  unknown contracts. That introduces a new attack surface (`sp.
  contract` revert paths). Operator-side filtering is the cheaper
  defense.
- **`batchUpdateOwner` gas-bounded.** Asserts `len(updates) <=
  MAX_BATCH (50)`. Settles each entry's old owner before reassign,
  so a 50-update batch reuses the per-update settlement pattern that
  `updateOwner` validated.
- **`sweepDust` recipient is a parameter.** Not `sp.sender`. Every
  sweep is auditable on tzkt with the destination address visible.
  Recommend pointing it at a multisig or operator pot (TBD,
  document the chosen target before mainnet).
- **First-touch creates the entry.** v2's lazy-create design means
  any txlId the oracle passes to `updateOwner` will be created if
  not present. We considered hardcoding a 271-element valid-IDs set
  to guard against typos/oracle-compromise, but:
    1. SmartPy 0.20 can't bake a 271-element `sp.set` in @sp.module
       __init__ (same dict-comprehension/literal-only constraint
       that drove the lazy-create design).
    2. A compromised oracle can already do worse things (drain
       active holders' shares by mass-reassigning to attacker
       addresses). The phantom-ID risk is a strict subset.
  Operationally, the reconcile script reads its token universe
  from a hardcoded list mirroring `txlOwners.js`, so it can't
  accidentally pass a bogus ID.

### Blocking before mainnet origination

- [ ] Generate a NEW `TXL_ORACLE_MNEMONIC` for mainnet — do not reuse
      the shadownet mnemonic, and do not reuse the v1 mnemonic.
- [ ] Replace `DEFAULT_ORACLE` in `src/services/smart_contract_txl.py`
      with the mainnet-only tz1.
- [ ] Decide the `sweepDust` recipient and document in
      `docs/TXL_MAINNET_RUNBOOK.md`.
- [ ] Decide the operator's push-payout script chunk size + ordering
      strategy (see runbook).
- [ ] Pause-test on shadownet: pause → confirm default/claim/push
      revert → unpause.
- [ ] Owner-change settlement test on shadownet: assign A → deposit →
      reassign to B → confirm A's accrual settles into `pending[A]`,
      B's `lastSeenAcc` = accPerToken (B doesn't backfill A's share).

**Acceptance for v2**: documented as the trust assumption in the
contract's docstring (lines 1-23) and `setAxes` body comment (line
278-279). No code change required for this batch.

### SQ-2 [MED] — `refundUnsold` is O(100); gas budget unverified at sellout

**File**: `smart_contract_squares_v2.py`, `refundUnsold` (lines 382-401).

The entrypoint unrolls `for i in range(100)` and, for each owned cell,
writes a `pending` big_map entry. Worst case is 98 owned cells across
~98 distinct buyers, which is ~98 big_map UPDATEs + the per-iteration
MEM check on `game.squares`. Whether that fits inside Tezos' per-op
gas budget (~1.04 Mgas) and storage budget (~60 KB) at the worst-case
fill has not been measured.

**Empirical verification required before mainnet**:

```
# 1. Originate a fresh shadownet game and buy it out across as many
#    distinct buyers as practical (emulate_squares.py uses 2; a stress
#    harness could spin up 8-10 disposable wallets via
#    scripts/new_test_wallet.py to be more representative).
# 2. Pause the live reportQuarter path (the worker, or just don't
#    setAxes) so the game sits in PHASE_LOCKED, refundUnsold-eligible.
# 3. Admin calls refundUnsold(gameId=N). Observe the receipt:
.venv/bin/python - <<'PY'
from pytezos import pytezos, Key
import os, pathlib
for raw in pathlib.Path('.env').read_text().splitlines():
    if '=' in raw and not raw.strip().startswith('#'):
        k, v = raw.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
key = Key.from_mnemonic(os.environ['DEPLOY_MNEMONIC'].split())
p = pytezos.using(shell='https://rpc.shadownet.teztnets.com', key=key)
addr = '<SQUARES_CONTRACT_ADDRESS_SHADOWNET>'
op = p.contract(addr).refundUnsold(gameId=0).send(min_confirmations=1)
print('consumed_milligas:', op.opg_result['contents'][0]['metadata']
      ['operation_result']['consumed_milligas'])
print('paid_storage_size_diff:', op.opg_result['contents'][0]['metadata']
      ['operation_result']['paid_storage_size_diff'])
PY
```

If `consumed_milligas` lands above ~800_000 (80% of the per-op limit) at
worst-case fill, escalate to **HIGH** and chunk the refund:

**Proposed fix (only if test fails)**: split into
`refundUnsoldRange(gameId, fromIdx, toIdx)` so admin can refund in
batches of e.g. 20-30 cells per op. No player impact — each batch
credits the same `pending` entries, and `claim()` works irrespective of
which op credited it.

### SQ-3 [LOW] — `createGame` is unmetered; storage-bloat DoS is self-paying

`createGame` is open to anyone (by design — the docstring calls this
out) and takes no fee. Each call writes a non-trivial game record into
the `games` big_map (record + nested maps + 9-slot `quarterReported`
initialiser). A motivated attacker could spam many empty games to
bloat the big_map.

Why this is LOW: `games` IS a big_map, so storage cost is paid by the
caller per insertion via Tezos' storage-burn mechanism (~250 µꜩ/byte).
Spamming 1 000 empty games would cost the attacker on the order of
ones-of-ꜩ for no payoff — the per-call burn IS the rate limiter. No
honest user is affected; the chain doesn't notice.

**Mitigation** (only if we ever see abuse): add a small required
`amount` on `createGame` that routes to the TXL distributor (same path
as `holderFee`), or gate the entrypoint behind admin pre-approval. Not
in v2.

### SQ-4 [LOW] — `currentGameId` overflow at realistic volume

The audit prompt asked. Confirmed safe: `sp.nat` compiles to
Michelson's `nat`, which is arbitrary-precision unsigned. At any
realistic event volume (e.g. 200 pools/year) the counter never gets
close to anything interesting. No action.

### SQ-5 [LOW] — house cells hardcoded as indices 44 + 90

`buySquare` rejects `squareIdx ∈ {44, 90}` via two literal asserts
(lines 216-217). The set has to be kept in lockstep with `HOUSE_SQUARES`
in `src/components/squaresGame.vue`. If the UI ever introduces a third
house cell, the contract must be redeployed — there's no admin
entrypoint to update the set.

Acceptable today (the cells were chosen visually for the centre+
bottom-left and aren't expected to change). If you ever want a
configurable house-cell list, lift it to storage with an admin updater.

### SQ-6 [INFO] — `paused` is intentionally selective

`paused` gates `createGame`, `buySquare`, and `reportQuarter`. It does
NOT gate `closeSales`, `setAxes`, `refundUnsold`, `claim`, or the admin
updaters. Intentional: a circuit-breaker should halt **new** game
inflow and **scoring**, but leave admin able to operationally manage
locked games (close + refund) and leave already-credited winners able
to withdraw their `pending` balance. Document in the incident-runbook
when one is written.

---

## Verification matrix

After all HIGH/MED fixes deploy, run:

```bash
# Compile every changed contract:
python src/services/smart_contractAD.py
python src/services/smart_contractPlinko.py
python src/services/smart_contract_TTT.py

# Copy artifacts into contracts/<id>/
for c in acey-duecey plinko ttt; do
  ...
done

# Deploy each:
./scripts/deploy.py acey-duecey --network shadownet
./scripts/deploy.py plinko --network shadownet
./scripts/deploy.py ttt --network shadownet

# Restart the oracle worker so it picks up the new addresses:
./scripts/oracle-worker.sh &

# Run the end-to-end exercise harness:
.venv/bin/python scripts/exercise_contracts.py --game ad
.venv/bin/python scripts/exercise_contracts.py --game plinko
.venv/bin/python scripts/exercise_contracts.py --game ttt   # needs DEPLOY_MNEMONIC_2
```

Each scenario must return exit code 0. If anything fails, that's the
signal to dig in — don't merge until all three pass.

Human-only steps:

- **Sanity-check Plinko payouts** by dropping a few balls at different
  multipliers and confirming the math against the published rake table.
- **Sanity-check AD pair handling** by dealing a known pair (oracle
  worker has the keys to do this; just submit the same card index twice).
- **Sanity-check TTT timeout** by setting `staleBlocks=5` temporarily
  and confirming `claimByTimeout` works at block N+5 but not N+4.

Once verified, bump the source-of-truth contract addresses in any
external docs (the public-facing site, the dApp's "About" page) and
tag the release commit `v0.3-security`.
