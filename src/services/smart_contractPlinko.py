import smartpy as sp

# ─── Plinko ───────────────────────────────────────────────────────────────
#
# Two-phase play:
#   play(rows, risk)  : player sends bet; contract records a pending round
#   resolve(roundId, slot, seed)  : oracle picks landing slot, contract pays
#
# Multipliers live in a flat map keyed by  rows*1000 + risk*100 + slot,
# values in basis-of-100 (1.0x = 100, 5.6x = 560). Admin pre-loads with
# setMultiplier / setMultipliers after deploy — keeps the contract tiny
# and lets you tune payouts without redeploying.
#
# Slot count = rows + 1  (Pascal's-triangle Plinko: an N-row board has
# N+1 buckets at the bottom).
#
# Risk levels:  0 = low, 1 = medium, 2 = high
# Rows allowed: 8, 12, 16
#
# Round.status:
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
            self.data.maxBet = sp.mutez(1000000)      # 1.0 ꜩ

            # Pot
            self.data.pot = sp.mutez(0)
            self.data.potReserve = sp.tez(0)

            # Monotonic round counter
            self.data.currentRoundId = sp.nat(0)

            # Per-round state. `path` holds the per-row 0/1 bits the oracle
            # supplied — each bit is one peg-collision decision (0=left,
            # 1=right). slot = sum of bits.
            self.data.rounds = sp.cast({}, sp.map[sp.nat, sp.record(
                player=sp.address,
                bet=sp.mutez,
                rows=sp.nat,
                risk=sp.nat,
                roundStatus=sp.nat,
                finalSlot=sp.nat,
                payout=sp.mutez,
                seed=sp.string,
                path=sp.map[sp.nat, sp.nat],
            )])

            # Multiplier table  key = rows*1000 + risk*100 + slot
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

        # Single-cell update — useful for hot-patching one slot.
        @sp.entrypoint()
        def setMultiplier(self, params):
            assert sp.sender == self.data.admin, "not admin"
            sp.cast(params.key, sp.nat)
            sp.cast(params.value, sp.nat)
            self.data.multipliers[params.key] = params.value

        # Bulk loader for a single (rows, risk) row of the table.
        # Pass the values left-to-right, one per slot 0..rows.
        @sp.entrypoint()
        def setMultiplierRow(self, params):
            assert sp.sender == self.data.admin, "not admin"
            sp.cast(params.rows, sp.nat)
            sp.cast(params.risk, sp.nat)
            sp.cast(params.values, sp.map[sp.nat, sp.nat])
            base = params.rows * 1000 + params.risk * 100
            for slot in params.values.keys():
                self.data.multipliers[base + slot] = params.values[slot]

        # ─── Player: request a drop ─────────────────────────────────
        @sp.entrypoint()
        def play(self, params):
            sp.cast(params.rows, sp.nat)
            sp.cast(params.risk, sp.nat)
            sp.cast(sp.sender, sp.address)
            sp.cast(sp.amount, sp.mutez)

            # Only the three standard board sizes.
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
                finalSlot=0,
                payout=sp.mutez(0),
                seed='',
                path=empty_path,
            )
            sp.emit(
                [self.data.currentRoundId, params.rows, params.risk],
                tag='playRequested',
            )
            self.data.currentRoundId += 1

        # ─── Oracle: settle a drop ──────────────────────────────────
        # `bits` is a map keyed by row index (0..rows-1) with values 0
        # (left) or 1 (right). The contract derives slot = sum(bits),
        # which means every drop's path is verifiable on chain — the UI
        # can replay the exact left/right decisions the oracle made.
        # `seed` is whatever auditable tag the oracle wants to commit.
        @sp.entrypoint()
        def resolve(self, params):
            sp.cast(params.roundId, sp.nat)
            sp.cast(params.bits, sp.map[sp.nat, sp.nat])
            sp.cast(params.seed, sp.string)
            assert sp.sender == self.data.oracle, "not oracle"

            r = self.data.rounds[params.roundId]
            assert r.roundStatus == 0, "already resolved"

            # Sum bits → slot. Also enforces 0/1 range and length == rows.
            slot = sp.nat(0)
            bitCount = sp.nat(0)
            for i in params.bits.keys():
                bit = params.bits[i]
                assert bit < 2, "bit must be 0 or 1"
                slot += bit
                bitCount += 1
            assert bitCount == r.rows, "bits length must equal rows"

            # Look up the multiplier (default 100 = 1.0x return-the-bet).
            key = r.rows * 1000 + r.risk * 100 + slot
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
                finalSlot=slot,
                payout=payout,
                seed=params.seed,
                path=params.bits,
            )

            # Settle: pull payout from pot. If short, auto-pull from
            # reserve in one shot so we always pay the full multiplier.
            # (SmartPy treats sp.tez and sp.mutez as the same mutez
            # under the hood, so straight arithmetic works.)
            if payout > sp.mutez(0):
                if payout > self.data.pot:
                    deficit = payout - self.data.pot
                    assert self.data.potReserve >= deficit, "pot + reserve too low"
                    self.data.potReserve -= deficit
                    self.data.pot += deficit
                self.data.pot -= payout
                sp.send(r.player, payout)

            sp.emit(
                [params.roundId, slot, multBp],
                tag='playResolved',
            )

        # Admin can shuffle balance between the working pot and the
        # cold reserve. Pass a positive `amount` to move reserve→pot,
        # negative to move pot→reserve.
        @sp.entrypoint()
        def topUpPot(self, params):
            assert sp.sender == self.data.admin, "not admin"
            sp.cast(params.amount, sp.mutez)
            self.data.potReserve -= params.amount
            self.data.pot += params.amount


# ─── Compile-only test ───────────────────────────────────────────────────
@sp.add_test()
def test():
    s = sp.test_scenario("plinko basic", main)
    c = main.Plinko()
    c.set_initial_balance(sp.tez(0))
    s += c
