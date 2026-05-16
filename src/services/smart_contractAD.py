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
        def updateAdmin(self, params):
            '''Admin-only: rotate the admin key. Two-step would be safer;
            for now, single-step. If the admin key is lost or compromised
            this is the only recovery path, so call it deliberately.
            Checklist §1.2.'''
            sp.cast(params.newAdmin, sp.address)
            assert sp.sender == self.data.admin, "not admin"
            self.data.admin = params.newAdmin

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
        def bet(self):
            '''
            Player creates a game by paying ante + fee. Aces are always
            high (rank 14) — there is no low-Ace mode.
            '''
            # SECURITY: §2.1 — the old `assert sp.amount == sp.amount` was a
            # tautology (AD-1). Enforce the exact price so a caller can't
            # underpay the ante and still open a game.
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
            '''Player commits an Acey-Duecey bet on the dealt anchors.

            The bet is added to the pot and the holder fee is paid out.
            The contract enforces a SPREAD-AWARE ceiling: the worst-case
            payout for this game's actual spread (bet * 1235 / (spread
            * 100)) must still fit in the pot+bet available at
            lastCard. Without this guard a tight-spread game (e.g.
            spread=1 with a 12.35x payout) could request more than the
            pot can pay and revert the lastCard SUB_MUTEZ, freezing
            the game forever at status 2.
            '''
            sp.cast(sp.sender, sp.address)
            if self.data.games[params.gameId].player == sp.sender:
                if self.data.games[params.gameId].gameStatus == 1:
                    bet = sp.amount - self.data.fee
                    # Spread for THIS game — both anchors are guaranteed
                    # to be set when gameStatus == 1 (secondCard advances
                    # to 1 only after writing handValue[2]).
                    lowCard = self.data.games[params.gameId].handValue[1]
                    highCard = self.data.games[params.gameId].handValue[2]
                    if highCard < lowCard:
                        lowCard = self.data.games[params.gameId].handValue[2]
                        highCard = self.data.games[params.gameId].handValue[1]
                    spread = sp.as_nat(highCard - lowCard - 1)
                    # max payout = bet * 1235 / (spread * 100). pot grows
                    # by `bet` in this entrypoint, so the lastCard pool
                    # is (pot + bet); the worst-case payout must fit in
                    # that. Spread-aware: tight spreads cap the bet
                    # MUCH lower than the old `bet <= pot` rule did.
                    maxPayout = sp.split_tokens(bet, 1235, spread * 100)
                    if maxPayout <= self.data.pot + bet:
                        self.data.games[params.gameId].gameStatus = 2
                        sp.cast(params.gameId, sp.int_or_nat)
                        sp.cast(sp.amount, sp.mutez)
                        sp.cast(sp.sender, sp.address)
                        self.data.games[params.gameId].finalBet = bet
                        self.data.pot += bet
                        sp.send(self.data.txlContract, self.data.fee)
                        sp.emit(self.data.pot, tag='pot')
                        if self.data.pot > sp.tez(2):
                            self.data.pot -= self.data.fee
                            self.data.potReserve += self.data.fee
                    else:
                        sp.emit('Bet Too Big', tag='betTooBigError')
                        sp.send(sp.sender, sp.amount)
                else:
                    sp.emit('bad game Status', tag='badGameStatus')
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
                        # Defense in depth: clamp to pot so the SUB_MUTEZ
                        # below never reverts. continueBet's spread-aware
                        # ceiling already guarantees this, but if that
                        # guard is ever bypassed (admin upgrade, parameter
                        # tweak, off-by-one), without this clamp the game
                        # would freeze at status 2 forever. Player gets a
                        # short payout in the rare bypass case, but they
                        # always get something and the game settles.
                        if winAmount > self.data.pot:
                            winAmount = self.data.pot
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
    """Exhaustive gameplay emulation.

    Plays through every final-status path AD can reach plus the new
    spread-aware bet ceiling. Each scenario asserts the post-condition
    (game status, pot delta), so a regression in payout / branching
    will trip s.verify() and fail the scenario.

    Card-index → rank: rank = (idx // 4) + 2, so:
       idx  0..3   → 2 ·  idx  4..7   → 3 ·  idx  8..11 → 4
       idx 16..19 → 6 ·  idx 20..23  → 7 ·  idx 24..27 → 8
       idx 28..31 → 9 ·  idx 48..51  → A (14)

    Game IDs are monotonic; we increment by hand to keep verify()
    readable.
    """
    s = sp.test_scenario("AD payout exhaustion", main)
    player = sp.test_account("player1")
    a = main.AceyDuecey()
    a.set_initial_balance(sp.tez(0))
    s += a
    oracle = a.data.oracle
    BET = sp.mutez(300000)   # ante (0.2) + fee (0.1)

    # Seed the pot reserve so refills are available throughout. The
    # default entrypoint credits potReserve, not pot — pot stays at the
    # 0.1 tez init value through this until games push it up.
    a.default(_amount=sp.tez(10))

    # ─── 1. PAIR (status 5) ─────────────────────────────────────────
    s.h2("1. PAIR — cards 1+2 match, ante forfeit to pot")
    a.bet(_sender=player, _amount=BET)
    a.firstCard(_sender=oracle, card=sp.int_or_nat(20), gameId=0, hash="g0c1")  # 7
    a.secondCard(_sender=oracle, card=sp.int_or_nat(23), gameId=0, hash="g0c2") # 7
    s.verify(a.data.games[0].gameStatus == 5)
    # init pot 100000 + ante 200000, no extra movement on pair.
    s.verify(a.data.pot == sp.mutez(300000))

    # ─── 2. WIN (status 3) ──────────────────────────────────────────
    s.h2("2. WIN — third lands strictly inside")
    # anchors 4 and 14 → spread = 9 → payout = bet * 12.35 / 9 ≈ 1.37x
    a.bet(_sender=player, _amount=BET)
    a.firstCard(_sender=oracle, card=sp.int_or_nat(8), gameId=1, hash="g1c1")   # 4
    a.secondCard(_sender=oracle, card=sp.int_or_nat(48), gameId=1, hash="g1c2") # 14
    a.continueBet(_sender=player, _amount=BET, gameId=1)
    a.lastCard(_sender=oracle, gameId=1, card=sp.int_or_nat(30), hash="g1c3")   # 9 → win
    s.verify(a.data.games[1].gameStatus == 3)
    # +ante +bet -winAmount where winAmount = 200000 * 1235 / 900 = 274,444.
    # Pot was 300000 going in. 300000 + 200000 + 200000 - 274444 = 425,556.
    s.verify(a.data.pot == sp.mutez(425556))

    # ─── 3. LOSS_UNDER (status 4) ───────────────────────────────────
    s.h2("3. LOSS — third below low anchor (no extra transfer)")
    a.bet(_sender=player, _amount=BET)
    a.firstCard(_sender=oracle, card=sp.int_or_nat(20), gameId=2, hash="g2c1")  # 7
    a.secondCard(_sender=oracle, card=sp.int_or_nat(48), gameId=2, hash="g2c2") # 14
    a.continueBet(_sender=player, _amount=BET, gameId=2)
    a.lastCard(_sender=oracle, gameId=2, card=sp.int_or_nat(4), hash="g2c3")    # 3 → under
    s.verify(a.data.games[2].gameStatus == 4)
    # +ante +bet, no payout (loss-under doesn't touch pot beyond accepting).
    s.verify(a.data.pot == sp.mutez(425556 + 400000))   # 825,556

    # ─── 4. LOSS_OVER (status 4) ────────────────────────────────────
    s.h2("4. LOSS — third above high anchor (no extra transfer)")
    a.bet(_sender=player, _amount=BET)
    a.firstCard(_sender=oracle, card=sp.int_or_nat(4), gameId=3, hash="g3c1")   # 3
    a.secondCard(_sender=oracle, card=sp.int_or_nat(20), gameId=3, hash="g3c2") # 7
    a.continueBet(_sender=player, _amount=BET, gameId=3)
    a.lastCard(_sender=oracle, gameId=3, card=sp.int_or_nat(48), hash="g3c3")   # 14 → over
    s.verify(a.data.games[3].gameStatus == 4)
    # +ante +bet, no payout (loss-over mirrors loss-under).
    s.verify(a.data.pot == sp.mutez(825556 + 400000))   # 1,225,556

    # ─── 5. RAIL_LOW (status 4 + bet+ante → txlContract) ────────────
    s.h2("5. RAIL_LOW — third == low anchor")
    a.bet(_sender=player, _amount=BET)
    a.firstCard(_sender=oracle, card=sp.int_or_nat(20), gameId=4, hash="g4c1")  # 7
    a.secondCard(_sender=oracle, card=sp.int_or_nat(48), gameId=4, hash="g4c2") # 14
    a.continueBet(_sender=player, _amount=BET, gameId=4)
    a.lastCard(_sender=oracle, gameId=4, card=sp.int_or_nat(22), hash="g4c3")   # 7 == low
    s.verify(a.data.games[4].gameStatus == 4)
    # +ante +bet then -(bet+ante) to txlContract — net pot change = 0.
    s.verify(a.data.pot == sp.mutez(1225556))

    # ─── 6. RAIL_HIGH (status 4 + bet+ante → txlContract) ───────────
    s.h2("6. RAIL_HIGH — third == high anchor")
    a.bet(_sender=player, _amount=BET)
    a.firstCard(_sender=oracle, card=sp.int_or_nat(20), gameId=5, hash="g5c1")  # 7
    a.secondCard(_sender=oracle, card=sp.int_or_nat(48), gameId=5, hash="g5c2") # 14
    a.continueBet(_sender=player, _amount=BET, gameId=5)
    a.lastCard(_sender=oracle, gameId=5, card=sp.int_or_nat(50), hash="g5c3")   # 14 == high
    s.verify(a.data.games[5].gameStatus == 4)
    # rail-high mirrors rail-low — net pot change = 0.
    s.verify(a.data.pot == sp.mutez(1225556))

    # ─── 7. BET_TOO_BIG — spread-aware cap rejects huge tight-spread bet
    # Use spread=1 (anchors ranks 7 and 9). 0.2 tez bet would request
    # 12.35× = 2.47 tez payout. Pot won't have that. The contract
    # should reject with 'Bet Too Big' and refund the amount; gameStatus
    # stays at 1 (continueBet didn't advance it).
    s.h2("7. BET_TOO_BIG — spread-1 bet over the pot's headroom rejected")
    a.bet(_sender=player, _amount=BET)
    a.firstCard(_sender=oracle, card=sp.int_or_nat(20), gameId=6, hash="g6c1")  # 7
    a.secondCard(_sender=oracle, card=sp.int_or_nat(28), gameId=6, hash="g6c2") # 9 → spread 1
    # 0.5 tez bet on spread 1 → maxPayout ≈ 6.17 tez, pot ≪ that → reject.
    a.continueBet(_sender=player, _amount=sp.mutez(500000), gameId=6)
    s.verify(a.data.games[6].gameStatus == 1)   # still at 1 — bet refused
    # The ante from bet() was already added, so pot grew by 200000.
    # Rejected continueBet refunded the amount; no pot change there.
    s.verify(a.data.pot == sp.mutez(1225556 + 200000))   # 1,425,556

    # Now a TIGHT-but-acceptable bet on the same spread-1 game: small
    # enough that maxPayout fits in pot+bet. Should advance to status 2.
    s.h2("7b. spread-1 bet within the cap should be accepted")
    a.continueBet(_sender=player, _amount=sp.mutez(120000), gameId=6)  # bet = 20k
    s.verify(a.data.games[6].gameStatus == 2)
    s.verify(a.data.pot == sp.mutez(1425556 + 20000))    # 1,445,556
