"""
Reversi (Othello) — H2H wagered, on-chain move validation. Legacy SmartPy.

Two players stake equal amounts. Game ends when no player can move; the player
with more stones wins the pot (minus the holder fee).

Game state:
  board: 64 ints addressed by `idx = row*8 + col`
         0 = empty, 1 = black (player1), 2 = white (player2)
  turn:  1 = black to move, 2 = white to move

Initial position (standard Othello opening):
  d4 = 33, d5 = 41 → white (2)   (rows 3,4 cols 3 — but with our row*8+col)
  e4 = 28, e5 = 36 → black (1)
  Actually using 0-indexed (row,col) on an 8x8 board:
     (3,3) = idx 27 — white
     (3,4) = idx 28 — black
     (4,3) = idx 35 — black
     (4,4) = idx 36 — white

Move validation:
  A move at (r,c) by player P is legal iff:
    - cell (r,c) is empty
    - in at least one of the 8 directions, the immediately-adjacent cell holds
      the opponent's stone, and a continuous run of opponent stones in that
      direction terminates with one of P's own stones (no empty in between).
  All such runs are flipped.

Compile + test:
    docker run --rm -v "$PWD":/work -w /work \\
      bakingbad/smartpy-cli:latest \\
      test src/services/smart_contract_reversi.py src/services/build/reversi/
"""

import smartpy as sp


# Phase enum (per game)
PHASE_OPEN = 0      # creator staked, awaiting opponent
PHASE_PLAYING = 1   # both staked, in-game
PHASE_DONE = 2      # finished (winner declared OR draw OR no-op final)

# 8 directions as (dr, dc) — used at compile time to unroll loops.
DIRECTIONS = [
    (-1, -1), (-1, 0), (-1, 1),
    ( 0, -1),          ( 0, 1),
    ( 1, -1), ( 1, 0), ( 1, 1),
]


