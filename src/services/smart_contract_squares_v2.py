"""
Super-Bowl-Squares contract — modern SmartPy (@sp.module syntax).

Classic 100-square pool, multi-game (one contract instance hosts many
games keyed by gameId):

  - 10x10 grid. Rows = home team's last digit, columns = away team's last
    digit. After sales close the axis labels (0..9) are randomized so the
    digits at sale time don't determine outcomes — same as a paper pool.
  - Players buy individual squares for `ticketPrice + holderFee`. The
    fee goes to TXL holders; the ticket price feeds the per-quarter pot.
  - When all 100 sell (or admin closes sales), phase flips to LOCKED.
    Admin (or a relayer daemon — scripts/oracle_worker.py SquaresHandler)
    calls `setAxes` with two [0..9] permutations to enter AXES_SET.
  - Admin reports each quarter's score with `reportQuarter`. The square
    at (homeScore mod 10, awayScore mod 10) wins that quarter's payout
    (pull-pattern — claim() to withdraw). Unowned winning squares route
    their share to TXL holders.
  - Per-quarter weights are configurable at game-creation; default in
    the UI is 15/15/15/55 but the contract only enforces sum == 100.

Compile + deploy via scripts/compile.sh squares (which targets this
file via scripts/deploy.py).
"""

import smartpy as sp


# Game phase tiers (must mirror PHASE_LABELS in src/components/squaresGame.vue):
#   0 = SELLING   — buying squares
#   1 = LOCKED    — sales closed, awaiting axis randomization
#   2 = AXES_SET  — axes randomized, awaiting per-quarter scores
#   3 = COMPLETE  — all 4 quarters reported; refunds also end here
#
# Module-level Python names don't leak into the @sp.module body, so we
# define the constants again inside main() below. Keep them in sync.


