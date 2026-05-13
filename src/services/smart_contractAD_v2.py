"""
Acey-Duecey (a.k.a. In-Between) — SmartPy contract, v2.

Rules implemented (matching the on-screen text in src/constants.js → AD_GAME_INFO):

  1. Player calls `bet` with `ante + fee` mutez. The ante goes to the pot,
     the fee is forwarded to the TXL holder contract.
  2. Oracle calls `firstCard` with a deck index 0..51 → revealed to the player.
  3. Oracle calls `secondCard`:
        - Same rank as first card → "pair drawn": half the ante refunds to
          the player, half goes to TXL holders, game ends (status = 5).
        - Otherwise → status = 1, game waits for the player's continueBet.
  4. Player calls `continueBet` with `bet + fee`. The bet must be ≤ pot.
     Status moves to 2.
  5. Oracle calls `lastCard`:
        - Strictly between low and high (exclusive) → player wins 2× their
          continueBet from the pot (status = 3).
        - Equal to either card ("rail") → player loses, the bet+ante are
          forwarded to TXL holders (status = 4).
        - Outside range → player loses (status = 4).

The card index is 0..51 where rank = card // 4 and suit = card % 4.
Numeric value = rank + 2 (so 2..14, with Ace=14 if `aceHigh=1`, else Ace=2).

Game status enum:
    0 = bet placed, awaiting first two cards
    1 = two cards drawn, awaiting continueBet
    2 = continueBet placed, awaiting last card
    3 = won
    4 = lost
    5 = pair drawn on ante (half refund)
"""

import smartpy as sp


# ─── Status constants (kept out of storage to save bytes) ────────────────────
STATUS_BET_PLACED = 0
STATUS_TWO_CARDS_DRAWN = 1
STATUS_CONTINUE_BET_PLACED = 2
STATUS_WON = 3
STATUS_LOST = 4
STATUS_PAIR_REFUND = 5


