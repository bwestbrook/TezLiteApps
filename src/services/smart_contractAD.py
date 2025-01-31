import smartpy as sp

@sp.module
def main():
    class AceyDuecey(sp.Contract):
        
        def __init__(self):
            '''
            Logic largely controlled by "gameStatus"
            0: Bet made
            1: Created and cards shown
            2: Ready for third card
            3: Game ended Win
            4: Game ended Loss
            5: Pair Drawn
            '''
            #Game Control         
            self.data.admin = sp.address("tz1XbrvTMVa5dWQQBSCn2jgX7BPZyLRhgtKS")
            self.data.txlContract = sp.address("KT1NCTnB4hYTgZvUqF5JgzTGpAtnfKSKYxwc")
            self.data.games = {}
            self.data.currentGameIndex = 0
            self.data.pot = sp.mutez(100000)   
            self.data.potReserve = sp.tez(2)
            self.data.ante = sp.mutez(125000)
            self.data.txlBalance = sp.mutez(0)
            self.data.fee = sp.mutez(100000)


        @sp.entrypoint()
        def bet(self, params):
            '''
            '''
            amount = self.data.ante + self.data.fee
            assert sp.amount == sp.amount
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
            #self.data.txlBalance += self.data.fee
            sp.send(self.data.txlContract, self.data.fee)
            self.data.games[self.data.currentGameIndex] = new_game
            self.data.currentGameIndex += 1                 
            sp.emit('new Game', tag='betMade')
            

        @sp.entrypoint()
        def firstTwoCards(self, params):
            '''
            '''
            sp.cast(sp.sender, sp.address)
            if sp.sender == self.data.admin:
                self.data.games[params.gameId].handValue[1] = params.firstCardValue
                self.data.games[params.gameId].handValue[2] = params.secondCardValue
                self.data.games[params.gameId].hand[1] = params.firstCard
                self.data.games[params.gameId].hand[2] = params.secondCard
                if params.firstCardValue == params.secondCardValue:                    
                    sp.emit('pairDraw Half Bet', tag='pairDrawn')
                    halfAmount = sp.split_tokens(self.data.ante, 1, 2)
                    sp.send(self.data.games[params.gameId].player, halfAmount)
                    sp.send(self.data.txlContract, halfAmount)
                    self.data.pot -= halfAmount
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
            else:
                sp.emit('notAdmin', tag='notAdmin')


        @sp.entrypoint()
        def continueBet(self, params):
            '''
            '''
            # Need a lock on contract during final bet
            sp.cast(sp.sender, sp.address)
            if self.data.games[params.gameId].player == sp.sender:
                if sp.amount - self.data.fee <= self.data.pot:                
                    if self.data.games[params.gameId].gameStatus == 1:                        
                        self.data.games[params.gameId].gameStatus = 2
                        sp.cast(params.gameId, sp.int_or_nat)
                        sp.cast(sp.amount, sp.mutez)
                        sp.cast(sp.sender, sp.address)
                        self.data.games[params.gameId].finalBet = sp.amount - self.data.fee
                        self.data.pot += sp.amount - self.data.fee
                        self.data.txlBalance += self.data.fee
                        sp.emit(self.data.pot, tag='pot')
                        if self.data.pot > sp.tez(2):
                            self.data.pot -= self.data.fee
                            self.data.potReserve += self.data.fee
                            
                    else:
                        sp.emit('bad game Status', tag='badGameStatus')
                        sp.send(sp.sender, sp.amount)
                else:
                    sp.emit('Bet Too Big', tag='betTooBigError')
            else:
                sp.emit('not Player', tag='notPlayer')

     
        @sp.entrypoint
        def default(self):
            pass

        @sp.entrypoint()
        def lastCard(self, params):
            '''
            '''
            # verify sender is game owner 
            sp.cast(sp.sender, sp.address)
            #assert sp.sender == self.data.admin
            sp.emit(self.data.pot, tag='startingPot')
            if sp.sender == self.data.admin:
                if self.data.games[params.gameId].gameStatus == 2:  
                    sp.cast(params.gameId, sp.int_or_nat)
                    sp.cast(sp.sender, sp.address) 
                    self.data.games[params.gameId].hand[3] = params.lastCard            
                    self.data.games[params.gameId].handValue[3] = params.lastCardValue
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
                        winAmount = self.data.games[params.gameId].finalBet
                        winAmount = sp.split_tokens(winAmount, 2, 1)
                        sp.send(self.data.games[params.gameId].player, winAmount) 
                        self.data.games[params.gameId].gameStatus = 3 
                        
                        self.data.pot -= winAmount
                        sp.emit(self.data.pot, tag='finalPot')
                        sp.emit(winAmount, tag='winAmount')
                    if params.lastCardValue == highCard:
                        self.data.pot -= self.data.games[params.gameId].finalBet + self.data.ante
                        self.data.txlBalance += self.data.games[params.gameId].finalBet + self.data.ante
                        self.data.games[params.gameId].gameStatus = 4
                    if params.lastCardValue > highCard:   
                        self.data.games[params.gameId].gameStatus = 4
                    sp.emit(self.data.pot)
                    if self.data.pot < sp.mutez(124999):
                        self.data.pot += sp.mutez(125000)
                        self.data.potReserve -= sp.mutez(125000)
                        
                else:
                    sp.emit('bad Game Status', tag='badGameStatus')
            else:
                sp.emit('not Admin', tag='notAdmin')
                            

                
                   
    


       
@sp.add_test()
def test():
    s = sp.test_scenario("my first test", main)
    player1 = sp.test_account("player1")
    a = main.AceyDuecey()
    a.set_initial_balance(sp.tez(2))
    s += a
    #s.set_initial_balance(sp.tez(2))
    player1 = sp.test_account("player1")
    player2 = sp.test_account("player2")
    admin = a.data.admin    
    tzMutezBet = sp.mutez(250000)
    a.data
    #a.set_initial_balance(sp.tez(2))
    s.show(a.balance)
    a.default(_amount=sp.tez(1))
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
        secondCardValue = sp.int_or_nat(3),
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
        lastCardValue = sp.int_or_nat(5)
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
    
    s.show(a.balance)
    a.continueBet(
        _sender=player1, 
        _amount=sp.mutez(500000), 
        gameId = 1
    )
    s.show(a.balance)
    a.lastCard(
        _sender=admin, 
        gameId = 1,
        lastCard = sp.int_or_nat(33),
        lastCardValue = sp.int_or_nat(7)
    ) 
    s.show(a.balance)
    