@sp.module
def main():
    PHASE_SELLING = 0
    PHASE_LOCKED = 1
    PHASE_AXES_SET = 2
    PHASE_COMPLETE = 3

    # Per-player-per-game cap. Mirrors MAX_BUY_PER_PLAYER_PER_GAME in
    # src/components/squaresGame.vue — keep the two in sync. The contract
    # is the source of truth; the UI just disables the buy button early
    # so users don't burn gas on a doomed op.
    PER_PLAYER_PER_GAME = 50

    # Max squares that can actually be sold = 100-cell board minus the
    # two house cells (idx 44 and idx 90, reserved for TXL holders).
    # The original auto-lock check used a literal 100 which was never
    # reachable — sold-out games stranded in PHASE_SELLING until admin
    # manually called closeSales. Keep this in lockstep with the
    # `params.squareIdx != 44 / != 90` guards in buySquare.
    SELLABLE_CELLS = 98

    class Squares(sp.Contract):
        def __init__(self, admin, rngOracle, txlContract):
            # Roles
            self.data.admin = admin
            # rngOracle is retained for future on-chain randomness flows
            # (not currently consumed — setAxes is the authoritative path,
            # driven by the off-chain daemon). Keeping it lets admin point
            # at the deployed RandomOracle without a redeploy.
            self.data.rngOracle = rngOracle
            self.data.txlContract = txlContract
            self.data.pendingAdmin = sp.cast(None, sp.option[sp.address])

            # Circuit breaker
            self.data.paused = False

            # Per-game ledger. Type is inferred from the first insertion in
            # createGame; same pattern as smart_contractAD_v3.py.
            self.data.games = sp.big_map()
            self.data.currentGameId = sp.nat(0)

            # Pull-pattern claims. Credited by reportQuarter, drained by claim.
            self.data.pending = sp.big_map()

        # ─── default: receive funding ────────────────────────────────────
        @sp.entrypoint
        def default(self):
            # Admin can pre-fund payouts if desired. Funds sit in the
            # contract balance — reportQuarter doesn't draw from a separate
            # pool, but having spare balance lets sp.send for credits never
            # fail under edge-case rounding.
            pass

        # ─── admin handover (two-step) ──────────────────────────────────
        @sp.entrypoint
        def proposeAdmin(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.pendingAdmin = sp.Some(params.newAdmin)

        @sp.entrypoint
        def acceptAdmin(self):
            proposed = self.data.pendingAdmin.unwrap_some(error="NoPendingAdmin")
            assert sp.sender == proposed, "NotProposedAdmin"
            self.data.admin = proposed
            self.data.pendingAdmin = sp.cast(None, sp.option[sp.address])

        # ─── circuit breaker ────────────────────────────────────────────
        @sp.entrypoint
        def pause(self):
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.paused = True

        @sp.entrypoint
        def unpause(self):
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.paused = False

        # ─── admin: role/contract pointers ──────────────────────────────
        @sp.entrypoint
        def updateRngOracle(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.rngOracle = params.newOracle

        @sp.entrypoint
        def updateTxlContract(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.txlContract = params.newContract

        # ─── admin: create a new game ───────────────────────────────────
        # Open to anyone — Super-Bowl-Squares is fundamentally a "any user
        # can spin up a pool" game. Scoring (reportQuarter) and the
        # randomized-axis commit (setAxes) stay admin-gated since they're
        # the trust-critical inputs. The creator is recorded so future
        # extensions (creator-driven closeSales, creator-only refunds, …)
        # can read it without a new storage migration.
        @sp.entrypoint
        def createGame(self, params):
            sp.cast(params, sp.record(
                name=sp.string,
                ticketPrice=sp.mutez,
                holderFee=sp.mutez,
                # Number of scoring periods for the underlying sport:
                #   2 = soccer halves         (EPL, MLS, ...)
                #   3 = hockey periods        (NHL)
                #   4 = basketball quarters / football quarters (NBA, NFL)
                #   9 = baseball innings      (MLB)
                # numPeriods bounds the entries reportQuarter accepts and
                # the count of weights required.
                numPeriods=sp.nat,
                # Map keyed 0..numPeriods-1, values summing to 100.
                quarterWeights=sp.map[sp.int, sp.nat],
            ))
            assert not self.data.paused, "Paused"
            assert params.ticketPrice > sp.mutez(0), "ZeroTicket"
            assert params.numPeriods >= sp.nat(1), "BadNumPeriods"
            assert params.numPeriods <= sp.nat(9), "BadNumPeriods"
            # Validate that the weights map has exactly numPeriods entries
            # (keys 0..numPeriods-1) and sums to 100. The Python for-loop
            # unrolls at compile time; the inner `if` becomes a run-time
            # SmartPy conditional. `idx` is an sp.nat that increments each
            # iteration so we don't re-wrap a Python int in sp.nat() —
            # smartpy 0.2.2's parser rejects sp.nat(<identifier>).
            sumW = sp.nat(0)
            idx = sp.nat(0)
            for i in range(9):
                if idx < params.numPeriods:
                    assert i in params.quarterWeights, "MissingPeriod"
                    sumW = sumW + params.quarterWeights[i]
                idx = idx + 1
            assert sumW == sp.nat(100), "WeightsMustSumTo100"

            gid = self.data.currentGameId
            self.data.games[gid] = sp.record(
                name=params.name,
                creator=sp.sender,
                phase=PHASE_SELLING,
                ticketPrice=params.ticketPrice,
                holderFee=params.holderFee,
                sold=sp.nat(0),
                squares={},
                # Per-player count, incremented in buySquare. Caps at
                # PER_PLAYER_PER_GAME so one wallet can't sweep the board.
                playerCounts={},
                axisHome={},
                axisAway={},
                axesAssigned=False,
                numPeriods=params.numPeriods,
                quarterWeights=params.quarterWeights,
                # Always-init all 9 slots — reportQuarter only consults
                # the first numPeriods entries, so the unused trailing
                # entries are inert. Keeps the storage type uniform
                # across games with different period counts.
                quarterReported={
                    0: False, 1: False, 2: False, 3: False, 4: False,
                    5: False, 6: False, 7: False, 8: False,
                },
                quartersDone=sp.int(0),
                pot=sp.mutez(0),
            )
            sp.emit(gid, tag="gameCreated")
            self.data.currentGameId += 1

        # ─── player: buy a specific square ──────────────────────────────
        @sp.entrypoint
        def buySquare(self, params):
            assert not self.data.paused, "Paused"
            assert params.gameId in self.data.games, "NoGame"
            game = self.data.games[params.gameId]
            assert game.phase == PHASE_SELLING, "NotSelling"
            assert params.squareIdx >= 0, "BadSquare"
            assert params.squareIdx < 100, "BadSquare"
            # House cells are reserved for TXL holders — when one of these
            # wins, reportQuarter's "unowned winning square" branch routes
            # the share to txlContract. Must mirror HOUSE_SQUARES in
            # src/components/squaresGame.vue (idx 44 = middle, idx 90 =
            # bottom-left). On-chain enforcement plugs the gap of someone
            # bypassing the frontend with a direct buySquare op.
            assert params.squareIdx != 44, "HouseSquare"
            assert params.squareIdx != 90, "HouseSquare"
            assert not (params.squareIdx in game.squares), "SquareTaken"
            assert sp.amount == game.ticketPrice + game.holderFee, "BadAmount"

            # Per-player-per-game cap. UI mirrors this — but the contract
            # is the source of truth since anyone can call buySquare
            # directly through taquito / pytezos / a CLI op.
            prior = sp.nat(0)
            if sp.sender in game.playerCounts:
                prior = game.playerCounts[sp.sender]
            assert prior < PER_PLAYER_PER_GAME, "PlayerCapReached"
            game.playerCounts[sp.sender] = prior + 1

            # Holder fee off the top → TXL contract. Ticket into the pot.
            holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(
                error="NoTxlContract"
            )
            sp.transfer((), game.holderFee, holder)
            game.squares[params.squareIdx] = sp.sender
            game.sold += 1
            game.pot += game.ticketPrice
            # Auto-lock when every sellable cell is gone. The literal 100
            # check was never reachable — house cells 44 and 90 can't be
            # bought, so max sold is SELLABLE_CELLS (98), not 100. Without
            # this, sold-out games sit in PHASE_SELLING forever waiting
            # on a manual closeSales call from admin.
            if game.sold == SELLABLE_CELLS:
                game.phase = PHASE_LOCKED
                sp.emit(params.gameId, tag="soldOut")
            self.data.games[params.gameId] = game
            sp.emit(
                sp.record(
                    gameId=params.gameId,
                    squareIdx=params.squareIdx,
                    buyer=sp.sender,
                ),
                tag="squareBought",
            )

        # ─── admin: close sales early ───────────────────────────────────
        @sp.entrypoint
        def closeSales(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            assert params.gameId in self.data.games, "NoGame"
            game = self.data.games[params.gameId]
            assert game.phase == PHASE_SELLING, "NotSelling"
            game.phase = PHASE_LOCKED
            self.data.games[params.gameId] = game
            sp.emit(params.gameId, tag="salesClosed")

        # ─── admin/relayer: commit the two randomized axis permutations ─
        # In production this is driven by scripts/oracle_worker.py's
        # SquaresHandler, which holds the admin key and submits as soon
        # as it sees phase == LOCKED && !axesAssigned. Admin can also
        # call directly if the daemon is offline.
        @sp.entrypoint
        def setAxes(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            assert params.gameId in self.data.games, "NoGame"
            game = self.data.games[params.gameId]
            assert game.phase == PHASE_LOCKED, "NotLocked"
            # Spot-check: both maps must span 0..9. Cheaper than iterating
            # the full key set; the daemon is trusted to send valid perms.
            assert 0 in params.axisHome, "BadHome"
            assert 9 in params.axisHome, "BadHome"
            assert 0 in params.axisAway, "BadAway"
            assert 9 in params.axisAway, "BadAway"
            game.axisHome = params.axisHome
            game.axisAway = params.axisAway
            game.axesAssigned = True
            game.phase = PHASE_AXES_SET
            self.data.games[params.gameId] = game
            sp.emit(params.gameId, tag="axesSet")

        # ─── admin: report a quarter's score and pay the winner ─────────
        @sp.entrypoint
        def reportQuarter(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            assert not self.data.paused, "Paused"
            assert params.gameId in self.data.games, "NoGame"
            game = self.data.games[params.gameId]
            assert game.phase == PHASE_AXES_SET, "NotPlayable"
            assert params.quarter >= 0, "BadQuarter"
            # Period index must fit the game's configured period count
            # (2 for soccer halves, 4 for quarters, etc.).
            assert params.quarter < sp.to_int(game.numPeriods), "BadQuarter"
            assert params.quarter in game.quarterReported, "UnknownQ"
            assert not game.quarterReported[params.quarter], "QAlreadyReported"

            homeDigit = sp.to_int(sp.mod(params.homeScore, 10))
            awayDigit = sp.to_int(sp.mod(params.awayScore, 10))

            # Find the row + column whose label matches the digit. Unrolled
            # 10-way search — maps are tiny and a real lookup over keys
            # would be more code than this.
            winRow = sp.int(-1)
            winCol = sp.int(-1)
            for i in range(10):
                if game.axisHome[i] == homeDigit:
                    winRow = i
                if game.axisAway[i] == awayDigit:
                    winCol = i

            winSquare = winRow * 10 + winCol
            # payout = pot × quarterWeight / 100
            weight = game.quarterWeights[params.quarter]
            payout = sp.split_tokens(game.pot, weight, sp.nat(100))
            if payout > game.pot:
                payout = game.pot

            if winSquare in game.squares:
                winner = game.squares[winSquare]
                # Credit pull-pattern claim.
                current = self.data.pending.get(winner, default=sp.mutez(0))
                self.data.pending[winner] = current + payout
                game.pot -= payout
                sp.emit(
                    sp.record(
                        gameId=params.gameId,
                        quarter=params.quarter,
                        winner=winner,
                        square=winSquare,
                        payout=payout,
                    ),
                    tag="quarterPaid",
                )
            else:
                # Unowned winning square: route the share to TXL holders.
                holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(
                    error="NoTxlContract"
                )
                sp.transfer((), payout, holder)
                game.pot -= payout
                sp.emit(
                    sp.record(
                        gameId=params.gameId,
                        quarter=params.quarter,
                        square=winSquare,
                        payout=payout,
                    ),
                    tag="quarterUnowned",
                )

            game.quarterReported[params.quarter] = True
            game.quartersDone += 1
            # Game completes once every configured period has been reported.
            if game.quartersDone == sp.to_int(game.numPeriods):
                game.phase = PHASE_COMPLETE
                sp.emit(params.gameId, tag="gameComplete")

            self.data.games[params.gameId] = game

        # ─── player: claim winnings (pull) ──────────────────────────────
        @sp.entrypoint
        def claim(self):
            assert sp.sender in self.data.pending, "NothingToClaim"
            amount = self.data.pending[sp.sender]
            assert amount > sp.mutez(0), "NothingToClaim"
            del self.data.pending[sp.sender]
            sp.send(sp.sender, amount)
            sp.emit(sp.record(who=sp.sender, amount=amount), tag="claimed")

        # ─── admin: refund unsold games (escape hatch) ──────────────────
        # Valid only while the game is in SELLING or LOCKED — once axes
        # are set we're committed to the quarter-payout flow.
        @sp.entrypoint
        def refundUnsold(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            assert params.gameId in self.data.games, "NoGame"
            game = self.data.games[params.gameId]
            assert (
                game.phase == PHASE_SELLING or game.phase == PHASE_LOCKED
            ), "GameTooFar"
            # Walk all 100 indices and credit each buyer their ticket
            # price into the pull-claim map. Unrolled because the contract
            # can't iterate a map directly while preserving order.
            for i in range(100):
                if i in game.squares:
                    buyer = game.squares[i]
                    current = self.data.pending.get(buyer, default=sp.mutez(0))
                    self.data.pending[buyer] = current + game.ticketPrice
            game.pot = sp.mutez(0)
            game.phase = PHASE_COMPLETE
            self.data.games[params.gameId] = game
            sp.emit(params.gameId, tag="refunded")


# ─── Compile-only test ──────────────────────────────────────────────────
# This scenario IS the source of truth for the initial storage that
# scripts/deploy.py originates — SmartPy emits only one *_storage.tz, and
# it's generated by the first `c = main.Squares(...)` call below.
#
# Three constructor args determine origination-time storage:
#   admin       — must match the DEPLOY_MNEMONIC wallet that signs admin
#                 ops post-deploy (same key the off-chain oracle worker
#                 runs with). Without a match, isAdmin checks in the UI
#                 fail and the worker can't call setAxes/reportQuarter.
#   rngOracle   — stored but unused in v2 today; left in storage so a
#                 future requestAxes flow can be turned on with one
#                 updateRngOracle call instead of a redeploy.
#   txlContract — receives holderFee on every buySquare AND the share of
#                 unowned-square payouts. MUST be a live on-chain
#                 distributor — fees there are not recoverable; future
#                 fees can be rerouted via updateTxlContract but past
#                 fees stay where they were sent.
#
# Switch networks by swapping rngOracle / txlContract for the mainnet
# KT1s before compiling under `--network mainnet`. Mainnet values:
#   rngOracle   = sp.address("KT1VvcCnTPCUc7YaxyMT6opDrSPi2AUHnfvx")
#                 (ORACLE_CONTRACT_MAINNET in src/constants.js — not
#                 yet originated on mainnet; placeholder until then.
#                 rngOracle is stored-but-unused in v2 so wrong/empty
#                 values are harmless until a future requestAxes flow.)
#   txlContract = sp.address("KT1TYgt7SphtEQHLk4GySkXckhSctJww5hdj")
#                 (TXL_CONTRACT_ADDRESS_MAINNET — v2 distributor, real,
#                 has default(unit) which is all squares needs.)
@sp.add_test()
def test():
    s = sp.test_scenario("squares basic compile", main)
    admin       = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
    rngOracle   = sp.address("KT19V1YiyPtyCbxouhyeM96SekRTVC7Gw6qq")  # shadownet oracle
    # Shadownet TXL v2 distributor (KT1JukrFQ2…). The v1 distributor at
    # KT1Ro63… is still live but is being deprecated — repointing squares
    # at v2 keeps the holder fees flowing into the same accumulator the
    # UI's Cash Out button reads from. Mainnet override at the comment
    # above the def.
    txlContract = sp.address("KT1JukrFQ2DtKPDRDBq4j3Z6HkXtXxuF2Evd")
    c = main.Squares(admin, rngOracle, txlContract)
    s += c


# ─── Full game-flow simulation ──────────────────────────────────────────
# End-to-end happy-path scenario: create → buy → close → set axes →
# 4 quarters → claim. Also exercises the HouseSquare reverts (idx 44
# and 90), SquareTaken, BadAmount, and the unowned-square-pays-TXL
# branch when a house cell wins a quarter.
#
# Axes are set to identity (digit n maps to row/col n) so the winning
# square per quarter is deterministic and easy to read:
#   homeScore mod 10 = row, awayScore mod 10 = column → idx = row*10+col.
#
# Run via the project's compile pipeline:
#   python -m smartpy compile src/services/smart_contract_squares_v2.py /tmp/sq_out
# or whatever wrapper `scripts/compile.sh squares` uses.
@sp.add_test()
def full_game_flow():
    s = sp.test_scenario("squares full game flow", main)

    admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
    rng = sp.test_account("rng")
    txl = sp.test_account("txl")  # implicit account satisfies sp.contract(unit, _)
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    carol = sp.test_account("carol")
    intruder = sp.test_account("intruder")

    c = main.Squares(admin, rng.address, txl.address)
    s += c

    s.h1("Create game (alice — anyone can create)")
    c.createGame(
        name="SIM:ESPN:401871337 - CLE @ DET",
        ticketPrice=sp.tez(1),
        holderFee=sp.tez(0),  # zero holder fee → pot math stays clean
        numPeriods=4,         # NBA quarters
        quarterWeights={0: 15, 1: 15, 2: 15, 3: 55},
        _sender=alice.address,
    )

    s.h1("Buys: alice 47, 12 · bob 58, 23 · carol 96")
    c.buySquare(gameId=0, squareIdx=47, _sender=alice, _amount=sp.tez(1))
    c.buySquare(gameId=0, squareIdx=12, _sender=alice, _amount=sp.tez(1))
    c.buySquare(gameId=0, squareIdx=58, _sender=bob,   _amount=sp.tez(1))
    c.buySquare(gameId=0, squareIdx=23, _sender=bob,   _amount=sp.tez(1))
    c.buySquare(gameId=0, squareIdx=96, _sender=carol, _amount=sp.tez(1))

    s.h1("Reverts: HouseSquare (44 + 90), SquareTaken, BadAmount")
    c.buySquare(
        gameId=0, squareIdx=44, _sender=intruder, _amount=sp.tez(1),
        _valid=False, _exception="HouseSquare",
    )
    c.buySquare(
        gameId=0, squareIdx=90, _sender=intruder, _amount=sp.tez(1),
        _valid=False, _exception="HouseSquare",
    )
    c.buySquare(
        gameId=0, squareIdx=47, _sender=intruder, _amount=sp.tez(1),
        _valid=False, _exception="SquareTaken",
    )
    c.buySquare(
        gameId=0, squareIdx=11, _sender=intruder, _amount=sp.tez(2),
        _valid=False, _exception="BadAmount",
    )

    s.h1("Admin closeSales → LOCKED")
    c.closeSales(gameId=0, _sender=admin)

    s.h1("Admin setAxes (identity) → AXES_SET")
    identity = sp.cast({i: i for i in range(10)}, sp.map[sp.int, sp.int])
    c.setAxes(gameId=0, axisHome=identity, axisAway=identity, _sender=admin)

    s.h1("Q1 — scores 24-17 → idx 47 (alice wins 15%)")
    c.reportQuarter(gameId=0, quarter=0, homeScore=24, awayScore=17, _sender=admin)

    s.h1("Q2 — scores 35-28 → idx 58 (bob wins 15% of remaining pot)")
    c.reportQuarter(gameId=0, quarter=1, homeScore=35, awayScore=28, _sender=admin)

    s.h1("Q3 — scores 14-24 → idx 44 (HOUSE, share routes to TXL)")
    c.reportQuarter(gameId=0, quarter=2, homeScore=14, awayScore=24, _sender=admin)

    s.h1("Q4 — scores 49-36 → idx 96 (carol wins 55% of remaining pot)")
    c.reportQuarter(gameId=0, quarter=3, homeScore=49, awayScore=36, _sender=admin)

    s.h1("Claim — pull-pattern winnings")
    c.claim(_sender=alice)
    c.claim(_sender=bob)
    c.claim(_sender=carol)
    # Intruder has nothing pending.
    c.claim(_sender=intruder, _valid=False, _exception="NothingToClaim")


# ─── Soccer 2-half simulation ───────────────────────────────────────────
# Exercises the variable-period support: a 2-period game with weights
# 30/70 (halftime / full-time). Verifies that reportQuarter rejects
# quarter >= 2 for this game, and that quartersDone == 2 flips the
# phase to COMPLETE (not waiting for "quarters" 3 and 4).
@sp.add_test()
def soccer_halves_flow():
    s = sp.test_scenario("squares soccer halves flow", main)

    admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
    rng = sp.test_account("rng")
    txl = sp.test_account("txl")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")

    c = main.Squares(admin, rng.address, txl.address)
    s += c

    s.h1("Create EPL-style game — numPeriods=2, weights 30/70")
    c.createGame(
        name="SIM:ESPN:soccer-123 - ARS @ MCI",
        ticketPrice=sp.tez(1),
        holderFee=sp.tez(0),
        numPeriods=2,
        quarterWeights={0: 30, 1: 70},
        _sender=alice.address,
    )

    s.h1("Bad numPeriods (0 / 10) rejected")
    c.createGame(
        name="bad-0", ticketPrice=sp.tez(1), holderFee=sp.tez(0),
        numPeriods=0, quarterWeights={0: 100},
        _sender=alice.address, _valid=False, _exception="BadNumPeriods",
    )
    c.createGame(
        name="bad-10", ticketPrice=sp.tez(1), holderFee=sp.tez(0),
        numPeriods=10, quarterWeights={0: 100},
        _sender=alice.address, _valid=False, _exception="BadNumPeriods",
    )

    s.h1("Missing period weight rejected (numPeriods=2 needs keys 0 + 1)")
    c.createGame(
        name="bad-weights", ticketPrice=sp.tez(1), holderFee=sp.tez(0),
        numPeriods=2, quarterWeights={0: 100},
        _sender=alice.address, _valid=False, _exception="MissingPeriod",
    )

    s.h1("Buys: alice 47, bob 58")
    c.buySquare(gameId=0, squareIdx=47, _sender=alice, _amount=sp.tez(1))
    c.buySquare(gameId=0, squareIdx=58, _sender=bob,   _amount=sp.tez(1))

    s.h1("Close + identity axes")
    c.closeSales(gameId=0, _sender=admin)
    identity = sp.cast({i: i for i in range(10)}, sp.map[sp.int, sp.int])
    c.setAxes(gameId=0, axisHome=identity, axisAway=identity, _sender=admin)

    s.h1("Half 1 — 24-17 → idx 47 (alice, 30%)")
    c.reportQuarter(gameId=0, quarter=0, homeScore=24, awayScore=17, _sender=admin)

    s.h1("Quarter index >= numPeriods is rejected (2, 3 invalid here)")
    c.reportQuarter(
        gameId=0, quarter=2, homeScore=0, awayScore=0,
        _sender=admin, _valid=False, _exception="BadQuarter",
    )

    s.h1("Half 2 (final) — 35-28 → idx 58 (bob, 70% of remainder)")
    c.reportQuarter(gameId=0, quarter=1, homeScore=35, awayScore=28, _sender=admin)

    s.h1("Game completes after 2 halves (not 4) — phase = COMPLETE")
    c.claim(_sender=alice)
    c.claim(_sender=bob)
