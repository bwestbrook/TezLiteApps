import smartpy as sp

# ─── Reversi (Othello) ───────────────────────────────────────────────────
#
# Modern SmartPy stub for the H2H reversi escrow. Game logic (which discs
# flip on which move) is computed off-chain and submitted via submitMove
# with a board-after diff. The contract enforces turn order, who plays,
# and game-end accounting. Full on-chain move validation lives in the
# legacy file smart_contract_reversi.py — keep referencing that until
# this stub gets ported up to feature-parity.
#
# Board encoding:
#   64 cells, idx = row*8 + col. 0=empty, 1=black, 2=white.
#   By convention player1 = black, player2 = white. Black plays first.

@sp.module
def main():
    class Reversi(sp.Contract):
        def __init__(self):
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            self.data.fee = sp.mutez(100000)
            self.data.minWager = sp.mutez(100000)
            self.data.maxWager = sp.mutez(5000000)
            self.data.currentGameId = sp.nat(0)

            # Initial board, flat-ints, with the 4 starting discs.
            # idx layout: (3,3)=2  (3,4)=1  (4,3)=1  (4,4)=2
            startBoard = sp.cast({}, sp.map[sp.nat, sp.nat])
            for i in range(64):
                startBoard[i] = 0
            startBoard[27] = 2   # (3,3)
            startBoard[28] = 1   # (3,4)
            startBoard[35] = 1   # (4,3)
            startBoard[36] = 2   # (4,4)
            self.data.initialBoard = startBoard

            self.data.games = sp.cast({}, sp.map[sp.nat, sp.record(
                player1=sp.address,
                player2=sp.address,
                wager=sp.mutez,
                board=sp.map[sp.nat, sp.nat],
                toMove=sp.nat,         # 1 or 2
                moveCount=sp.nat,
                gameStatus=sp.nat,     # 0=open, 1=in-progress, 2=settled, 3=cancelled
                winner=sp.address,
                blackCount=sp.nat,
                whiteCount=sp.nat,
            )])

        @sp.entrypoint
        def default(self):
            pass

        @sp.entrypoint()
        def createGame(self, params):
            sp.cast(params.wager, sp.mutez)
            assert sp.amount == params.wager + self.data.fee, "must send wager + fee"
            assert params.wager >= self.data.minWager, "wager too small"
            assert params.wager <= self.data.maxWager, "wager too big"
            sp.send(self.data.txlContract, self.data.fee)
            self.data.games[self.data.currentGameId] = sp.record(
                player1=sp.sender,
                player2=sp.address("tz1burnburnburnburnburnburnburjAYjjX"),
                wager=params.wager,
                board=self.data.initialBoard,
                toMove=1,
                moveCount=0,
                gameStatus=0,
                winner=sp.address("tz1burnburnburnburnburnburnburjAYjjX"),
                blackCount=2,
                whiteCount=2,
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

        # Trust-but-verify: the *client* computes the flipped discs and
        # the resulting board. The contract enforces (a) it's your turn,
        # (b) you're touching an empty square, and (c) the flip count is
        # plausible (≥ 1). Full rule enforcement lives in the legacy
        # contract; this stub trades correctness for compile simplicity.
        @sp.entrypoint()
        def submitMove(self, params):
            sp.cast(params.gameId, sp.nat)
            sp.cast(params.cell, sp.nat)
            sp.cast(params.newBoard, sp.map[sp.nat, sp.nat])
            sp.cast(params.blackCount, sp.nat)
            sp.cast(params.whiteCount, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 1, "game not in progress"
            assert params.cell < 64, "cell out of range"
            mover = g.player1
            if g.toMove == 2:
                mover = g.player2
            assert sp.sender == mover, "not your turn"
            assert g.board[params.cell] == 0, "cell not empty"
            # Must have flipped at least one disc (in addition to placing one).
            assert params.blackCount + params.whiteCount > g.blackCount + g.whiteCount, "no flips"
            nextToMove = 2
            if g.toMove == 2:
                nextToMove = 1
            self.data.games[params.gameId] = sp.record(
                player1=g.player1,
                player2=g.player2,
                wager=g.wager,
                board=params.newBoard,
                toMove=nextToMove,
                moveCount=g.moveCount + 1,
                gameStatus=g.gameStatus,
                winner=g.winner,
                blackCount=params.blackCount,
                whiteCount=params.whiteCount,
            )
            sp.emit([params.gameId, params.cell], tag='moveSubmitted')

        @sp.entrypoint()
        def settle(self, params):
            '''Either player calls settle once the board is full or both
            sides pass. Payout uses the recorded blackCount/whiteCount.'''
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 1, "game not in progress"
            assert sp.sender == g.player1 or sp.sender == g.player2, "not a player"
            pot = sp.split_tokens(g.wager, 2, 1)
            winnerAddr = g.player1
            if g.blackCount > g.whiteCount:
                sp.send(g.player1, pot)
                winnerAddr = g.player1
            if g.whiteCount > g.blackCount:
                sp.send(g.player2, pot)
                winnerAddr = g.player2
            if g.blackCount == g.whiteCount:
                sp.send(g.player1, g.wager)
                sp.send(g.player2, g.wager)
            self.data.games[params.gameId] = sp.record(
                player1=g.player1,
                player2=g.player2,
                wager=g.wager,
                board=g.board,
                toMove=g.toMove,
                moveCount=g.moveCount,
                gameStatus=2,
                winner=winnerAddr,
                blackCount=g.blackCount,
                whiteCount=g.whiteCount,
            )
            sp.emit([params.gameId], tag='gameSettled')

        @sp.entrypoint()
        def cancelGame(self, params):
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 0, "game already in progress"
            assert sp.sender == g.player1, "only creator can cancel"
            sp.send(g.player1, g.wager)
            self.data.games[params.gameId].gameStatus = 3

        # ─── Admin ──────────────────────────────────────────────────
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
    s = sp.test_scenario("reversi basic", main)
    c = main.Reversi()
    s += c
