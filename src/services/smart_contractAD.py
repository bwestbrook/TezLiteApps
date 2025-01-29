import smartpy as sp

@sp.module
def main():
    class AceyDuecey(sp.Contract):
        
        def __init__(self):
            '''
            Logic largely controlled by "gameStatus"
            1: Created and cards shown
            2: Ready for third card
            3: Game ended Win
            4: Game ended Loss
            5: Pair Drawn
            '''
            #Game Control         
            self.data.admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
            self.data.txlContract = sp.address("KT1NCTnB4hYTgZvUqF5JgzTGpAtnfKSKYxwc")
            self.data.games = {}
            self.data.currentGameIndex = 0
            self.data.pot = sp.mutez(0)

        @sp.entrypoint()
        def bet(self):
            '''
            '''
            #verify bet less than pot 
            sp.cast(sp.sender, sp.address)
            sp.cast(sp.amount, sp.mutez)
            hand = {1: -1, 2: -2, 3: -1}            
            new_game = sp.record(
                hand = hand,
                player = sp.sender,
                tzGameBalance = sp.amount,
                gameStatus = 0
            )  
            self.data.pot += sp.amount
            self.data.games[self.data.currentGameIndex] = new_game
            self.data.currentGameIndex += 1
            sp.emit('new Game', tag='betMade')

        @sp.entrypoint()
        def firstTwoCards(self, params):
            '''
            '''
            # verify sender is game owner 
            if self.data.games[params.gameId].gameStatus == 0:
                sp.cast(params.gameId, sp.int_or_nat)
                sp.cast(params.firstCard, sp.int_or_nat)
                sp.cast(params.secondCard, sp.int_or_nat)
                sp.cast(sp.sender, sp.address) 
                self.data.games[params.gameId].hand[1] = params.firstCard
                self.data.games[params.gameId].hand[2] = params.secondCard
                sp.emit([params.gameId, params.firstCard, params.secondCard], tag='firstTwoCards')
                
                if params.firstCard == params.secondCard:                    
                    sp.emit('pairDraw Half Bet', tag='pairDrawn')
                    halfAmount = sp.split_tokens(sp.amount, 1, 2)
                    sp.send(sp.sender, halfAmount)
                    sp.send(self.data.txlContract, halfAmount)
                    self.data.pot -= halfAmount
                    self.data.games[params.gameId].tzGameBalance -= sp.amount
                    self.data.games[params.gameId].gameStatus = 5
                else:
                    self.data.games[params.gameId].gameStatus = 1
            else:
                sp.emit('bad game status', tag='badGameStatus')

        @sp.entrypoint()
        def continueBet(self, params):
            '''
            '''
            # Need a lock on contract during final bet
            if self.data.games[params.gameId].gameStatus == 1:    
                self.data.games[params.gameId].gameStatus = 2
                sp.cast(params.gameId, sp.int_or_nat)
                sp.cast(sp.amount, sp.mutez)
                sp.cast(sp.sender, sp.address)
                self.data.games[params.gameId].tzGameBalance += sp.amount
                self.data.pot += sp.amount
            else:
                sp.emit('bad game Status', tag='badGameStatus')

        @sp.entrypoint()
        def lastCard(self, params):
            '''
            '''
            # verify sender is game owner 
            if self.data.games[params.gameId].gameStatus == 2:                           
                sp.cast(params.gameId, sp.int_or_nat)
                sp.cast(sp.sender, sp.address) 
                self.data.games[params.gameId].hand[3] = params.lastCard
                sp.emit([params.gameId, params.lastCard], tag='lastCard')
                sp.cast(params.gameId, sp.int_or_nat)         
                lowCard = self.data.games[params.gameId].hand[1]
                highCard = self.data.games[params.gameId].hand[2]
                if params.lastCard < lowCard:   
                    self.data.pot += sp.amount
                    self.data.games[params.gameId].gameStatus = 4
                if params.lastCard == lowCard:
                    self.data.pot -= sp.amount
                    sp.send(self.data.txlContract, sp.amount)
                    self.data.games[params.gameId].gameStatus = 4
                if params.lastCard > lowCard and params.lastCard < highCard:         
                    sp.emit('win in', tag='winIn')
                    sp.send(self.data.games[params.gameId].player, self.data.games[params.gameId].tzGameBalance) 
                    self.data.games[params.gameId].gameStatus = 3 
                    sp.data.pot -= self.data.games[params.gameId].tzGameBalance
                if params.lastCard == highCard:
                    self.data.pot -= sp.amount
                    sp.send(self.data.txlContract, sp.amount)
                    self.data.games[params.gameId].gameStatus = 4
                if params.lastCard > highCard:   
                    self.data.pot += sp.amount
                    self.data.games[params.gameId].gameStatus = 4
            else:
                sp.emit('bad Game Status', tag='badGameStatus')
                            

                
                   
    


       
@sp.add_test()
def test():
    s = sp.test_scenario("my first test", main)
    player1 = sp.test_account("player1")
    a = main.AceyDuecey()
    s += a
    #a.set_initial_balance(sp.tez(2))
    player1 = sp.test_account("player1")
    player2 = sp.test_account("player2")
    player3 = sp.test_account("player3")

    tzMutezBet = sp.mutez(1000000)
    
    a.bet(
        _sender=player1, 
        _amount=tzMutezBet
    )
    a.firstTwoCards(
        _sender=player1, 
        firstCard = sp.int_or_nat(3),
        secondCard = sp.int_or_nat(8),
        gameId = 0
    )
    a.continueBet(
        _sender=player1, 
        _amount=tzMutezBet, 
        gameId = 0
    )
    a.lastCard(
        _sender=player1, 
        lastCard = sp.int_or_nat(5),
        gameId = 0
    )   
    s.show(a.balance)
    a.bet(
        _sender=player1, 
        _amount=tzMutezBet
    )
    a.firstTwoCards(
        _sender=player1, 
        firstCard = sp.int_or_nat(2),
        secondCard = sp.int_or_nat(13),
        gameId = 1
    )   

    a.continueBet(
        _sender=player1, 
        _amount=tzMutezBet, 
        gameId = 1
    )
    a.lastCard(
        _sender=player1, 
        lastCard = sp.int_or_nat(9),
        gameId = 0
    )  
    s.show(a.balance)
    