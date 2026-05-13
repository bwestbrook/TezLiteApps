"""
Acey-Duecey contract — legacy SmartPy syntax.

Targets the older SmartPy version shipped in the bakingbad/smartpy-cli Docker
image (no @sp.module, uses self.init(...), @sp.entry_point, sp.TMutez, etc.).

Same game logic and bug fixes as smart_contractAD_v3.py:
  - oracle role enforced on firstCard / secondCard / lastCard
  - pair detection compares apples-to-apples (rank+2 vs rank+2)
  - aceHigh choice is honored when sorting low/high
  - storage pot starts at 0 (seed via default after origination)
  - games stored in a big_map, not a regular map
  - error messages on every assert so the frontend can surface them

Status enum:
    0 = bet placed, awaiting first two cards
    1 = two cards drawn, awaiting continueBet
    2 = continueBet placed, awaiting last card
    3 = won
    4 = lost
    5 = pair drawn on ante (half refund)

Compile + test:
    docker run --rm -v "$PWD":/work -w /work \\
      bakingbad/smartpy-cli:latest \\
      test src/services/smart_contractAD_legacy.py src/services/build/aceyDuecey/
"""

import smartpy as sp


class AceyDuecey(sp.Contract):
    def __init__(self, admin, oracle, txlContract):
        self.init(
            # Roles
            admin=admin,
            oracle=oracle,
            txlContract=txlContract,
            # Money (all mutez — single unit, no tez/mutez mixing)
            ante=sp.mutez(200000),
            fee=sp.mutez(100000),
            potTopUp=sp.mutez(125000),
            potTopUpTrigger=sp.mutez(125000),
            pot=sp.mutez(0),
            potReserve=sp.mutez(0),
            # Game ledger
            games=sp.big_map(
                tkey=sp.TNat,
                tvalue=sp.TRecord(
                    player=sp.TAddress,
                    aceHigh=sp.TInt,
                    gameStatus=sp.TInt,
                    finalBet=sp.TMutez,
                    hand=sp.TMap(sp.TInt, sp.TInt),
                    handValue=sp.TMap(sp.TInt, sp.TInt),
                    handHashes=sp.TMap(sp.TInt, sp.TString),
                ),
            ),
            currentGameIndex=sp.nat(0),
        )

    # ─── helpers (regular methods — legacy SmartPy doesn't have @sp.private) ─
    def _forwardFee(self):
        c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
        sp.transfer(sp.unit, self.data.fee, c)

    # ─── default: receive funding into the reserve ─────────────────────────
    @sp.entry_point
    def default(self):
        self.data.potReserve += sp.amount

    # ─── admin: change roles ───────────────────────────────────────────────
    @sp.entry_point
    def updateTxlContract(self, params):
        sp.set_type(params, sp.TRecord(newContract=sp.TAddress))
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")
        self.data.txlContract = params.newContract

    @sp.entry_point
    def updateOracle(self, params):
        sp.set_type(params, sp.TRecord(newOracle=sp.TAddress))
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")
        self.data.oracle = params.newOracle

    @sp.entry_point
    def updateAdmin(self, params):
        sp.set_type(params, sp.TRecord(newAdmin=sp.TAddress))
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")
        self.data.admin = params.newAdmin

    # ─── player: open a new game ───────────────────────────────────────────
    @sp.entry_point
    def bet(self, params):
        sp.set_type(params, sp.TRecord(aceHigh=sp.TInt))
        sp.verify(sp.amount == self.data.ante + self.data.fee, message="BadAmount")
        sp.verify((params.aceHigh == 1) | (params.aceHigh == 0), message="BadAceHigh")

        self.data.pot += self.data.ante
        self._forwardFee()

        self.data.games[self.data.currentGameIndex] = sp.record(
            player=sp.sender,
            aceHigh=params.aceHigh,
            gameStatus=0,
            finalBet=sp.mutez(0),
            hand={1: -1, 2: -1, 3: -1},
            handValue={1: -1, 2: -1, 3: -1},
            handHashes={1: "", 2: "", 3: ""},
        )
        sp.emit(self.data.currentGameIndex, tag="betMade")
        self.data.currentGameIndex += 1

    # ─── oracle: reveal first card ─────────────────────────────────────────
    @sp.entry_point
    def firstCard(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, card=sp.TNat, hash=sp.TString))
        sp.verify(sp.sender == self.data.oracle, message="NotOracle")
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

    # ─── oracle: reveal second card (auto-resolves pair) ───────────────────
    @sp.entry_point
    def secondCard(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, card=sp.TNat, hash=sp.TString))
        sp.verify(sp.sender == self.data.oracle, message="NotOracle")
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        sp.verify(params.card < 52, message="BadCard")

        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.gameStatus == 0, message="BadStatus")

        value = sp.to_int(params.card / 4) + 2
        game.value.hand[2] = sp.to_int(params.card)
        game.value.handValue[2] = value
        game.value.handHashes[2] = params.hash

        if game.value.handValue[1] == value:
            # Pair drawn: half ante back to player, half to TXL holders.
            halfAnte = sp.split_tokens(self.data.ante, 1, 2)
            game.value.gameStatus = 5
            self.data.pot -= self.data.ante
            sp.send(game.value.player, halfAnte)
            c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
            sp.transfer(sp.unit, halfAnte, c)
            sp.emit(params.gameId, tag="pairDrawn")
        else:
            game.value.gameStatus = 1
            sp.emit(sp.record(gameId=params.gameId, card=params.card), tag="secondCard")

        self.data.games[params.gameId] = game.value

    # ─── player: place the in-between bet ──────────────────────────────────
    @sp.entry_point
    def continueBet(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(sp.sender == game.value.player, message="NotPlayer")
        sp.verify(game.value.gameStatus == 1, message="BadStatus")
        sp.verify(sp.amount > self.data.fee, message="BetTooSmall")
        bet = sp.local("bet", sp.amount - self.data.fee)
        sp.verify(bet.value <= self.data.pot, message="BetExceedsPot")

        self._forwardFee()
        game.value.finalBet = bet.value
        game.value.gameStatus = 2
        self.data.pot += bet.value
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, bet=bet.value), tag="continueBet")

    # ─── oracle: reveal the third card and settle ─────────────────────────
    @sp.entry_point
    def lastCard(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, card=sp.TNat, hash=sp.TString))
        sp.verify(sp.sender == self.data.oracle, message="NotOracle")
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        sp.verify(params.card < 52, message="BadCard")

        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.gameStatus == 2, message="BadStatus")

        value = sp.to_int(params.card / 4) + 2
        game.value.hand[3] = sp.to_int(params.card)
        game.value.handValue[3] = value
        game.value.handHashes[3] = params.hash

        # Apply Ace-high vs Ace-low. Aces are 14; if aceHigh==0, remap to 1.
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
            # Win — pay 2× finalBet from the pot.
            payout = sp.split_tokens(game.value.finalBet, 2, 1)
            game.value.gameStatus = 3
            self.data.pot -= payout
            sp.send(game.value.player, payout)
            sp.emit(sp.record(gameId=params.gameId, payout=payout), tag="win")
        else:
            game.value.gameStatus = 4
            if (v3.value == low.value) | (v3.value == high.value):
                rail = sp.local("rail", game.value.finalBet + self.data.ante)
                if rail.value > self.data.pot:
                    rail.value = self.data.pot
                self.data.pot -= rail.value
                c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
                sp.transfer(sp.unit, rail.value, c)
                sp.emit(sp.record(gameId=params.gameId, rail=rail.value), tag="rail")
            else:
                sp.emit(params.gameId, tag="loss")

        # Top up pot from reserve if it dropped below the trigger.
        if self.data.pot < self.data.potTopUpTrigger:
            if self.data.potReserve >= self.data.potTopUp:
                self.data.pot += self.data.potTopUp
                self.data.potReserve -= self.data.potTopUp

        self.data.games[params.gameId] = game.value

    # ─── admin: drain reserve only ─────────────────────────────────────────
    @sp.entry_point
    def withdrawReserve(self, params):
        sp.set_type(params, sp.TRecord(amount=sp.TMutez, dest=sp.TAddress))
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")
        sp.verify(params.amount <= self.data.potReserve, message="ReserveTooLow")
        self.data.potReserve -= params.amount
        sp.send(params.dest, params.amount)


