import smartpy as sp

@sp.module
def main():
    class TezTacToe(sp.Contract):
        
        def __init__(self, player1, player2):
            '''
            '''
        
            self.data.game_winners = {
                    0: [111, 112, 113, 114],
                    1: [121, 122, 123, 124],
                    2: [131, 132, 133, 134],
                    3: [141, 142, 143, 144],
                    4: [211, 212, 213, 214],
                    5: [221, 222, 223, 224],
                    6: [231, 232, 233, 234],
                    7: [241, 242, 243, 244],
                    8: [311, 312, 313, 314],
                    9: [321, 322, 323, 324],
                    10: [331, 332, 333, 334],
                    11: [341, 342, 343, 344],
                    12: [411, 412, 413, 414],
                    13: [421, 422, 423, 424],
                    14: [431, 432, 433, 434],
                    15: [441, 442, 443, 444],
                    16: [111, 121, 131, 141],
                    17: [211, 221, 231, 241],
                    18: [311, 321, 331, 341],
                    19: [411, 421, 431, 441],
                    20: [112, 122, 132, 142],
                    21: [212, 222, 232, 242],
                    22: [312, 322, 332, 342],
                    23: [412, 422, 432, 442],
                    24: [113, 123, 133, 143],
                    25: [213, 223, 233, 243],
                    26: [313, 323, 333, 343],
                    27: [413, 423, 433, 443],
                    28: [114, 124, 134, 144],
                    29: [214, 224, 234, 244],
                    30: [314, 324, 334, 344],
                    31: [414, 424, 434, 444],
                    32: [111, 211, 311, 411],
                    33: [112, 212, 312, 412],
                    34: [113, 213, 313, 413],
                    35: [114, 214, 314, 414],
                    36: [121, 221, 321, 421],
                    37: [122, 222, 322, 422],
                    38: [123, 223, 323, 423],
                    39: [124, 224, 324, 424],
                    40: [131, 231, 331, 431],
                    41: [132, 232, 332, 432],
                    42: [133, 233, 333, 433],
                    43: [134, 234, 334, 434],
                    44: [141, 241, 341, 441],
                    45: [142, 242, 342, 442],
                    46: [143, 243, 343, 443],
                    47: [144, 244, 344, 444],
                    48: [111, 122, 133, 144],
                    49: [114, 123, 132, 141],
                    50: [211, 222, 233, 244],
                    51: [214, 223, 232, 241],
                    52: [311, 322, 333, 344],
                    53: [314, 323, 332, 341],
                    54: [411, 422, 433, 444],
                    55: [414, 423, 432, 441],
                    56: [111, 212, 313, 414],
                    57: [114, 213, 312, 411],
                    58: [121, 222, 323, 424],
                    59: [124, 223, 322, 421],
                    60: [131, 232, 333, 434],
                    61: [134, 233, 332, 431],
                    62: [141, 242, 343, 444],
                    63: [144, 243, 342, 441],
                    64: [111, 221, 331, 441],
                    65: [141, 231, 321, 411],
                    66: [112, 222, 332, 442],
                    67: [142, 232, 322, 412],
                    68: [113, 223, 333, 443],
                    69: [143, 233, 323, 413],
                    70: [114, 224, 334, 444],
                    71: [144, 234, 324, 414],
                    72: [111, 222, 333, 444],
                    73: [414, 323, 232, 141],
                    74: [441, 332, 223, 114]
                }
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.games = {}
            self.data.metadata = {
                "currentGameIndex": 0,
                "pendingGames": 0
            }



            
        @sp.entrypoint()
        def startGame(self, params):
            '''
            '''
            sp.cast(params.player, sp.address)
            sp.cast(params.mutezPerMove, sp.nat)
            new_game_grid = {
                    111: 0,
                    112: 1,
                    113: 2,
                    114: 1,
                    121: 0,
                    122: 0,
                    123: 2,
                    124: 0,
                    131: 0,
                    132: 0,
                    133: 0,
                    134: 0,
                    141: 0,
                    142: 0,
                    143: 0,
                    144: 0,
                    211: 0,
                    212: 0,
                    213: 0,
                    214: 0,
                    221: 0,
                    222: 0,
                    223: 0,
                    224: 0,
                    231: 0,
                    232: 0,
                    233: 0,
                    234: 0,
                    241: 0,
                    242: 0,
                    243: 0,
                    244: 0,
                    311: 0,
                    312: 0,
                    313: 0,
                    314: 0,
                    321: 0,
                    322: 0,
                    323: 0,
                    324: 0,
                    331: 0,
                    332: 0,
                    333: 0,
                    334: 0,
                    341: 0,
                    342: 0,
                    343: 0,
                    344: 0,
                    411: 0,
                    412: 0,
                    413: 0,
                    414: 0,
                    421: 0,
                    422: 0,
                    423: 0,
                    424: 0,
                    431: 0,
                    432: 0,
                    433: 0,
                    434: 0,
                    441: 0,
                    442: 0,
                    443: 0,
                    444: 0
                    }
            idx = self.data.metadata["currentGameIndex"]
            players = {1: params.player, 2: params.player}
            metadata = {
                "mutezPerMove": params.mutezPerMove,
                "playerTurn": 1, 
                "gameStatus": 0,
                "gameBalance": 0,
            }      
            new_game = sp.record(
                grid = new_game_grid,
                players = players,
                metadata = metadata
            )           
            self.data.games[idx] = new_game
            self.data.metadata["currentGameIndex"] += 1
            
        @sp.entry_point()    
        def joinGame(self, params):
            '''
            '''
            if self.data.games[params.gameId].metadata['gameStatus'] != 1:
                sp.cast(params.player, sp.address)
                sp.cast(params.gameId, sp.int)
                self.data.games[params.gameId].players[2] = params.player
                self.data.games[params.gameId].metadata['gameStatus'] = 1

        @sp.entry_point()
        def makeMove(self, params):
            '''
            '''
            sp.cast(params.player, sp.address)
            sp.cast(params.gameId, sp.int)
            sp.cast(params.move, sp.int)
            #sp.cast(params.caddress, sp.address)
            #caddress = sp.self_address
            #sp.send(params.caddress, sp.mutez(10))
            if self.data.games[params.gameId].metadata["gameStatus"] == 0:
                player_turn = self.data.games[params.gameId].metadata["playerTurn"]
                if self.data.games[params.gameId].players[player_turn] == params.player:
                    self.data.games[params.gameId].grid[params.move] = player_turn
                    if player_turn == 1:
                        self.data.games[params.gameId].metadata["playerTurn"] = 2
                    else:
                        self.data.games[params.gameId].metadata["playerTurn"] = 1



@sp.add_test()
def test():
    s = sp.test_scenario("my first test", main)
    #caddress = sp.self_address
    

    player1 = sp.test_account("player1")
    player2 = sp.test_account("player2")
    player3 = sp.test_account("player3")
    a = main.TezTacToe(player1.address, player2.address)
    s += a
    mutezPerMove = 10000
    values = [player1.address, mutezPerMove]
    #params = sp.cast(values, sp.record)
    a.startGame(player= player1.address, mutezPerMove=mutezPerMove)
    a.joinGame(player = player2.address, gameId=0)
    a.joinGame(player = player3.address, gameId=0)
    a.makeMove(player = player2.address, gameId=0, move=111)
    