import smartpy as sp

# ─── Plinko 3D — v3 commit-reveal randomness ─────────────────────────────
#
# Two-phase play, with the second phase now driven by the RandomOracle's
# commit-reveal scheme instead of an oracle-keyed `resolve` entrypoint:
#
#   play(rows, risk, userNonce, commitId)
#     → record the round in roundStatus=0
#     → call oracle.requestRandom(nRandoms=2*rows, maxValue=1)
#       — userNonce flows through; callbackContext = pack(roundId)
#     → round stays at status 0 until the oracle reveals + fulfills.
#
#   onRandomFulfilled(requestId, randomValues, callbackContext)
#     → unpack callbackContext → roundId
#     → randomValues has 2*rows nats in [0,1]: first `rows` are xBits,
#       second `rows` are zBits. Mirrors the v2 resolve API but now
#       derives bits from the on-chain commit-revealed seed.
#     → finalX = sum(xBits), finalZ = sum(zBits)
#     → ring = max(|finalX − rows/2|, |finalZ − rows/2|)
#     → multiplier lookup, payout, settle.
#
# 3D model
# --------
# The ball drops through `rows` layers. Each layer makes TWO independent
# 50/50 deflections — one on X, one on Z. After `rows` layers:
#
#   finalX = sum(xBits)   ∈ [0, rows]   (Binomial(rows, 1/2))
#   finalZ = sum(zBits)   ∈ [0, rows]
#
# Landing on a (rows+1)×(rows+1) grid. Payout is RADIAL — based on
# Chebyshev distance from centre:
#
#   ring = max(|finalX − rows/2|, |finalZ − rows/2|)   ∈ [0, rows/2]
#
# Multipliers live in a flat map keyed by  rows*1000 + risk*100 + ring,
# values in basis-of-100 (1.0x = 100, 5.6x = 560).
#
# Risk levels:  0 = low, 1 = medium, 2 = high
# Rows allowed: 8, 12, 16  (so 2*rows ∈ {16, 24, 32} — fits oracle's
# default maxRandomsPerRequest = 32.)
#
# Round.roundStatus:
#   0 = pending oracle fulfillment
#   1 = resolved win  (payout > bet)
#   2 = resolved push (payout == bet)
#   3 = resolved loss (payout < bet, possibly zero)


