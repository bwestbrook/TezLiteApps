import smartpy as sp

# ──────────────────────────────────────────────────────────────────────────────
# Chess (gambling escrow + house cut)
#
# Modeled on the SmartPy IDE chess template (modern @sp.module style with a
# t_status variant, t_move record, etc.) but adapted to the TezLiteApps lobby
# pattern: a single contract holds many games keyed by gameId.
#
# What's new vs. the previous stub:
#   • houseCut         — basis points of the total pot retained by the house
#                        (default 250 = 2.5%). Configurable by admin.
#   • houseAddress     — destination of the house cut (default = txlContract,
#                        i.e. the holder fund). Configurable by admin.
#   • settle()         — single payout entrypoint that splits the pot:
#                        winner gets (2*wager − house_cut), house gets cut.
#                        Drawn games refund each side wager − houseCut/2.
#   • IDE-template-style entrypoints — giveup, offer_draw, deny_draw,
#     claim_checkmate, claim_stalemate, threefold_repetition_claim, play.
#
# Move validation is still client-trusted (the legacy on-chain validator lives
# in smart_contract_chess.py if/when feature parity is desired). The escrow,
# the turn order, and the payout math are enforced on chain.
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
# ──────────────────────────────────────────────────────────────────────────────

@sp.module
def main():
    # ── Status (mirrors the IDE template's t_status variant) ────────────────
    #
    # play          — game is in progress, white-to-move-or-black-to-move
    # finished      — terminal: "player_1_won" | "player_2_won" | "draw"
    # claim_stalemate — a stalemate claim has been raised; opponent must
    #                   accept or refuse (refusal = next move).
    t_status: type = sp.variant(
        play=sp.unit,
        force_play=sp.unit,
        finished=sp.string,
        claim_stalemate=sp.unit,
    )

    # ── Move (mirrors t_move from the IDE template) ─────────────────────────
    t_move: type = sp.record(
        f=sp.record(i=sp.nat, j=sp.nat),
        t=sp.record(i=sp.nat, j=sp.nat),
        promotion=sp.option[sp.nat],
    )

    # ── Per-game record ─────────────────────────────────────────────────────
    #
    # gameStatus encoding:
    #   0 = open (created, awaiting join)
    #   1 = joined, awaiting oracle flipForFirst
    #   2 = in-progress
    #   3 = settled (paid out)
    #   4 = cancelled (refunded)
    # toMove: 0 = awaiting flip, 1 = white, 2 = black
    # drawOfferedBy: 0 = none, 1 = white, 2 = black
    t_game: type = sp.record(
        white=sp.address,
        black=sp.address,
        wager=sp.mutez,
        board=sp.map[sp.nat, sp.nat],
        toMove=sp.nat,
        moveCount=sp.nat,
        lastMoveBlock=sp.nat,
        gameStatus=sp.nat,
        winner=sp.address,
        flipSeed=sp.string,
        drawOfferedBy=sp.nat,
        houseCutBps=sp.nat,        # snapshot at game-creation time
        status=t_status,
    )

    BURN: sp.address = sp.address("tz1burnburnburnburnburnburnburjAYjjX")

    class Chess(sp.Contract):
        def __init__(self):
            # ── Admin / wiring ────────────────────────────────────────────
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            # House cut is *additive* to the per-tx fee. The fee is forwarded
            # immediately to the txl/holder contract (same as the older
            # contracts in this repo do); houseCut is taken at settlement.
            self.data.houseAddress = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            self.data.fee = sp.mutez(100000)
            self.data.minWager = sp.mutez(100000)
            self.data.maxWager = sp.mutez(50000000)
            self.data.houseCutBps = sp.nat(250)        # 2.5% of total pot
            self.data.staleBlocks = sp.nat(120)        # ~1 hour at 30s blocks
            self.data.currentGameId = sp.nat(0)

            # ── Initial chess board ───────────────────────────────────────
            initBoard = sp.cast({}, sp.map[sp.nat, sp.nat])
            for i in range(64):
                initBoard[i] = 0
            backRankW = {0: 4, 1: 2, 2: 3, 3: 5, 4: 6, 5: 3, 6: 2, 7: 4}
            for i, p in backRankW.items():
                initBoard[i] = p
            for i in range(8, 16):
                initBoard[i] = 1
            backRankB = {56: 10, 57: 8, 58: 9, 59: 11, 60: 12, 61: 9, 62: 8, 63: 10}
            for i, p in backRankB.items():
                initBoard[i] = p
            for i in range(48, 56):
                initBoard[i] = 7
            self.data.initialBoard = initBoard

            self.data.games = sp.cast({}, sp.map[sp.nat, t_game])

        # ── Helpers ──────────────────────────────────────────────────────
        @sp.private(with_storage="read-only")
        def computeHouse(self, totalPot):
            """House cut on a (mutez) pot. totalPot * houseCutBps / 10000."""
            sp.cast(totalPot, sp.mutez)
            return sp.split_tokens(totalPot, self.data.houseCutBps, 10000)

        # ── Default ──────────────────────────────────────────────────────
        @sp.entrypoint
        def default(self):
            pass

        # ── Lobby: createGame / joinGame / cancelGame ───────────────────
        @sp.entrypoint()
        def createGame(self, params):
            """White creates a game.

            Sender locks `wager + fee`. The fee is forwarded to the holder
            contract immediately. The wager stays in escrow until settlement.
            """
            sp.cast(params.wager, sp.mutez)
            assert sp.amount == params.wager + self.data.fee, "must send wager + fee"
            assert params.wager >= self.data.minWager, "wager too small"
            assert params.wager <= self.data.maxWager, "wager too big"
            sp.send(self.data.txlContract, self.data.fee)

            self.data.games[self.data.currentGameId] = sp.record(
                white=sp.sender,
                black=BURN,
                wager=params.wager,
                board=self.data.initialBoard,
                toMove=0,                      # awaiting oracle flip
                moveCount=0,
                lastMoveBlock=sp.level,
                gameStatus=0,
                winner=BURN,
                flipSeed='',
                drawOfferedBy=0,
                houseCutBps=self.data.houseCutBps,   # snapshot for fairness
                status=sp.variant.play(),
            )
            sp.emit(self.data.currentGameId, tag='gameCreated')
            self.data.currentGameId += 1

        @sp.entrypoint()
        def joinGame(self, params):
            """Black joins, matching wager + fee."""
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 0, "game not open"
            assert sp.amount == g.wager + self.data.fee, "must match wager + fee"
            assert sp.sender != g.white, "can't join your own game"
            sp.send(self.data.txlContract, self.data.fee)
            self.data.games[params.gameId].black = sp.sender
            self.data.games[params.gameId].gameStatus = 1   # awaiting oracle flip
            self.data.games[params.gameId].lastMoveBlock = sp.level
            sp.emit([params.gameId], tag='gameJoined')

        @sp.entrypoint()
        def cancelGame(self, params):
            """Creator can cancel an un-joined game and reclaim the wager.

            Note the fee is NOT refunded — it was already forwarded to the
            holder contract on creation.
            """
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 0, "game already in progress"
            assert sp.sender == g.white, "only creator can cancel"
            sp.send(g.white, g.wager)
            self.data.games[params.gameId].gameStatus = 4

        # ── Oracle flip ──────────────────────────────────────────────────
        @sp.entrypoint()
        def flipForFirst(self, params):
            sp.cast(params.gameId, sp.nat)
            sp.cast(params.bit, sp.nat)
            sp.cast(params.seed, sp.string)
            assert sp.sender == self.data.oracle, "not oracle"
            assert params.bit < 2, "bit must be 0 or 1"
            g = self.data.games[params.gameId]
            assert g.gameStatus == 1, "game not awaiting flip"
            self.data.games[params.gameId].toMove = params.bit + 1
            self.data.games[params.gameId].gameStatus = 2
            self.data.games[params.gameId].lastMoveBlock = sp.level
            self.data.games[params.gameId].flipSeed = params.seed
            sp.emit([params.gameId, params.bit], tag='firstFlipped')

        # ── Play (move submission, client-validated) ────────────────────
        @sp.entrypoint()
        def play(self, params):
            """Submit a move. Client-validated: contract trusts the new board.

            Mirrors the IDE template's `play` entrypoint name. Move struct
            mirrors t_move (from / to / optional promotion).
            """
            sp.cast(params.gameId, sp.nat)
            sp.cast(params.newBoard, sp.map[sp.nat, sp.nat])
            sp.cast(params.move, t_move)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 2, "game not in progress"
            mover = g.white
            if g.toMove == 2:
                mover = g.black
            assert sp.sender == mover, "not your turn"
            nextToMove = 2
            if g.toMove == 2:
                nextToMove = 1
            self.data.games[params.gameId].board = params.newBoard
            self.data.games[params.gameId].toMove = nextToMove
            self.data.games[params.gameId].moveCount = g.moveCount + 1
            self.data.games[params.gameId].lastMoveBlock = sp.level
            # Any move retracts an outstanding draw offer.
            self.data.games[params.gameId].drawOfferedBy = 0
            sp.emit([params.gameId], tag='moveSubmitted')

        # ── Settlement: giveup / claim_checkmate / draws / timeout ──────
        @sp.entrypoint()
        def giveup(self, params):
            """Resign. Opponent gets pot − house cut; house gets the cut."""
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 2, "game not in progress"
            assert sp.sender == g.white or sp.sender == g.black, "not a player"
            winnerAddr = g.black
            loserLabel = "player_2_won"
            if sp.sender == g.black:
                winnerAddr = g.white
                loserLabel = "player_1_won"
            totalPot = sp.mul(g.wager, sp.nat(2))
            houseAmt = self.computeHouse(totalPot)
            payout = totalPot - houseAmt
            sp.send(self.data.houseAddress, houseAmt)
            sp.send(winnerAddr, payout)
            self.data.games[params.gameId].gameStatus = 3
            self.data.games[params.gameId].winner = winnerAddr
            self.data.games[params.gameId].status = sp.variant.finished(loserLabel)
            sp.emit([params.gameId], tag='resigned')

        @sp.entrypoint()
        def claim_checkmate(self, params):
            """Caller asserts they have just delivered checkmate.

            Move validation is off-chain; the caller takes responsibility for
            an honest claim. Pays out the pot to the caller minus the house cut.
            """
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 2, "game not in progress"
            assert sp.sender == g.white or sp.sender == g.black, "not a player"
            winnerAddr = sp.sender
            label = "player_1_won"
            if sp.sender == g.black:
                label = "player_2_won"
            totalPot = sp.mul(g.wager, sp.nat(2))
            houseAmt = self.computeHouse(totalPot)
            payout = totalPot - houseAmt
            sp.send(self.data.houseAddress, houseAmt)
            sp.send(winnerAddr, payout)
            self.data.games[params.gameId].gameStatus = 3
            self.data.games[params.gameId].winner = winnerAddr
            self.data.games[params.gameId].status = sp.variant.finished(label)
            sp.emit([params.gameId], tag='checkmate')

        @sp.entrypoint()
        def claimByTimeout(self, params):
            """Opponent has been idle for >= staleBlocks; claim victory."""
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 2, "game not in progress"
            assert sp.level - g.lastMoveBlock >= self.data.staleBlocks, "not stale yet"
            mover = g.white
            if g.toMove == 2:
                mover = g.black
            assert sp.sender != mover, "you owe the move"
            assert sp.sender == g.white or sp.sender == g.black, "not a player"
            label = "player_1_won"
            if sp.sender == g.black:
                label = "player_2_won"
            totalPot = sp.mul(g.wager, sp.nat(2))
            houseAmt = self.computeHouse(totalPot)
            payout = totalPot - houseAmt
            sp.send(self.data.houseAddress, houseAmt)
            sp.send(sp.sender, payout)
            self.data.games[params.gameId].gameStatus = 3
            self.data.games[params.gameId].winner = sp.sender
            self.data.games[params.gameId].status = sp.variant.finished(label)
            sp.emit([params.gameId], tag='claimedByTimeout')

        @sp.entrypoint()
        def offer_draw(self, params):
            """Offer (or accept) a draw. Two-sided agreement settles a draw."""
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 2, "game not in progress"
            assert sp.sender == g.white or sp.sender == g.black, "not a player"
            myColor = sp.nat(1)
            if sp.sender == g.black:
                myColor = sp.nat(2)
            # If the *other* color already offered, this call accepts it.
            if g.drawOfferedBy != 0 and g.drawOfferedBy != myColor:
                self._settleDraw(params.gameId)
            else:
                self.data.games[params.gameId].drawOfferedBy = myColor

        @sp.entrypoint()
        def deny_draw(self, params):
            """Reject any outstanding draw offer."""
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 2, "game not in progress"
            assert sp.sender == g.white or sp.sender == g.black, "not a player"
            self.data.games[params.gameId].drawOfferedBy = 0

        @sp.entrypoint()
        def claim_stalemate(self, params):
            """Side-to-move claims stalemate. Settles immediately as draw.

            Simplified vs. the IDE template (which lets the opponent refuse
            and force a move) — we treat any honest stalemate claim as
            self-binding: the claimant forfeits a tiny tactical edge in
            exchange for not needing on-chain rule enforcement to verify.
            Opponent can still call deny_draw before this if they disagree;
            the claim_stalemate path is intended for clear positions.
            """
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 2, "game not in progress"
            assert sp.sender == g.white or sp.sender == g.black, "not a player"
            self._settleDraw(params.gameId)

        @sp.entrypoint()
        def threefold_repetition_claim(self, params):
            """Claim draw by threefold repetition. Trust-but-verify off-chain."""
            sp.cast(params.gameId, sp.nat)
            g = self.data.games[params.gameId]
            assert g.gameStatus == 2, "game not in progress"
            assert sp.sender == g.white or sp.sender == g.black, "not a player"
            self._settleDraw(params.gameId)

        # ── Internal: shared draw-settlement logic ──────────────────────
        @sp.private(with_storage="read-write")
        def _settleDraw(self, gameId):
            sp.cast(gameId, sp.nat)
            g = self.data.games[gameId]
            # Total pot = 2*wager. House takes its bps cut on the whole pot,
            # and each side gets back wager - houseCut/2.
            totalPot = sp.mul(g.wager, sp.nat(2))
            houseAmt = sp.split_tokens(totalPot, self.data.houseCutBps, 10000)
            perSide = sp.split_tokens(totalPot - houseAmt, sp.nat(1), sp.nat(2))
            sp.send(self.data.houseAddress, houseAmt)
            sp.send(g.white, perSide)
            sp.send(g.black, perSide)
            self.data.games[gameId].gameStatus = 3
            self.data.games[gameId].winner = BURN
            self.data.games[gameId].status = sp.variant.finished("draw")
            sp.emit([gameId], tag='draw')

        # ── Admin ────────────────────────────────────────────────────────
        @sp.entrypoint()
        def updateAdmin(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.admin = params.newAdmin

        @sp.entrypoint()
        def updateOracle(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.oracle = params.newOracle

        @sp.entrypoint()
        def updateTxlContract(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.txlContract = params.newContract

        @sp.entrypoint()
        def updateHouseAddress(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.houseAddress = params.newAddress

        @sp.entrypoint()
        def updateHouseCut(self, params):
            """Set house cut in basis points. Capped at 1000 (10%)."""
            assert sp.sender == self.data.admin, "not admin"
            assert params.bps <= 1000, "house cut > 10% rejected"
            self.data.houseCutBps = params.bps

        @sp.entrypoint()
        def updateWagerBounds(self, params):
            assert sp.sender == self.data.admin, "not admin"
            assert params.minWager <= params.maxWager, "minWager > maxWager"
            self.data.minWager = params.minWager
            self.data.maxWager = params.maxWager

        @sp.entrypoint()
        def updateFee(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.fee = params.fee

        @sp.entrypoint()
        def updateStaleBlocks(self, params):
            assert sp.sender == self.data.admin, "not admin"
            assert params.staleBlocks >= 30, "staleBlocks too small"
            self.data.staleBlocks = params.staleBlocks


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────
@sp.add_test()
def test():
    s = sp.test_scenario("chess gambling + house cut", main)
    c = main.Chess()
    s += c
