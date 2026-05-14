import smartpy as sp

# ─── RandomOracle (v2) ───────────────────────────────────────────────────
#
# Generic randomness service for Tezos. Two-phase request/fulfill:
#
#   1. Requester contract calls requestRandom(callback, callbackEntrypoint,
#      nRandoms, maxValue) and attaches at least `fee` ꜩ. Contract records
#      the request and emits an event.
#   2. Off-chain oracle worker observes pending requests, draws random
#      values, and calls fulfillRandom(requestId, values, seed). Contract
#      invokes the requester's callback entrypoint with the values, pays
#      the operator the recorded fee, and marks the request fulfilled.
#
# Requester contracts need a single callback entrypoint with signature:
#
#       (record(requestId=nat, randomValues=list[nat]))
#
# and they should verify sp.sender == oracle contract address in the
# callback so nobody else can spoof results.
#
# See src/services/smart_contract_oracle_reference.py for a copy-paste
# 50-line example dApp that calls this oracle and handles the callback.
# See docs/ORACLE_INTEGRATION.md for the integration walkthrough.

CALLBACK_PARAM_TYPE = sp.record(
    requestId=sp.nat,
    randomValues=sp.list[sp.nat],
)


@sp.module
def main():
    class RandomOracle(sp.Contract):
        def __init__(self):
            # Admin: can change oracle key, fee, withdraw operator earnings.
            # Oracle: the off-chain worker's signing key (settles requests).
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")

            # Minimum payment per request. Operator keeps whatever's actually
            # paid (i.e. requester can tip by sending more than the fee).
            self.data.fee = sp.mutez(100000)        # 0.1 ꜩ default

            # Bounds on what we'll oblige in a single request — keeps the
            # callback gas cost predictable.
            self.data.maxRandomsPerRequest = sp.nat(32)

            # Total operator earnings sitting in the contract awaiting
            # withdrawal. Updated on every fulfillRandom.
            self.data.operatorEarnings = sp.mutez(0)

            # Monotonic request counter; doubles as request id.
            self.data.currentRequestId = sp.nat(0)

            # Outstanding & historical requests.
            #
            # requestStatus:
            #   0 = pending   (awaiting oracle worker)
            #   1 = fulfilled (callback invoked successfully)
            #   2 = cancelled (admin / requester reclaimed fee — future use)
            self.data.requests = sp.cast({}, sp.map[sp.nat, sp.record(
                requester=sp.address,           # who called requestRandom
                callback=sp.address,            # where to deliver the result
                callbackEntrypoint=sp.string,   # which entrypoint on callback
                nRandoms=sp.nat,                # how many values requested
                maxValue=sp.nat,                # values will be in [0, maxValue]
                feePaid=sp.mutez,               # how much they paid
                requestStatus=sp.nat,           # 0/1/2 — see above
                requestTime=sp.timestamp,
                fulfillTime=sp.timestamp,
                randomValues=sp.list[sp.nat],
                seed=sp.string,                 # auditable hex tag
            )])

        # ─── Funding ────────────────────────────────────────────────
        @sp.entrypoint
        def default(self):
            '''Anonymous top-up — supports the operator earnings pool.'''
            self.data.operatorEarnings += sp.amount

        # ─── Public: anyone with a contract can request randomness ──
        @sp.entrypoint()
        def requestRandom(self, params):
            '''Record a randomness request. Requirements:
              - sp.amount >= fee
              - 1 <= nRandoms <= maxRandomsPerRequest
              - maxValue >= 1
              - callback must be a contract address (KT1...)
            The worker picks this up off-chain and calls fulfillRandom.'''
            sp.cast(params.callback, sp.address)
            sp.cast(params.callbackEntrypoint, sp.string)
            sp.cast(params.nRandoms, sp.nat)
            sp.cast(params.maxValue, sp.nat)
            assert sp.amount >= self.data.fee, "fee too low"
            assert params.nRandoms >= 1, "nRandoms must be >= 1"
            assert params.nRandoms <= self.data.maxRandomsPerRequest, "nRandoms too large"
            assert params.maxValue >= 1, "maxValue must be >= 1"

            empty_list = sp.cast([], sp.list[sp.nat])
            self.data.requests[self.data.currentRequestId] = sp.record(
                requester=sp.sender,
                callback=params.callback,
                callbackEntrypoint=params.callbackEntrypoint,
                nRandoms=params.nRandoms,
                maxValue=params.maxValue,
                feePaid=sp.amount,
                requestStatus=0,
                requestTime=sp.now,
                fulfillTime=sp.timestamp(0),
                randomValues=empty_list,
                seed='',
            )
            sp.emit(
                [self.data.currentRequestId, params.nRandoms, params.maxValue],
                tag='randomRequested',
            )
            self.data.currentRequestId += 1

        # ─── Oracle: settle a pending request ───────────────────────
        @sp.entrypoint()
        def fulfillRandom(self, params):
            '''Oracle-only. Settle the request by:
              1. Crediting the operator earnings pool with feePaid
              2. Updating the request record with values + seed
              3. Invoking the requester's callback with the values

            If the callback fails, the whole op fails atomically. Worker
            should pre-simulate to catch bad-callback requests rather
            than burning gas on doomed ops.'''
            sp.cast(params.requestId, sp.nat)
            sp.cast(params.randomValues, sp.list[sp.nat])
            sp.cast(params.seed, sp.string)
            assert sp.sender == self.data.oracle, "not oracle"

            r = self.data.requests[params.requestId]
            assert r.requestStatus == 0, "already settled"
            # Validate result count matches what was requested.
            count = sp.nat(0)
            for _v in params.randomValues:
                count += 1
            assert count == r.nRandoms, "value count mismatch"

            # Mark fulfilled + credit operator. We don't sp.send to the
            # operator here — admin sweeps the pool via withdraw() to
            # keep this entrypoint's gas predictable for the callback.
            self.data.operatorEarnings += r.feePaid
            self.data.requests[params.requestId] = sp.record(
                requester=r.requester,
                callback=r.callback,
                callbackEntrypoint=r.callbackEntrypoint,
                nRandoms=r.nRandoms,
                maxValue=r.maxValue,
                feePaid=r.feePaid,
                requestStatus=1,
                requestTime=r.requestTime,
                fulfillTime=sp.now,
                randomValues=params.randomValues,
                seed=params.seed,
            )

            # Invoke the requester's callback. The callback contract is
            # expected to expose an entrypoint typed as:
            #   sp.record(requestId=sp.nat, randomValues=sp.list[sp.nat])
            callback_record = sp.record(
                requestId=params.requestId,
                randomValues=params.randomValues,
            )
            callback_contract = sp.contract(
                sp.record(requestId=sp.nat, randomValues=sp.list[sp.nat]),
                r.callback,
                entrypoint=r.callbackEntrypoint,
            ).unwrap_some(error="callback not a contract or wrong entrypoint type")
            sp.transfer(callback_record, sp.mutez(0), callback_contract)

            sp.emit(
                [params.requestId, params.randomValues],
                tag='randomFulfilled',
            )

        # ─── Admin: payouts + parameter tuning ──────────────────────
        @sp.entrypoint()
        def withdrawEarnings(self, params):
            '''Send the accumulated operator earnings to the admin (or
            any recipient the admin specifies). Reset the pool counter.'''
            sp.cast(params.recipient, sp.address)
            assert sp.sender == self.data.admin, "not admin"
            assert self.data.operatorEarnings > sp.mutez(0), "nothing to withdraw"
            sp.send(params.recipient, self.data.operatorEarnings)
            self.data.operatorEarnings = sp.mutez(0)

        @sp.entrypoint()
        def updateOracle(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.oracle = params.newOracle

        @sp.entrypoint()
        def updateFee(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.fee = params.newFee

        @sp.entrypoint()
        def updateMaxRandoms(self, params):
            assert sp.sender == self.data.admin, "not admin"
            self.data.maxRandomsPerRequest = params.newMax


@sp.add_test()
def test():
    s = sp.test_scenario("RandomOracle v2 deploy", main)
    s.h1("Originate RandomOracle")
    oracle = main.RandomOracle()
    s += oracle
