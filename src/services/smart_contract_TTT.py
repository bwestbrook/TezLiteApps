import smartpy as sp

# ──────────────────────────────────────────────────────────────────────────────
# TezTacToe — H2H 4-in-a-row (4×4×4 cube), wagered + house cut.
#
# Modernized over the legacy contract (smart_contract_TTT_legacy_backup.py)
# while preserving the entrypoint names (startGame, joinGame, leaveGame,
# makeMove, surrenderGame) so the existing UI keeps working.
#
# What changed vs. the legacy contract:
#   • Added houseCutBps + houseAddress (configurable by admin, capped 10%).
#     Default 250 bps (2.5%) on settlement.
#   • Per-game houseCutBps snapshot — locked at startGame so a mid-game
#     admin change can't surprise players.
#   • Fixed cat's game payout — used to send 30%-of-one-wager to each side
#     (1.4 wagers stranded on the contract). Now: each side gets back
#     wager − houseCut/2 (full pot pays out cleanly).
#   • Surrender payout — used to total only 1 wager out of a 2-wager
#     pot (1 wager stranded). Now a pure forfeit (TTT-5): the opponent
#     takes the full pot − houseCut, the surrenderer gets nothing.
#   • Fixed surrenderGame — used to take no params; now takes gameId.
#   • Fixed joinGame — used to trust whatever sp.amount the joiner sent.
#     Now asserts sp.amount == tzGameBet + fee.
#   • Fixed updateOracle — used to write to txlContract under an oracle gate.
#     Now writes to oracle under an admin gate.
#   • Gated all admin entrypoints (asserts that were commented out).
#   • Added updateAdmin / updateHouseCut / updateHouseAddress / updateFee /
#     updateMinWager / updateMaxWager.
#   • Min/max wager bounds (configurable).
#
# Storage compatibility:
#   game record adds `houseCutBps` (sp.nat). The UI reads `tzGameBet`,
#   `players`, `metaData`, `grid` — all preserved.
# ──────────────────────────────────────────────────────────────────────────────

