import smartpy as sp

# ─── Speed-War (best-of-3 card showdown) ─────────────────────────────────
#
# 3-round H2H. Both players stake the same wager, the oracle deals six
# distinct cards (3 per side) in one tx, the contract settles inline by
# round-win count.
#
# Flow:
#   1. createGame(wager)       — player1; contract holds wager + fee
#   2. joinGame(gameId)        — player2 matches; contract holds 2× wager
#   3. deal(gameId, cards1, cards2, seed)
#                              — oracle supplies two 3-entry maps
#                                (round_idx 0..2 → deck_idx 0..51)
#   4. Settles inline. p1Wins / p2Wins counted across the three rounds:
#        higher score takes the pot,
#        equal scores (including 0–0 or 1–1 with a tied round) refund both.
#
# Card indices: 0..51, rank = idx // 4 + 2 (2..14, 14 = Ace). Suits don't
# affect outcome — only rank matters per round.
#
# Why best-of-3 instead of N-card sum-of-ranks:
#   - More dramatic UI reveal (round-by-round flips).
#   - Cleaner tie semantics (round wins are integers, no rounding).
#   - 2-0 sweeps let the UI short-circuit the third reveal for "speed."
#   - On-chain it's still one deal() call — no extra ops.

@sp.module
def main():
    class War(sp.Contract):
        def __init__(self):
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            self.data.fee = sp.mutez(100000)
            self.data.minWager = sp.mutez(100000)
            self.data.maxWager = sp.mutez(5000000)
            self.data.currentGameId = sp.nat(0)
            # Game record: per-round cards stored as maps so the slot for an
            # un-dealt round is simply absent (vs sentinel -1 across N fields).
            self.data.games = sp.cast({}, sp.map[sp.nat, sp.record(
                player1=sp.address,
                player2=sp.address,
                wager=sp.mutez,
                cards1=sp.map[sp.nat, sp.int],   # round_idx (0,1,2) → deck_idx
                cards2=sp.map[sp.nat, sp.int],
                p1Wins=sp.nat,                   # rounds won by player1
                p2Wins=sp.nat,                   # rounds won by player2
                gameStatus=sp.nat,               # 0=open, 1=joined/awaiting deal, 2=settled, 3=cancelled
                winner=sp.address,
                seed=sp.string,
            )])

        @sp.entrypoint
        def default(self):
            '''Anonymous top-up — funds future ties\' refunds.'''
            pass

        @sp.entrypoint()
        def createGame(self, params):
            sp.cast(params.wager, sp.mutez)
            sp.cast(sp.amount, sp.mutez)
            assert sp.amount == params.wager + self.data.fee, "must send wager + fee"
            assert params.wager >= self.data.minWager, "wager too small"
            assert params.wager <= self.data.maxWager, "wager too big"
            sp.send(self.data.txlContract, self.data.fee)
            self.data.games[self.data.currentGameId] = sp.record(
                player1=sp.sender,
                player2=sp.address("tz1burnburnburnburnburnburnburjAYjjX"),
                wager=params.wager,
                cards1={},
                cards2={},
                p1Wins=sp.nat(0),
                p2Wins=sp.nat(0),
                gameStatus=0,
                winner=sp.address("tz1burnburnburnburnburnburnburjAYjjX"),
                seed='',
            )
            sp.emit(self.data.currentGameId, tag='gameCreated')
            self.data.currentGameId += 1

        @sp.entrypoint()
        def joinGame(self, params):
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 0, "game not open"
            assert sp.amount == g.wager + self.data.fee, "must match wager + fee"
            assert sp.sender != g.player1, "can't join your own game"
            sp.send(self.data.txlContract, self.data.fee)
            self.data.games[params.gameId].player2 = sp.sender
            self.data.games[params.gameId].gameStatus = 1
            sp.emit([params.gameId], tag='gameJoined')

        @sp.entrypoint()
        def cancelGame(self, params):
            '''Creator can pull their wager back if no one has joined.'''
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 0, "game already in progress"
            assert sp.sender == g.player1, "only creator can cancel"
            sp.send(g.player1, g.wager)
            self.data.games[params.gameId].gameStatus = 3

        @sp.entrypoint()
        def deal(self, params):
            sp.cast(params, sp.record(
                gameId=sp.nat,
                cards1=sp.map[sp.nat, sp.int],
                cards2=sp.map[sp.nat, sp.int],
                seed=sp.string,
            ))
            assert sp.sender == self.data.oracle, "not oracle"
            g = self.data.games[params.gameId]
            assert g.gameStatus == 1, "game not awaiting deal"

            # Each map must contain entries for rounds 0, 1, 2 — and only
            # those — so we get exactly 3 cards per side. The range
            # assertions below guard against out-of-deck indices.
            assert 0 in params.cards1, "missing round 0 (player1)"
            assert 1 in params.cards1, "missing round 1 (player1)"
            assert 2 in params.cards1, "missing round 2 (player1)"
            assert 0 in params.cards2, "missing round 0 (player2)"
            assert 1 in params.cards2, "missing round 1 (player2)"
            assert 2 in params.cards2, "missing round 2 (player2)"

            # Tally round wins. The Python list loop is unrolled at compile
            # time — each iteration emits straight-line Michelson.
            p1Wins = sp.nat(0)
            p2Wins = sp.nat(0)
            for r in [0, 1, 2]:
                c1 = params.cards1[r]
                c2 = params.cards2[r]
                assert c1 >= 0 and c1 < 52, "cards1 entry out of range"
                assert c2 >= 0 and c2 < 52, "cards2 entry out of range"
                rank1 = c1 / 4
                rank2 = c2 / 4
                if rank1 > rank2:
                    p1Wins += 1
                if rank2 > rank1:
                    p2Wins += 1
                # Equal ranks in a round → no one scores; the round is a wash.

            pot = sp.split_tokens(g.wager, 2, 1)
            winnerAddr = g.player1
            if p1Wins > p2Wins:
                sp.send(g.player1, pot)
                winnerAddr = g.player1
            if p2Wins > p1Wins:
                sp.send(g.player2, pot)
                winnerAddr = g.player2
            if p1Wins == p2Wins:
                # Series tie — refund each wager. Burn address signals "no
                # winner" in storage so the UI can paint a push verdict.
                sp.send(g.player1, g.wager)
                sp.send(g.player2, g.wager)
                winnerAddr = sp.address("tz1burnburnburnburnburnburnburjAYjjX")

            self.data.games[params.gameId] = sp.record(
                player1=g.player1,
                player2=g.player2,
                wager=g.wager,
                cards1=params.cards1,
                cards2=params.cards2,
                p1Wins=p1Wins,
                p2Wins=p2Wins,
                gameStatus=2,
                winner=winnerAddr,
                seed=params.seed,
            )
            sp.emit(
                sp.record(
                    gameId=params.gameId,
                    p1Wins=p1Wins,
                    p2Wins=p2Wins,
                    winner=winnerAddr,
                ),
                tag='gameSettled',
            )

        # ─── Admin ──────────────────────────────────────────────────
        @sp.entrypoint()
        def updateOracle(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.oracle = params.newOracle

        @sp.entrypoint()
        def updateTxlContract(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.txlContract = params.newContract

        @sp.entrypoint()
        def updateWagerBounds(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.minWager = params.minWager
            self.data.maxWager = params.maxWager

        @sp.entrypoint()
        def updateFee(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.fee = params.fee


@sp.add_test()
def test():
    s = sp.test_scenario("war basic", main)
    c = main.War()
    s += c