# ─── Tests ───────────────────────────────────────────────────────────────────
@sp.add_test(name="basic_flow")
def test_basic_flow():
    scenario = sp.test_scenario()
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    scenario += c

    scenario += c.default().run(sender=admin, amount=sp.tez(2))
    scenario += c.bet(aceHigh=1).run(sender=player, amount=sp.mutez(300000))
    scenario += c.firstCard(gameId=0, card=10, hash="h1").run(sender=oracle)
    scenario += c.secondCard(gameId=0, card=40, hash="h2").run(sender=oracle)
    scenario += c.continueBet(gameId=0).run(sender=player, amount=sp.mutez(200000))
    scenario += c.lastCard(gameId=0, card=24, hash="h3").run(sender=oracle)


@sp.add_test(name="pair_refund")
def test_pair_refund():
    scenario = sp.test_scenario()
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    scenario += c
    scenario += c.default().run(sender=admin, amount=sp.tez(2))
    scenario += c.bet(aceHigh=1).run(sender=player, amount=sp.mutez(300000))
    scenario += c.firstCard(gameId=0, card=8, hash="h1").run(sender=oracle)   # value 4
    scenario += c.secondCard(gameId=0, card=11, hash="h2").run(sender=oracle) # value 4 -> pair


@sp.add_test(name="rail")
def test_rail():
    scenario = sp.test_scenario()
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    scenario += c
    scenario += c.default().run(sender=admin, amount=sp.tez(2))
    scenario += c.bet(aceHigh=1).run(sender=player, amount=sp.mutez(300000))
    scenario += c.firstCard(gameId=0, card=4, hash="h1").run(sender=oracle)   # value 3
    scenario += c.secondCard(gameId=0, card=44, hash="h2").run(sender=oracle) # value 13
    scenario += c.continueBet(gameId=0).run(sender=player, amount=sp.mutez(200000))
    scenario += c.lastCard(gameId=0, card=4, hash="h3").run(sender=oracle)    # rail = low


@sp.add_test(name="auth")
def test_not_oracle_blocked():
    scenario = sp.test_scenario()
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")
    attacker = sp.test_account("attacker")

    c = AceyDuecey(admin.address, oracle.address, holder.address)
    scenario += c
    scenario += c.default().run(sender=admin, amount=sp.tez(2))
    scenario += c.bet(aceHigh=1).run(sender=player, amount=sp.mutez(300000))
    scenario += c.firstCard(gameId=0, card=10, hash="h").run(
        sender=attacker, valid=False, exception="NotOracle"
    )