@sp.module
def main():
    # ─── Per-game record type ────────────────────────────────────────────────
    game_t: type = sp.record(
        player=sp.address,
        aceHigh=sp.int,         # 1 = Ace counts as 14, 0 = Ace counts as 2
        gameStatus=sp.int,
        finalBet=sp.mutez,      # the continueBet amount (excluding fee)
        # Hands: keys 1, 2, 3 → first, second, third card
        hand=sp.map[sp.int, sp.int],         # raw deck index 0..51
        handValue=sp.map[sp.int, sp.int],    # numeric rank 2..14
        handHashes=sp.map[sp.int, sp.string],
    ).layout(("player", ("aceHigh", ("gameStatus", ("finalBet", ("hand", ("handValue", "handHashes")))))))

    class AceyDuecey(sp.Contract):
        def __init__(self, admin, oracle, txlContract):
            # ─── Roles ──────────────────────────────────────────────────────
            self.data.admin = admin
            self.data.oracle = oracle
            self.data.txlContract = txlContract

            # ─── Money (all in mutez — single unit, no tez/mutez mixing) ────
            self.data.ante = sp.mutez(200_000)        # 0.2 ꜩ ante
            self.data.fee = sp.mutez(100_000)         # 0.1 ꜩ holder fee per action
            self.data.potTopUp = sp.mutez(125_000)    # auto-top-up amount when pot is empty
            self.data.potTopUpTrigger = sp.mutez(125_000)  # if pot drops below this, top up

            # ─── Pot accounting ─────────────────────────────────────────────
            # NOTE: starts at 0 so storage matches actual balance at origination.
            # Seed the pot via the `default` entrypoint after deploy.
            self.data.pot = sp.mutez(0)
            self.data.potReserve = sp.mutez(0)

            # ─── Game ledger ────────────────────────────────────────────────
            self.data.games = sp.cast(sp.big_map(), sp.big_map[sp.nat, game_t])
            self.data.currentGameIndex = 0

        # ─── Helpers ────────────────────────────────────────────────────────
        @sp.private(with_storage="read-write")
        def _forwardFee(self):
            """Send the configured fee to the TXL holder contract."""
            holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(error="NoTxlContract")
            sp.transfer((), self.data.fee, holder)

        @sp.private(with_storage="read-write")
        def _send(self, params):
            """Send `amount` mutez to `dest` if dest is implicit."""
            sp.cast(params, sp.record(dest=sp.address, amount=sp.mutez))
            assert params.amount > sp.mutez(0), "ZeroSend"
            sp.send(params.dest, params.amount)

        # ─── Default: receive funding into the reserve ──────────────────────
        @sp.entrypoint
        def default(self):
            self.data.potReserve += sp.amount

        # ─── Admin: change roles ────────────────────────────────────────────
        @sp.entrypoint
        def updateTxlContract(self, params):
            sp.cast(params, sp.record(newContract=sp.address))
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.txlContract = params.newContract

        @sp.entrypoint
        def updateOracle(self, params):
            sp.cast(params, sp.record(newOracle=sp.address))
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.oracle = params.newOracle  # ← was overwriting txlContract in v1

        @sp.entrypoint
        def updateAdmin(self, params):
            sp.cast(params, sp.record(newAdmin=sp.address))
            assert sp.sender == self.data.admin, "NotAdmin"
            self.data.admin = params.newAdmin

        # ─── Player: open a new game ────────────────────────────────────────
        @sp.entrypoint
        def bet(self, params):
            sp.cast(params, sp.record(aceHigh=sp.int))
            # v1 had `assert sp.amount == sp.amount` (tautology). Real check:
            assert sp.amount == self.data.ante + self.data.fee, "BadAmount"
            assert params.aceHigh == 1 or params.aceHigh == 0, "BadAceHigh"

            self.data.pot += self.data.ante
            self._forwardFee()

            new_game = sp.record(
                player=sp.sender,
                aceHigh=params.aceHigh,
                gameStatus=STATUS_BET_PLACED,
                finalBet=sp.mutez(0),
                hand=sp.cast({1: -1, 2: -1, 3: -1}, sp.map[sp.int, sp.int]),
                handValue=sp.cast({1: -1, 2: -1, 3: -1}, sp.map[sp.int, sp.int]),
                handHashes=sp.cast({1: "", 2: "", 3: ""}, sp.map[sp.int, sp.string]),
            )
            self.data.games[self.data.currentGameIndex] = new_game
            sp.emit(self.data.currentGameIndex, tag="betMade")
            self.data.currentGameIndex += 1

        # ─── Oracle: reveal first card ──────────────────────────────────────
        @sp.entrypoint
        def firstCard(self, params):
            sp.cast(params, sp.record(gameId=sp.nat, card=sp.nat, hash=sp.string))
            assert sp.sender == self.data.oracle, "NotOracle"  # v1: was commented out
            assert self.data.games.contains(params.gameId), "NoGame"
            game = self.data.games[params.gameId]
            assert game.gameStatus == STATUS_BET_PLACED, "BadStatus"
            assert params.card < 52, "BadCard"

            value = sp.to_int(params.card / 4) + 2  # 2..14
            game.hand[1] = sp.to_int(params.card)
            game.handValue[1] = value
            game.handHashes[1] = params.hash
            self.data.games[params.gameId] = game
            sp.emit(sp.record(gameId=params.gameId, card=params.card), tag="firstCard")

        # ─── Oracle: reveal second card ─────────────────────────────────────
        @sp.entrypoint
        def secondCard(self, params):
            sp.cast(params, sp.record(gameId=sp.nat, card=sp.nat, hash=sp.string))
            assert sp.sender == self.data.oracle, "NotOracle"
            assert self.data.games.contains(params.gameId), "NoGame"
            game = self.data.games[params.gameId]
            assert game.gameStatus == STATUS_BET_PLACED, "BadStatus"
            assert params.card < 52, "BadCard"

            value = sp.to_int(params.card / 4) + 2  # 2..14, comparable to handValue[1]
            game.hand[2] = sp.to_int(params.card)
            game.handValue[2] = value
            game.handHashes[2] = params.hash

            # v1 BUG: compared `handValue[1]` (2..14) to `cardValue` (0..12) → never matched.
            if game.handValue[1] == value:
                # Pair drawn on the ante: half ante back to player, half to holders.
                halfAnte = sp.split_tokens(self.data.ante, 1, 2)
                game.gameStatus = STATUS_PAIR_REFUND
                self.data.pot -= self.data.ante
                self._send(sp.record(dest=game.player, amount=halfAnte))
                holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(error="NoTxlContract")
                sp.transfer((), halfAnte, holder)
                sp.emit(params.gameId, tag="pairDrawn")
            else:
                game.gameStatus = STATUS_TWO_CARDS_DRAWN
                sp.emit(sp.record(gameId=params.gameId, card=params.card), tag="secondCard")

            self.data.games[params.gameId] = game

        # ─── Player: place the in-between bet ───────────────────────────────
        @sp.entrypoint
        def continueBet(self, params):
            sp.cast(params, sp.record(gameId=sp.nat))
            assert self.data.games.contains(params.gameId), "NoGame"
            game = self.data.games[params.gameId]
            assert sp.sender == game.player, "NotPlayer"
            assert game.gameStatus == STATUS_TWO_CARDS_DRAWN, "BadStatus"
            assert sp.amount > self.data.fee, "BetTooSmall"
            bet = sp.amount - self.data.fee
            assert bet <= self.data.pot, "BetExceedsPot"

            self._forwardFee()
            game.finalBet = bet
            game.gameStatus = STATUS_CONTINUE_BET_PLACED
            self.data.pot += bet
            self.data.games[params.gameId] = game
            sp.emit(sp.record(gameId=params.gameId, bet=bet), tag="continueBet")

        # ─── Oracle: reveal the third (in-between) card ─────────────────────
        @sp.entrypoint
        def lastCard(self, params):
            sp.cast(params, sp.record(gameId=sp.nat, card=sp.nat, hash=sp.string))
            assert sp.sender == self.data.oracle, "NotOracle"
            assert self.data.games.contains(params.gameId), "NoGame"
            game = self.data.games[params.gameId]
            assert game.gameStatus == STATUS_CONTINUE_BET_PLACED, "BadStatus"
            assert params.card < 52, "BadCard"

            value = sp.to_int(params.card / 4) + 2
            game.hand[3] = sp.to_int(params.card)
            game.handValue[3] = value
            game.handHashes[3] = params.hash

            # ─── Apply Ace-high vs Ace-low for the player's chosen orientation ─
            # Card rank for ace is encoded as 14 (since rank = card//4 + 2 and ace = 12+2).
            # If player chose aceHigh=0, treat aces (14) as 1 for the comparison.
            v1 = game.handValue[1]
            v2 = game.handValue[2]
            v3 = value
            if game.aceHigh == 0:
                if v1 == 14: v1 = 1
                if v2 == 14: v2 = 1
                if v3 == 14: v3 = 1

            low = v1
            high = v2
            if v2 < v1:
                low = v2
                high = v1

            # ─── Settlement ──────────────────────────────────────────────────
            if v3 > low and v3 < high:
                # Win: pay 2× the player's continueBet from the pot.
                payout = sp.split_tokens(game.finalBet, 2, 1)
                game.gameStatus = STATUS_WON
                self.data.pot -= payout
                self._send(sp.record(dest=game.player, amount=payout))
                sp.emit(sp.record(gameId=params.gameId, payout=payout), tag="win")
            else:
                game.gameStatus = STATUS_LOST
                if v3 == low or v3 == high:
                    # "Hit the rail": bet + ante go to the holder contract (penalty).
                    railAmount = game.finalBet + self.data.ante
                    if railAmount > self.data.pot:
                        railAmount = self.data.pot  # don't underflow
                    self.data.pot -= railAmount
                    holder = sp.contract(sp.unit, self.data.txlContract).unwrap_some(error="NoTxlContract")
                    sp.transfer((), railAmount, holder)
                    sp.emit(sp.record(gameId=params.gameId, rail=railAmount), tag="rail")
                else:
                    # Just lost — bet stays in the pot.
                    sp.emit(params.gameId, tag="loss")

            # ─── Pot top-up if it dropped below the trigger ──────────────────
            if self.data.pot < self.data.potTopUpTrigger:
                if self.data.potReserve >= self.data.potTopUp:
                    self.data.pot += self.data.potTopUp
                    self.data.potReserve -= self.data.potTopUp

            self.data.games[params.gameId] = game

        # ─── Admin: emergency drain (unrelated reserve only — never the pot) ─
        @sp.entrypoint
        def withdrawReserve(self, params):
            sp.cast(params, sp.record(amount=sp.mutez, dest=sp.address))
            assert sp.sender == self.data.admin, "NotAdmin"
            assert params.amount <= self.data.potReserve, "ReserveTooLow"
            self.data.potReserve -= params.amount
            self._send(sp.record(dest=params.dest, amount=params.amount))


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

    # Fund the pot reserve.
    c.default(_amount=sp.tez(2), _sender=admin)

    # Player ante.
    c.bet(aceHigh=1, _sender=player, _amount=sp.mutez(300_000))

    # Two non-pair cards.
    c.firstCard(gameId=0, card=10, hash="h1", _sender=oracle)   # rank 4 (4 of hearts), value 4
    c.secondCard(gameId=0, card=40, hash="h2", _sender=oracle)  # rank 12 (Q), value 12

    # Player continues the bet.
    c.continueBet(gameId=0, _sender=player, _amount=sp.mutez(200_000))

    # Third card between low(4) and high(12) → player wins 2× bet.
    c.lastCard(gameId=0, card=24, hash="h3", _sender=oracle)    # rank 8, value 8

    s.show(c.balance)


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

    c.bet(aceHigh=1, _sender=player, _amount=sp.mutez(300_000))
    c.firstCard(gameId=0, card=8, hash="h1", _sender=oracle)    # rank 2, value 4
    c.secondCard(gameId=0, card=11, hash="h2", _sender=oracle)  # rank 2, value 4 → PAIR


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

    c.bet(aceHigh=1, _sender=player, _amount=sp.mutez(300_000))
    c.firstCard(gameId=0, card=4, hash="h1", _sender=oracle)    # rank 1, value 3
    c.secondCard(gameId=0, card=44, hash="h2", _sender=oracle)  # rank 13, value 14 (A)
    c.continueBet(gameId=0, _sender=player, _amount=sp.mutez(200_000))
    c.lastCard(gameId=0, card=4, hash="h3", _sender=oracle)     # value 3 == low → RAIL


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

    c.bet(aceHigh=1, _sender=player, _amount=sp.mutez(300_000))
    # Attacker tries to deal cards — must be rejected.
    c.firstCard(gameId=0, card=10, hash="h", _sender=attacker, _valid=False, _exception="NotOracle")
