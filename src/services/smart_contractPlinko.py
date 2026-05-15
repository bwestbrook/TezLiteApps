import smartpy as sp

# ─── Plinko 3D ────────────────────────────────────────────────────────────
#
# Two-phase play, now in three dimensions:
#   play(rows, risk)                       : player sends bet; pending round
#   resolve(roundId, xBits, zBits, seed)   : oracle commits the 3D walk, pays
#
# 3D model
# --------
# The ball drops through `rows` layers of a peg pyramid. At every layer it
# makes TWO independent 50/50 deflections — one on the X axis, one on the Z
# axis (a diagonal step in the horizontal plane). After `rows` layers:
#
#   finalX = sum(xBits)   ∈ [0, rows]   (Binomial(rows, 1/2))
#   finalZ = sum(zBits)   ∈ [0, rows]   (Binomial(rows, 1/2))
#
# so the ball lands on a (rows+1) × (rows+1) grid of bins, with the centre
# bin overwhelmingly likely and the corners exponentially rare — the 2D
# analogue of classic Plinko's bell curve.
#
# Payout is RADIAL: it depends only on how far the landing bin sits from
# the centre, measured as the Chebyshev "ring":
#
#   ring = max(|finalX - rows/2|, |finalZ - rows/2|)   ∈ [0, rows/2]
#
# ring 0 is the dead-centre bin (lowest multiplier); ring rows/2 is the
# outer square of corner bins (highest multiplier). Concentric square
# rings all pay the same — a 3D Galton board is radially symmetric, so
# the table stays tiny (rows/2 + 1 entries per (rows,risk)).
#
# Multipliers live in a flat map keyed by  rows*1000 + risk*100 + ring,
# values in basis-of-100 (1.0x = 100, 5.6x = 560). Admin pre-loads with
# setMultiplier / setMultiplierRow after deploy.
#
# Risk levels:  0 = low, 1 = medium, 2 = high
# Rows allowed: 8, 12, 16        (rows/2 is always an integer)
#
# Round.roundStatus:
#   0 = pending (oracle owes a resolve)
#   1 = resolved win  (payout > bet)
#   2 = resolved push (payout == bet)
#   3 = resolved loss (payout < bet, possibly zero)


