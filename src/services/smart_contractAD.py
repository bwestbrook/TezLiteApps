import smartpy as sp

# ──────────────────────────────────────────────────────────────────────────────
# Acey-Duecey (a.k.a. In-Between) — v3 commit-reveal randomness.
#
# Cards no longer come from an oracle-only entrypoint pair (firstCard /
# secondCard / lastCard with sp.sender == self.data.oracle gate). Instead
# this contract is a CONSUMER of the RandomOracle service (KT1…). Two
# phases drive the deal:
#
#   bet(userNonce, commitId)
#     → record game in status 0
#     → call oracle.requestRandom for nRandoms=2, maxValue=51
#       — userNonce flows through; callbackContext = pack({gameId, phase=0})
#     → game stays at status 0 until the oracle reveals + fulfills
#
#   onRandomFulfilled(requestId, randomValues, callbackContext)
#     → unpack callbackContext → (gameId, phase)
#     → phase 0 (firstCards): fill hand[1], hand[2]. Pair → status 5
#       (ante forfeit). Otherwise status → 1.
#     → phase 1 (lastCard): fill hand[3], settle, status → 3/4.
#
#   continueBet(gameId, userNonce, commitId)
#     → player sees status 1, accepts the spread, posts the bet
#     → spread-aware bet ceiling check (unchanged from v2)
#     → call oracle.requestRandom for nRandoms=1, maxValue=51
#       — userNonce flows through; callbackContext = pack({gameId, phase=1})
#     → status → 2 until onRandomFulfilled (lastCard phase) lands
#
# Why: pre-v3, the oracle key was trusted to pick any card value it wanted —
# AD's trust model was "this single key is honest." v3 removes that trust
# via the commit-reveal scheme documented in docs/V3_COMMIT_REVEAL.md.
# AD's contract here is exactly the integration pattern shown in
# smart_contract_oracle_reference.py, scaled up to two requests per game.
#
# Player UX delta:
#   - bet() takes (userNonce, commitId) and an extra `oracleFee` mutez.
#   - continueBet() takes (userNonce, commitId) plus the same oracleFee.
#   - Card dealing is async — the dApp shows "awaiting oracle…" while
#     the worker reveals the commit and fulfills the request.
# ──────────────────────────────────────────────────────────────────────────────


