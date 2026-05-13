import smartpy as sp

# ─── War (card showdown) ─────────────────────────────────────────────────
#
# 1-card-each pure-luck H2H. Players each stake the wager, oracle deals
# one card per side, higher card wins the full pot. Ties refund.
#
# Flow:
#   1. createGame(wager)         — first player; contract holds wager
#   2. joinGame(gameId)          — second player; contract holds 2× wager
#   3. deal(gameId, card1, card2, seed)  — oracle picks two card indices
#   4. Settles inline: winner gets 2× wager minus fee, or both refunded.
#
# Card indices: 0..51, rank = idx // 4 + 2 (so 2..14, 14 = Ace).

@sp.module
def main():
    class War(sp.Contract):
        def __init__(self):
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.oracle = sp.address("tz1XbrvTMVa5dWQQBSCn2jgX7BPZyLRhgtKS")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            self.data.fee = sp.mutez(100000)
            self.data.minWager = sp.mutez(100000)
            self.data.maxWager = sp.mutez(5000000)
            self.data.currentGameId = sp.nat(0)
            self.data.games = sp.cast({}, sp.map[sp.nat, sp.record(
                player1=sp.address,
                player2=sp.address,
                wager=sp.mutez,
                card1=sp.int,
                card2=sp.int,
                gameStatus=sp.nat,        # 0=open, 1=joined/awaiting deal, 2=settled, 3=cancelled
                winner=sp.address,
                seed=sp.string,
            )])

        @sp.entrypoint
        def default(self):
            '''Anonymous top-up — funds future ties' refunds.'''
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
                card1=-1,
                card2=-1,
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
            sp.cast(params.gameId, sp.nat)
            sp.cast(params.card1, sp.int)
            sp.cast(params.card2, sp.int)
            sp.cast(params.seed, sp.string)
            assert sp.sender == self.data.oracle, "not oracle"
            g = self.data.games[params.gameId]
            assert g.gameStatus == 1, "game not awaiting deal"
            assert params.card1 >= 0 and params.card1 < 52, "card1 out of range"
            assert params.card2 >= 0 and params.card2 < 52, "card2 out of range"
            rank1 = params.card1 / 4
            rank2 = params.card2 / 4
            pot = sp.split_tokens(g.wager, 2, 1)
            winnerAddr = g.player1
            if rank1 > rank2:
                sp.send(g.player1, pot)
                winnerAddr = g.player1
            if rank2 > rank1:
                sp.send(g.player2, pot)
                winnerAddr = g.player2
            if rank1 == rank2:
                # Tie — split refund
                sp.send(g.player1, g.wager)
                sp.send(g.player2, g.wager)
            self.data.games[params.gameId] = sp.record(
                player1=g.player1,
                player2=g.player2,
                wager=g.wager,
                card1=params.card1,
                card2=params.card2,
                gameStatus=2,
                winner=winnerAddr,
                seed=params.seed,
            )
            sp.emit([params.gameId, params.card1, params.card2], tag='gameSettled')

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