@sp.module
def main():
    class Plinko(sp.Contract):
        def __init__(self):
            # Admin / oracle / payments. Both admin and oracle default to
            # the test-wallet derived from DEPLOY_MNEMONIC so the same key
            # that originates can also seed multipliers + resolve rounds.
            # Use updateOracle (no admin-update yet) to split the roles
            # once you're past dev.
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.txlContract = sp.address("KT1Ro63rVDUx2x8pMChCLSySso8t6JH47oRQ")

            # Bet sizing — admin tunable post-deploy
            self.data.fee = sp.mutez(100000)          # 0.1 ꜩ holder fee
            self.data.minBet = sp.mutez(100000)       # 0.1 ꜩ
            self.data.maxBet = sp.mutez(10000000)     # 10.0 ꜩ

            # Pot
            self.data.pot = sp.mutez(0)
            self.data.potReserve = sp.tez(0)

            # Monotonic round counter
            self.data.currentRoundId = sp.nat(0)

            # Per-round state. `xPath` / `zPath` hold the per-layer 0/1
            # deflection bits the oracle supplied (0 = -axis, 1 = +axis);
            # finalX = sum(xPath), finalZ = sum(zPath). The UI replays the
            # exact 3D walk from these. `ring` is the cached Chebyshev
            # distance from centre that drove the multiplier lookup.
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
                seed=sp.string,
                xPath=sp.map[sp.nat, sp.nat],
                zPath=sp.map[sp.nat, sp.nat],
            )])

            # Multiplier table  key = rows*1000 + risk*100 + ring
            # values are basis-of-100 (1.0x = 100, 0.5x = 50, 29x = 2900).
            # Empty by default; admin loads via setMultiplier(s).
            self.data.multipliers = sp.cast({}, sp.map[sp.nat, sp.nat])

        # ─── Funding ────────────────────────────────────────────────
        @sp.entrypoint
        def default(self):
            '''Anyone can top up the reserve.'''
            self.data.potReserve += sp.amount

        # ─── Admin: pot/fee/bet-bounds knobs ────────────────────────
        @sp.entrypoint()
        def updateAdmin(self, params):
            '''Admin-only: rotate the admin key. Single-step; the only
            recovery path if the deployer key is lost or compromised, so
            call it deliberately. Checklist §1.2.'''
            sp.cast(params.newAdmin, sp.address)
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
            '''Admin-only: delete a settled round to reclaim storage.
            Emits the full pre-prune record so off-chain indexers can
            keep history. Checklist §3.1.'''
            sp.cast(params.roundId, sp.nat)
            assert sp.sender == self.data.admin, "not admin"
            r = self.data.rounds[params.roundId]
            assert r.roundStatus != 0, "round not settled"
            sp.emit(r, tag='roundPruned')
            del self.data.rounds[params.roundId]

        # Single-cell update — useful for hot-patching one ring.
        @sp.entrypoint()
        def setMultiplier(self, params):
            assert sp.sender == self.data.admin, "not admin"
            sp.cast(params.key, sp.nat)
            sp.cast(params.value, sp.nat)
            self.data.multipliers[params.key] = params.value

        # Bulk loader for a single (rows, risk) ring profile.
        # `values` is keyed by ring index 0..rows/2.
        @sp.entrypoint()
        def setMultiplierRow(self, params):
            assert sp.sender == self.data.admin, "not admin"
            sp.cast(params.rows, sp.nat)
            sp.cast(params.risk, sp.nat)
            sp.cast(params.values, sp.map[sp.nat, sp.nat])
            # SECURITY: §3.2 — cap entry count to defeat gas-balloon
            # griefing if the admin key is ever compromised (PLINKO-4).
            # Largest legitimate profile is a 16-row board's rings 0..8;
            # 17 leaves headroom for the full 0..16 slot domain.
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
            sp.cast(params.rows, sp.nat)
            sp.cast(params.risk, sp.nat)
            sp.cast(sp.sender, sp.address)
            sp.cast(sp.amount, sp.mutez)

            # Only the three standard board sizes (all have an even
            # rows/2 so the ring centre is exact).
            assert (
                params.rows == 8
                or params.rows == 12
                or params.rows == 16
            ), "rows must be 8, 12, or 16"
            assert params.risk < 3, "risk must be 0..2"
            assert sp.amount >= self.data.minBet, "bet too small"
            assert sp.amount <= self.data.maxBet, "bet too big"

            # Strip holder fee off the top; the rest goes to the pot.
            betAfterFee = sp.amount - self.data.fee
            self.data.pot += betAfterFee
            sp.send(self.data.txlContract, self.data.fee)

            empty_path = sp.cast({}, sp.map[sp.nat, sp.nat])
            self.data.rounds[self.data.currentRoundId] = sp.record(
                player=sp.sender,
                bet=betAfterFee,
                rows=params.rows,
                risk=params.risk,
                roundStatus=0,
                finalX=0,
                finalZ=0,
                ring=0,
                payout=sp.mutez(0),
                seed='',
                xPath=empty_path,
                zPath=empty_path,
            )
            sp.emit(
                [self.data.currentRoundId, params.rows, params.risk],
                tag='playRequested',
            )
            self.data.currentRoundId += 1

        # ─── Oracle: settle a drop ──────────────────────────────────
        # `xBits` / `zBits` are maps keyed by layer index (0..rows-1)
        # with values 0 or 1. The contract derives finalX = sum(xBits),
        # finalZ = sum(zBits), then the Chebyshev `ring`, so every drop's
        # 3D path is verifiable on chain — the UI replays the exact
        # deflections. `seed` is whatever auditable tag the oracle wants
        # to commit.
        @sp.entrypoint()
        def resolve(self, params):
            sp.cast(params.roundId, sp.nat)
            sp.cast(params.xBits, sp.map[sp.nat, sp.nat])
            sp.cast(params.zBits, sp.map[sp.nat, sp.nat])
            sp.cast(params.seed, sp.string)
            assert sp.sender == self.data.oracle, "not oracle"

            r = self.data.rounds[params.roundId]
            assert r.roundStatus == 0, "already resolved"

            # Sum xBits → finalX. Enforces 0/1 range and length == rows.
            finalX = sp.nat(0)
            xCount = sp.nat(0)
            for i in params.xBits.keys():
                xbit = params.xBits[i]
                assert xbit < 2, "xBit must be 0 or 1"
                finalX += xbit
                xCount += 1
            assert xCount == r.rows, "xBits length must equal rows"

            # Sum zBits → finalZ. Same checks.
            finalZ = sp.nat(0)
            zCount = sp.nat(0)
            for j in params.zBits.keys():
                zbit = params.zBits[j]
                assert zbit < 2, "zBit must be 0 or 1"
                finalZ += zbit
                zCount += 1
            assert zCount == r.rows, "zBits length must equal rows"

            # ring = max(|finalX - rows/2|, |finalZ - rows/2|).
            # rows ∈ {8,12,16} so rows/2 ∈ {4,6,8} — set it explicitly
            # to dodge any nat-division ambiguity.
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

            # Look up the multiplier (default 100 = 1.0x return-the-bet).
            key = r.rows * 1000 + r.risk * 100 + ring
            multBp = self.data.multipliers.get(key, default=sp.nat(100))
            payout = sp.split_tokens(r.bet, multBp, 100)

            # Status classification for the indexer/UI:
            #   payout >  bet -> 1 win
            #   payout == bet -> 2 push
            #   payout <  bet -> 3 loss
            newStatus = sp.nat(3)
            if payout == r.bet:
                newStatus = sp.nat(2)
            if payout > r.bet:
                newStatus = sp.nat(1)

            self.data.rounds[params.roundId] = sp.record(
                player=r.player,
                bet=r.bet,
                rows=r.rows,
                risk=r.risk,
                roundStatus=newStatus,
                finalX=finalX,
                finalZ=finalZ,
                ring=ring,
                payout=payout,
                seed=params.seed,
                xPath=params.xBits,
                zPath=params.zBits,
            )

            # Settle: pull payout from pot. SECURITY: §2.2 — a hard assert
            # here (PLINKO-2) meant any pot+reserve shortfall reverted the
            # whole resolve op, so the oracle worker burned fees retrying
            # it forever. Instead, cap the payout at what's actually
            # available: the round still settles (roundStatus flips off 0),
            # the worker moves on, and a payoutShortfall event lets
            # off-chain alerting prompt an admin top-up.
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
                # Bookkeep what we actually paid vs. what was owed.
                self.data.rounds[params.roundId].payout = actualPayout
                if actualPayout < payout:
                    sp.emit(
                        sp.record(
                            roundId=params.roundId,
                            owed=payout,
                            paid=actualPayout,
                        ),
                        tag='payoutShortfall',
                    )

            sp.emit(
                [params.roundId, finalX, finalZ, ring, multBp],
                tag='playResolved',
            )

        # Admin can shuffle balance between the working pot and the cold
        # reserve. PLINKO-5: two directional entrypoints instead of one
        # signed amount — the name now constrains the direction, and each
        # asserts its source can cover the move (§2.2, no SUB_MUTEZ).
        @sp.entrypoint()
        def topUpPot(self, params):
            '''Move `amount` from reserve into the playable pot.'''
            sp.cast(params.amount, sp.mutez)
            assert sp.sender == self.data.admin, "not admin"
            assert params.amount > sp.mutez(0), "amount must be positive"
            assert self.data.potReserve >= params.amount, "reserve too low"
            self.data.potReserve -= params.amount
            self.data.pot += params.amount
            sp.emit(
                [params.amount, self.data.pot, self.data.potReserve],
                tag='potToppedUp',
            )

        @sp.entrypoint()
        def withdrawToReserve(self, params):
            '''Move `amount` from the playable pot back to the reserve.'''
            sp.cast(params.amount, sp.mutez)
            assert sp.sender == self.data.admin, "not admin"
            assert params.amount > sp.mutez(0), "amount must be positive"
            assert self.data.pot >= params.amount, "pot too low"
            self.data.pot -= params.amount
            self.data.potReserve += params.amount
            sp.emit(
                [params.amount, self.data.pot, self.data.potReserve],
                tag='potDrained',
            )


# ─── Compile-only test ───────────────────────────────────────────────────
@sp.add_test()
def test():
    s = sp.test_scenario("plinko 3d basic", main)
    c = main.Plinko()
    c.set_initial_balance(sp.tez(0))
    s += c
