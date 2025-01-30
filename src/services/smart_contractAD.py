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
            self.data.admin = sp.address("tz1grSQDByRpnVs7sPtaprNZRp531ZKz6Jmm")
            self.data.txlContract = sp.address("KT1NCTnB4hYTgZvUqF5JgzTGpAtnfKSKYxwc")
            self.data.games = {}
            self.data.currentGameIndex = 0
            self.data.pot = sp.mutez(0)            
            self.data.ante = sp.mutez(500000)
            self.data.txlBalance = sp.mutez(0)
            self.data.fee = sp.mutez(100000)

        @sp.entrypoint()
        def bet(self, params):
            '''
            '''
            amount = self.data.ante + self.data.fee
            assert sp.amount == amount
            sp.cast(sp.sender, sp.address)
            sp.cast(sp.amount, sp.mutez)
            sp.cast(params.aceHigh, sp.int_or_nat)
            hand = {1: -1, 2: -1, 3: -1} 
            handValue = {1: -1, 2: -1, 3: -1}
            new_game = sp.record(
                hand = hand,
                handValue = handValue,
                player = sp.sender,
                aceHigh = params.aceHigh,
                gameStatus = 0,
                finalBet = sp.mutez(0)
            )  
            self.data.pot += sp.amount - self.data.fee
            self.data.txlBalance += self.data.fee
            self.data.games[self.data.currentGameIndex] = new_game
            self.data.currentGameIndex += 1
            sp.emit('new Game', tag='betMade')

        @sp.entrypoint()
        def firstTwoCards(self, params):
            '''
            '''
            #assert sp.sender == self.data.admin
            self.data.games[params.gameId].handValue[1] = params.firstCardValue
            self.data.games[params.gameId].handValue[2] = params.secondCardValue
            self.data.games[params.gameId].hand[1] = params.firstCard
            self.data.games[params.gameId].hand[2] = params.secondCard
            if params.firstCardValue == params.secondCardValue:                    
                sp.emit('pairDraw Half Bet', tag='pairDrawn')
                halfAmount = sp.split_tokens(self.data.ante, 1, 2)
                sp.send(sp.sender, halfAmount)
                self.data.pot -= self.data.ante - self.data.fee
                self.data.txlBalance += halfAmount
                self.data.games[params.gameId].gameStatus = 5  
            else:
                if self.data.games[params.gameId].gameStatus == 0:
                    sp.cast(params.gameId, sp.int_or_nat)
                    sp.cast(params.firstCard, sp.int_or_nat)
                    sp.cast(params.secondCard, sp.int_or_nat)
                    sp.cast(params.firstCardValue, sp.int_or_nat)
                    sp.cast(params.secondCardValue, sp.int_or_nat)
                    sp.cast(sp.sender, sp.address) 
                    self.data.games[params.gameId].gameStatus = 1
                    sp.emit([params.gameId, params.firstCard, params.secondCard], tag='firstTwoCards')           
                else:
                    sp.emit('bad game status', tag='badGameStatus')


        @sp.entrypoint()
        def continueBet(self, params):
            '''
            '''
            # Need a lock on contract during final bet
            #assert self.data.games[params.gameId].player == sp.sender
    
            if self.data.games[params.gameId].gameStatus == 1:    
                
                self.data.games[params.gameId].gameStatus = 2
                sp.cast(params.gameId, sp.int_or_nat)
                sp.cast(sp.amount, sp.mutez)
                sp.cast(sp.sender, sp.address)
                self.data.games[params.gameId].finalBet = sp.amount - self.data.fee
                self.data.pot += sp.amount - self.data.fee
                self.data.txlBalance += self.data.fee
            else:
                sp.emit('bad game Status', tag='badGameStatus')
                sp.send(sp.sender, sp.amount)

        @sp.entrypoint()
        def lastCard(self, params):
            '''
            '''
            # verify sender is game owner 
            # assert sp.sender == self.data.admin
            if self.data.games[params.gameId].gameStatus == 2:   
                sp.cast(params.gameId, sp.int_or_nat)
                sp.cast(sp.sender, sp.address) 
                self.data.games[params.gameId].hand[3] = params.lastCard            
                self.data.games[params.gameId].handValue[3] = params.lastCardValue
                sp.emit([params.gameId, params.lastCard], tag='lastCard')
                sp.cast(params.gameId, sp.int_or_nat)         
                lowCard = self.data.games[params.gameId].handValue[1]
                highCard = self.data.games[params.gameId].handValue[2]
                if params.lastCardValue < lowCard:                       
                    self.data.games[params.gameId].gameStatus = 4
                if params.lastCardValue == lowCard:
                    self.data.pot -= self.data.games[params.gameId].finalBet + self.data.ante
                    self.data.txlBalance += self.data.games[params.gameId].finalBet + self.data.ante
                    self.data.games[params.gameId].gameStatus = 4
                if params.lastCardValue > lowCard and params.lastCardValue < highCard:         
                    sp.emit('win in', tag='winIn')
                    winAmount = self.data.ante + self.data.games[params.gameId].finalBet
                    sp.send(self.data.games[params.gameId].player, winAmount) 
                    self.data.games[params.gameId].gameStatus = 3 
                    self.data.pot -= winAmount
                if params.lastCardValue == highCard:
                    self.data.pot -= self.data.games[params.gameId].finalBet + self.data.ante
                    self.data.txlBalance += self.data.games[params.gameId].finalBet + self.data.ante
                    self.data.games[params.gameId].gameStatus = 4
                if params.lastCardValue > highCard:   
                    self.data.games[params.gameId].gameStatus = 4
                sp.emit(self.data.txlBalance)
                sp.emit(self.data.pot)
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
    admin = a.data.admin    
    tzMutezBet = sp.mutez(600000)
    
    a.bet(
        _sender=player1, 
        _amount=tzMutezBet,
        aceHigh=sp.int_or_nat(1)
    )
    a.firstTwoCards(
        _sender=admin, 
        firstCard = sp.int_or_nat(30),
        secondCard = sp.int_or_nat(8),
        firstCardValue = sp.int_or_nat(3),
        secondCardValue = sp.int_or_nat(4),
        gameId = 0
    )
    a.continueBet(
        _sender=player1, 
        _amount=tzMutezBet, 
        gameId = 0
    )
    a.lastCard(
        _sender=admin, 
        gameId = 0,
        lastCard = sp.int_or_nat(33),
        lastCardValue = sp.int_or_nat(3)
    )   
    s.show(a.balance)
    a.bet(
        _sender=player1, 
        _amount=tzMutezBet,
        aceHigh=sp.int_or_nat(1)
    )
    a.firstTwoCards(
        _sender=admin, 
        firstCard = sp.int_or_nat(2),
        secondCard = sp.int_or_nat(13),
        firstCardValue = sp.int_or_nat(3),
        secondCardValue = sp.int_or_nat(8),
        gameId = 1
    )   
    a.continueBet(
        _sender=player1, 
        _amount=tzMutezBet, 
        gameId = 1
    )
    a.lastCard(
        _sender=admin, 
        gameId = 0,
        lastCard = sp.int_or_nat(33),
        lastCardValue = sp.int_or_nat(8)
    )  
    s.show(a.balance)
    