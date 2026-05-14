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
