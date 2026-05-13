"""
Super-Bowl-Squares contract — legacy SmartPy syntax.

Classic 100-square pool:
  - 10x10 grid. Rows = home team's last digit, columns = away team's last digit.
  - Players buy squares for a fixed `ticketPrice`.
  - When all 100 are sold (or admin closes), the axis labels (0..9) are
    randomized via the unified RNG oracle. Each row/col is mapped to one
    of 0..9 — same random permutation logic as a real Squares pool, where
    the digits are drawn after sales close.
  - Admin reports the score at the end of each quarter. The square whose
    (row_digit, col_digit) matches (home_score % 10, away_score % 10) wins
    that quarter's payout.
  - Per-quarter weights default to 15% / 15% / 15% / 55% but are
    configurable at game-creation.
  - Pull-pattern claim — winners call `claim()` to withdraw.

Multi-game: one contract instance, many games keyed by `gameId`. Each game
has its own grid, axis assignment, scores, and payouts.

Compile + test:
    docker run --rm -v "$PWD":/work -w /work \\
      bakingbad/smartpy-cli:latest \\
      test src/services/smart_contract_squares_v2.py src/services/build/squares/
"""

import smartpy as sp


# Game phases:
#   0 = SELLING   (buying squares)
#   1 = LOCKED    (sales closed, awaiting axis randomization)
#   2 = AXES_SET  (axes randomized, awaiting kickoff / scores)
#   3 = COMPLETE  (all 4 quarters reported, no more payouts)
PHASE_SELLING = 0
PHASE_LOCKED = 1
PHASE_AXES_SET = 2
PHASE_COMPLETE = 3


