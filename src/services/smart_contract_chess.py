"""
Chess — H2H wagered, on-chain move validation. Legacy SmartPy.

What's enforced on chain:
  - All standard piece movement rules (pawn / knight / bishop / rook / queen / king)
  - Path-clear for sliding pieces (no jumping)
  - Captures only land on opposite-color or empty
  - Pawn first-move 2 squares, diagonal captures, en passant, auto-promotion to queen
  - Castling (kingside + queenside) with castling-rights tracking, no-castling-out-of-check, no-castling-through-check
  - Check enforcement: a move that leaves your king in check reverts

What is NOT auto-detected:
  - Checkmate / stalemate. Loser must `resign()`, or the opponent claims via
    `claimByTimeout()` once `staleBlocks` of inactivity have passed.
  - Draws by repetition / 50-move rule. Players agree via `offerDraw()` / `acceptDraw()`.

Square encoding:
  idx = rank * 8 + file        (rank 0 = white's home row, 7 = black's)
  rank, file ∈ 0..7

Piece codes:
  0  empty
  1  white pawn      7   black pawn
  2  white knight    8   black knight
  3  white bishop    9   black bishop
  4  white rook      10  black rook
  5  white queen     11  black queen
  6  white king      12  black king

Compile + test:
    docker run --rm -v "$PWD":/work -w /work \\
      bakingbad/smartpy-cli:latest \\
      test src/services/smart_contract_chess.py src/services/build/chess/
"""

import smartpy as sp


# Game phases
PHASE_OPEN = 0
PHASE_PLAYING = 1
PHASE_WHITE_WINS = 2
PHASE_BLACK_WINS = 3
PHASE_DRAW = 4

# Knight offsets
KNIGHT_OFFSETS = [(-2, -1), (-2, 1), (-1, -2), (-1, 2),
                  (1, -2), (1, 2), (2, -1), (2, 1)]
# King / queen / bishop / rook directions
DIAG_DIRS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
ORTHO_DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
ALL_DIRS = DIAG_DIRS + ORTHO_DIRS


def starting_board():
    """The standard initial position, encoded into 64-key map."""
    b = {}
    # Empty middle ranks
    for r in range(2, 6):
        for c in range(8):
            b[r * 8 + c] = 0
    # White back rank: R N B Q K B N R
    back_white = [4, 2, 3, 5, 6, 3, 2, 4]
    back_black = [10, 8, 9, 11, 12, 9, 8, 10]
    for c in range(8):
        b[0 * 8 + c] = back_white[c]
        b[1 * 8 + c] = 1               # white pawns
        b[6 * 8 + c] = 7               # black pawns
        b[7 * 8 + c] = back_black[c]
    return b


