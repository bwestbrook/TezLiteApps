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
#   • Fixed surrender payout — used to total only 1 wager out of a 2-wager
#     pot (1 wager stranded). Now: surrender-er gets 30% of (pot − houseCut),
#     opponent gets 70% of (pot − houseCut), house gets the cut.
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
    BURN: sp.address = sp.address("tz1burnburnburnburnburnburnburjAYjjX")

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
            # ── Bookkeeping ────────────────────────────────────────────
            self.data.games = {}
            self.data.currentGameIndex = 0
            # Logic Control for game winners (4×4×4 win lines, 75 of them)
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
                72: [111, 222, 333, 444], 73: [414, 323, 232, 141],
                74: [441, 332, 223, 114],
            }
            # Move-evaluation scratch space (reset each move)
            self.data.setSum = 0
            self.data.gameWon = 0
            self.data.lastCoord = 0
            self.data.hasRemainingWinners = 0
            self.data.winnerHasZero = 0
            self.data.winnerHasOne = 0
            self.data.winnerHasTwo = 0

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
            sp.emit(params.gameId, tag="gameJoined")

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
            self.data.gameWon = 0
            g = self.data.games[params.gameId]
            assert g.metaData["gameStatus"] == 2, "game not active"
            playerTurn = g.metaData["playerTurn"]
            assert sp.sender == g.players[playerTurn], "not your turn"
            assert g.grid[params.move] == 0, "cell occupied"

            # Place mark + flip turn
            self.data.games[params.gameId].grid[params.move] = playerTurn
            if playerTurn == 1:
                self.data.games[params.gameId].metaData["playerTurn"] = 2
            else:
                self.data.games[params.gameId].metaData["playerTurn"] = 1

            # Re-evaluate the board
            self.data.hasRemainingWinners = 0
            for gameWinningSet in self.data.game_winners.values():
                self.data.setSum = 0
                self.data.winnerHasZero = 0
                self.data.winnerHasOne = 0
                self.data.winnerHasTwo = 0
                for coord in gameWinningSet:
                    owner = self.data.games[params.gameId].grid[coord]
                    if owner == 0:
                        self.data.winnerHasZero = 1
                    if owner == 1:
                        self.data.setSum += owner
                        self.data.winnerHasOne = 1
                    if owner == 2:
                        self.data.setSum += owner
                        self.data.winnerHasTwo = 1
                    self.data.lastCoord = owner
                if self.data.setSum <= 2:
                    self.data.hasRemainingWinners += 1
                if self.data.setSum == 3:
                    if self.data.winnerHasTwo == 0:
                        self.data.hasRemainingWinners += 1
                if self.data.setSum == 4:
                    if self.data.winnerHasZero != 1 and self.data.winnerHasTwo != 1:
                        self.data.gameWon = 1
                        self.data.games[params.gameId].metaData["winningPlayer"] = 1
                    else:
                        self.data.hasRemainingWinners += 1
                if self.data.setSum == 6:
                    if self.data.winnerHasOne == 0:
                        self.data.hasRemainingWinners += 1
                if self.data.setSum == 8:
                    self.data.gameWon = 2
                    self.data.games[params.gameId].metaData["winningPlayer"] = 2

            # ── Settlement: WIN ────────────────────────────────────────
            if self.data.gameWon > 0:
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
                sp.emit(self.data.gameWon, tag="gameWonBy")

            # ── Settlement: CAT'S GAME ────────────────────────────────
            # Only check if no win was just recorded.
            if self.data.gameWon == 0 and self.data.hasRemainingWinners == 0:
                self.data.games[params.gameId].metaData["gameStatus"] = 4
                pot = sp.mul(g.tzGameBet, sp.nat(2))
                houseAmt = sp.split_tokens(pot, g.houseCutBps, 10000)
                perSide = sp.split_tokens(pot - houseAmt, sp.nat(1), sp.nat(2))
                sp.send(self.data.houseAddress, houseAmt)
                sp.send(g.players[1], perSide)
                sp.send(g.players[2], perSide)
                sp.emit(params.gameId, tag="catsGame")

        # ── Surrender ──────────────────────────────────────────────────
        @sp.entrypoint()
        def surrenderGame(self, params):
            """Surrender. Surrender-er gets back 30% of (pot − houseCut);
            opponent gets 70% of (pot − houseCut); house gets the cut.
            """
            sp.cast(params.gameId, sp.int)
            g = self.data.games[params.gameId]
            assert g.metaData["gameStatus"] == 2, "game not active"
            assert sp.sender == g.players[1] or sp.sender == g.players[2], "not a player"

            pot = sp.mul(g.tzGameBet, sp.nat(2))
            houseAmt = sp.split_tokens(pot, g.houseCutBps, 10000)
            netPot = pot - houseAmt
            surrenderAmt = sp.split_tokens(netPot, sp.nat(3), sp.nat(10))
            otherAmt = sp.split_tokens(netPot, sp.nat(7), sp.nat(10))

            sp.send(self.data.houseAddress, houseAmt)
            if sp.sender == g.players[1]:
                sp.send(g.players[1], surrenderAmt)
                sp.send(g.players[2], otherAmt)
                self.data.games[params.gameId].metaData["winningPlayer"] = 2
            else:
                sp.send(g.players[2], surrenderAmt)
                sp.send(g.players[1], otherAmt)
                self.data.games[params.gameId].metaData["winningPlayer"] = 1
            self.data.games[params.gameId].metaData["gameStatus"] = 5
            sp.emit(params.gameId, tag="surrendered")


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────
@sp.add_test()
def test():
    s = sp.test_scenario("TTT gambling + house cut", main)
    c = main.TezTacToe()
    s += c