class Squares(sp.Contract):
    def __init__(self, admin, rngOracle, txlContract):
        self.init(
            # Roles
            admin=admin,
            rngOracle=rngOracle,            # KT1 of the unified RNG oracle
            txlContract=txlContract,        # holder distribution
            pendingAdmin=sp.none,

            # Circuit breaker
            paused=False,

            # Per-game ledger
            games=sp.big_map(
                tkey=sp.TNat,
                tvalue=sp.TRecord(
                    name=sp.TString,
                    creator=sp.TAddress,
                    phase=sp.TInt,
                    ticketPrice=sp.TMutez,
                    holderFee=sp.TMutez,            # taken on each ticket → TXL
                    sold=sp.TNat,                    # 0..100
                    # squares: idx (0..99) = row*10 + col → owner address
                    squares=sp.TMap(sp.TInt, sp.TAddress),
                    # axisHome[i] = digit assigned to row i (home team's mod-10)
                    axisHome=sp.TMap(sp.TInt, sp.TInt),
                    axisAway=sp.TMap(sp.TInt, sp.TInt),
                    axesAssigned=sp.TBool,
                    # quarterWeights[q] = numerator out of 100 (sums to ≤100)
                    quarterWeights=sp.TMap(sp.TInt, sp.TNat),
                    # quarterReported[q] = True once admin reported scores
                    quarterReported=sp.TMap(sp.TInt, sp.TBool),
                    quartersDone=sp.TInt,
                    pot=sp.TMutez,                   # ticketPrice × sold − fees
                    rngTag=sp.TString,               # RNG oracle request tag
                ),
            ),
            currentGameId=sp.nat(0),

            # Pending claims (pull pattern)
            pending=sp.big_map(tkey=sp.TAddress, tvalue=sp.TMutez),
        )

    # ─── helpers ──────────────────────────────────────────────────────────
    def _onlyAdmin(self):
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")

    def _notPaused(self):
        sp.verify(~self.data.paused, message="Paused")

    def _credit(self, who, amount):
        current = self.data.pending.get(who, default_value=sp.mutez(0))
        self.data.pending[who] = current + amount

    # ─── admin lifecycle ─────────────────────────────────────────────────
    @sp.entry_point
    def proposeAdmin(self, params):
        sp.set_type(params, sp.TRecord(newAdmin=sp.TAddress))
        self._onlyAdmin()
        self.data.pendingAdmin = sp.some(params.newAdmin)

    @sp.entry_point
    def acceptAdmin(self):
        proposed = self.data.pendingAdmin.open_some(message="NoPendingAdmin")
        sp.verify(sp.sender == proposed, message="NotProposedAdmin")
        self.data.admin = proposed
        self.data.pendingAdmin = sp.none

    @sp.entry_point
    def pause(self):
        self._onlyAdmin()
        self.data.paused = True

    @sp.entry_point
    def unpause(self):
        self._onlyAdmin()
        self.data.paused = False

    @sp.entry_point
    def updateRngOracle(self, params):
        sp.set_type(params, sp.TRecord(newOracle=sp.TAddress))
        self._onlyAdmin()
        self.data.rngOracle = params.newOracle

    @sp.entry_point
    def updateTxlContract(self, params):
        sp.set_type(params, sp.TRecord(newContract=sp.TAddress))
        self._onlyAdmin()
        self.data.txlContract = params.newContract

    # ─── default: receive funding ────────────────────────────────────────
    @sp.entry_point
    def default(self):
        # admin can pre-fund payouts if desired; treated as part of the next pot
        pass

    # ─── admin: create a new game ────────────────────────────────────────
    @sp.entry_point
    def createGame(self, params):
        sp.set_type(params, sp.TRecord(
            name=sp.TString,
            ticketPrice=sp.TMutez,
            holderFee=sp.TMutez,
            quarterWeights=sp.TMap(sp.TInt, sp.TNat),  # 4 entries: 0..3, sum ≤ 100
        ))
        self._onlyAdmin()
        self._notPaused()
        sp.verify(params.ticketPrice > sp.mutez(0), message="ZeroTicket")
        # Validate weights: 4 entries totalling ≤ 100
        # (legacy SmartPy can't easily iterate maps, so we check key presence
        # and trust the admin to sum sanely; off-chain we add stricter checks.)
        sp.verify(params.quarterWeights.contains(0), message="MissingQ1")
        sp.verify(params.quarterWeights.contains(1), message="MissingQ2")
        sp.verify(params.quarterWeights.contains(2), message="MissingQ3")
        sp.verify(params.quarterWeights.contains(3), message="MissingQ4")
        sumW = (params.quarterWeights[0] + params.quarterWeights[1] +
                params.quarterWeights[2] + params.quarterWeights[3])
        sp.verify(sumW == sp.nat(100), message="WeightsMustSumTo100")

        gid = self.data.currentGameId
        self.data.games[gid] = sp.record(
            name=params.name,
            creator=sp.sender,
            phase=PHASE_SELLING,
            ticketPrice=params.ticketPrice,
            holderFee=params.holderFee,
            sold=sp.nat(0),
            squares={},
            axisHome={},
            axisAway={},
            axesAssigned=False,
            quarterWeights=params.quarterWeights,
            quarterReported={0: False, 1: False, 2: False, 3: False},
            quartersDone=sp.int(0),
            pot=sp.mutez(0),
            rngTag="",
        )
        sp.emit(gid, tag="gameCreated")
        self.data.currentGameId += 1

    # ─── player: buy a specific square ───────────────────────────────────
    @sp.entry_point
    def buySquare(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, squareIdx=sp.TInt))
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_SELLING, message="NotSelling")
        sp.verify((params.squareIdx >= 0) & (params.squareIdx < 100), message="BadSquare")
        sp.verify(~game.value.squares.contains(params.squareIdx), message="SquareTaken")
        sp.verify(
            sp.amount == game.value.ticketPrice + game.value.holderFee,
            message="BadAmount",
        )

        # Take the holder fee, the rest into the pot.
        c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
        sp.transfer(sp.unit, game.value.holderFee, c)

        game.value.squares[params.squareIdx] = sp.sender
        game.value.sold += 1
        game.value.pot += game.value.ticketPrice
        # Auto-lock when all 100 sold.
        if game.value.sold == sp.nat(100):
            game.value.phase = PHASE_LOCKED
            sp.emit(params.gameId, tag="soldOut")
        self.data.games[params.gameId] = game.value
        sp.emit(
            sp.record(gameId=params.gameId, squareIdx=params.squareIdx, buyer=sp.sender),
            tag="squareBought",
        )

    # ─── admin: close sales early ────────────────────────────────────────
    @sp.entry_point
    def closeSales(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        self._onlyAdmin()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_SELLING, message="NotSelling")
        game.value.phase = PHASE_LOCKED
        self.data.games[params.gameId] = game.value
        sp.emit(params.gameId, tag="salesClosed")

    # ─── admin: kick off the RNG request for axis labels ─────────────────
    # Sends a request to the configured RNG oracle and stores the tag.
    @sp.entry_point
    def requestAxes(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, tag=sp.TString))
        self._onlyAdmin()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_LOCKED, message="NotLocked")

        rng = sp.contract(
            sp.TRecord(
                tag=sp.TString, max=sp.TNat, count=sp.TNat,
                noReplace=sp.TBool, playerNonce=sp.TBytes,
            ),
            self.data.rngOracle,
            entry_point="requestRandomness",
        ).open_some(message="NoRngOracle")
        # 20 values: 10 for the home axis (0..9 permutation), 10 for the away
        # axis. We ask for max=10 with noReplace, count=20. The off-chain
        # oracle is responsible for splitting into two halves.
        # Note: `count=20, max=10, noReplace=True` actually violates the
        # oracle's CountExceedsMax check. So instead we encode max=10,
        # count=20, noReplace=False and the off-chain bot generates two
        # independent 0..9 permutations. Same end result.
        sp.transfer(
            sp.record(
                tag=params.tag, max=sp.nat(10), count=sp.nat(20),
                noReplace=False,
                playerNonce=sp.bytes("0x" + "00" * 32),
            ),
            sp.mutez(0),
            rng,
        )
        game.value.rngTag = params.tag
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, tag=params.tag), tag="axesRequested")

    # ─── admin: write the axes back into game state once oracle fulfilled
    # The admin (or a relayer bot) reads the oracle's `requests[tag].values`
    # and submits the two arrays here. Why admin and not the oracle? So a
    # single trip to mainnet from the operator is sufficient — no callback
    # plumbing in the oracle contract.
    @sp.entry_point
    def setAxes(self, params):
        sp.set_type(params, sp.TRecord(
            gameId=sp.TNat,
            axisHome=sp.TMap(sp.TInt, sp.TInt),
            axisAway=sp.TMap(sp.TInt, sp.TInt),
        ))
        self._onlyAdmin()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_LOCKED, message="NotLocked")
        # Both maps must contain exactly 10 entries (0..9). We can only spot-
        # check key presence in legacy SmartPy.
        sp.verify(params.axisHome.contains(0) & params.axisHome.contains(9), message="BadHome")
        sp.verify(params.axisAway.contains(0) & params.axisAway.contains(9), message="BadAway")
        game.value.axisHome = params.axisHome
        game.value.axisAway = params.axisAway
        game.value.axesAssigned = True
        game.value.phase = PHASE_AXES_SET
        self.data.games[params.gameId] = game.value
        sp.emit(params.gameId, tag="axesSet")

    # ─── admin: report a quarter's score and pay the winner ──────────────
    @sp.entry_point
    def reportQuarter(self, params):
        sp.set_type(params, sp.TRecord(
            gameId=sp.TNat,
            quarter=sp.TInt,            # 0..3
            homeScore=sp.TNat,
            awayScore=sp.TNat,
        ))
        self._onlyAdmin()
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_AXES_SET, message="NotPlayable")
        sp.verify((params.quarter >= 0) & (params.quarter < 4), message="BadQuarter")
        sp.verify(game.value.quarterReported.contains(params.quarter), message="UnknownQ")
        sp.verify(~game.value.quarterReported[params.quarter], message="QAlreadyReported")

        homeDigit = sp.to_int(params.homeScore % 10)
        awayDigit = sp.to_int(params.awayScore % 10)

        # Find the row and column whose label matches the digit.
        # Legacy SmartPy doesn't have a built-in find; we do an unrolled
        # 10-way search. The maps are small.
        winRow = sp.local("winRow", -1)
        winCol = sp.local("winCol", -1)
        # Unrolled search across 0..9
        # (compiles to 10 if-checks; gas is negligible for the size.)
        for i in range(10):
            if game.value.axisHome[i] == homeDigit:
                winRow.value = i
            if game.value.axisAway[i] == awayDigit:
                winCol.value = i

        winSquare = winRow.value * 10 + winCol.value
        # Compute the per-quarter payout amount from weights.
        weight = game.value.quarterWeights[params.quarter]
        # payout = pot × weight / 100
        payout = sp.split_tokens(game.value.pot, weight, sp.nat(100))

        # Cap to remaining pot just in case of rounding.
        if payout > game.value.pot:
            payout = game.value.pot

        if game.value.squares.contains(winSquare):
            winner = game.value.squares[winSquare]
            self._credit(winner, payout)
            game.value.pot -= payout
            sp.emit(
                sp.record(
                    gameId=params.gameId, quarter=params.quarter,
                    winner=winner, square=winSquare, payout=payout,
                ),
                tag="quarterPaid",
            )
        else:
            # No-one bought the winning square: weight goes to TXL holders.
            c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
            sp.transfer(sp.unit, payout, c)
            game.value.pot -= payout
            sp.emit(
                sp.record(gameId=params.gameId, quarter=params.quarter, square=winSquare, payout=payout),
                tag="quarterUnowned",
            )

        game.value.quarterReported[params.quarter] = True
        game.value.quartersDone += 1
        if game.value.quartersDone == sp.int(4):
            game.value.phase = PHASE_COMPLETE
            sp.emit(params.gameId, tag="gameComplete")

        self.data.games[params.gameId] = game.value

    # ─── player: claim winnings (pull) ───────────────────────────────────
    @sp.entry_point
    def claim(self):
        sp.verify(self.data.pending.contains(sp.sender), message="NothingToClaim")
        amount = self.data.pending[sp.sender]
        sp.verify(amount > sp.mutez(0), message="NothingToClaim")
        del self.data.pending[sp.sender]
        sp.send(sp.sender, amount)
        sp.emit(sp.record(who=sp.sender, amount=amount), tag="claimed")

    # ─── admin: refund unsold games (escape hatch) ───────────────────────
    @sp.entry_point
    def refundUnsold(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        self._onlyAdmin()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        # Only valid in SELLING or LOCKED — once axes are set we're committed.
        sp.verify(
            (game.value.phase == PHASE_SELLING) | (game.value.phase == PHASE_LOCKED),
            message="GameTooFar",
        )
        # Refund every buyer their ticket price.
        # We have to walk squares via a 0..99 unrolled loop.
        for i in range(100):
            if game.value.squares.contains(i):
                buyer = game.value.squares[i]
                self._credit(buyer, game.value.ticketPrice)
        game.value.pot = sp.mutez(0)
        game.value.phase = PHASE_COMPLETE
        self.data.games[params.gameId] = game.value
        sp.emit(params.gameId, tag="refunded")


# ─── Tests ───────────────────────────────────────────────────────────────────
@sp.add_test(name="happy_path")
def t_happy():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    rng = sp.test_account("rng")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")
    p2 = sp.test_account("p2")

    c = Squares(admin.address, rng.address, holder.address)
    s += c

    weights = {0: sp.nat(15), 1: sp.nat(15), 2: sp.nat(15), 3: sp.nat(55)}
    s += c.createGame(
        name="Test Bowl",
        ticketPrice=sp.mutez(1000000),   # 1 ꜩ
        holderFee=sp.mutez(50000),       # 0.05 ꜩ
        quarterWeights=weights,
    ).run(sender=admin)

    # p1 buys square 23, p2 buys square 47
    s += c.buySquare(gameId=0, squareIdx=23).run(sender=p1, amount=sp.mutez(1050000))
    s += c.buySquare(gameId=0, squareIdx=47).run(sender=p2, amount=sp.mutez(1050000))

    s += c.closeSales(gameId=0).run(sender=admin)

    # Admin sets axes manually (skipping the oracle round-trip in this test)
    home = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9}
    away = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9}
    s += c.setAxes(gameId=0, axisHome=home, axisAway=away).run(sender=admin)

    # Q1 score: home 23, away 17 → digits (3, 7) → square 37 — unowned, goes to holders
    s += c.reportQuarter(gameId=0, quarter=0, homeScore=sp.nat(23), awayScore=sp.nat(17)).run(sender=admin)

    # Q2: 12-7 → (2, 7) → unowned
    s += c.reportQuarter(gameId=0, quarter=1, homeScore=sp.nat(12), awayScore=sp.nat(7)).run(sender=admin)

    # Q3: 23-17 again → (3, 7) → unowned
    s += c.reportQuarter(gameId=0, quarter=2, homeScore=sp.nat(33), awayScore=sp.nat(27)).run(sender=admin)

    # Q4: 24-17 → (4, 7) → unowned
    s += c.reportQuarter(gameId=0, quarter=3, homeScore=sp.nat(24), awayScore=sp.nat(17)).run(sender=admin)