class Reversi(sp.Contract):
    def __init__(self, admin, txlContract):
        self.init(
            admin=admin,
            txlContract=txlContract,
            pendingAdmin=sp.none,
            paused=False,

            # Fee model: each create/join pays `holderFee` to txl on top of stake.
            # Stake amount is whatever the creator chose at game-creation time.
            holderFee=sp.mutez(50000),    # 0.05 ꜩ flat per player

            games=sp.big_map(
                tkey=sp.TNat,
                tvalue=sp.TRecord(
                    player1=sp.TAddress,            # black
                    player2=sp.TAddress,            # white (set on join)
                    stake=sp.TMutez,                # per-player; pot = 2*stake
                    phase=sp.TInt,
                    turn=sp.TInt,                   # 1 or 2
                    passes=sp.TInt,                 # consecutive passes; 2 = game over
                    board=sp.TMap(sp.TInt, sp.TInt),
                    score1=sp.TInt,
                    score2=sp.TInt,
                    winner=sp.TInt,                 # 0 = draw / unset, 1 or 2 once known
                    createdAtLevel=sp.TNat,
                ),
            ),
            currentGameId=sp.nat(0),

            # Pull-pattern winnings ledger
            pending=sp.big_map(tkey=sp.TAddress, tvalue=sp.TMutez),
        )

    # ─── helpers ──────────────────────────────────────────────────────────
    def _onlyAdmin(self):
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")

    def _notPaused(self):
        sp.verify(~self.data.paused, message="Paused")

    def _credit(self, who, amount):
        current = self.data.pending.get(who, default_value=sp.mutez(0))
        self.data.pending[who] = current + amount

    def _forwardFee(self, amount):
        c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
        sp.transfer(sp.unit, amount, c)

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
    def updateFee(self, params):
        sp.set_type(params, sp.TRecord(newFee=sp.TMutez))
        self._onlyAdmin()
        self.data.holderFee = params.newFee

    # ─── game lifecycle ───────────────────────────────────────────────────
    @sp.entry_point
    def createGame(self, params):
        """Player 1 (black) creates a game and stakes `stake + holderFee`."""
        sp.set_type(params, sp.TRecord(stake=sp.TMutez))
        self._notPaused()
        sp.verify(sp.amount == params.stake + self.data.holderFee, message="BadAmount")
        sp.verify(params.stake > sp.mutez(0), message="ZeroStake")

        self._forwardFee(self.data.holderFee)

        # Standard Othello opening: white at (3,3) and (4,4); black at (3,4) and (4,3).
        # idx = row*8 + col
        board = {
            27: 2,   # (3,3) white
            28: 1,   # (3,4) black
            35: 1,   # (4,3) black
            36: 2,   # (4,4) white
        }

        gid = self.data.currentGameId
        self.data.games[gid] = sp.record(
            player1=sp.sender,
            player2=sp.sender,                    # placeholder until joined
            stake=params.stake,
            phase=PHASE_OPEN,
            turn=sp.int(1),
            passes=sp.int(0),
            board=board,
            score1=sp.int(2),
            score2=sp.int(2),
            winner=sp.int(0),
            createdAtLevel=sp.level,
        )
        sp.emit(sp.record(gameId=gid, creator=sp.sender), tag="reversiCreated")
        self.data.currentGameId += 1

    @sp.entry_point
    def joinGame(self, params):
        """Player 2 (white) joins an open game; must match the stake + fee."""
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_OPEN, message="NotOpen")
        sp.verify(sp.sender != game.value.player1, message="SelfJoin")
        sp.verify(
            sp.amount == game.value.stake + self.data.holderFee,
            message="BadAmount",
        )
        self._forwardFee(self.data.holderFee)

        game.value.player2 = sp.sender
        game.value.phase = PHASE_PLAYING
        self.data.games[params.gameId] = game.value
        sp.emit(sp.record(gameId=params.gameId, joiner=sp.sender), tag="reversiJoined")

    @sp.entry_point
    def leaveOpenGame(self, params):
        """Creator can withdraw an unmatched game and reclaim their stake."""
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_OPEN, message="NotOpen")
        sp.verify(sp.sender == game.value.player1, message="NotCreator")
        # Refund stake (fee already forwarded to TXL — that's gone)
        self._credit(game.value.player1, game.value.stake)
        game.value.phase = PHASE_DONE
        self.data.games[params.gameId] = game.value
        sp.emit(params.gameId, tag="reversiLeft")

    # ─── helper: count pieces of `who` on the board (2..64 entries) ──────
    def _countPieces(self, board, who):
        # Unrolled across 64 cells.
        count = sp.local("count", sp.int(0))
        for i in range(64):
            if board.get(i, default_value=0) == who:
                count.value += 1
        return count.value

    # ─── helper: try to flip in one direction. Returns 0 if nothing to flip,
    # else flips in-place and returns the number flipped. ─────────────────
    def _tryDirection(self, board, r, c, dr, dc, who, opp):
        # Two-phase walk along (dr, dc):
        #   Phase 1: scan to find whether this direction has a legal "line"
        #            of opponent stones closed by one of ours.
        #   Phase 2: if legal AND only along the contiguous opponent-run
        #            (using a `stopped` flag, since legacy SmartPy can't break),
        #            flip those opponent stones to our colour.
        gained = sp.local("gained", sp.int(0))
        legal = sp.local("legal", False)
        # Track that phase-1 has stopped extending the line: once it sees
        # something other than `opp`, no further `who`-find should mark legal.
        scanStopped = sp.local("scanStopped", False)

        for step in range(1, 8):
            nr2 = r + dr * step
            nc2 = c + dc * step
            on_board = (nr2 >= 0) & (nr2 < 8) & (nc2 >= 0) & (nc2 < 8)
            idx = nr2 * 8 + nc2
            cell = sp.eif(on_board, board.get(idx, default_value=0), sp.int(-1))
            # Once we've stopped extending the run we ignore further cells.
            if ~scanStopped.value:
                if cell == opp:
                    pass  # part of the run, keep walking
                else:
                    if cell == who:
                        if step > 1:
                            legal.value = True
                    # Any non-opp cell ends the run.
                    scanStopped.value = True

        # Phase 2: walk again, flipping only the contiguous opp run that
        # phase 1 validated. Stop once we hit our own stone or empty.
        if legal.value:
            flipStopped = sp.local("flipStopped", False)
            for step in range(1, 8):
                nr2 = r + dr * step
                nc2 = c + dc * step
                on_board = (nr2 >= 0) & (nr2 < 8) & (nc2 >= 0) & (nc2 < 8)
                idx = nr2 * 8 + nc2
                cell = sp.eif(on_board, board.get(idx, default_value=0), sp.int(-1))
                if ~flipStopped.value:
                    if cell == opp:
                        board[idx] = who
                        gained.value += 1
                    else:
                        flipStopped.value = True
        return gained.value

    # ─── make a move ──────────────────────────────────────────────────────
    @sp.entry_point
    def makeMove(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat, row=sp.TInt, col=sp.TInt))
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_PLAYING, message="NotPlaying")
        sp.verify(
            (params.row >= 0) & (params.row < 8) & (params.col >= 0) & (params.col < 8),
            message="OffBoard",
        )

        who = game.value.turn
        opp = sp.eif(who == 1, sp.int(2), sp.int(1))
        expectedPlayer = sp.eif(who == 1, game.value.player1, game.value.player2)
        sp.verify(sp.sender == expectedPlayer, message="NotYourTurn")

        idx = params.row * 8 + params.col
        sp.verify(game.value.board.get(idx, default_value=0) == 0, message="CellTaken")

        # Try every direction. Sum gains. If 0, the move is illegal.
        totalGained = sp.local("totalGained", sp.int(0))
        # Build a fresh local copy of the board so we don't half-mutate on
        # invalid moves. Copy is implicit because game.value.board is itself
        # a deep-copied local already.
        for dr, dc in DIRECTIONS:
            totalGained.value += self._tryDirection(
                game.value.board, params.row, params.col, dr, dc, who, opp
            )

        sp.verify(totalGained.value > 0, message="IllegalMove")
        # Place the moving player's stone.
        game.value.board[idx] = who
        # Update scores: who gained `totalGained` (flips) + 1 (placed); opp
        # lost `totalGained`.
        if who == 1:
            game.value.score1 += totalGained.value + 1
            game.value.score2 -= totalGained.value
        else:
            game.value.score2 += totalGained.value + 1
            game.value.score1 -= totalGained.value

        # Reset pass counter — someone moved.
        game.value.passes = sp.int(0)
        # Switch turn.
        game.value.turn = opp

        self.data.games[params.gameId] = game.value
        sp.emit(
            sp.record(gameId=params.gameId, who=who, idx=idx, gained=totalGained.value),
            tag="reversiMove",
        )

    # ─── pass turn (only legal if no moves available; client-asserted) ────
    @sp.entry_point
    def passTurn(self, params):
        sp.set_type(params, sp.TRecord(gameId=sp.TNat))
        self._notPaused()
        sp.verify(self.data.games.contains(params.gameId), message="NoGame")
        game = sp.local("game", self.data.games[params.gameId])
        sp.verify(game.value.phase == PHASE_PLAYING, message="NotPlaying")
        who = game.value.turn
        expectedPlayer = sp.eif(who == 1, game.value.player1, game.value.player2)
        sp.verify(sp.sender == expectedPlayer, message="NotYourTurn")

        # Increment passes. Two consecutive passes ends the game.
        game.value.passes += 1
        game.value.turn = sp.eif(who == 1, sp.int(2), sp.int(1))

        if game.value.passes >= sp.int(2):
            self._settle(game, params.gameId)

        self.data.games[params.gameId] = game.value

    # ─── helper: settle pot to the winner (or split on draw) ─────────────
    def _settle(self, game, gameId):
        """Internal — sets game.phase = DONE, credits the winner."""
        pot = game.value.stake + game.value.stake
        if game.value.score1 > game.value.score2:
            game.value.winner = sp.int(1)
            self._credit(game.value.player1, pot)
        else:
            if game.value.score2 > game.value.score1:
                game.value.winner = sp.int(2)
                self._credit(game.value.player2, pot)
            else:
                # Draw: split the pot evenly.
                half = sp.split_tokens(pot, 1, 2)
                self._credit(game.value.player1, half)
                self._credit(game.value.player2, half)
                game.value.winner = sp.int(0)
        game.value.phase = PHASE_DONE
        sp.emit(
            sp.record(gameId=gameId, winner=game.value.winner,
                      score1=game.value.score1, score2=game.value.score2),
            tag="reversiSettled",
        )

    # ─── claim winnings (pull) ───────────────────────────────────────────
    @sp.entry_point
    def claim(self):
        sp.verify(self.data.pending.contains(sp.sender), message="NothingToClaim")
        amount = self.data.pending[sp.sender]
        sp.verify(amount > sp.mutez(0), message="NothingToClaim")
        del self.data.pending[sp.sender]
        sp.send(sp.sender, amount)
        sp.emit(sp.record(who=sp.sender, amount=amount), tag="reversiClaimed")


