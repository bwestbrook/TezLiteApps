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
            # Game control
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")

            # Outstanding & historical games, keyed by monotonic
            # currentGameIndex. The empty {} needs an explicit type cast so
            # the compiled storage doesn't end up with unresolved generic
            # type variables (same fix as the RandomOracle).
            self.data.games = sp.cast({}, sp.map[sp.nat, sp.record(
                hand=sp.map[sp.nat, sp.int],
                handValue=sp.map[sp.nat, sp.int],
                handHashes=sp.map[sp.nat, sp.string],
                player=sp.address,
                aceHigh=sp.int,
                gameStatus=sp.nat,
                finalBet=sp.mutez,
            )])

            self.data.currentGameIndex = sp.nat(0)
            self.data.pot = sp.mutez(100000)
            self.data.potReserve = sp.tez(0)
            self.data.ante = sp.mutez(200000)
            self.data.fee = sp.mutez(100000)

        @sp.entrypoint
        def default(self):
            '''
            '''
            self.data.potReserve += sp.amount
            pass

        @sp.entrypoint()
        def updateTxlContract(self, params):
            '''Admin-only: point the contract at a new TXL holder-fee
            contract. Previously gated on `oracle` with an `if` (silent
            no-op for non-callers) — see AD-1.5 in docs/SECURITY_FIXES.md.
            Checklist §1.1, §9.1.'''
            assert sp.sender == self.data.admin, "not admin"
            self.data.txlContract = params.newContract

        @sp.entrypoint()
        def updateOracle(self, params):
            '''Admin-only: rotate the oracle key. Previously wrote to
            `txlContract` (wrong field) so the oracle address could never
            actually be rotated — see AD-1.5 in docs/SECURITY_FIXES.md.
            Checklist §1.1, §1.3, §9.1.'''
            assert sp.sender == self.data.admin, "not admin"
            self.data.oracle = params.newOracle

        @sp.entrypoint()
        def pruneGame(self, params):
            '''Admin-only: delete a finished game record (status 3/4/5) to
            reclaim storage. Emits the full pre-prune record so off-chain
            indexers can keep history. Checklist §3.1.'''
            sp.cast(params.gameId, sp.nat)
            assert sp.sender == self.data.admin, "not admin"
            g = self.data.games[params.gameId]
            assert g.gameStatus >= 3, "game not finished"
            sp.emit(g, tag='gamePruned')
            del self.data.games[params.gameId]

        @sp.entrypoint()
        def bet(self, params):
            '''
            Player creates a game by paying ante + fee.
            '''
            # SECURITY: §2.1 — the old `assert sp.amount == sp.amount` was a
            # tautology (AD-1). Enforce the exact price so a caller can't
            # underpay the ante and still open a game.
            sp.cast(params.aceHigh, sp.int_or_nat)
            sp.cast(sp.sender, sp.address)
            sp.cast(sp.amount, sp.mutez)
            assert sp.amount == self.data.ante + self.data.fee, "must send ante + fee"
            hand = {1: -1, 2: -1, 3: -1} 
            handValue = {1: -1, 2: -1, 3: -1}
            handHashes = {1: '', 2: '', 3: ''}
            new_game = sp.record(
                hand = hand,
                handValue = handValue,
                handHashes = handHashes,
                player = sp.sender,
                aceHigh = params.aceHigh,
                gameStatus = 0,
                finalBet = sp.mutez(0)
            )
            self.data.pot += sp.amount - self.data.fee
            sp.send(self.data.txlContract, self.data.fee)
            self.data.games[self.data.currentGameIndex] = new_game
            self.data.currentGameIndex += 1                 
            sp.emit('new Game', tag='betMade')

        @sp.entrypoint()
        def firstCard(self, params):
            '''
            '''
            sp.cast(sp.sender, sp.address)
            #if sp.sender == self.data.oracle:
            sp.cast(params.gameId, sp.int_or_nat)
            sp.cast(params.card, sp.int_or_nat)
            sp.cast(params.hash, sp.string)
            cardValue = sp.to_int(params.card / 4)
            card = sp.to_int(params.card / 1)
            self.data.games[params.gameId].handValue[1] = cardValue + 2
            self.data.games[params.gameId].hand[1] = card
            self.data.games[params.gameId].handHashes[1] = params.hash
            if self.data.games[params.gameId].gameStatus == 0:
                sp.emit([params.gameId, params.card], tag='firstCard')           
            else:
                sp.emit('bad game status', tag='badGameStatus')
            #else:
                #sp.emit('notOracleADFirst2C', tag='notOracleADFirst2C')

        @sp.entrypoint()
        def secondCard(self, params):
            '''
            '''
            sp.cast(sp.sender, sp.address)
            if sp.sender == self.data.oracle:
 
                cardValue = sp.to_int(params.card / 4) + 2
                card = sp.to_int(params.card / 1)
                sp.cast(params.hash, sp.string)
                self.data.games[params.gameId].handValue[2] = cardValue
                self.data.games[params.gameId].hand[2] = card
                self.data.games[params.gameId].handHashes[2] = params.hash
                if self.data.games[params.gameId].handValue[1] == cardValue:
                    # Pair: full forfeit. Ante stays in the pot — no refund
                    # to the player, no fee skim. This is the house's
                    # compensation for the volatility on wide spreads.
                    sp.emit('pairDrawnFullForfeit', tag='pairDrawn')
                    self.data.games[params.gameId].gameStatus = 5
                else:
                    if self.data.games[params.gameId].gameStatus == 0:
                        sp.cast(params.gameId, sp.int_or_nat)
                        sp.cast(params.card, sp.int_or_nat)
                        sp.cast(sp.sender, sp.address) 
                        self.data.games[params.gameId].gameStatus = 1
                        sp.emit([params.gameId, params.card], tag='secondCard')           
                    else:
                        sp.emit('bad game status', tag='badGameStatus')
            else:
                sp.emit('notOracleADFirst2C', tag='notOracleADFirst2C')


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
                        sp.send(self.data.txlContract, self.data.fee)
                        sp.emit(self.data.pot, tag='pot')
                        if self.data.pot > sp.tez(2):
                            self.data.pot -= self.data.fee
                            self.data.potReserve += self.data.fee                            
                    else:
                        sp.emit('bad game Status', tag='badGameStatus')
                        sp.send(sp.sender, sp.amount)
                else:
                    sp.emit('Bet Too Big', tag='betTooBigError')
                    sp.send(sp.sender, sp.amount)
            else:
                sp.emit('not Player', tag='notPlayer')

     
    

        @sp.entrypoint()
        def lastCard(self, params):
            '''
            '''
            sp.cast(sp.sender, sp.address)
            sp.emit(self.data.pot, tag='startingPot')
            if sp.sender == self.data.oracle:
                if self.data.games[params.gameId].gameStatus == 2:  
                    sp.cast(params.gameId, sp.int_or_nat)
                    sp.cast(sp.sender, sp.address) 
                    sp.cast(params.card, sp.int_or_nat)
                    cardValue = sp.to_int(params.card / 4) + 2
                    card = sp.to_int(params.card / 1)
                    sp.cast(params.hash, sp.string)
                    self.data.games[params.gameId].handHashes[3] = params.hash
                    self.data.games[params.gameId].hand[3] = card
                    self.data.games[params.gameId].handValue[3] = cardValue
                    sp.cast(params.gameId, sp.int_or_nat)         
                    lowCard = self.data.games[params.gameId].handValue[1]
                    highCard = self.data.games[params.gameId].handValue[2]
                    if highCard < lowCard:
                        highCard = self.data.games[params.gameId].handValue[1]
                        lowCard = self.data.games[params.gameId].handValue[2]
                    sp.emit([lowCard, cardValue, highCard])
                    if cardValue < lowCard:                       
                        self.data.games[params.gameId].gameStatus = 4
                    if cardValue == lowCard:
                        self.data.pot -= self.data.games[params.gameId].finalBet + self.data.ante
                        sp.send(self.data.txlContract, self.data.games[params.gameId].finalBet + self.data.ante)
                        self.data.games[params.gameId].gameStatus = 4
                    if cardValue > lowCard and cardValue < highCard:
                        # True-odds payout with 5% rake.
                        #   Fair payout multiplier  = 13 / spread  (since P(win) = spread/13)
                        #   With 5% rake            = 12.35 / spread
                        # We multiply finalBet by 1235 / (100 * spread):
                        #   spread = 1   →  12.35× payout
                        #   spread = 5   →  2.47×
                        #   spread = 11  →  1.12×
                        # Tight spreads pay huge, wide ones pay slim. Player's
                        # net EV is uniformly -5% regardless of spread choice
                        # (plus the ante drag).
                        spread = sp.as_nat(highCard - lowCard - 1)
                        winAmount = sp.split_tokens(
                            self.data.games[params.gameId].finalBet,
                            1235,
                            spread * 100,
                        )
                        sp.send(self.data.games[params.gameId].player, winAmount)
                        self.data.games[params.gameId].gameStatus = 3
                        self.data.pot -= winAmount
                        sp.emit(self.data.pot, tag='finalPot')
                        sp.emit(winAmount, tag='winAmount')
                    if cardValue == highCard:
                        self.data.pot -= self.data.games[params.gameId].finalBet + self.data.ante
                        sp.send(self.data.txlContract, self.data.games[params.gameId].finalBet + self.data.ante)
                        self.data.games[params.gameId].gameStatus = 4
                    if cardValue > highCard:   
                        self.data.games[params.gameId].gameStatus = 4
                    # SECURITY: §2.2 — sp.mutez is unsigned; subtracting
                    # 125000 from a lighter potReserve raises SUB_MUTEZ and
                    # reverts the whole lastCard op, freezing the game at
                    # status 2 forever (AD-2). Only refill when the reserve
                    # can actually cover it.
                    sp.emit(self.data.pot, tag='postSettlePot')
                    if self.data.pot < sp.mutez(124999) and self.data.potReserve >= sp.mutez(125000):
                        self.data.pot += sp.mutez(125000)
                        self.data.potReserve -= sp.mutez(125000)
                        
                else:
                    sp.emit('bad Game Status', tag='badGameStatus')
            else:
                sp.emit('not Oracle', tag='notOracleLastCard')
                            

                
                
       
