"""
Acey-Duecey (a.k.a. In-Between) — SmartPy contract, v3.

Same logic as v2, simpler syntax to avoid SmartPy parser quirks:
  - no module-level type aliases
  - no numeric underscores in literals
  - no @sp.private (helpers inlined)
  - no .layout() calls
  - no sp.cast on big_map declarations

Status enum (kept as ints for cheap storage):
    0 = bet placed, awaiting first two cards
    1 = two cards drawn, awaiting continueBet
    2 = continueBet placed, awaiting last card
    3 = won
    4 = lost
    5 = pair drawn on ante (half refund)

Card index 0..51:  rank = card // 4   (0..12)
                   suit = card % 4
                   numeric value = rank + 2  →  2..14, with Ace = 14 if
                                                aceHigh==1 else remapped to 1
"""

import smartpy as sp


@sp.module
def main():
    class AceyDuecey(sp.Contract):
        def __init__(self, admin, oracle, txlContract):
            # Roles
            self.data.admin = admin
            self.data.oracle = oracle
            self.data.txlContract = txlContract

            # Money (all in mutez — no tez/mutez mixing)
            self.data.ante = sp.mutez(200000)              # 0.2 ꜩ
            self.data.fee = sp.mutez(100000)               # 0.1 ꜩ
            self.data.potTopUp = sp.mutez(125000)
            self.data.potTopUpTrigger = sp.mutez(125000)

            # Pot accounting (starts empty; seed via `default` after origination)
            self.data.pot = sp.mutez(0)
            self.data.potReserve = sp.mutez(0)

            # Game ledger
            self.data.games = sp.big_map()
            self.data.currentGameIndex = 0

        # ─── default: receive funding into the reserve ─────────────────────
        @sp.entrypoint
        def default(self):
            self.data.potReserve += sp.amount

        # ─── admin: change roles ───────────────────────────────────────────
        @sp.entrypoint
        def updateTxlContract(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.txlContract = params.newContract

        @sp.entrypoint
        def updateOracle(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.oracle = params.newOracle

        @sp.entrypoint
        def updateAdmin(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.admin = params.newAdmin

        # ─── player: open a new game (ante + fee) ──────────────────────────
        @sp.entrypoint
        def bet(self, params):
            assert sp.amount == self.data.ante + self.data.fee, "BadAmount"
            assert params.aceHigh == 1 or params.aceHigh == 0, "BadAceHigh"

            self.data.pot += self.data.ante
            holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(error="NoTxlContract")
            sp.transfer((), self.data.fee, holder)

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

        # ─── oracle: reveal first card ─────────────────────────────────────
        @sp.entrypoint
        def firstCard(self, params):
            assert sp.sender == self.data.oracle, "NotOracle"
            assert self.data.games.contains(params.gameId), "NoGame"
            assert params.card < 52, "BadCard"
            game = self.data.games[params.gameId]
            assert game.gameStatus == 0, "BadStatus"

            value = sp.to_int(params.card / 4) + 2
            game.hand[1] = sp.to_int(params.card)
            game.handValue[1] = value
            game.handHashes[1] = params.hash
            self.data.games[params.gameId] = game
            sp.emit(sp.record(gameId=params.gameId, card=params.card), tag="firstCard")

        # ─── oracle: reveal second card (may auto-resolve as pair) ─────────
        @sp.entrypoint
        def secondCard(self, params):
            assert sp.sender == self.data.oracle, "NotOracle"
            assert self.data.games.contains(params.gameId), "NoGame"
            assert params.card < 52, "BadCard"
            game = self.data.games[params.gameId]
            assert game.gameStatus == 0, "BadStatus"

            value = sp.to_int(params.card / 4) + 2  # comparable to handValue[1]
            game.hand[2] = sp.to_int(params.card)
            game.handValue[2] = value
            game.handHashes[2] = params.hash

            if game.handValue[1] == value:
                # Pair drawn: half ante back to player, half to TXL holders.
                halfAnte = sp.split_tokens(self.data.ante, 1, 2)
                game.gameStatus = 5
                self.data.pot -= self.data.ante
                sp.send(game.player, halfAnte)
                holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(error="NoTxlContract")
                sp.transfer((), halfAnte, holder)
                sp.emit(params.gameId, tag="pairDrawn")
            else:
                game.gameStatus = 1
                sp.emit(sp.record(gameId=params.gameId, card=params.card), tag="secondCard")

            self.data.games[params.gameId] = game

        # ─── player: place the in-between bet ──────────────────────────────
        @sp.entrypoint
        def continueBet(self, params):
            assert self.data.games.contains(params.gameId), "NoGame"
            game = self.data.games[params.gameId]
            assert sp.sender == game.player, "NotPlayer"
            assert game.gameStatus == 1, "BadStatus"
            assert sp.amount > self.data.fee, "BetTooSmall"
            bet = sp.amount - self.data.fee
            assert bet <= self.data.pot, "BetExceedsPot"

            holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(error="NoTxlContract")
            sp.transfer((), self.data.fee, holder)
            game.finalBet = bet
            game.gameStatus = 2
            self.data.pot += bet
            self.data.games[params.gameId] = game
            sp.emit(sp.record(gameId=params.gameId, bet=bet), tag="continueBet")

        # ─── oracle: reveal the third card and settle ─────────────────────
        @sp.entrypoint
        def lastCard(self, params):
            assert sp.sender == self.data.oracle, "NotOracle"
            assert self.data.games.contains(params.gameId), "NoGame"
            assert params.card < 52, "BadCard"
            game = self.data.games[params.gameId]
            assert game.gameStatus == 2, "BadStatus"

            value = sp.to_int(params.card / 4) + 2
            game.hand[3] = sp.to_int(params.card)
            game.handValue[3] = value
            game.handHashes[3] = params.hash

            # Apply the player's Ace-high vs Ace-low choice. Aces are encoded
            # as 14; if aceHigh==0 we remap any 14 to 1 for the comparison.
            v1 = game.handValue[1]
            v2 = game.handValue[2]
            v3 = value
            if game.aceHigh == 0:
                if v1 == 14:
                    v1 = 1
                if v2 == 14:
                    v2 = 1
                if v3 == 14:
                    v3 = 1

            low = v1
            high = v2
            if v2 < v1:
                low = v2
                high = v1

            if v3 > low:
                if v3 < high:
                    # Win — pay 2× finalBet from the pot.
                    payout = sp.split_tokens(game.finalBet, 2, 1)
                    game.gameStatus = 3
                    self.data.pot -= payout
                    sp.send(game.player, payout)
                    sp.emit(sp.record(gameId=params.gameId, payout=payout), tag="win")
                else:
                    # v3 >= high
                    game.gameStatus = 4
                    if v3 == high:
                        rail = game.finalBet + self.data.ante
                        if rail > self.data.pot:
                            rail = self.data.pot
                        self.data.pot -= rail
                        holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(error="NoTxlContract")
                        sp.transfer((), rail, holder)
                        sp.emit(sp.record(gameId=params.gameId, rail=rail), tag="rail")
                    else:
                        sp.emit(params.gameId, tag="loss")
            else:
                # v3 <= low
                game.gameStatus = 4
                if v3 == low:
                    rail = game.finalBet + self.data.ante
                    if rail > self.data.pot:
                        rail = self.data.pot
                    self.data.pot -= rail
                    holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(error="NoTxlContract")
                    sp.transfer((), rail, holder)
                    sp.emit(sp.record(gameId=params.gameId, rail=rail), tag="rail")
                else:
                    sp.emit(params.gameId, tag="loss")

            # Top up pot from reserve if it dropped below the trigger.
            if self.data.pot < self.data.potTopUpTrigger:
                if self.data.potReserve >= self.data.potTopUp:
                    self.data.pot += self.data.potTopUp
                    self.data.potReserve -= self.data.potTopUp

            self.data.games[params.gameId] = game

        # ─── admin: drain reserve only (never touches the active pot) ──────
        @sp.entrypoint
        def withdrawReserve(self, params):
            assert sp.sender == self.data.admin, "NotAdmin"
            assert params.amount <= self.data.potReserve, "ReserveTooLow"
            self.data.potReserve -= params.amount
            sp.send(params.dest, params.amount)


# ─── Tests ───────────────────────────────────────────────────────────────────
@sp.add_test()
def test_basic_flow():
    s = sp.test_scenario("basic_flow", main)
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = main.AceyDuecey(admin.address, oracle.address, holder.address)
    c.set_initial_balance(sp.tez(0))
    s += c

    c.default(_amount=sp.tez(2), _sender=admin)
    c.bet(aceHigh=1, _sender=player, _amount=sp.mutez(300000))
    c.firstCard(gameId=0, card=10, hash="h1", _sender=oracle)   # value 4
    c.secondCard(gameId=0, card=40, hash="h2", _sender=oracle)  # value 12
    c.continueBet(gameId=0, _sender=player, _amount=sp.mutez(200000))
    c.lastCard(gameId=0, card=24, hash="h3", _sender=oracle)    # value 8 (between)


@sp.add_test()
def test_pair_refund():
    s = sp.test_scenario("pair_refund", main)
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = main.AceyDuecey(admin.address, oracle.address, holder.address)
    c.set_initial_balance(sp.tez(0))
    s += c
    c.default(_amount=sp.tez(2), _sender=admin)
    c.bet(aceHigh=1, _sender=player, _amount=sp.mutez(300000))
    c.firstCard(gameId=0, card=8, hash="h1", _sender=oracle)    # value 4
    c.secondCard(gameId=0, card=11, hash="h2", _sender=oracle)  # value 4 → pair


@sp.add_test()
def test_rail():
    s = sp.test_scenario("rail", main)
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")

    c = main.AceyDuecey(admin.address, oracle.address, holder.address)
    c.set_initial_balance(sp.tez(0))
    s += c
    c.default(_amount=sp.tez(2), _sender=admin)
    c.bet(aceHigh=1, _sender=player, _amount=sp.mutez(300000))
    c.firstCard(gameId=0, card=4, hash="h1", _sender=oracle)    # value 3
    c.secondCard(gameId=0, card=44, hash="h2", _sender=oracle)  # value 13
    c.continueBet(gameId=0, _sender=player, _amount=sp.mutez(200000))
    c.lastCard(gameId=0, card=4, hash="h3", _sender=oracle)     # rail = low


@sp.add_test()
def test_not_oracle_blocked():
    s = sp.test_scenario("auth", main)
    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    holder = sp.test_account("holder")
    player = sp.test_account("player")
    attacker = sp.test_account("attacker")

    c = main.AceyDuecey(admin.address, oracle.address, holder.address)
    c.set_initial_balance(sp.tez(0))
    s += c
    c.default(_amount=sp.tez(2), _sender=admin)
    c.bet(aceHigh=1, _sender=player, _amount=sp.mutez(300000))
    c.firstCard(gameId=0, card=10, hash="h", _sender=attacker,
                _valid=False, _exception="NotOracle")