# ─── Tests ───────────────────────────────────────────────────────────────────
@sp.add_test(name="happy_path_join_and_play_one_move")
def t_happy():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")
    p2 = sp.test_account("p2")

    c = Reversi(admin.address, holder.address)
    s += c

    # p1 creates a game with 1 ꜩ stake.
    s += c.createGame(stake=sp.mutez(1000000)).run(
        sender=p1, amount=sp.mutez(1050000)
    )
    # p2 joins.
    s += c.joinGame(gameId=0).run(sender=p2, amount=sp.mutez(1050000))

    # Black (p1) plays at (2,3): legal opener — flanks white at (3,3) with
    # black at (4,3) along the column. Flips one stone.
    s += c.makeMove(gameId=0, row=sp.int(2), col=sp.int(3)).run(sender=p1)


@sp.add_test(name="cannot_play_an_illegal_cell")
def t_illegal():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")
    p2 = sp.test_account("p2")

    c = Reversi(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(500000)).run(sender=p1, amount=sp.mutez(550000))
    s += c.joinGame(gameId=0).run(sender=p2, amount=sp.mutez(550000))

    # (0,0) corner is empty but doesn't flank any white stone — illegal.
    s += c.makeMove(gameId=0, row=sp.int(0), col=sp.int(0)).run(
        sender=p1, valid=False, exception="IllegalMove"
    )


