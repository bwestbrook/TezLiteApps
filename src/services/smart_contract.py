import smartpy as sp

@sp.module
def main():
    class TezTacToe(sp.Contract):
        
        def __init__(self, player1, player2):
            '''
            Logic largely controlled by "gameStatus"
            1: Created and at least one player in game
            2: Active and no Winners
            3: Game has Winner
            4: Cats Game
            5: Surrender 
            '''
            #Game Control         
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.contractAddress = sp.address("KT1TezoooozzSmartPyzzSTATiCzzzwwBFA1")
            self.data.games = {}
            self.data.currentGameIndex = 0
            #NFT Payout
            #self.data.nftHolders = {}
            #Logic Control for game winners
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
            self.data.winningSet = {
                1: 0, 
                2: 0,
                3: 0,
                4: 0}  
            self.data.setSum = 0
            self.data.gameWon = 0
            self.data.lastCoord = 0            
            self.data.failedAttempts = 0
            self.data.hasRemainingWinners = 0 
            self.data.winnerHasZero = 0
            self.data.winnerHasOne = 0
            self.data.winnerHasTwo = 0
            self.data.nChecks = 0 # probaly delete after stable
            self.data.lockedBalance = sp.mutez(0)
            
        @sp.entrypoint()
        def startGame(self, params):
            '''
            There's no 'send' to contract here as this entry point like join game costs tez on the FE in taquito
            '''
            sp.emit(1, tag="contractUpdated")
            new_game_grid = {
                    111: 0,
                    112: 0,
                    113: 0,
                    114: 0,
                    121: 0,
                    122: 0,
                    123: 0,
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
            idx = self.data.currentGameIndex
            players = {1: sp.sender, 2: sp.address('---')}  
            gameBalance = sp.mutez(0)
            sp.cast(params.mutezPerMove, sp.mutez)
            sp.cast(params.surrenderAmount, sp.mutez)
            sp.cast(params.surrenderOtherAmount, sp.mutez)
            metaData = {
                "playerTurn": params.playerTurn,
                "gameStatus": params.gameStatus,
                "winningPlayer": 0
            }
            new_game = sp.record(
                grid = new_game_grid,
                players = players,                
                mutezPerMove = params.mutezPerMove,# computed by front end 1X mutez * (1 - fee), used by Cat's Game
                gameBalance = gameBalance, #computed by front end 2X mutez (fee asseseed by FE in mutez per Muve)
                surrenderAmount = params.surrenderAmount, #computed by front end 1X mutez * 0.75
                surrenderOtherAmount = params.surrenderOtherAmount, #computed by front end 1X mutez * 0.25
                playerTurn = params.playerTurn,
                gamesStatus = params.gameStatus,
                metaData = metaData
            )     
            new_game.gameBalance += new_game.mutezPerMove
            self.data.lockedBalance += new_game.mutezPerMove
            self.data.games[idx] = new_game
            self.data.currentGameIndex += 1
            
       
            
        @sp.entry_point()    
        def joinGame(self, params):
            '''
            There's no 'send' to contract here as this entry point like make game costs tez on the FE in taquito
            '''
            assert sp.sender != self.data.games[params.gameId].players[1], "already in game"
            thisPlayerIndex = 0
            if self.data.games[params.gameId].metaData['gameStatus'] == 1:
                sp.cast(params.gameId, sp.int)
                if self.data.games[params.gameId].players[1] == sp.address('---'):
                     thisPlayerIndex = 1
                else:
                     thisPlayerIndex = 2
                sp.emit(thisPlayerIndex, tag="thisPlayerIndex")
                self.data.games[params.gameId].players[thisPlayerIndex] = sp.sender
                self.data.games[params.gameId].metaData['gameStatus'] = 1                
                if self.data.games[params.gameId].players[1] != sp.address('---'):
                     if self.data.games[params.gameId].players[2] != sp.address('---'):
                         self.data.games[params.gameId].metaData['gameStatus'] = 2
                         sp.emit('game Full')
                         sp.emit(self.data.games[params.gameId].players, tag='players')  
                         self.data.lockedBalance += self.data.games[params.gameId].mutezPerMove
                         self.data.games[params.gameId].gameBalance += self.data.games[params.gameId].mutezPerMove
            sp.emit(params.gameId, tag="contractUpdated")

        @sp.entry_point()    
        def leaveGame(self, params):
            '''
            '''
            #assert sp.sender == self.data.games[params.gameId].players[2], "not your money" #<--- Why this not working? 
            thisPlayerIndex = 0
            if self.data.games[params.gameId].players[1] == sp.sender:
                thisPlayerIndex = 1
            else:
                thisPlayerIndex = 2
            sp.emit(thisPlayerIndex, tag="thisPlayerIndex")
            self.data.games[params.gameId].players[thisPlayerIndex] = sp.address('---') 
            self.data.games[params.gameId].metaData['gameStatus'] = 1
            sp.emit(params.gameId, tag="contractUpdated")
            sp.send(sp.sender, self.data.games[params.gameId].mutezPerMove)
            
            self.data.games[params.gameId].gameBalance -= self.data.games[params.gameId].mutezPerMove
            self.data.lockedBalance -= self.data.games[params.gameId].mutezPerMove
            sp.emit(self.data.games[params.gameId].gameBalance, tag="gameBalance")

        @sp.entry_point()
        def makeMove(self, params):
            '''
            '''
            playerTurn = self.data.games[params.gameId].metaData["playerTurn"]
            sp.emit(playerTurn, tag='playerTurn')            
            #assert sp.sender == self.data.games[params.gameId].players[player_turn], "not playerTurn"
            #assert sp.sender == self.data.gameWon, "not your money" <--- Why this not working? 
            self.data.gameWon = 0            
            sp.emit(params.move, tag="contractUpdated")
            if self.data.games[params.gameId].metaData["gameStatus"] == 2:
                sp.cast(params.gameId, sp.int)
                sp.cast(params.move, sp.int)                
                if self.data.games[params.gameId].players[playerTurn] == sp.sender:
                    self.data.games[params.gameId].grid[params.move] = playerTurn
                    if playerTurn == 1:
                        self.data.games[params.gameId].metaData["playerTurn"] = 2
                    else:
                        self.data.games[params.gameId].metaData["playerTurn"] = 1                    
                    self.data.hasRemainingWinners = 0
                    for gameWinnningSet in self.data.game_winners.values():                        
                        self.data.setSum = 0
                        self.data.winnerHasZero = 0
                        self.data.winnerHasOne = 0
                        self.data.winnerHasTwo = 0
                        for coord in gameWinnningSet:
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
                            if self.data.winnerHasTwo == 0: # all ones
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

                    if self.data.gameWon > 0:
                        sp.emit(self.data.gameWon, tag="gameWonBy")
                        self.data.games[params.gameId].metaData["gameStatus"] = 3 # 3 is game won
                    if self.data.hasRemainingWinners == 0:
                        sp.emit('cats Game', tag="catsGame")
                        self.data.games[params.gameId].metaData["gameStatus"] = 4 # Cats Game
                else:
                    sp.emit('not Player Turn', tag="notPlayerTurnError")
            else:
                sp.emit('game not active', tag="gameNotActiveError")
                #sp.emit(params.move, tag="contractUpdated")

        @sp.entry_point()
        def claimWinnings(self, params):
            '''
            '''
            #assert sp.sender == self.data.gameWon, "not your money" <--- Why this not working? 
            if self.data.games[params.gameId].metaData["gameStatus"] == 3:
                winningPlayerIndex = self.data.games[params.gameId].metaData["winningPlayer"]               
                winningPlayer = self.data.games[params.gameId].players[winningPlayerIndex]
                sp.emit(winningPlayer, tag="winningPlayer")
                sp.emit(sp.sender, tag="sender")
                if winningPlayer == sp.sender:
                    winAmount = self.data.games[params.gameId].gameBalance
                    sp.emit(winAmount, tag='sentWinAmount')
                    sp.send(winningPlayer, winAmount)
                else:
                    sp.emit('did not Win!', tag="didNotWinError")
            else: 
                sp.emit('no Winner Yet', tag="noWinnerYetError")

       
        @sp.entry_point()
        def payoutCatsGame(self, params):
            '''
            '''
            #assert sp.sender == self.data.gameWon, "not your money" <--- Why this not working? 
            if self.data.games[params.gameId].metaData["gameStatus"] == 4:
                sendCatsGameTez = 0
                if self.data.games[params.gameId].players[1] == sp.sender:
                    sendCatsGameTez = 1
                if self.data.games[params.gameId].players[2] == sp.sender:
                    sendCatsGameTez = 1
                else: 
                    sp.emit('Requester Not in Game Cats Game', tag="notInGameCatsGame")
                if sendCatsGameTez == 1:                    
                    sp.send(self.data.games[params.gameId].players[1], self.data.games[params.gameId].mutezPerMove)
                    sp.emit(self.data.games[params.gameId].mutezPerMove, tag='sentPlayer1CatsGame')
                    sp.send(self.data.games[params.gameId].players[2], self.data.games[params.gameId].mutezPerMove)
                    sp.emit(self.data.games[params.gameId].mutezPerMove, tag='sentPlayer2CatsGame')
            else: 
                sp.emit("not Cats Game", tag="notCatsGameError")

         
        @sp.entry_point()
        def surrenderGame(self, params):
            '''
            '''
            #assert self.data.games[params.gameId].players.contains(sp.sender), "not in game"
            #assert sp.sender != self.data.games[params.gameId].players[2], 
            surrenderPlayerIndex = 0
            otherPlayerIndex = 0
            if self.data.games[params.gameId].metaData["gameStatus"] == 2:
                if self.data.games[params.gameId].players[1] == sp.sender:
                    surrenderPlayerIndex = 1
                    otherPlayerIndex = 2
                else:
                    surrenderPlayerIndex = 2
                    otherPlayerIndex = 1    
                sp.send(self.data.games[params.gameId].players[1], self.data.games[params.gameId].surrenderAmount)
                sp.emit(self.data.games[params.gameId].mutezPerMove, tag='sentPlayer1CatsGame')
                sp.send(self.data.games[params.gameId].players[2], self.data.games[params.gameId].surrenderOtherAmount)
                sp.emit(self.data.games[params.gameId].mutezPerMove, tag='sentPlayer2CatsGame')
                self.data.games[params.gameId].metaData["gameStatus"] = 5
            else: 
                sp.emit('Wrong Game Status', tag="wrongGameStatusError")

        @sp.entry_point()    
        def payAdmin(self, params):
            '''
            '''
            sp.cast(params.totalBalance, sp.mutez)
            sp.cast(sp.sender, sp.address)
            sp.emit(sp.sender,  tag='request')
            #assert sp.sender == self.data.admin, "not Admin"
            sp.emit(params.totalBalance, tag="totalBalance")
            sp.emit(self.data.lockedBalance, tag="lockedBalcn")
            #unlockedBalance = params.totalBalance - self.data.lockedBalance
            #sp.send(self.data.admin, unlockedBalance)
            #sp.emit(unlockedBalance, tag="adminPaid")





               
@sp.add_test()
def test():
    s = sp.test_scenario("my first test", main)
    player1 = sp.test_account("player1")
    player2 = sp.test_account("player2")
    player3 = sp.test_account("player3")
    player4 = sp.test_account("player4")
    #player1.set_initial_balance(sp.tez(2))
    a = main.TezTacToe(player1.address, player2.address)
    a.set_initial_balance(sp.tez(2))
    s += a
    mutezPerMoveInt = 10000
    mutezPerMove = sp.mutez(1500000)
    surrenderAmount = sp.mutez(250000)
    surrenderOtherAmount = sp.mutez(750000)
    values = [player1.address, mutezPerMove]
    a.startGame(
        _sender = player1.address, 
        _amount = mutezPerMove, 
        mutezPerMove = mutezPerMove, 
        surrenderAmount = surrenderAmount,
        surrenderOtherAmount = surrenderOtherAmount,
        playerTurn = 1, 
        gameStatus =1
    )
    a.leaveGame(_sender = player1.address, gameId=0)
    a.joinGame(_sender = player1.address, _amount = mutezPerMove,  gameId=0)
    a.joinGame(_sender = player2.address, _amount = mutezPerMove,  gameId=0)
    a.startGame(
        _sender = player1.address, 
        _amount = mutezPerMove, 
        mutezPerMove = mutezPerMove, 
        surrenderAmount = surrenderAmount,
        surrenderOtherAmount = surrenderOtherAmount,
        playerTurn = 1, 
        gameStatus =1
    )
    a.joinGame(_sender = player2.address, gameId=0)
    a.joinGame(_sender = player2.address, gameId=0)
    a.makeMove(_sender = player2.address, gameId=0, move=223)    
    a.makeMove(_sender = player1.address, gameId=0, move=141)
    a.makeMove(_sender = player2.address, gameId=0, move=122)
    a.makeMove(_sender = player1.address, gameId=0, move=141)
    a.startGame(
        _sender = player1.address, 
        mutezPerMove = mutezPerMove, 
        surrenderAmount = surrenderAmount,
        surrenderOtherAmount = surrenderOtherAmount,
        playerTurn = 1, 
        gameStatus =1
    )
    a.joinGame(_sender = player2.address, gameId=0)
    #a.claimWinnings(_sender = player1.address, gameId=0)
    #a.claimWinnings(_sender = player2.address, gameId=0)
    s.show(a.balance)    
    admin = sp.test_account("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
    a.payAdmin(_sender = admin.address, totalBalance = a.balance)
    uniqueHolders = [player1.address, player3.address, player4.address]
    uniqueHoldersCount = [0, 3, 1]
    #uniqueHoldersCount [0, 1, 2]
    #a.updateNftHolders(_sender = player1.address, uniqueHolders = uniqueHolders)#, uniqueHoldersCount = uniqueHoldersCount)
    s.show(a.balance)
    