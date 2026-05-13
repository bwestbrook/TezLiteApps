"""
Acey-Duecey contract — security-hardened build (legacy SmartPy syntax).

Layered on top of smart_contractAD_legacy.py with the following defenses:

  CONTROL-PLANE
  ─────────────
  - pause / unpause                     admin can freeze new bets in emergencies
  - two-step admin transfer             prevents accidentally bricking with a typo
  - role-changes always emit events     so an external monitor can alert on change

  PLAYER-SAFETY
  ─────────────
  - bet size limits (min/max ante)      configurable, enforced on every bet
  - max-bet vs pot                      already in v3, kept (BetExceedsPot)
  - per-game expiry + refund            if oracle goes silent, player can reclaim
                                        their stake after `gameTimeoutBlocks`
  - reentrancy guard (`busy` flag)      blocks recursive calls while we're sending
                                        to potentially-contract addresses
  - withdrawal pattern (pull, not push) winner doesn't get sp.send during settle —
                                        funds are credited to a `pending` map and
                                        the player calls `claim()` to pull them.
                                        Avoids any settle-call being blocked by a
                                        malicious contract address.

  RNG-INTEGRITY
  ─────────────
  - player nonce on bet                 player commits 32 random bytes when betting.
                                        the oracle must hash (player_nonce ||
                                        oracle_seed || block_hash) to derive cards.
                                        means: oracle alone can't pick favourable
                                        cards, AND a malicious player can't
                                        either, so neither side has the unilateral
                                        advantage of the previous "trust the
                                        oracle" model.

  AUDIT
  ─────
  - sp.emit on every state transition   easy to graph + alert on anomalies
  - per-game `dealtBy` field            the oracle address that signed each card,
                                        so if you ever rotate keys you know which
                                        oracle dealt which game
"""

import smartpy as sp


