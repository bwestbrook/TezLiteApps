import smartpy as sp

# ─── Chess (escrow + move-record stub) ───────────────────────────────────
#
# Modern SmartPy stub. We trust the client (or the legacy chess contract,
# which has full move validation) to compute legal moves; this contract
# just records the wagering escrow, turn order, and resignation/timeout
# settlement. Production-grade rule enforcement lives in the legacy file
# smart_contract_chess.py — port that here when you're ready.
#
# Board encoding (FEN-ish):
#   64 cells, idx = rank * 8 + file. Piece codes:
#     0  empty
#     1  white pawn      7   black pawn
#     2  white knight    8   black knight
#     3  white bishop    9   black bishop
#     4  white rook      10  black rook
#     5  white queen     11  black queen
#     6  white king      12  black king

@sp.module
def main():
    class Chess(sp.Contract):
        def __init__(self):
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            self.data.fee = sp.mutez(100000)
            self.data.minWager = sp.mutez(100000)
            self.data.maxWager = sp.mutez(5000000)
            self.data.staleBlocks = sp.nat(120)   # ~1 hour at 30s blocks
            self.data.currentGameId = sp.nat(0)

            # Initial chess board.
            initBoard = sp.cast({}, sp.map[sp.nat, sp.nat])
            for i in range(64):
                initBoard[i] = 0
            # White back rank
            backRankW = {0: 4, 1: 2, 2: 3, 3: 5, 4: 6, 5: 3, 6: 2, 7: 4}
            for i, p in backRankW.items():
                initBoard[i] = p
            for i in range(8, 16):
                initBoard[i] = 1
            # Black back rank
            backRankB = {56: 10, 57: 8, 58: 9, 59: 11, 60: 12, 61: 9, 62: 8, 63: 10}
            for i, p in backRankB.items():
                initBoard[i] = p
            for i in range(48, 56):
                initBoard[i] = 7
            self.data.initialBoard = initBoard

            self.data.games = sp.cast({}, sp.map[sp.nat, sp.record(
                white=sp.address,
                black=sp.address,
                wager=sp.mutez,
                board=sp.map[sp.nat, sp.nat],
                toMove=sp.nat,           # 1=white 2=black
                moveCount=sp.nat,
                lastMoveBlock=sp.nat,
                gameStatus=sp.nat,        # 0=open, 1=in-progress, 2=settled, 3=cancelled
                winner=sp.address,
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
                white=sp.sender,
                black=sp.address("tz1burnburnburnburnburnburnburjAYjjX"),
                wager=params.wager,
                board=self.data.initialBoard,
                toMove=1,
                moveCount=0,
                lastMoveBlock=sp.level,
                gameStatus=0,
                winner=sp.address("tz1burnburnburnburnburnburnburjAYjjX"),
            )
            sp.emit(self.data.currentGameId, tag='gameCreated')
            self.data.currentGameId += 1

        @sp.entrypoint()
        def joinGame(self, params):
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 0, "game not open"
            assert sp.amount == g.wager + self.data.fee, "must match wager + fee"
            assert sp.sender != g.white, "can't join your own game"
            sp.send(self.data.txlContract, self.data.fee)
            self.data.games[params.gameId].black = sp.sender
            self.data.games[params.gameId].gameStatus = 1
            self.data.games[params.gameId].lastMoveBlock = sp.level
            sp.emit([params.gameId], tag='gameJoined')

        @sp.entrypoint()
        def submitMove(self, params):
            '''Client-validated. Contract trusts the board diff and records
            it. Use the legacy chess contract for on-chain validation.'''
            sp.cast(params.gameId, sp.nat)
            sp.cast(params.newBoard, sp.map[sp.nat, sp.nat])
            g = self.data.games[params.gameId]
            assert g.gameStatus == 1, "game not in progress"
            mover = g.white
            if g.toMove == 2:
                mover = g.black
            assert sp.sender == mover, "not your turn"
            nextToMove = 2
            if g.toMove == 2:
                nextToMove = 1
            self.data.games[params.gameId] = sp.record(
                white=g.white,
                black=g.black,
                wager=g.wager,
                board=params.newBoard,
                toMove=nextToMove,
                moveCount=g.moveCount + 1,
                lastMoveBlock=sp.level,
                gameStatus=g.gameStatus,
                winner=g.winner,
            )

        @sp.entrypoint()
        def resign(self, params):
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 1, "game not in progress"
            assert sp.sender == g.white or sp.sender == g.black, "not a player"
            winnerAddr = g.black
            if sp.sender == g.black:
                winnerAddr = g.white
            pot = sp.split_tokens(g.wager, 2, 1)
            sp.send(winnerAddr, pot)
            self.data.games[params.gameId].gameStatus = 2
            self.data.games[params.gameId].winner = winnerAddr
            sp.emit([params.gameId], tag='resigned')

        @sp.entrypoint()
        def claimByTimeout(self, params):
            '''Opponent has been idle for staleBlocks; claim victory.'''
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 1, "game not in progress"
            assert sp.level - g.lastMoveBlock >= self.data.staleBlocks, "not stale yet"
            mover = g.white
            if g.toMove == 2:
                mover = g.black
            assert sp.sender != mover, "you owe the move"
            pot = sp.split_tokens(g.wager, 2, 1)
            sp.send(sp.sender, pot)
            self.data.games[params.gameId].gameStatus = 2
            self.data.games[params.gameId].winner = sp.sender
            sp.emit([params.gameId], tag='claimedByTimeout')

        @sp.entrypoint()
        def cancelGame(self, params):
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 0, "game already in progress"
            assert sp.sender == g.white, "only creator can cancel"
            sp.send(g.white, g.wager)
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

        @sp.entrypoint()
        def updateStaleBlocks(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.staleBlocks = params.staleBlocks


@sp.add_test()
def test():
    s = sp.test_scenario("chess basic", main)
    c = main.Chess()
    s += c