@sp.module
def main():
    class Plinko(sp.Contract):
        def __init__(self):
            # Admin / wiring. Both admin and oracle-contract default to the
            # operator's tz1 / tezliteapps oracle KT1 until rotated.
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")
            # v3: RandomOracle KT1. updateOracleContract rotates it.
            self.data.oracleContract = sp.address("KT19V1YiyPtyCbxouhyeM96SekRTVC7Gw6qq")
            # Per-request mutez forwarded to oracle.requestRandom.
            self.data.oracleFee = sp.mutez(100000)

            # Bet sizing — admin tunable.
            self.data.fee = sp.mutez(100000)
            self.data.minBet = sp.mutez(100000)
            self.data.maxBet = sp.mutez(10000000)

            self.data.pot = sp.mutez(0)
            self.data.potReserve = sp.tez(0)
            self.data.currentRoundId = sp.nat(0)

            # Per-round state. v3 adds:
            #   userNonce        — player entropy attached at play() time
            #   pendingReqId     — oracle requestId for this round's resolve
            self.data.rounds = sp.cast({}, sp.map[sp.nat, sp.record(
                player=sp.address,
                bet=sp.mutez,
                rows=sp.nat,
                risk=sp.nat,
                roundStatus=sp.nat,
                finalX=sp.nat,
                finalZ=sp.nat,
                ring=sp.nat,
                payout=sp.mutez,
                xPath=sp.map[sp.nat, sp.nat],
                zPath=sp.map[sp.nat, sp.nat],
                userNonce=sp.bytes,
                pendingReqId=sp.nat,
            )])

            # Multiplier table  key = rows*1000 + risk*100 + ring
            # values in basis-of-100. Admin loads via setMultiplier(s).
            self.data.multipliers = sp.cast({}, sp.map[sp.nat, sp.nat])

        # ─── Funding ────────────────────────────────────────────────
        @sp.entrypoint
        def default(self):
            self.data.potReserve += sp.amount

        # ─── Admin ──────────────────────────────────────────────────
        @sp.entrypoint()
        def updateAdmin(self, params):
            '''Admin-only: rotate the admin key. Checklist §1.1, §1.2.'''
            sp.cast(params.newAdmin, sp.address)
            assert sp.sender == self.data.admin, "not admin"
            self.data.admin = params.newAdmin

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
            oracle. v3. Checklist §1.1.'''
            sp.cast(params.newFee, sp.mutez)
            assert sp.sender == self.data.admin, "not admin"
            self.data.oracleFee = params.newFee

        @sp.entrypoint()
        def updateTxlContract(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.txlContract = params.newContract

        @sp.entrypoint()
        def updateBetBounds(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.minBet = params.minBet
            self.data.maxBet = params.maxBet

        @sp.entrypoint()
        def updateFee(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.fee = params.fee

        @sp.entrypoint()
        def pruneRound(self, params):
            '''Admin-only: delete a settled round. §3.1, §8.3.'''
            sp.cast(params.roundId, sp.nat)
            assert sp.sender == self.data.admin, "not admin"
            r = self.data.rounds[params.roundId]
            assert r.roundStatus != 0, "round not settled"
            sp.emit(r, tag='roundPruned')
            del self.data.rounds[params.roundId]

        @sp.entrypoint()
        def setMultiplier(self, params):
            assert sp.sender == self.data.admin, "not admin"
            sp.cast(params.key, sp.nat)
            sp.cast(params.value, sp.nat)
            self.data.multipliers[params.key] = params.value

        @sp.entrypoint()
        def setMultiplierRow(self, params):
            assert sp.sender == self.data.admin, "not admin"
            sp.cast(params.rows, sp.nat)
            sp.cast(params.risk, sp.nat)
            sp.cast(params.values, sp.map[sp.nat, sp.nat])
            # §3.2 — cap entry count to defeat gas-balloon griefing if
            # the admin key is ever compromised (PLINKO-4). Largest
            # legitimate profile is rings 0..8 (rows=16); 17 leaves a
            # slot of headroom for the full 0..16 domain.
            count = sp.nat(0)
            for _k in params.values.keys():
                count += 1
            assert count <= 17, "too many entries (max 17)"
            base = params.rows * 1000 + params.risk * 100
            for ring in params.values.keys():
                self.data.multipliers[base + ring] = params.values[ring]

        # ─── Player: request a drop ─────────────────────────────────
        @sp.entrypoint()
        def play(self, params):
            '''Player triggers a drop. Pays bet + holder fee + oracle fee.

            v3: takes (userNonce: bytes, commitId: nat) — the random bits
            are derived in onRandomFulfilled from the commit-revealed seed
            + this nonce, removing the operator's ability to bias.
            Checklist §1.1, §2.1, §3.3, §6.1, §6.2, §7.2, §8.3.'''
            sp.cast(params.rows, sp.nat)
            sp.cast(params.risk, sp.nat)
            sp.cast(params.userNonce, sp.bytes)
            sp.cast(params.commitId, sp.nat)
            sp.cast(sp.sender, sp.address)
            sp.cast(sp.amount, sp.mutez)

            assert (
                params.rows == 8
                or params.rows == 12
                or params.rows == 16
            ), "rows must be 8, 12, or 16"
            assert params.risk < 3, "risk must be 0..2"
            # sp.amount = bet + fee + oracleFee. minBet/maxBet apply to bet.
            assert sp.amount >= self.data.minBet + self.data.fee + self.data.oracleFee, "bet too small"
            assert sp.amount <= self.data.maxBet + self.data.fee + self.data.oracleFee, "bet too big"
            betAfterFees = sp.amount - self.data.fee - self.data.oracleFee
            self.data.pot += betAfterFees
            sp.send(self.data.txlContract, self.data.fee)

            roundId = self.data.currentRoundId
            empty_path = sp.cast({}, sp.map[sp.nat, sp.nat])
            self.data.rounds[roundId] = sp.record(
                player=sp.sender,
                bet=betAfterFees,
                rows=params.rows,
                risk=params.risk,
                roundStatus=0,
                finalX=0,
                finalZ=0,
                ring=0,
                payout=sp.mutez(0),
                xPath=empty_path,
                zPath=empty_path,
                userNonce=params.userNonce,
                pendingReqId=sp.nat(0),
            )
            self.data.currentRoundId += 1

            # Forward to oracle. nRandoms = 2 * rows (xBits + zBits),
            # maxValue = 1 (each bit is 0 or 1). callbackContext = pack(roundId).
            nRand = sp.mul(sp.nat(2), params.rows)
            oracle = sp.contract(sp.record(callback=sp.address, nRandoms=sp.nat, maxValue=sp.nat, userNonce=sp.bytes, commitId=sp.nat, callbackContext=sp.bytes), self.data.oracleContract, entrypoint="requestRandom").unwrap_some(error="oracle contract not found")
            ctx = sp.pack(roundId)
            sp.transfer(sp.record(callback=sp.self_address, nRandoms=nRand, maxValue=sp.nat(1), userNonce=params.userNonce, commitId=params.commitId, callbackContext=ctx), self.data.oracleFee, oracle)
            sp.emit([roundId, params.rows, params.risk], tag='playRequested')

        # ─── Oracle callback (v3) ──────────────────────────────────
        @sp.entrypoint()
        def onRandomFulfilled(self, params):
            '''RandomOracle callback. randomValues has 2*rows nats in [0,1]:
            first `rows` are xBits, second `rows` are zBits. Derives the
            landing ring, looks up the multiplier, settles the round.
            Checklist §1.1, §1.4, §3.3, §4.1, §6.1, §7.2, §7.3, §8.3.'''
            sp.cast(params.requestId, sp.nat)
            sp.cast(params.randomValues, sp.list[sp.nat])
            sp.cast(params.callbackContext, sp.bytes)
            assert sp.sender == self.data.oracleContract, "not oracle"
            roundId = sp.unpack(params.callbackContext, sp.nat).unwrap_some(error="bad context")
            assert roundId in self.data.rounds, "no such round"
            r = self.data.rounds[roundId]
            assert r.roundStatus == 0, "already resolved"

            # Split randomValues into xPath then zPath, lengths = rows.
            xPath = sp.cast({}, sp.map[sp.nat, sp.nat])
            zPath = sp.cast({}, sp.map[sp.nat, sp.nat])
            idx = sp.nat(0)
            finalX = sp.nat(0)
            finalZ = sp.nat(0)
            for v in params.randomValues:
                if idx < r.rows:
                    xPath[idx] = v
                    finalX += v
                else:
                    j = sp.as_nat(idx - r.rows)
                    zPath[j] = v
                    finalZ += v
                idx += 1
            # Defensive: enforce the oracle gave us exactly 2*rows values.
            assert idx == sp.mul(sp.nat(2), r.rows), "wrong value count"

            # ring = max(|finalX - rows/2|, |finalZ - rows/2|). rows ∈
            # {8,12,16} → rows/2 ∈ {4,6,8}. Set half explicitly to dodge
            # nat-division ambiguity.
            half = sp.nat(4)
            if r.rows == 12:
                half = sp.nat(6)
            if r.rows == 16:
                half = sp.nat(8)
            dx = abs(sp.to_int(finalX) - sp.to_int(half))
            dz = abs(sp.to_int(finalZ) - sp.to_int(half))
            ring = dx
            if dz > dx:
                ring = dz

            key = r.rows * 1000 + r.risk * 100 + ring
            multBp = self.data.multipliers.get(key, default=sp.nat(100))
            payout = sp.split_tokens(r.bet, multBp, 100)

            # Status classification.
            newStatus = sp.nat(3)
            if payout == r.bet:
                newStatus = sp.nat(2)
            if payout > r.bet:
                newStatus = sp.nat(1)

            self.data.rounds[roundId] = sp.record(
                player=r.player,
                bet=r.bet,
                rows=r.rows,
                risk=r.risk,
                roundStatus=newStatus,
                finalX=finalX,
                finalZ=finalZ,
                ring=ring,
                payout=payout,
                xPath=xPath,
                zPath=zPath,
                userNonce=r.userNonce,
                pendingReqId=params.requestId,
            )

            # Settle. §2.2: hard assert on pot+reserve coverage (PLINKO-2's
            # fix) — cap payout at what's available so the callback never
            # reverts (which would block the oracle's settlement forever
            # and burn the request).
            if payout > sp.mutez(0):
                available = self.data.pot + self.data.potReserve
                actualPayout = payout
                if payout > available:
                    actualPayout = available
                if actualPayout > self.data.pot:
                    deficit = actualPayout - self.data.pot
                    self.data.potReserve -= deficit
                    self.data.pot += deficit
                self.data.pot -= actualPayout
                sp.send(r.player, actualPayout)
                self.data.rounds[roundId].payout = actualPayout
                if actualPayout < payout:
                    sp.emit(sp.record(roundId=roundId, owed=payout, paid=actualPayout), tag='payoutShortfall')

            sp.emit([roundId, finalX, finalZ, ring, multBp], tag='playResolved')

        # ─── Admin pot management ──────────────────────────────────
        @sp.entrypoint()
        def topUpPot(self, params):
            '''Move `amount` from reserve into the playable pot.'''
            sp.cast(params.amount, sp.mutez)
            assert sp.sender == self.data.admin, "not admin"
            assert params.amount > sp.mutez(0), "amount must be positive"
            assert self.data.potReserve >= params.amount, "reserve too low"
            self.data.potReserve -= params.amount
            self.data.pot += params.amount
            sp.emit([params.amount, self.data.pot, self.data.potReserve], tag='potToppedUp')

        @sp.entrypoint()
        def withdrawToReserve(self, params):
            '''Move `amount` from the playable pot back to the reserve.'''
            sp.cast(params.amount, sp.mutez)
            assert sp.sender == self.data.admin, "not admin"
            assert params.amount > sp.mutez(0), "amount must be positive"
            assert self.data.pot >= params.amount, "pot too low"
            self.data.pot -= params.amount
            self.data.potReserve += params.amount
            sp.emit([params.amount, self.data.pot, self.data.potReserve], tag='potDrained')


# ─── Compile-only test ───────────────────────────────────────────────────
@sp.add_test()
def test():
    s = sp.test_scenario("plinko v3 basic", main)
    c = main.Plinko()
    c.set_initial_balance(sp.tez(0))
    s += c