class Chess(sp.Contract):
    def __init__(self, admin, txlContract):
        self.init(
            admin=admin,
            txlContract=txlContract,
            pendingAdmin=sp.none,
            paused=False,
            holderFee=sp.mutez(50000),
            staleBlocks=sp.nat(480),    # ~2h grace before timeout-claim

            games=sp.big_map(
                tkey=sp.TNat,
                tvalue=sp.TRecord(
                    white=sp.TAddress,
                    black=sp.TAddress,
                    stake=sp.TMutez,
                    phase=sp.TInt,
                    turn=sp.TInt,                    # 1 = white, 2 = black
                    board=sp.TMap(sp.TInt, sp.TInt),
                    # Castling rights
                    wCanK=sp.TBool, wCanQ=sp.TBool,
                    bCanK=sp.TBool, bCanQ=sp.TBool,
                    # En passant target square (-1 = none). Set to the square
                    # *behind* a pawn that just made a 2-square push.
                    enPassant=sp.TInt,
                    # Bookkeeping
                    moveCount=sp.TNat,
                    lastMoveLevel=sp.TNat,
                    drawOfferedBy=sp.TInt,            # 0 = none, 1 = white, 2 = black
                ),
            ),
            currentGameId=sp.nat(0),
            pending=sp.big_map(tkey=sp.TAddress, tvalue=sp.TMutez),
        )

    # ─── helpers ──────────────────────────────────────────────────────────
    def _onlyAdmin(self):
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")

    def _notPaused(self):
        sp.verify(~self.data.paused, message="Paused")

    def _credit(self, who, amount):
        cur = self.data.pending.get(who, default_value=sp.mutez(0))
        self.data.pending[who] = cur + amount

    def _forwardFee(self, amount):
        c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
        sp.transfer(sp.unit, amount, c)

    def _isWhitePiece(self, p):
        return (p >= 1) & (p <= 6)

    def _isBlackPiece(self, p):
        return (p >= 7) & (p <= 12)

    def _abs(self, x):
        return sp.eif(x < 0, sp.int(0) - x, x)

    def _sign(self, x):
        return sp.eif(x > 0, sp.int(1), sp.eif(x < 0, sp.int(-1), sp.int(0)))

    # ─── admin ────────────────────────────────────────────────────────────
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
    def updateConfig(self, params):
        sp.set_type(params, sp.TRecord(
            holderFee=sp.TMutez, staleBlocks=sp.TNat,
        ))
        self._onlyAdmin()
        self.data.holderFee = params.holderFee
        sp.verify(params.staleBlocks >= sp.nat(60), message="TimeoutTooShort")
        self.data.staleBlocks = params.staleBlocks

    # ─── lifecycle ────────────────────────────────────────────────────────
    @sp.entry_point
    def createGame(self, params):
        """White creates the game and locks their stake + holderFee."""
        sp.set_type(params, sp.TRecord(stake=sp.TMutez))
        self._notPaused()
        sp.verify(sp.amount == params.stake + self.data.holderFee, message="BadAmount")
        sp.verify(params.stake > sp.mutez(0), message="ZeroStake")
        self._forwardFee(self.data.holderFee)

        gid = self.data.currentGameId
        self.data.games[gid] = sp.record(
            white=sp.sender,
            black=sp.sender,
            stake=params.stake,
            phase=PHASE_OPEN,
            turn=sp.int(1),
            board=starting_board(),
            wCanK=True, wCanQ=True, bCanK=True, bCanQ=True,
            enPassant=sp.int(-1),
            moveCount=sp.nat(0),
            lastMoveLevel=sp.level,
            drawOfferedBy=sp.int(0),
        )
        sp.emit(sp.record(gameId=gid, creator=sp.sender), tag="chessCreated")
        self.data.currentGameId += 1

    @sp.entry_point
    def joinGame(self, params):
        """Black joins an open game with matching stake + fee."""
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_OPEN, message="NotOpen")
        sp.verify(sp.sender != game.value.white, message="SelfJoin")
        sp.verify(sp.amount == game.value.stake + self.data.holderFee, message="BadAmount")
        self._forwardFee(self.data.holderFee)
        game.value.black = sp.sender
        game.value.phase = PHASE_PLAYING
        game.value.lastMoveLevel = sp.level
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, joiner=sp.sender), tag="chessJoined")

    @sp.entry_point
    def leaveOpenGame(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_OPEN, message="NotOpen")
        sp.verify(sp.sender == game.value.white, message="NotCreator")
        self._credit(game.value.white, game.value.stake)
        game.value.phase = PHASE_DRAW   # mark as resolved-without-result
        self.data.games[params.gameId] = game.value
        sp.emit(params.gameId, tag="chessLeft")

    # ─── check detection ──────────────────────────────────────────────────
    # Returns whether `sq` is attacked by any piece of color `byColor`
    # (1=white, 2=black). Used to enforce "can't move into check".
    def _isSquareAttacked(self, board, sq, byColor):
        # sq is an int 0..63. We unroll over all 64 squares and ask: does the
        # piece on that square attack `sq`? Pieces that don't exist or are of
        # the wrong color contribute nothing.
        attacked = sp.local("attacked", False)

        sqR = sq / 8
        sqC = sq % 8

        # Pawn attacks: a pawn on (r, c) attacks (r+dir, c±1).
        # White pawns attack upward (r+1), black downward (r-1).
        # We iterate the squares that *could* hold an attacking pawn:
        if byColor == 1:
            # White pawns are one rank below sq, on either adjacent file.
            for dc in (-1, 1):
                pR = sqR - 1
                pC = sqC + dc
                onb = (pR >= 0) & (pR < 8) & (pC >= 0) & (pC < 8)
                idx = pR * 8 + pC
                cell = sp.eif(onb, board.get(idx, default_value=0), sp.int(0))
                if cell == 1:
                    attacked.value = True
        else:
            for dc in (-1, 1):
                pR = sqR + 1
                pC = sqC + dc
                onb = (pR >= 0) & (pR < 8) & (pC >= 0) & (pC < 8)
                idx = pR * 8 + pC
                cell = sp.eif(onb, board.get(idx, default_value=0), sp.int(0))
                if cell == 7:
                    attacked.value = True

        # Knight attacks
        knightCode = sp.eif(byColor == 1, sp.int(2), sp.int(8))
        for (dr, dc) in KNIGHT_OFFSETS:
            pR = sqR + dr
            pC = sqC + dc
            onb = (pR >= 0) & (pR < 8) & (pC >= 0) & (pC < 8)
            idx = pR * 8 + pC
            cell = sp.eif(onb, board.get(idx, default_value=0), sp.int(0))
            if cell == knightCode:
                attacked.value = True

        # Sliding attacks: bishop/queen on diagonals; rook/queen on orthos.
        # For each direction, walk outward until we hit a piece or off-board.
        bishopCode = sp.eif(byColor == 1, sp.int(3), sp.int(9))
        rookCode = sp.eif(byColor == 1, sp.int(4), sp.int(10))
        queenCode = sp.eif(byColor == 1, sp.int(5), sp.int(11))

        for (dr, dc) in DIAG_DIRS:
            stopped = sp.local("stopped", False)
            for step in range(1, 8):
                pR = sqR + dr * step
                pC = sqC + dc * step
                onb = (pR >= 0) & (pR < 8) & (pC >= 0) & (pC < 8)
                idx = pR * 8 + pC
                cell = sp.eif(onb, board.get(idx, default_value=0), sp.int(-1))
                if ~stopped.value:
                    if (cell == bishopCode) | (cell == queenCode):
                        attacked.value = True
                        stopped.value = True
                    else:
                        if (cell != 0) | (~onb):
                            stopped.value = True

        for (dr, dc) in ORTHO_DIRS:
            stopped = sp.local("stopped", False)
            for step in range(1, 8):
                pR = sqR + dr * step
                pC = sqC + dc * step
                onb = (pR >= 0) & (pR < 8) & (pC >= 0) & (pC < 8)
                idx = pR * 8 + pC
                cell = sp.eif(onb, board.get(idx, default_value=0), sp.int(-1))
                if ~stopped.value:
                    if (cell == rookCode) | (cell == queenCode):
                        attacked.value = True
                        stopped.value = True
                    else:
                        if (cell != 0) | (~onb):
                            stopped.value = True

        # King attacks (1 square)
        kingCode = sp.eif(byColor == 1, sp.int(6), sp.int(12))
        for (dr, dc) in ALL_DIRS:
            pR = sqR + dr
            pC = sqC + dc
            onb = (pR >= 0) & (pR < 8) & (pC >= 0) & (pC < 8)
            idx = pR * 8 + pC
            cell = sp.eif(onb, board.get(idx, default_value=0), sp.int(0))
            if cell == kingCode:
                attacked.value = True

        return attacked.value

    # ─── helper: find king position ───────────────────────────────────────
    def _findKing(self, board, color):
        target = sp.eif(color == 1, sp.int(6), sp.int(12))
        kSq = sp.local("kSq", sp.int(-1))
        for sq in range(64):
            if board.get(sq, default_value=0) == target:
                kSq.value = sq
        return kSq.value

    # ─── path-clear for sliding pieces ────────────────────────────────────
    # Verifies every cell strictly between (fromR,fromC) and (toR,toC) along
    # the ray defined by (stepR, stepC) is empty. `distance` is the number
    # of cells between, exclusive of both endpoints.
    def _verifyPathClear(self, board, fromR, fromC, stepR, stepC, distance):
        for step in range(1, 8):
            if step < distance:
                r = fromR + stepR * step
                c = fromC + stepC * step
                idx = r * 8 + c
                sp.verify(board.get(idx, default_value=0) == 0, message="PathBlocked")

    # ─── make a move ──────────────────────────────────────────────────────
    @sp.entry_point
    def makeMove(self, params):
        """Apply a move from `fromSq` to `toSq`. Pawn promotions auto-queen."""
        sp.set_type(params, sp.TRecord(
            gameId=sp.TNat, fromSq=sp.TInt, toSq=sp.TInt,
        ))
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_PLAYING, message="NotPlaying")
        sp.verify(
            (params.fromSq >= 0) & (params.fromSq < 64) &
            (params.toSq >= 0) & (params.toSq < 64),
            message="OffBoard",
        )
        sp.verify(params.fromSq != params.toSq, message="NullMove")

        mover = game.value.turn
        opp = sp.eif(mover == 1, sp.int(2), sp.int(1))
        expected = sp.eif(mover == 1, game.value.white, game.value.black)
        sp.verify(sp.sender == expected, message="NotYourTurn")

        piece = game.value.board.get(params.fromSq, default_value=0)
        sp.verify(piece > 0, message="EmptyFromSq")
        # Mover must own the piece
        if mover == 1:
            sp.verify(self._isWhitePiece(piece), message="NotYourPiece")
        else:
            sp.verify(self._isBlackPiece(piece), message="NotYourPiece")

        target = game.value.board.get(params.toSq, default_value=0)
        # Cannot capture own piece
        if mover == 1:
            sp.verify(~self._isWhitePiece(target), message="OwnPieceTarget")
        else:
            sp.verify(~self._isBlackPiece(target), message="OwnPieceTarget")

        # Decode coordinates
        fromR = params.fromSq / 8
        fromC = params.fromSq % 8
        toR = params.toSq / 8
        toC = params.toSq % 8
        dR = toR - fromR
        dC = toC - fromC
        absR = self._abs(dR)
        absC = self._abs(dC)

        # Normalize piece type 1..6
        ptype = sp.eif(piece <= 6, piece, piece - 6)

        # Track special-move flags so we can update state after.
        isCastleK = sp.local("isCastleK", False)
        isCastleQ = sp.local("isCastleQ", False)
        isEnPassant = sp.local("isEnPassant", False)
        isPawn2 = sp.local("isPawn2", False)
        isPromotion = sp.local("isPromotion", False)

        # ─── pawn ──────────────────────────────────────────────────────
        if ptype == 1:
            # White pawns move +1 rank; black -1.
            forward = sp.eif(mover == 1, sp.int(1), sp.int(-1))
            startRank = sp.eif(mover == 1, sp.int(1), sp.int(6))
            promoRank = sp.eif(mover == 1, sp.int(7), sp.int(0))

            # Quiet move: 1 square forward to empty
            if (dR == forward) & (dC == 0):
                sp.verify(target == 0, message="PawnBlockedFwd")
            # Quiet move: 2 squares forward from start, both squares empty
            else:
                if (dR == forward * 2) & (dC == 0) & (fromR == startRank):
                    midSq = (fromR + forward) * 8 + fromC
                    sp.verify(game.value.board.get(midSq, default_value=0) == 0, message="PawnPathBlocked")
                    sp.verify(target == 0, message="PawnBlockedFwd")
                    isPawn2.value = True
                # Diagonal capture
                else:
                    if (dR == forward) & (absC == 1):
                        # Either captures opp piece OR en-passant target square
                        if target != 0:
                            pass
                        else:
                            sp.verify(
                                params.toSq == game.value.enPassant,
                                message="BadPawnMove",
                            )
                            isEnPassant.value = True
                    else:
                        sp.failwith("BadPawnMove")

            if toR == promoRank:
                isPromotion.value = True

        # ─── knight ────────────────────────────────────────────────────
        else:
            if ptype == 2:
                # |dR|*|dC| == 2 with neither 0 (i.e., L-shape)
                sp.verify(
                    ((absR == 1) & (absC == 2)) | ((absR == 2) & (absC == 1)),
                    message="BadKnightMove",
                )

            # ─── bishop ────────────────────────────────────────────────
            else:
                if ptype == 3:
                    sp.verify((absR == absC) & (absR > 0), message="BadBishopMove")
                    self._verifyPathClear(
                        game.value.board, fromR, fromC,
                        self._sign(dR), self._sign(dC), absR,
                    )

                # ─── rook ──────────────────────────────────────────────
                else:
                    if ptype == 4:
                        sp.verify(((dR == 0) & (absC > 0)) | ((dC == 0) & (absR > 0)),
                                  message="BadRookMove")
                        dist = sp.eif(dR == 0, absC, absR)
                        self._verifyPathClear(
                            game.value.board, fromR, fromC,
                            self._sign(dR), self._sign(dC), dist,
                        )

                    # ─── queen ─────────────────────────────────────────
                    else:
                        if ptype == 5:
                            isDiag = (absR == absC) & (absR > 0)
                            isOrtho = (((dR == 0) & (absC > 0)) | ((dC == 0) & (absR > 0)))
                            sp.verify(isDiag | isOrtho, message="BadQueenMove")
                            dist = sp.eif(absR > absC, absR, absC)
                            self._verifyPathClear(
                                game.value.board, fromR, fromC,
                                self._sign(dR), self._sign(dC), dist,
                            )

                        # ─── king ──────────────────────────────────────
                        else:
                            # Normal king move: 1 square in any direction.
                            if (absR <= 1) & (absC <= 1):
                                pass
                            else:
                                # Castling: king moves 2 squares horizontally
                                if (dR == 0) & (absC == 2):
                                    # Determine side and validate rights + path + check
                                    if mover == 1:
                                        sp.verify(fromR == 0, message="BadCastle")
                                        if dC == 2:
                                            sp.verify(game.value.wCanK, message="NoCastleK")
                                            # Squares 5 (f1), 6 (g1) empty; rook on h1 (7)
                                            sp.verify(game.value.board.get(5, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(6, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(7, default_value=0) == 4, message="CastleNoRook")
                                            # Cannot castle out of, through, or into check
                                            sp.verify(~self._isSquareAttacked(game.value.board, sp.int(4), sp.int(2)), message="CastleThroughCheck")
                                            sp.verify(~self._isSquareAttacked(game.value.board, sp.int(5), sp.int(2)), message="CastleThroughCheck")
                                            isCastleK.value = True
                                        else:
                                            sp.verify(game.value.wCanQ, message="NoCastleQ")
                                            sp.verify(game.value.board.get(1, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(2, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(3, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(0, default_value=0) == 4, message="CastleNoRook")
                                            sp.verify(~self._isSquareAttacked(game.value.board, sp.int(4), sp.int(2)), message="CastleThroughCheck")
                                            sp.verify(~self._isSquareAttacked(game.value.board, sp.int(3), sp.int(2)), message="CastleThroughCheck")
                                            isCastleQ.value = True
                                    else:
                                        sp.verify(fromR == 7, message="BadCastle")
                                        if dC == 2:
                                            sp.verify(game.value.bCanK, message="NoCastleK")
                                            sp.verify(game.value.board.get(61, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(62, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(63, default_value=0) == 10, message="CastleNoRook")
                                            sp.verify(~self._isSquareAttacked(game.value.board, sp.int(60), sp.int(1)), message="CastleThroughCheck")
                                            sp.verify(~self._isSquareAttacked(game.value.board, sp.int(61), sp.int(1)), message="CastleThroughCheck")
                                            isCastleK.value = True
                                        else:
                                            sp.verify(game.value.bCanQ, message="NoCastleQ")
                                            sp.verify(game.value.board.get(57, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(58, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(59, default_value=0) == 0, message="CastlePathBlocked")
                                            sp.verify(game.value.board.get(56, default_value=0) == 10, message="CastleNoRook")
                                            sp.verify(~self._isSquareAttacked(game.value.board, sp.int(60), sp.int(1)), message="CastleThroughCheck")
                                            sp.verify(~self._isSquareAttacked(game.value.board, sp.int(59), sp.int(1)), message="CastleThroughCheck")
                                            isCastleQ.value = True
                                else:
                                    sp.failwith("BadKingMove")

        # ─── apply move to a working copy ─────────────────────────────
        # Move the piece
        game.value.board[params.fromSq] = sp.int(0)
        # Promotion: replace pawn with queen
        if isPromotion.value:
            game.value.board[params.toSq] = sp.eif(mover == 1, sp.int(5), sp.int(11))
        else:
            game.value.board[params.toSq] = piece
        # En passant: remove the pawn that was captured (it's NOT on toSq)
        if isEnPassant.value:
            captureSq = sp.eif(mover == 1, params.toSq - 8, params.toSq + 8)
            game.value.board[captureSq] = sp.int(0)
        # Castling: also move the rook
        if isCastleK.value:
            if mover == 1:
                game.value.board[7] = sp.int(0)
                game.value.board[5] = sp.int(4)
            else:
                game.value.board[63] = sp.int(0)
                game.value.board[61] = sp.int(10)
        if isCastleQ.value:
            if mover == 1:
                game.value.board[0] = sp.int(0)
                game.value.board[3] = sp.int(4)
            else:
                game.value.board[56] = sp.int(0)
                game.value.board[59] = sp.int(10)

        # ─── update castling rights ────────────────────────────────────
        # If king moved at all → lose both rights for that color
        if ptype == 6:
            if mover == 1:
                game.value.wCanK = False
                game.value.wCanQ = False
            else:
                game.value.bCanK = False
                game.value.bCanQ = False
        # If rook moved from a starting corner → lose that side's right
        if ptype == 4:
            if (mover == 1) & (params.fromSq == 0):
                game.value.wCanQ = False
            if (mover == 1) & (params.fromSq == 7):
                game.value.wCanK = False
            if (mover == 2) & (params.fromSq == 56):
                game.value.bCanQ = False
            if (mover == 2) & (params.fromSq == 63):
                game.value.bCanK = False
        # If a rook was captured on its home square → opponent loses that right
        if params.toSq == 0:
            game.value.wCanQ = False
        if params.toSq == 7:
            game.value.wCanK = False
        if params.toSq == 56:
            game.value.bCanQ = False
        if params.toSq == 63:
            game.value.bCanK = False

        # ─── set / clear en-passant target ─────────────────────────────
        if isPawn2.value:
            # The en-passant target is the square the pawn skipped over.
            game.value.enPassant = (fromR + (toR - fromR) / 2) * 8 + toC
        else:
            game.value.enPassant = sp.int(-1)

        # ─── verify own king is not in check after the move ────────────
        kingSq = self._findKing(game.value.board, mover)
        sp.verify(
            ~self._isSquareAttacked(game.value.board, kingSq, opp),
            message="LeavesKingInCheck",
        )

        # ─── persist state and pass turn ───────────────────────────────
        game.value.turn = opp
        game.value.moveCount += 1
        game.value.lastMoveLevel = sp.level
        # Any move clears any standing draw offer (the offerer can re-issue).
        game.value.drawOfferedBy = sp.int(0)
        self.data.games[params.gameId] = game.value
        sp.emit(
            sp.record(gameId=params.gameId, fromSq=params.fromSq, toSq=params.toSq, mover=mover),
            tag="chessMove",
        )

    # ─── resign ───────────────────────────────────────────────────────────
    @sp.entry_point
    def resign(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_PLAYING, message="NotPlaying")
        sp.verify(
            (sp.sender == game.value.white) | (sp.sender == game.value.black),
            message="NotPlayer",
        )
        pot = game.value.stake + game.value.stake
        if sp.sender == game.value.white:
            self._credit(game.value.black, pot)
            game.value.phase = PHASE_BLACK_WINS
        else:
            self._credit(game.value.white, pot)
            game.value.phase = PHASE_WHITE_WINS
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, resigner=sp.sender), tag="chessResigned")

    # ─── draw flow ────────────────────────────────────────────────────────
    @sp.entry_point
    def offerDraw(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_PLAYING, message="NotPlaying")
        if sp.sender == game.value.white:
            game.value.drawOfferedBy = sp.int(1)
        else:
            sp.verify(sp.sender == game.value.black, message="NotPlayer")
            game.value.drawOfferedBy = sp.int(2)
        self.data.games[params.gameId] = game.value
        sp.emit(params.gameId, tag="chessDrawOffered")

    @sp.entry_point
    def acceptDraw(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_PLAYING, message="NotPlaying")
        sp.verify(game.value.drawOfferedBy != sp.int(0), message="NoOffer")
        # Acceptor must be the OTHER player.
        if game.value.drawOfferedBy == sp.int(1):
            sp.verify(sp.sender == game.value.black, message="NotPlayer")
        else:
            sp.verify(sp.sender == game.value.white, message="NotPlayer")
        # Split the pot.
        pot = game.value.stake + game.value.stake
        half = sp.split_tokens(pot, 1, 2)
        self._credit(game.value.white, half)
        self._credit(game.value.black, half)
        game.value.phase = PHASE_DRAW
        self.data.games[params.gameId] = game.value
        sp.emit(params.gameId, tag="chessDrawAccepted")

    # ─── claim by timeout ─────────────────────────────────────────────────
    # If the opponent hasn't moved for `staleBlocks` blocks, you win.
    @sp.entry_point
    def claimByTimeout(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_PLAYING, message="NotPlaying")
        # The waiting player is the one whose turn it ISN'T (opponent is on the clock).
        waiter = sp.eif(game.value.turn == 1, game.value.black, game.value.white)
        sp.verify(sp.sender == waiter, message="NotPlayer")
        sp.verify(
            sp.level >= game.value.lastMoveLevel + self.data.staleBlocks,
            message="NotYetExpired",
        )
        pot = game.value.stake + game.value.stake
        self._credit(waiter, pot)
        game.value.phase = sp.eif(game.value.turn == 1, PHASE_BLACK_WINS, PHASE_WHITE_WINS)
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, winner=waiter), tag="chessTimeout")

    # ─── claim winnings ───────────────────────────────────────────────────
    @sp.entry_point
    def claim(self):
        sp.verify(self.data.pending.contains(sp.sender), message="NothingToClaim")
        amount = self.data.pending[sp.sender]
        sp.verify(amount > sp.mutez(0), message="NothingToClaim")
        del self.data.pending[sp.sender]
        sp.send(sp.sender, amount)
        sp.emit(sp.record(who=sp.sender, amount=amount), tag="chessClaimed")


# ─── Tests ───────────────────────────────────────────────────────────────────
@sp.add_test(name="opening_move_e4")
def t_e4():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    w = sp.test_account("w")
    b = sp.test_account("b")

    c = Chess(admin.address, holder.address)
    s += c

    s += c.createGame(stake=sp.mutez(1000000)).run(sender=w, amount=sp.mutez(1050000))
    s += c.joinGame(gameId=0).run(sender=b, amount=sp.mutez(1050000))
    # White plays e2 (sq 12) -> e4 (sq 28). 2-square pawn push.
    s += c.makeMove(gameId=0, fromSq=sp.int(12), toSq=sp.int(28)).run(sender=w)


@sp.add_test(name="cannot_move_into_check")
def t_check():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    w = sp.test_account("w")
    b = sp.test_account("b")

    c = Chess(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(500000)).run(sender=w, amount=sp.mutez(550000))
    s += c.joinGame(gameId=0).run(sender=b, amount=sp.mutez(550000))
    # White: e2-e4
    s += c.makeMove(gameId=0, fromSq=sp.int(12), toSq=sp.int(28)).run(sender=w)
    # Black: e7-e5 (sq 52 -> 36)
    s += c.makeMove(gameId=0, fromSq=sp.int(52), toSq=sp.int(36)).run(sender=b)
    # White: Qh5 (sq 3 -> 39)
    s += c.makeMove(gameId=0, fromSq=sp.int(3), toSq=sp.int(39)).run(sender=w)
    # Black tries Ke7 — illegal (king walks into queen's diagonal? actually
    # Qh5 → e8 is blocked by black pawn on e7... let's pick a clearer check).
    # Instead: black plays Nf6 (sq 62 -> 45), then white Qxe5+ then black tries
    # Kf7 (sq 60 -> 53) which is into check from queen on e5 along e-file.
    s += c.makeMove(gameId=0, fromSq=sp.int(62), toSq=sp.int(45)).run(sender=b)
    s += c.makeMove(gameId=0, fromSq=sp.int(39), toSq=sp.int(36)).run(sender=w)  # Qxe5
    # Now black king can't move to e7 (sq 52) — empty? Actually the e7 square
    # is empty (pawn was captured). And the queen on e5 attacks e7. So Ke7 is
    # illegal: LeavesKingInCheck.
    s += c.makeMove(gameId=0, fromSq=sp.int(60), toSq=sp.int(52)).run(
        sender=b, valid=False, exception="LeavesKingInCheck",
    )


@sp.add_test(name="resign_pays_opponent")
def t_resign():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    w = sp.test_account("w")
    b = sp.test_account("b")
    c = Chess(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(500000)).run(sender=w, amount=sp.mutez(550000))
    s += c.joinGame(gameId=0).run(sender=b, amount=sp.mutez(550000))
    s += c.resign(gameId=0).run(sender=w)
    s += c.claim().run(sender=b)


@sp.add_test(name="not_your_turn")
def t_turn():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    w = sp.test_account("w")
    b = sp.test_account("b")
    c = Chess(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(500000)).run(sender=w, amount=sp.mutez(550000))
    s += c.joinGame(gameId=0).run(sender=b, amount=sp.mutez(550000))
    # Black tries to move first
    s += c.makeMove(gameId=0, fromSq=sp.int(52), toSq=sp.int(36)).run(
        sender=b, valid=False, exception="NotYourTurn",
    )


@sp.add_test(name="cannot_capture_own")
def t_owncap():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    w = sp.test_account("w")
    b = sp.test_account("b")
    c = Chess(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(500000)).run(sender=w, amount=sp.mutez(550000))
    s += c.joinGame(gameId=0).run(sender=b, amount=sp.mutez(550000))
    # White tries to put knight on e2 — own pawn there
    s += c.makeMove(gameId=0, fromSq=sp.int(6), toSq=sp.int(12)).run(
        sender=w, valid=False, exception="OwnPieceTarget",
    )


@sp.add_test(name="draw_offer_and_accept")
def t_draw():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    w = sp.test_account("w")
    b = sp.test_account("b")
    c = Chess(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(500000)).run(sender=w, amount=sp.mutez(550000))
    s += c.joinGame(gameId=0).run(sender=b, amount=sp.mutez(550000))
    s += c.offerDraw(gameId=0).run(sender=w)
    s += c.acceptDraw(gameId=0).run(sender=b)
    s += c.claim().run(sender=w)
    s += c.claim().run(sender=b)