@sp.module
def main():
    # gameStatus encoding (preserved from legacy):
    #   0 Created but creator left game before challenger
    #   1 Created and at least one player in game
    #   2 Active and no Winners
    #   3 Game has Winner
    #   4 Cats Game (no winning lines remain)
    #   5 Surrender
    # Plain assignment, no type annotation — SmartPy's @sp.module parser
    # rejects annotated assignments at module scope ("Not a module statement").
    BURN = sp.address("tz1burnburnburnburnburnburnburjAYjjX")

    class TezTacToe(sp.Contract):

        def __init__(self):
            # ── Admin / wiring ─────────────────────────────────────────
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            # houseAddress receives the per-pot cut at settlement (separate
            # from txlContract so the admin can route it elsewhere if needed).
            self.data.houseAddress = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            # ── Economics ──────────────────────────────────────────────
            self.data.fee = sp.mutez(100000)            # flat per-tx, → txl
            self.data.minWager = sp.mutez(0)            # 0 ꜩ allowed (free games)
            self.data.maxWager = sp.mutez(50000000)     # 50 ꜩ
            self.data.houseCutBps = sp.nat(250)         # 2.5% of pot
            # Blocks of opponent idleness after which claimByTimeout can
            # settle a stalled game (TTT-6, mirror of Chess). ~1 hour at
            # 30s blocks. Admin-tunable via updateStaleBlocks.
            self.data.staleBlocks = sp.nat(120)
            # ── Bookkeeping ────────────────────────────────────────────
            # §3.3 — type-cast the empty map explicitly (TTT-1). The
            # current SmartPy infers this from startGame's downstream
            # record assignment, but inference is fragile; the explicit
            # cast matches the AD/Plinko pattern and survives refactors.
            self.data.games = sp.cast({}, sp.map[sp.int, sp.record(
                grid=sp.map[sp.int, sp.int],
                players=sp.map[sp.int, sp.address],
                metaData=sp.map[sp.string, sp.int],
                tzGameBet=sp.mutez,
                houseCutBps=sp.nat,
            )])
            self.data.currentGameIndex = sp.int(0)
            # Logic Control for game winners (4×4×4 win lines, 76 of them:
            # 48 axis-aligned + 24 face diagonals + 4 space diagonals)
            self.data.game_winners = {
                0: [111, 112, 113, 114],   1: [121, 122, 123, 124],
                2: [131, 132, 133, 134],   3: [141, 142, 143, 144],
                4: [211, 212, 213, 214],   5: [221, 222, 223, 224],
                6: [231, 232, 233, 234],   7: [241, 242, 243, 244],
                8: [311, 312, 313, 314],   9: [321, 322, 323, 324],
                10: [331, 332, 333, 334], 11: [341, 342, 343, 344],
                12: [411, 412, 413, 414], 13: [421, 422, 423, 424],
                14: [431, 432, 433, 434], 15: [441, 442, 443, 444],
                16: [111, 121, 131, 141], 17: [211, 221, 231, 241],
                18: [311, 321, 331, 341], 19: [411, 421, 431, 441],
                20: [112, 122, 132, 142], 21: [212, 222, 232, 242],
                22: [312, 322, 332, 342], 23: [412, 422, 432, 442],
                24: [113, 123, 133, 143], 25: [213, 223, 233, 243],
                26: [313, 323, 333, 343], 27: [413, 423, 433, 443],
                28: [114, 124, 134, 144], 29: [214, 224, 234, 244],
                30: [314, 324, 334, 344], 31: [414, 424, 434, 444],
                32: [111, 211, 311, 411], 33: [112, 212, 312, 412],
                34: [113, 213, 313, 413], 35: [114, 214, 314, 414],
                36: [121, 221, 321, 421], 37: [122, 222, 322, 422],
                38: [123, 223, 323, 423], 39: [124, 224, 324, 424],
                40: [131, 231, 331, 431], 41: [132, 232, 332, 432],
                42: [133, 233, 333, 433], 43: [134, 234, 334, 434],
                44: [141, 241, 341, 441], 45: [142, 242, 342, 442],
                46: [143, 243, 343, 443], 47: [144, 244, 344, 444],
                48: [111, 122, 133, 144], 49: [114, 123, 132, 141],
                50: [211, 222, 233, 244], 51: [214, 223, 232, 241],
                52: [311, 322, 333, 344], 53: [314, 323, 332, 341],
                54: [411, 422, 433, 444], 55: [414, 423, 432, 441],
                56: [111, 212, 313, 414], 57: [114, 213, 312, 411],
                58: [121, 222, 323, 424], 59: [124, 223, 322, 421],
                60: [131, 232, 333, 434], 61: [134, 233, 332, 431],
                62: [141, 242, 343, 444], 63: [144, 243, 342, 441],
                64: [111, 221, 331, 441], 65: [141, 231, 321, 411],
                66: [112, 222, 332, 442], 67: [142, 232, 322, 412],
                68: [113, 223, 333, 443], 69: [143, 233, 323, 413],
                70: [114, 224, 334, 444], 71: [144, 234, 324, 414],
                # The 4 space diagonals. 75 was missing — a 4-in-a-row on
                # (1,4,4)-(4,1,1) used to go unrewarded.
                72: [111, 222, 333, 444], 73: [414, 323, 232, 141],
                74: [441, 332, 223, 114], 75: [144, 233, 322, 411],
            }
            # §8.1 (TTT-4) — reverse index: grid cell → the win-set
            # indices that include it. makeMove scans only the sets
            # touching the just-placed cell (4–7 of them) instead of all
            # 76. Derived mechanically from game_winners above (see
            # scripts/exercise_contracts.py / the TTT-4 generator) — if
            # you edit game_winners, regenerate this.
            self.data.cell_to_winsets = {
                111: [0, 16, 32, 48, 56, 64, 72], 112: [0, 20, 33, 66], 113: [0, 24, 34, 68], 114: [0, 28, 35, 49, 57, 70, 74],
                121: [1, 16, 36, 58], 122: [1, 20, 37, 48], 123: [1, 24, 38, 49], 124: [1, 28, 39, 59],
                131: [2, 16, 40, 60], 132: [2, 20, 41, 49], 133: [2, 24, 42, 48], 134: [2, 28, 43, 61],
                141: [3, 16, 44, 49, 62, 65, 73], 142: [3, 20, 45, 67], 143: [3, 24, 46, 69], 144: [3, 28, 47, 48, 63, 71, 75],
                211: [4, 17, 32, 50], 212: [4, 21, 33, 56], 213: [4, 25, 34, 57], 214: [4, 29, 35, 51],
                221: [5, 17, 36, 64], 222: [5, 21, 37, 50, 58, 66, 72], 223: [5, 25, 38, 51, 59, 68, 74], 224: [5, 29, 39, 70],
                231: [6, 17, 40, 65], 232: [6, 21, 41, 51, 60, 67, 73], 233: [6, 25, 42, 50, 61, 69, 75], 234: [6, 29, 43, 71],
                241: [7, 17, 44, 51], 242: [7, 21, 45, 62], 243: [7, 25, 46, 63], 244: [7, 29, 47, 50],
                311: [8, 18, 32, 52], 312: [8, 22, 33, 57], 313: [8, 26, 34, 56], 314: [8, 30, 35, 53],
                321: [9, 18, 36, 65], 322: [9, 22, 37, 52, 59, 67, 75], 323: [9, 26, 38, 53, 58, 69, 73], 324: [9, 30, 39, 71],
                331: [10, 18, 40, 64], 332: [10, 22, 41, 53, 61, 66, 74], 333: [10, 26, 42, 52, 60, 68, 72], 334: [10, 30, 43, 70],
                341: [11, 18, 44, 53], 342: [11, 22, 45, 63], 343: [11, 26, 46, 62], 344: [11, 30, 47, 52],
                411: [12, 19, 32, 54, 57, 65, 75], 412: [12, 23, 33, 67], 413: [12, 27, 34, 69], 414: [12, 31, 35, 55, 56, 71, 73],
                421: [13, 19, 36, 59], 422: [13, 23, 37, 54], 423: [13, 27, 38, 55], 424: [13, 31, 39, 58],
                431: [14, 19, 40, 61], 432: [14, 23, 41, 55], 433: [14, 27, 42, 54], 434: [14, 31, 43, 60],
                441: [15, 19, 44, 55, 63, 64, 74], 442: [15, 23, 45, 66], 443: [15, 27, 46, 68], 444: [15, 31, 47, 54, 62, 70, 72],
            }
            # §7.4 (TTT-3) — move-evaluation scratch (setSum / gameWon /
            # hasRemainingWinners / winnerHas*) used to live here on
            # self.data, costing storage forever for values only
            # meaningful within a single makeMove call. They're now
            # locals inside makeMove. `lastCoord` was dead and is dropped.

        # ── Default ────────────────────────────────────────────────────
        @sp.entrypoint
        def default(self):
            pass

        # ── Admin ──────────────────────────────────────────────────────
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
            """House cut in basis points. Capped at 1000 (10%)."""
            assert sp.sender == self.data.admin, "not admin"
            assert params.bps <= 1000, "house cut > 10% rejected"
            self.data.houseCutBps = params.bps

        @sp.entrypoint()
        def updateFee(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.fee = params.fee

        @sp.entrypoint()
        def updateWagerBounds(self, params):
            assert sp.sender == self.data.admin, "not admin"
            assert params.minWager <= params.maxWager, "minWager > maxWager"
            self.data.minWager = params.minWager
            self.data.maxWager = params.maxWager

        @sp.entrypoint()
        def updateStaleBlocks(self, params):
            """Tune the claimByTimeout idle window (TTT-6). Floored at 30
            blocks so it can't be set low enough to snipe an opponent
            who is merely between moves."""
            sp.cast(params.staleBlocks, sp.nat)
            assert sp.sender == self.data.admin, "not admin"
            assert params.staleBlocks >= 30, "staleBlocks too small"
            self.data.staleBlocks = params.staleBlocks

        # ── Lifecycle ──────────────────────────────────────────────────
        @sp.entrypoint()
        def startGame(self):
            """Player 1 creates a game with sp.amount == wager + fee.

            tzGameBet (the per-side wager) is computed as sp.amount - fee.
            """
            assert sp.amount >= self.data.fee, "must cover fee"
            tzGameBet = sp.amount - self.data.fee
            assert tzGameBet >= self.data.minWager, "wager too small"
            assert tzGameBet <= self.data.maxWager, "wager too big"
            sp.send(self.data.txlContract, self.data.fee)

            new_game_grid = {
                111: 0, 112: 0, 113: 0, 114: 0,
                121: 0, 122: 0, 123: 0, 124: 0,
                131: 0, 132: 0, 133: 0, 134: 0,
                141: 0, 142: 0, 143: 0, 144: 0,
                211: 0, 212: 0, 213: 0, 214: 0,
                221: 0, 222: 0, 223: 0, 224: 0,
                231: 0, 232: 0, 233: 0, 234: 0,
                241: 0, 242: 0, 243: 0, 244: 0,
                311: 0, 312: 0, 313: 0, 314: 0,
                321: 0, 322: 0, 323: 0, 324: 0,
                331: 0, 332: 0, 333: 0, 334: 0,
                341: 0, 342: 0, 343: 0, 344: 0,
                411: 0, 412: 0, 413: 0, 414: 0,
                421: 0, 422: 0, 423: 0, 424: 0,
                431: 0, 432: 0, 433: 0, 434: 0,
                441: 0, 442: 0, 443: 0, 444: 0,
            }
            idx = self.data.currentGameIndex
            players = {1: sp.sender, 2: BURN}
            metaData = {
                "playerTurn": 1,
                "gameStatus": 1,
                "player1Paid": 1,
                "player2Paid": 0,
                "winningPlayer": 0,
                # 0 until the oracle's flipForFirst runs once both players
                # have paired. makeMove is gated on this so neither side can
                # move before the coin flip sets playerTurn.
                "firstMoveDecided": 0,
                # §8.1 (TTT-4) — count of win-sets not yet contested by
                # both players. Starts at 76 (all of game_winners);
                # makeMove decrements it as lines die. 0 → cat's game.
                "remainingWinsets": 76,
                # TTT-6 — block height at which the game last advanced
                # (created / joined / flipped / moved). claimByTimeout
                # measures opponent idleness against this.
                "lastMoveBlock": sp.to_int(sp.level),
            }
            new_game = sp.record(
                grid=new_game_grid,
                players=players,
                metaData=metaData,
                tzGameBet=tzGameBet,
                houseCutBps=self.data.houseCutBps,   # snapshot for fairness
            )
            self.data.games[idx] = new_game
            self.data.currentGameIndex += 1
            sp.emit(idx, tag="gameCreated")

        @sp.entrypoint()
        def joinGame(self, params):
            """Player 2 joins. Must send tzGameBet + fee."""
            sp.cast(params.gameId, sp.int)
            g = self.data.games[params.gameId]
            assert g.metaData["gameStatus"] == 1, "game not joinable"
            assert g.metaData["player2Paid"] == 0, "already full"
            assert sp.sender != g.players[1], "can't join your own game"
            assert sp.amount == g.tzGameBet + self.data.fee, "must match wager + fee"
            sp.send(self.data.txlContract, self.data.fee)
            self.data.games[params.gameId].players[2] = sp.sender
            self.data.games[params.gameId].metaData["player2Paid"] = 1
            self.data.games[params.gameId].metaData["gameStatus"] = 2  # active
            self.data.games[params.gameId].metaData["lastMoveBlock"] = sp.to_int(sp.level)
            sp.emit(params.gameId, tag="gameJoined")

        @sp.entrypoint()
        def flipForFirst(self, params):
            """Oracle decides who moves first, once both players have paired.

            bit 0 → player 1 moves first, bit 1 → player 2. The seed is
            emitted (not stored — metaData is int-only) so the flip stays
            auditable on-chain via the firstMoveDecided event. Idempotent:
            the firstMoveDecided flag guards against a re-flip.
            """
            sp.cast(params.gameId, sp.int)
            sp.cast(params.bit, sp.int)
            sp.cast(params.seed, sp.string)
            assert sp.sender == self.data.oracle, "not oracle"
            g = self.data.games[params.gameId]
            assert g.metaData["gameStatus"] == 2, "game not active"
            assert g.metaData["firstMoveDecided"] == 0, "first move already decided"
            assert params.bit == 0 or params.bit == 1, "bit must be 0 or 1"
            firstPlayer = 1
            if params.bit == 1:
                firstPlayer = 2
            self.data.games[params.gameId].metaData["playerTurn"] = firstPlayer
            self.data.games[params.gameId].metaData["firstMoveDecided"] = 1
            # TTT-6 — reset the idle clock: the first mover's turn starts
            # now, not back at joinGame (the oracle's flip may lag).
            self.data.games[params.gameId].metaData["lastMoveBlock"] = sp.to_int(sp.level)
            sp.emit(
                sp.record(
                    gameId=params.gameId,
                    firstPlayer=firstPlayer,
                    seed=params.seed,
                ),
                tag="firstMoveDecided",
            )

        @sp.entrypoint()
        def leaveGame(self, params):
            """Creator can leave a not-yet-joined game and reclaim the wager.

            The fee is non-refundable (already forwarded to the holder fund).
            """
            sp.cast(params.gameId, sp.int)
            g = self.data.games[params.gameId]
            assert g.metaData["gameStatus"] == 1, "game already started"
            assert sp.sender == g.players[1], "not creator"
            sp.send(g.players[1], g.tzGameBet)
            self.data.games[params.gameId].metaData["gameStatus"] = 0
            self.data.games[params.gameId].metaData["player1Paid"] = 0
            sp.emit(params.gameId, tag="gameLeft")

        # ── Move + auto-settle on win/cat's ────────────────────────────
        @sp.entrypoint()
        def makeMove(self, params):
            """Submit a move. Auto-settles on win or cat's game.

            Win  → winner gets pot − houseCut, house gets cut.
            Cat  → each side gets back wager − houseCut/2, house gets cut.
            """
            sp.cast(params.gameId, sp.int)
            sp.cast(params.move, sp.int)
            g = self.data.games[params.gameId]
            assert g.metaData["gameStatus"] == 2, "game not active"
            assert g.metaData["firstMoveDecided"] == 1, "awaiting first-move flip"
            playerTurn = g.metaData["playerTurn"]
            assert sp.sender == g.players[playerTurn], "not your turn"
            # §7.1 — reject coords outside the 64-cell domain before the
            # map lookup, so a bad params.move fails with a clear message
            # instead of a Michelson-level panic (TTT-2).
            assert params.move in g.grid, "invalid move coord"
            assert g.grid[params.move] == 0, "cell occupied"

            # Place mark + flip turn
            self.data.games[params.gameId].grid[params.move] = playerTurn
            nextTurn = 2
            if playerTurn == 2:
                nextTurn = 1
            self.data.games[params.gameId].metaData["playerTurn"] = nextTurn

            # §8.1 (TTT-4) — placing a mark can only complete a line
            # through params.move, and can only newly-kill win-sets
            # through params.move. Scan just that index (4–7 sets)
            # instead of all 76. remainingWinsets is kept on the game
            # record and decremented as lines die, so cat's-game
            # detection stays correct without a full re-scan.
            #
            # This also corrects an over-count in the old setSum logic,
            # which treated some already-contested sets (e.g. a line
            # holding P2,P1,P1,_) as still winnable. A set is dead the
            # moment it holds marks from BOTH players. §7.4 — gameWon /
            # newlyDead / count* are per-call scratch locals.
            gameWon = sp.int(0)
            newlyDead = sp.int(0)
            for setIdx in self.data.cell_to_winsets[params.move]:
                gameWinningSet = self.data.game_winners[setIdx]
                countMine = sp.int(0)
                countOpp = sp.int(0)
                for coord in gameWinningSet:
                    owner = self.data.games[params.gameId].grid[coord]
                    if owner == playerTurn:
                        countMine += 1
                    if owner == nextTurn:
                        countOpp += 1
                # Win: this move completed all four cells for playerTurn.
                # Only playerTurn can win a line through their own move.
                if countMine == 4:
                    gameWon = playerTurn
                    self.data.games[params.gameId].metaData["winningPlayer"] = playerTurn
                # Newly dead: this move placed playerTurn's ONLY mark in a
                # set the opponent was already in — nobody can win it now.
                if countMine == 1:
                    if countOpp >= 1:
                        newlyDead += 1
            remainingWinsets = g.metaData["remainingWinsets"] - newlyDead
            self.data.games[params.gameId].metaData["remainingWinsets"] = remainingWinsets

            # ── Settlement: WIN ────────────────────────────────────────
            if gameWon > 0:
                self.data.games[params.gameId].metaData["gameStatus"] = 3
                pot = sp.mul(g.tzGameBet, sp.nat(2))
                houseAmt = sp.split_tokens(pot, g.houseCutBps, 10000)
                payout = pot - houseAmt
                sp.send(self.data.houseAddress, houseAmt)
                sp.send(
                    self.data.games[params.gameId].players[
                        self.data.games[params.gameId].metaData["winningPlayer"]
                    ],
                    payout,
                )
                sp.emit(gameWon, tag="gameWonBy")

            # ── Settlement: CAT'S GAME ────────────────────────────────
            # Only check if no win was just recorded.
            if gameWon == 0 and remainingWinsets == 0:
                self.data.games[params.gameId].metaData["gameStatus"] = 4
                pot = sp.mul(g.tzGameBet, sp.nat(2))
                houseAmt = sp.split_tokens(pot, g.houseCutBps, 10000)
                perSide = sp.split_tokens(pot - houseAmt, sp.nat(1), sp.nat(2))
                sp.send(self.data.houseAddress, houseAmt)
                sp.send(g.players[1], perSide)
                sp.send(g.players[2], perSide)
                sp.emit(params.gameId, tag="catsGame")

            # TTT-6 — record this block as the game's last advance, so
            # the opponent's idle clock for claimByTimeout starts now.
            self.data.games[params.gameId].metaData["lastMoveBlock"] = sp.to_int(sp.level)

        # ── Surrender ──────────────────────────────────────────────────
        @sp.entrypoint()
        def surrenderGame(self, params):
            """Surrender — pure forfeit (TTT-5). The surrenderer gets
            nothing; the opponent takes the whole pot minus the house
            cut. The old 30/70 split was unusually generous to the side
            that quit; pure forfeit is the strongest disincentive to
            rage-quit and pays the full pot out cleanly.
            """
            sp.cast(params.gameId, sp.int)
            g = self.data.games[params.gameId]
            assert g.metaData["gameStatus"] == 2, "game not active"
            assert sp.sender == g.players[1] or sp.sender == g.players[2], "not a player"

            pot = sp.mul(g.tzGameBet, sp.nat(2))
            houseAmt = sp.split_tokens(pot, g.houseCutBps, 10000)
            netPot = pot - houseAmt

            sp.send(self.data.houseAddress, houseAmt)
            if sp.sender == g.players[1]:
                sp.send(g.players[2], netPot)
                self.data.games[params.gameId].metaData["winningPlayer"] = 2
            else:
                sp.send(g.players[1], netPot)
                self.data.games[params.gameId].metaData["winningPlayer"] = 1
            self.data.games[params.gameId].metaData["gameStatus"] = 5
            sp.emit(params.gameId, tag="surrendered")

        # ── Claim a stalled game ───────────────────────────────────────
        @sp.entrypoint()
        def claimByTimeout(self, params):
            """If the player who owes the next move has been idle for
            >= staleBlocks, the waiting player claims the win — pot minus
            the house cut, same settlement as a makeMove win (TTT-6,
            mirror of Chess). §7.2 — gated on gameStatus 2 + a decided
            first move, so it can't fire on a game that isn't playable.
            """
            sp.cast(params.gameId, sp.int)
            g = self.data.games[params.gameId]
            assert g.metaData["gameStatus"] == 2, "game not active"
            assert g.metaData["firstMoveDecided"] == 1, "awaiting first-move flip"
            elapsed = sp.to_int(sp.level) - g.metaData["lastMoveBlock"]
            assert elapsed >= sp.to_int(self.data.staleBlocks), "not stale yet"
            playerTurn = g.metaData["playerTurn"]
            # The claimant must be the player NOT on the clock.
            assert sp.sender != g.players[playerTurn], "you owe the move"
            assert sp.sender == g.players[1] or sp.sender == g.players[2], "not a player"

            # Settle exactly like a makeMove win: §4.1 — record terminal
            # state before paying out.
            self.data.games[params.gameId].metaData["gameStatus"] = 3
            if sp.sender == g.players[1]:
                self.data.games[params.gameId].metaData["winningPlayer"] = 1
            else:
                self.data.games[params.gameId].metaData["winningPlayer"] = 2
            pot = sp.mul(g.tzGameBet, sp.nat(2))
            houseAmt = sp.split_tokens(pot, g.houseCutBps, 10000)
            payout = pot - houseAmt
            sp.send(self.data.houseAddress, houseAmt)
            sp.send(sp.sender, payout)
            sp.emit(params.gameId, tag="claimedByTimeout")


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────
@sp.add_test()
def test():
    s = sp.test_scenario("TTT gambling + house cut", main)
    c = main.TezTacToe()
    s += c

    # ── Play a full game through to a P1 win ──────────────────────────
    # Regression cover for TTT-2 (coord validation), TTT-3 (scratch as
    # locals) and TTT-4 (cell_to_winsets scan + win detection). A full
    # cat's-game fill is left to the on-chain exercise harness.
    p1 = sp.test_account("p1")
    p2 = sp.test_account("p2")
    oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
    fee = sp.mutez(100000)
    wager = sp.mutez(1000000)
    c.startGame(_sender=p1, _amount=wager + fee)
    c.joinGame(gameId=0, _sender=p2, _amount=wager + fee)
    c.flipForFirst(gameId=0, bit=0, seed="seed", _sender=oracle)
    # P1 takes win-set 0 = [111,112,113,114]; P2 plays harmlessly.
    c.makeMove(gameId=0, move=111, _sender=p1)
    c.makeMove(gameId=0, move=211, _sender=p2)
    c.makeMove(gameId=0, move=112, _sender=p1)
    c.makeMove(gameId=0, move=212, _sender=p2)
    c.makeMove(gameId=0, move=113, _sender=p1)
    c.makeMove(gameId=0, move=212, _sender=p2, _valid=False)   # cell occupied
    c.makeMove(gameId=0, move=999, _sender=p2, _valid=False)   # TTT-2: bad coord
    c.makeMove(gameId=0, move=213, _sender=p2)
    c.makeMove(gameId=0, move=114, _sender=p1)                 # P1 completes line 0
    s.verify(c.data.games[0].metaData["gameStatus"] == 3)
    s.verify(c.data.games[0].metaData["winningPlayer"] == 1)
    # No move can be played on a settled game.
    c.makeMove(gameId=0, move=311, _sender=p2, _valid=False)

    # ── TTT-6: claim a stalled game by timeout ────────────────────────
    c.startGame(_sender=p1, _amount=wager + fee, _level=1000)
    c.joinGame(gameId=1, _sender=p2, _amount=wager + fee, _level=1000)
    # bit=1 → player 2 moves first, so p2 is on the clock.
    c.flipForFirst(gameId=1, bit=1, seed="s2", _sender=oracle, _level=1000)
    # Before staleBlocks (120) elapse, nobody can claim.
    c.claimByTimeout(gameId=1, _sender=p1, _level=1100, _valid=False)
    # The player who owes the move can't claim their own timeout.
    c.claimByTimeout(gameId=1, _sender=p2, _level=1200, _valid=False)
    # 200 blocks idle (>= 120) → the waiting player (p1) claims the win.
    c.claimByTimeout(gameId=1, _sender=p1, _level=1200)
    s.verify(c.data.games[1].metaData["gameStatus"] == 3)
    s.verify(c.data.games[1].metaData["winningPlayer"] == 1)