@sp.add_test(name="cannot_play_out_of_turn")
def t_turn():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")
    p2 = sp.test_account("p2")

    c = Reversi(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(500000)).run(sender=p1, amount=sp.mutez(550000))
    s += c.joinGame(gameId=0).run(sender=p2, amount=sp.mutez(550000))
    # White (p2) tries to move first — should fail.
    s += c.makeMove(gameId=0, row=sp.int(2), col=sp.int(3)).run(
        sender=p2, valid=False, exception="NotYourTurn"
    )


@sp.add_test(name="leave_open_game_refunds_creator")
def t_leave():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")

    c = Reversi(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(750000)).run(sender=p1, amount=sp.mutez(800000))
    s += c.leaveOpenGame(gameId=0).run(sender=p1)
    s += c.claim().run(sender=p1)


@sp.add_test(name="two_passes_ends_game_and_pays_leader")
def t_passes():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")
    p2 = sp.test_account("p2")

    c = Reversi(admin.address, holder.address)
    s += c
    s += c.createGame(stake=sp.mutez(500000)).run(sender=p1, amount=sp.mutez(550000))
    s += c.joinGame(gameId=0).run(sender=p2, amount=sp.mutez(550000))
    # Both pass — game ends immediately (it's a 2-2 tie, so split pot).
    s += c.passTurn(gameId=0).run(sender=p1)
    s += c.passTurn(gameId=0).run(sender=p2)
    s += c.claim().run(sender=p1)
    s += c.claim().run(sender=p2)