@sp.module
def main():
    class AceyDuecey(sp.Contract):

        def __init__(self):
            '''
            gameStatus state machine:
              0 = bet placed, awaiting first-cards oracle fulfillment
              1 = first cards dealt, awaiting player's continueBet
              2 = continueBet placed, awaiting last-card oracle fulfillment
              3 = settled win
              4 = settled loss
              5 = pair drawn on initial deal → ante forfeit, no continueBet
            '''
            # ── Roles + wiring ────────────────────────────────────────────
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            # v3: RandomOracle KT1 (placeholder — admin rotates via
            # updateOracleContract). All randomness flows through here.
            self.data.oracleContract = sp.address("KT19V1YiyPtyCbxouhyeM96SekRTVC7Gw6qq")
            # Per-request mutez forwarded to oracle.requestRandom. Must be
            # >= live RandomOracle.fee. Tunable via updateOracleFee.
            self.data.oracleFee = sp.mutez(100000)

            # Per-game record. v3 adds:
            #   userNonce              — player entropy attached at bet time
            #   pendingFirstCardsReq   — oracle requestId for the bet-time deal
            #   pendingLastCardReq     — oracle requestId for the lastCard deal
            # We DO NOT zero pending* after fulfillment — the gameStatus
            # state machine prevents double-fulfillment, and keeping the IDs
            # lets off-chain audit correlate to the oracle's request log.
            self.data.games = sp.cast({}, sp.map[sp.nat, sp.record(
                hand=sp.map[sp.nat, sp.int],
                handValue=sp.map[sp.nat, sp.int],
                handHashes=sp.map[sp.nat, sp.string],
                player=sp.address,
                gameStatus=sp.nat,
                finalBet=sp.mutez,
                userNonce=sp.bytes,
                pendingFirstCardsReq=sp.nat,
                pendingLastCardReq=sp.nat,
            )])

            self.data.currentGameIndex = sp.nat(0)
            self.data.pot = sp.tez(5)
            self.data.potReserve = sp.tez(10)
            self.data.ante = sp.mutez(200000)
            self.data.fee = sp.mutez(100000)

        # ── Funding ────────────────────────────────────────────────────────
        @sp.entrypoint
        def default(self):
            self.data.potReserve += sp.amount

        # ── Admin ──────────────────────────────────────────────────────────
        @sp.entrypoint()
        def updateAdmin(self, params):
            '''Admin-only: rotate the admin key. Single-step recovery path.
            Checklist §1.1, §1.2.'''
            sp.cast(params.newAdmin, sp.address)
            assert sp.sender == self.data.admin, "not admin"
            self.data.admin = params.newAdmin

        @sp.entrypoint()
        def updateTxlContract(self, params):
            '''Admin-only: point the holder-fee contract elsewhere.
            Checklist §1.1, §9.1.'''
            assert sp.sender == self.data.admin, "not admin"
            self.data.txlContract = params.newContract

        @sp.entrypoint()
        def updateOracleContract(self, params):
            '''Admin-only: rotate the RandomOracle KT1. v3.
            Checklist §1.1, §9.1.'''
            sp.cast(params.newOracle, sp.address)
            assert sp.sender == self.data.admin, "not admin"
            self.data.oracleContract = params.newOracle

        @sp.entrypoint()
        def updateOracleFee(self, params):
            '''Admin-only: tune the per-request mutez forwarded to the
            oracle. Must stay >= live RandomOracle.fee. v3.
            Checklist §1.1.'''
            sp.cast(params.newFee, sp.mutez)
            assert sp.sender == self.data.admin, "not admin"
            self.data.oracleFee = params.newFee

        @sp.entrypoint()
        def pruneGame(self, params):
            '''Admin-only: delete a finished game record (status 3/4/5) to
            reclaim storage. Emits the pre-prune record for indexers.
            Checklist §3.1, §8.3.'''
            sp.cast(params.gameId, sp.nat)
            assert sp.sender == self.data.admin, "not admin"
            g = self.data.games[params.gameId]
            assert g.gameStatus >= 3, "game not finished"
            sp.emit(g, tag='gamePruned')
            del self.data.games[params.gameId]

        # ── Lifecycle ──────────────────────────────────────────────────────
        @sp.entrypoint()
        def bet(self, params):
            '''Player creates a game. Pays ante + holder fee + oracle fee.
            Forwards a 2-card randomness request to the RandomOracle. The
            cards land asynchronously via onRandomFulfilled (phase 0).

            v3 vs v2:
              - Takes (userNonce: bytes, commitId: nat) — mixed into the
                oracle's seed so the operator cannot pre-pick a preimage
                that favors any specific game.
              - Requires sp.amount == ante + fee + oracleFee (was ante + fee).
              - No more firstCard/secondCard entrypoints — the deal happens
                in onRandomFulfilled when the bound commit gets revealed.
            Checklist §1.1, §1.4, §2.1, §3.3, §6.1, §6.2, §7.2, §8.3.'''
            sp.cast(params.userNonce, sp.bytes)
            sp.cast(params.commitId, sp.nat)
            sp.cast(sp.sender, sp.address)
            sp.cast(sp.amount, sp.mutez)
            assert sp.amount == self.data.ante + self.data.fee + self.data.oracleFee, "must send ante + fee + oracleFee"

            # Bookkeeping: ante → pot, holder fee → txl. oracleFee flows
            # into the sp.transfer to requestRandom below.
            self.data.pot += self.data.ante
            sp.send(self.data.txlContract, self.data.fee)

            gameId = self.data.currentGameIndex
            hand = {1: -1, 2: -1, 3: -1}
            handValue = {1: -1, 2: -1, 3: -1}
            handHashes = {1: '', 2: '', 3: ''}
            new_game = sp.record(
                hand=hand,
                handValue=handValue,
                handHashes=handHashes,
                player=sp.sender,
                gameStatus=0,
                finalBet=sp.mutez(0),
                userNonce=params.userNonce,
                pendingFirstCardsReq=sp.nat(0),
                pendingLastCardReq=sp.nat(0),
            )
            self.data.games[gameId] = new_game
            self.data.currentGameIndex += 1

            # Forward to the oracle. callbackContext = pack({gameId, phase=0})
            # — onRandomFulfilled will unpack it to dispatch back to this
            # game's first-cards-dealt path.
            oracle = sp.contract(sp.record(callback=sp.address, nRandoms=sp.nat, maxValue=sp.nat, userNonce=sp.bytes, commitId=sp.nat, callbackContext=sp.bytes), self.data.oracleContract, entrypoint="requestRandom").unwrap_some(error="oracle contract not found")
            ctx = sp.pack(sp.record(gameId=gameId, phase=sp.nat(0)))
            sp.transfer(sp.record(callback=sp.self_address, nRandoms=sp.nat(2), maxValue=sp.nat(51), userNonce=params.userNonce, commitId=params.commitId, callbackContext=ctx), self.data.oracleFee, oracle)
            sp.emit(gameId, tag='betMade')

        @sp.entrypoint()
        def continueBet(self, params):
            '''Player commits the spread bet on the dealt anchors. Pays
            (final bet) + holder fee + oracle fee. Spread-aware ceiling
            check (carried over from v2) ensures the worst-case payout
            fits in the post-add pot. On success, forwards a 1-card
            randomness request; last card lands via onRandomFulfilled
            (phase 1). Checklist §1.1, §1.4, §2.1, §5.1, §5.3, §6.1,
            §7.2, §8.3.'''
            sp.cast(params.gameId, sp.nat)
            sp.cast(params.userNonce, sp.bytes)
            sp.cast(params.commitId, sp.nat)
            sp.cast(sp.sender, sp.address)
            sp.cast(sp.amount, sp.mutez)
            assert params.gameId in self.data.games, "no such game"
            g = self.data.games[params.gameId]
            assert g.player == sp.sender, "not player"
            assert g.gameStatus == 1, "bad game Status"
            assert sp.amount >= self.data.fee + self.data.oracleFee, "must cover fee + oracleFee"
            bet = sp.amount - self.data.fee - self.data.oracleFee

            # Spread for this game — both anchors are populated when status
            # advanced to 1 (set by onRandomFulfilled phase=0).
            lowCard = g.handValue[1]
            highCard = g.handValue[2]
            if highCard < lowCard:
                lowCard = g.handValue[2]
                highCard = g.handValue[1]
            spread = sp.as_nat(highCard - lowCard - 1)
            maxPayout = sp.split_tokens(bet, 1235, spread * 100)
            assert maxPayout <= self.data.pot + bet, "bet too big for spread"

            self.data.games[params.gameId].finalBet = bet
            self.data.games[params.gameId].gameStatus = 2
            self.data.pot += bet
            sp.send(self.data.txlContract, self.data.fee)
            if self.data.pot > sp.tez(2):
                self.data.pot -= self.data.fee
                self.data.potReserve += self.data.fee
            sp.emit(self.data.pot, tag='pot')

            # Forward to the oracle for the last card.
            oracle = sp.contract(sp.record(callback=sp.address, nRandoms=sp.nat, maxValue=sp.nat, userNonce=sp.bytes, commitId=sp.nat, callbackContext=sp.bytes), self.data.oracleContract, entrypoint="requestRandom").unwrap_some(error="oracle contract not found")
            ctx = sp.pack(sp.record(gameId=params.gameId, phase=sp.nat(1)))
            sp.transfer(sp.record(callback=sp.self_address, nRandoms=sp.nat(1), maxValue=sp.nat(51), userNonce=params.userNonce, commitId=params.commitId, callbackContext=ctx), self.data.oracleFee, oracle)

        # ── Oracle callback (v3) ───────────────────────────────────────────
        @sp.entrypoint()
        def onRandomFulfilled(self, params):
            '''RandomOracle callback. Dispatches on callbackContext phase:
              phase 0 (firstCards): two values in [0,51] → fill hand[1] &
                hand[2]. Pair on rank → status 5 (ante forfeit).
                Otherwise status → 1 awaiting player's continueBet.
              phase 1 (lastCard): one value in [0,51] → fill hand[3] and
                settle. Spread-band rules from v2 apply unchanged.
            Checklist §1.1, §1.4, §3.3, §4.1, §6.1, §7.2, §7.3, §8.3.'''
            sp.cast(params.requestId, sp.nat)
            sp.cast(params.randomValues, sp.list[sp.nat])
            sp.cast(params.callbackContext, sp.bytes)
            assert sp.sender == self.data.oracleContract, "not oracle"
            ctx = sp.unpack(params.callbackContext, sp.record(gameId=sp.nat, phase=sp.nat)).unwrap_some(error="bad context")
            assert ctx.gameId in self.data.games, "no such game"
            g = self.data.games[ctx.gameId]

            if ctx.phase == 0:
                # ── First-cards phase ────────────────────────────────────
                assert g.gameStatus == 0, "bad game Status"
                # Pull two cards by index. randomValues are nats in [0,51].
                card1 = sp.nat(0)
                card2 = sp.nat(0)
                idx = sp.nat(0)
                for v in params.randomValues:
                    if idx == 0:
                        card1 = v
                    if idx == 1:
                        card2 = v
                    idx += 1
                # Card → (rank face-value, raw deck index). §5.2: ranks in
                # [2,14] face value (cardValue = card/4 + 2). Comparisons
                # against handValue stay in face-value units throughout.
                cv1 = sp.to_int(card1 / 4) + 2
                cv2 = sp.to_int(card2 / 4) + 2
                c1 = sp.to_int(card1)
                c2 = sp.to_int(card2)
                self.data.games[ctx.gameId].hand[1] = c1
                self.data.games[ctx.gameId].hand[2] = c2
                self.data.games[ctx.gameId].handValue[1] = cv1
                self.data.games[ctx.gameId].handValue[2] = cv2
                self.data.games[ctx.gameId].pendingFirstCardsReq = params.requestId
                if cv1 == cv2:
                    # Pair: ante stays in pot, no continueBet path.
                    self.data.games[ctx.gameId].gameStatus = 5
                    sp.emit(ctx.gameId, tag='pairDrawn')
                else:
                    self.data.games[ctx.gameId].gameStatus = 1
                    sp.emit(sp.record(gameId=ctx.gameId, card1=c1, card2=c2), tag='firstCardsDealt')
            else:
                # ── Last-card phase ──────────────────────────────────────
                assert g.gameStatus == 2, "bad game Status"
                lastCard = sp.nat(0)
                for v in params.randomValues:
                    lastCard = v
                cv3 = sp.to_int(lastCard / 4) + 2
                c3 = sp.to_int(lastCard)
                self.data.games[ctx.gameId].hand[3] = c3
                self.data.games[ctx.gameId].handValue[3] = cv3
                self.data.games[ctx.gameId].pendingLastCardReq = params.requestId

                lowCard = g.handValue[1]
                highCard = g.handValue[2]
                if highCard < lowCard:
                    lowCard = g.handValue[2]
                    highCard = g.handValue[1]
                sp.emit([lowCard, cv3, highCard])

                if cv3 < lowCard:
                    self.data.games[ctx.gameId].gameStatus = 4
                if cv3 == lowCard:
                    self.data.pot -= g.finalBet + self.data.ante
                    sp.send(self.data.txlContract, g.finalBet + self.data.ante)
                    self.data.games[ctx.gameId].gameStatus = 4
                if cv3 > lowCard and cv3 < highCard:
                    # In-between win. True-odds payout with 5% rake:
                    #   payout = bet * 1235 / (spread * 100)
                    # continueBet's spread-aware ceiling guarantees this
                    # fits, but defense-in-depth: clamp to pot so the
                    # SUB_MUTEZ never reverts. §5.3.
                    spread = sp.as_nat(highCard - lowCard - 1)
                    winAmount = sp.split_tokens(g.finalBet, 1235, spread * 100)
                    if winAmount > self.data.pot:
                        winAmount = self.data.pot
                    # §4.1: terminal state before sp.send.
                    self.data.games[ctx.gameId].gameStatus = 3
                    self.data.pot -= winAmount
                    sp.send(g.player, winAmount)
                    sp.emit(winAmount, tag='winAmount')
                if cv3 == highCard:
                    self.data.pot -= g.finalBet + self.data.ante
                    sp.send(self.data.txlContract, g.finalBet + self.data.ante)
                    self.data.games[ctx.gameId].gameStatus = 4
                if cv3 > highCard:
                    self.data.games[ctx.gameId].gameStatus = 4

                # Pot auto-refill from reserve when low. §2.2: only refill
                # when reserve can cover — SUB_MUTEZ panic in this callback
                # would block the oracle's settlement permanently. Carried
                # from v2's AD-2 fix.
                sp.emit(self.data.pot, tag='postSettlePot')
                if self.data.pot < sp.mutez(124999) and self.data.potReserve >= sp.mutez(125000):
                    self.data.pot += sp.mutez(125000)
                    self.data.potReserve -= sp.mutez(125000)


# ──────────────────────────────────────────────────────────────────────────────
# Compile-only test
# ──────────────────────────────────────────────────────────────────────────────
@sp.add_test()
def test():
    s = sp.test_scenario("AceyDuecey v3 deploy", main)
    s.h1("Originate AceyDuecey (v3 commit-reveal consumer)")
    a = main.AceyDuecey()
    a.set_initial_balance(sp.tez(0))
    s += a