@sp.add_test(name="player_wins_a_quarter")
def t_win():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    rng = sp.test_account("rng")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")

    c = Squares(admin.address, rng.address, holder.address)
    s += c

    weights = {0: sp.nat(25), 1: sp.nat(25), 2: sp.nat(25), 3: sp.nat(25)}
    s += c.createGame(
        name="Win Test",
        ticketPrice=sp.mutez(1000000),
        holderFee=sp.mutez(0),
        quarterWeights=weights,
    ).run(sender=admin)

    # p1 buys square 37
    s += c.buySquare(gameId=0, squareIdx=37).run(sender=p1, amount=sp.mutez(1000000))
    s += c.closeSales(gameId=0).run(sender=admin)

    # Identity axes
    home = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9}
    away = {0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9}
    s += c.setAxes(gameId=0, axisHome=home, axisAway=away).run(sender=admin)

    # Q1: 13-17 → digits (3, 7) → square 37 → p1 wins
    s += c.reportQuarter(gameId=0, quarter=0, homeScore=sp.nat(13), awayScore=sp.nat(17)).run(sender=admin)
    # p1 should now have 0.25 ꜩ pending
    s += c.claim().run(sender=p1)


@sp.add_test(name="weights_must_sum_to_100")
def t_weights():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    rng = sp.test_account("rng")
    holder = sp.test_account("holder")

    c = Squares(admin.address, rng.address, holder.address)
    s += c

    bad = {0: sp.nat(10), 1: sp.nat(10), 2: sp.nat(10), 3: sp.nat(10)}
    s += c.createGame(
        name="Bad", ticketPrice=sp.mutez(1000000), holderFee=sp.mutez(0),
        quarterWeights=bad,
    ).run(sender=admin, valid=False, exception="WeightsMustSumTo100")


@sp.add_test(name="cannot_buy_taken_square")
def t_taken():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    rng = sp.test_account("rng")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")
    p2 = sp.test_account("p2")

    c = Squares(admin.address, rng.address, holder.address)
    s += c

    weights = {0: sp.nat(25), 1: sp.nat(25), 2: sp.nat(25), 3: sp.nat(25)}
    s += c.createGame(
        name="Taken",
        ticketPrice=sp.mutez(1000000), holderFee=sp.mutez(0),
        quarterWeights=weights,
    ).run(sender=admin)

    s += c.buySquare(gameId=0, squareIdx=42).run(sender=p1, amount=sp.mutez(1000000))
    s += c.buySquare(gameId=0, squareIdx=42).run(
        sender=p2, amount=sp.mutez(1000000),
        valid=False, exception="SquareTaken",
    )