@sp.add_test()
def test():
    s = sp.test_scenario("my first test", main)
    player1 = sp.test_account("player1")
    a = main.AceyDuecey()
    a.set_initial_balance(sp.tez(0))
    s += a
    #s.set_initial_balance(sp.tez(2))
    player1 = sp.test_account("player1")
    player2 = sp.test_account("player2")
    oracle = a.data.oracle    
    # ante 0.2 + fee 0.1 — AD-1 now enforces the exact bet() price.
    tzMutezBet = sp.mutez(300000)
    a.data
    #a.set_initial_balance(sp.tez(2))
    s.show(a.balance)
    a.default(_amount=sp.tez(1))
    a.bet(
        _sender=player1, 
        _amount=tzMutezBet,
        aceHigh=sp.int_or_nat(1)
    )
    a.firstCard(
        _sender=oracle, 
        card = sp.int_or_nat(51),
        hash = 'adfao3',
        gameId = 0
    )
    a.secondCard(
        _sender=oracle,
        card = sp.int_or_nat(8),
        hash = 'adfayui657o3',
        gameId = 0
    )
    a.continueBet(
        _sender=player1, 
        _amount=tzMutezBet, 
        gameId = 0
    )
    a.lastCard(
        _sender=oracle, 
        gameId = 0,
        card = sp.int_or_nat(33),
        hash = 'adfeqweEQWFF3ui657o3',
    )   
    s.show(a.balance)
    a.bet(
        _sender=player1, 
        _amount=tzMutezBet,
        aceHigh=sp.int_or_nat(1)
    )

    
    a.firstCard(
        _sender=oracle, 
        card = sp.int_or_nat(30),
        
        hash = 'adfewrewrao3',
        gameId = 1
    )
    a.secondCard(
        _sender=oracle,
        card = sp.int_or_nat(8),
        hash = 'advncxvbzcx435fao3',
        gameId = 1
    )
    

    
    s.show(a.balance)
    a.continueBet(
        _sender=player1, 
        _amount=tzMutezBet, 
        gameId = 1
    )
    s.show(a.balance)
    a.lastCard(
        _sender=oracle, 
        gameId = 1,
        card = sp.int_or_nat(33),
        hash = 'adfPUIOYJDyui57o3',
    ) 
    s.show(a.balance)
    