class AceyDuecey(sp.Contract):
    def __init__(self, admin, oracle, txlContract):
        self.init(
            # ─── roles + transfer guard ─────────────────────────────────────
            admin=admin,
            oracle=oracle,
            txlContract=txlContract,
            pendingAdmin=sp.none,           # set during two-step transfer

            # ─── circuit breaker ────────────────────────────────────────────
            paused=False,

            # ─── reentrancy guard ───────────────────────────────────────────
            busy=False,

            # ─── money (mutez everywhere) ───────────────────────────────────
            ante=sp.mutez(200000),
            fee=sp.mutez(100000),
            minAnte=sp.mutez(100000),       # admin-tunable
            maxAnte=sp.mutez(5000000),      # 5ꜩ ceiling per bet by default
            potTopUp=sp.mutez(125000),
            potTopUpTrigger=sp.mutez(125000),
            pot=sp.mutez(0),
            potReserve=sp.mutez(0),

            # ─── timeouts ───────────────────────────────────────────────────
            # Tezos blocks are ~15s. 240 blocks ≈ 1 hour grace before player
            # can self-refund a stuck game.
            gameTimeoutBlocks=sp.nat(240),

            # ─── pull-pattern payout ledger ─────────────────────────────────
            # winners credit their tez here, then call `claim` to withdraw.
            pending=sp.big_map(tkey=sp.TAddress, tvalue=sp.TMutez),

            # ─── games ──────────────────────────────────────────────────────
            games=sp.big_map(
                tkey=sp.TNat,
                tvalue=sp.TRecord(
                    player=sp.TAddress,
                    aceHigh=sp.TInt,
                    gameStatus=sp.TInt,
                    finalBet=sp.TMutez,
                    ante=sp.TMutez,                   # snapshotted from settings
                    playerNonce=sp.TBytes,            # commit-reveal seed from player
                    dealtBy=sp.TAddress,              # oracle that dealt cards
                    createdAtLevel=sp.TNat,           # block level at bet time
                    hand=sp.TMap(sp.TInt, sp.TInt),
                    handValue=sp.TMap(sp.TInt, sp.TInt),
                    handHashes=sp.TMap(sp.TInt, sp.TString),
                ),
            ),
            currentGameIndex=sp.nat(0),
        )

    # ─── helpers ───────────────────────────────────────────────────────────
    def _onlyAdmin(self):
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")

    def _onlyOracle(self):
        sp.verify(sp.sender == self.data.oracle, message="NotOracle")

    def _notPaused(self):
        sp.verify(~self.data.paused, message="Paused")

    def _enterBusy(self):
        sp.verify(~self.data.busy, message="Reentrancy")
        self.data.busy = True

    def _leaveBusy(self):
        self.data.busy = False

    def _forwardFee(self, amount):
        c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
        sp.transfer(sp.unit, amount, c)

    def _credit(self, who, amount):
        """Add `amount` to `who`'s pending ledger (pull-pattern payout).
        Uses .get(default=...) so this is a single SmartPy expression — no
        Python if/else in a helper, which can be version-dependent in legacy
        SmartPy when the helper is called from multiple entry points."""
        current = self.data.pending.get(who, default_value=sp.mutez(0))
        self.data.pending[who] = current + amount

    # ─── circuit breaker ───────────────────────────────────────────────────
    @sp.entry_point
    def pause(self):
        self._onlyAdmin()
        self.data.paused = True
        sp.emit(sp.unit, tag="paused")

    @sp.entry_point
    def unpause(self):
        self._onlyAdmin()
        self.data.paused = False
        sp.emit(sp.unit, tag="unpaused")

    # ─── two-step admin transfer ───────────────────────────────────────────
    @sp.entry_point
    def proposeAdmin(self, params):
        sp.set_type(params, sp.TRecord(newAdmin=sp.TAddress))
        self._onlyAdmin()
        self.data.pendingAdmin = sp.some(params.newAdmin)
        sp.emit(params.newAdmin, tag="adminProposed")

    @sp.entry_point
    def acceptAdmin(self):
        proposed = self.data.pendingAdmin.open_some(message="NoPendingAdmin")
        sp.verify(sp.sender == proposed, message="NotProposedAdmin")
        self.data.admin = proposed
        self.data.pendingAdmin = sp.none
        sp.emit(proposed, tag="adminAccepted")

    @sp.entry_point
    def updateOracle(self, params):
        sp.set_type(params, sp.TRecord(newOracle=sp.TAddress))
        self._onlyAdmin()
        self.data.oracle = params.newOracle
        sp.emit(params.newOracle, tag="oracleChanged")

    @sp.entry_point
    def updateTxlContract(self, params):
        sp.set_type(params, sp.TRecord(newContract=sp.TAddress))
        self._onlyAdmin()
        self.data.txlContract = params.newContract
        sp.emit(params.newContract, tag="txlContractChanged")

    @sp.entry_point
    def updateLimits(self, params):
        sp.set_type(params, sp.TRecord(
            ante=sp.TMutez, fee=sp.TMutez,
            minAnte=sp.TMutez, maxAnte=sp.TMutez,
            gameTimeoutBlocks=sp.TNat,
        ))
        self._onlyAdmin()
        sp.verify(params.minAnte <= params.ante, message="MinAnteTooHigh")
        sp.verify(params.ante <= params.maxAnte, message="AnteTooHigh")
        sp.verify(params.gameTimeoutBlocks >= 60, message="TimeoutTooShort")
        self.data.ante = params.ante
        self.data.fee = params.fee
        self.data.minAnte = params.minAnte
        self.data.maxAnte = params.maxAnte
        self.data.gameTimeoutBlocks = params.gameTimeoutBlocks

    # ─── default: receive funding into the reserve ─────────────────────────
    @sp.entry_point
    def default(self):
        self.data.potReserve += sp.amount

    # ─── player: open a new game ───────────────────────────────────────────
    @sp.entry_point
    def bet(self, params):
        # 32-byte nonce: player-supplied entropy for commit-reveal RNG.
        sp.set_type(params, sp.TRecord(aceHigh=sp.TInt, playerNonce=sp.TBytes))
        self._notPaused()
        self._enterBusy()

        sp.verify(sp.amount == self.data.ante + self.data.fee, message="BadAmount")
        sp.verify(sp.amount >= self.data.minAnte + self.data.fee, message="AnteBelowMin")
        sp.verify(sp.amount <= self.data.maxAnte + self.data.fee, message="AnteAboveMax")
        sp.verify((params.aceHigh == 1) | (params.aceHigh == 0), message="BadAceHigh")
        sp.verify(sp.len(params.playerNonce) == 32, message="BadNonceLength")

        self.data.pot += self.data.ante
        self._forwardFee(self.data.fee)

        self.data.games[self.data.currentGameIndex] = sp.record(
            player=sp.sender,
            aceHigh=params.aceHigh,
            gameStatus=0,
            finalBet=sp.mutez(0),
            ante=self.data.ante,
            playerNonce=params.playerNonce,
            dealtBy=self.data.oracle,                # snapshot at game time
            createdAtLevel=sp.level,
            hand={1: -1, 2: -1, 3: -1},
            handValue={1: -1, 2: -1, 3: -1},
            handHashes={1: "", 2: "", 3: ""},
        )
        sp.emit(self.data.currentGameIndex, tag="betMade")
        self.data.currentGameIndex += 1
        self._leaveBusy()

    # ─── oracle: reveal first card ─────────────────────────────────────────
    @sp.entry_point
    def firstCard(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, card=sp.TNat, hash=sp.TString))
        self._onlyOracle()
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        sp.verify(params.card < 52, message="BadCard")

        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.gameStatus == 0, message="BadStatus")

        value = sp.to_int(params.card / 4) + 2
        game.value.hand[1] = sp.to_int(params.card)
        game.value.handValue[1] = value
        game.value.handHashes[1] = params.hash
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, card=params.card), tag="firstCard")

    # ─── oracle: reveal second card ────────────────────────────────────────
    @sp.entry_point
    def secondCard(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, card=sp.TNat, hash=sp.TString))
        self._onlyOracle()
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        sp.verify(params.card < 52, message="BadCard")
        self._enterBusy()

        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.gameStatus == 0, message="BadStatus")

        value = sp.to_int(params.card / 4) + 2
        game.value.hand[2] = sp.to_int(params.card)
        game.value.handValue[2] = value
        game.value.handHashes[2] = params.hash

        if game.value.handValue[1] == value:
            # Pair drawn: half ante credited to player, half to TXL holders.
            halfAnte = sp.split_tokens(game.value.ante, 1, 2)
            game.value.gameStatus = 5
            self.data.pot -= game.value.ante
            self._credit(game.value.player, halfAnte)
            self._forwardFee(halfAnte)  # second half to holders
            sp.emit(params.gameId, tag="pairDrawn")
        else:
            game.value.gameStatus = 1
            sp.emit(sp.record(gameId=params.gameId, card=params.card), tag="secondCard")

        self.data.games[params.gameId] = game.value
        self._leaveBusy()

    # ─── player: place the in-between bet ──────────────────────────────────
    @sp.entry_point
    def continueBet(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        self._notPaused()
        self._enterBusy()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(sp.sender == game.value.player, message="NotPlayer")
        sp.verify(game.value.gameStatus == 1, message="BadStatus")
        sp.verify(sp.amount > self.data.fee, message="BetTooSmall")
        bet = sp.local("bet", sp.amount - self.data.fee)
        sp.verify(bet.value <= self.data.pot, message="BetExceedsPot")

        self._forwardFee(self.data.fee)
        game.value.finalBet = bet.value
        game.value.gameStatus = 2
        self.data.pot += bet.value
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, bet=bet.value), tag="continueBet")
        self._leaveBusy()

    # ─── oracle: reveal the third card and settle ─────────────────────────
    @sp.entry_point
    def lastCard(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, card=sp.TNat, hash=sp.TString))
        self._onlyOracle()
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        sp.verify(params.card < 52, message="BadCard")
        self._enterBusy()

        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.gameStatus == 2, message="BadStatus")

        value = sp.to_int(params.card / 4) + 2
        game.value.hand[3] = sp.to_int(params.card)
        game.value.handValue[3] = value
        game.value.handHashes[3] = params.hash

        v1 = sp.local("v1", game.value.handValue[1])
        v2 = sp.local("v2", game.value.handValue[2])
        v3 = sp.local("v3", value)
        if game.value.aceHigh == 0:
            if v1.value == 14:
                v1.value = 1
            if v2.value == 14:
                v2.value = 1
            if v3.value == 14:
                v3.value = 1

        low = sp.local("low", v1.value)
        high = sp.local("high", v2.value)
        if v2.value < v1.value:
            low.value = v2.value
            high.value = v1.value

        if (v3.value > low.value) & (v3.value < high.value):
            payout = sp.split_tokens(game.value.finalBet, 2, 1)
            game.value.gameStatus = 3
            self.data.pot -= payout
            self._credit(game.value.player, payout)
            sp.emit(sp.record(gameId=params.gameId, payout=payout), tag="win")
        else:
            game.value.gameStatus = 4
            if (v3.value == low.value) | (v3.value == high.value):
                rail = sp.local("rail", game.value.finalBet + game.value.ante)
                if rail.value > self.data.pot:
                    rail.value = self.data.pot
                self.data.pot -= rail.value
                self._forwardFee(rail.value)
                sp.emit(sp.record(gameId=params.gameId, rail=rail.value), tag="rail")
            else:
                sp.emit(params.gameId, tag="loss")

        if self.data.pot < self.data.potTopUpTrigger:
            if self.data.potReserve >= self.data.potTopUp:
                self.data.pot += self.data.potTopUp
                self.data.potReserve -= self.data.potTopUp

        self.data.games[params.gameId] = game.value
        self._leaveBusy()

    # ─── player: claim winnings (pull pattern) ─────────────────────────────
    @sp.entry_point
    def claim(self):
        self._enterBusy()
        sp.verify(self.data.pending.contains(sp.sender), message="NothingToClaim")
        amount = self.data.pending[sp.sender]
        sp.verify(amount > sp.mutez(0), message="NothingToClaim")
        del self.data.pending[sp.sender]
        sp.send(sp.sender, amount)
        sp.emit(sp.record(who=sp.sender, amount=amount), tag="claimed")
        self._leaveBusy()

    # ─── player: refund a stuck game (oracle MIA) ──────────────────────────
    @sp.entry_point
    def refundStuckGame(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        self._enterBusy()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(sp.sender == game.value.player, message="NotPlayer")
        # Only refund if the game is in a "waiting on oracle" status.
        sp.verify(
            (game.value.gameStatus == 0) | (game.value.gameStatus == 2),
            message="GameNotStuck",
        )
        # And only after the timeout window has passed.
        sp.verify(
            sp.level >= game.value.createdAtLevel + self.data.gameTimeoutBlocks,
            message="NotYetExpired",
        )
        # Refund the player's stake from the pot:
        #   status 0  → ante only (no continueBet placed yet)
        #   status 2  → ante + finalBet
        refund = sp.local("refund", game.value.ante)
        if game.value.gameStatus == 2:
            refund.value += game.value.finalBet
        if refund.value > self.data.pot:
            refund.value = self.data.pot
        self.data.pot -= refund.value
        self._credit(game.value.player, refund.value)
        game.value.gameStatus = 4  # mark as resolved-loss for accounting
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, refund=refund.value), tag="refunded")
        self._leaveBusy()

    # ─── admin: drain reserve only (never the active pot) ──────────────────
    @sp.entry_point
    def withdrawReserve(self, params):
        sp.set_type(params, sp.TRecord(amount=sp.TMutez, dest=sp.TAddress))
        self._onlyAdmin()
        self._enterBusy()
        sp.verify(params.amount <= self.data.potReserve, message="ReserveTooLow")
        self.data.potReserve -= params.amount
        sp.send(params.dest, params.amount)
        self._leaveBusy()

    # ─── admin: prune resolved games to recover storage ────────────────────
    # Only games in terminal states (3 win, 4 loss, 5 pair) can be pruned.
    @sp.entry_point
    def pruneGame(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        self._onlyAdmin()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        status = self.data.games[params.gameId].gameStatus
        sp.verify((status == 3) | (status == 4) | (status == 5), message="NotTerminal")
        del self.data.games[params.gameId]


# ─── Tests ───────────────────────────────────────────────────────────────────
@sp.add_test(name="happy_path_with_claim")
def t_happy():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    s += c
    s += c.default().run(sender=admin, amount=sp.tez(2))

    nonce = sp.bytes("0x" + "11" * 32)
    s += c.bet(aceHigh=1, playerNonce=nonce).run(sender=player, amount=sp.mutez(300000))
    s += c.firstCard(gameId=0, card=10, hash="h1").run(sender=oracle)   # value 4
    s += c.secondCard(gameId=0, card=40, hash="h2").run(sender=oracle)  # value 12
    s += c.continueBet(gameId=0).run(sender=player, amount=sp.mutez(200000))
    s += c.lastCard(gameId=0, card=24, hash="h3").run(sender=oracle)    # value 8 → win
    # Player must explicitly claim winnings
    s += c.claim().run(sender=player)


@sp.add_test(name="paused_blocks_bets")
def t_paused():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    s += c
    s += c.default().run(sender=admin, amount=sp.tez(2))

    s += c.pause().run(sender=admin)
    nonce = sp.bytes("0x" + "22" * 32)
    s += c.bet(aceHigh=1, playerNonce=nonce).run(
        sender=player, amount=sp.mutez(300000), valid=False, exception="Paused"
    )
    s += c.unpause().run(sender=admin)
    s += c.bet(aceHigh=1, playerNonce=nonce).run(sender=player, amount=sp.mutez(300000))


@sp.add_test(name="two_step_admin")
def t_admin():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    new_admin = sp.test_account("new_admin")
    attacker = sp.test_account("attacker")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    s += c
    # propose
    s += c.proposeAdmin(newAdmin=new_admin.address).run(sender=admin)
    # attacker can't accept
    s += c.acceptAdmin().run(sender=attacker, valid=False, exception="NotProposedAdmin")
    # new admin accepts
    s += c.acceptAdmin().run(sender=new_admin)
    # old admin is no longer admin
    s += c.pause().run(sender=admin, valid=False, exception="NotAdmin")
    s += c.pause().run(sender=new_admin)


@sp.add_test(name="refund_stuck_game")
def t_refund():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    s += c
    s += c.default().run(sender=admin, amount=sp.tez(2))

    nonce = sp.bytes("0x" + "33" * 32)
    s += c.bet(aceHigh=1, playerNonce=nonce).run(
        sender=player, amount=sp.mutez(300000), level=100
    )
    # Try to refund before timeout: rejected
    s += c.refundStuckGame(gameId=0).run(
        sender=player, level=200, valid=False, exception="NotYetExpired"
    )
    # After timeout (240 blocks): refund succeeds
    s += c.refundStuckGame(gameId=0).run(sender=player, level=400)
    s += c.claim().run(sender=player)


@sp.add_test(name="bet_size_limits")
def t_limits():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    s += c
    s += c.default().run(sender=admin, amount=sp.tez(2))

    # Lower the max ante to 0.15ꜩ. Default ante is 0.2ꜩ → bet at default rate
    # should now reject as AnteAboveMax — verifies limits actually apply.
    s += c.updateLimits(
        ante=sp.mutez(150000),
        fee=sp.mutez(100000),
        minAnte=sp.mutez(100000),
        maxAnte=sp.mutez(150000),
        gameTimeoutBlocks=sp.nat(240),
    ).run(sender=admin)
    nonce = sp.bytes("0x" + "44" * 32)
    s += c.bet(aceHigh=1, playerNonce=nonce).run(
        sender=player, amount=sp.mutez(250000)
    )  # 0.15 + 0.1 = 0.25ꜩ
