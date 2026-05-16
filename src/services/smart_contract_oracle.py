import smartpy as sp

# ─── RandomOracle (v3 — commit-reveal + user-contributed entropy) ─────────
#
# Trustless randomness service for Tezos. Three-phase commit-reveal:
#
#   0. (continuous)  oracle posts hash(preimage) commits on a rolling
#      schedule via postCommit(). Each commit becomes binding for new
#      requests after `minCommitAge` blocks.
#   1. requester contract calls requestRandom(callback, callbackEntrypoint,
#      nRandoms, maxValue, userNonce, commitId, callbackContext) and
#      attaches at least `fee` ꜩ. The request binds to `commitId` which
#      must (a) exist, (b) be at least minCommitAge blocks old, and
#      (c) NOT yet be revealed. userNonce is 32 bytes of caller-supplied
#      entropy. callbackContext is opaque bytes echoed back in the callback
#      so the caller can correlate the response with its own state without
#      needing to know the auto-incremented requestId at submit time.
#   2. oracle reveals the preimage via revealCommit(commitId, preimage).
#      The contract checks sha256(preimage) == hash so the oracle can only
#      publish what it committed to.
#   3. ANYONE calls fulfillRandom(requestId). Contract derives
#         finalSeed = sha256(preimage || userNonce || pack(requestId))
#         value[0] = bytes_to_nat(finalSeed)               mod (maxValue+1)
#         value[i] = bytes_to_nat(sha256(finalSeed || pack(i))) mod (maxValue+1)
#      and invokes the caller's callback with the derived values plus the
#      original callbackContext bytes.
#
# Fairness property: at commit time the oracle didn't know what userNonce
# the next request would carry. At request time the bound commit was
# already on chain (postedAtBlock + minCommitAge <= sp.level) so its
# hash was visible to the player before they signed. Neither side can
# adaptively pick to favor a particular outcome. The preimage uniquely
# determines the result, and any third party can re-derive it from
# (preimage, userNonce, requestId) — all of which live on chain.
#
# Threat / design notes are in docs/V3_COMMIT_REVEAL.md. The "saturation"
# attack (a single commit binding many requests, giving the oracle a
# single preimage choice that drives many outcomes) is mitigated
# OFF-chain via per-commit binding histograms + alerting — keeping it
# off-chain so this contract stays simple. See V3 doc §monitoring.
#
# Callback contract requirements:
#
#   @sp.entrypoint
#   def onRandomFulfilled(self, params):
#       sp.cast(params.requestId, sp.nat)
#       sp.cast(params.randomValues, sp.list[sp.nat])
#       sp.cast(params.callbackContext, sp.bytes)
#       assert sp.sender == self.data.oracleContract, "not oracle"
#       # ... use params.randomValues, dispatch via callbackContext ...
#
# See docs/ORACLE_INTEGRATION.md for the integration walkthrough.

CALLBACK_PARAM_TYPE = sp.record(
    requestId=sp.nat,
    randomValues=sp.list[sp.nat],
    callbackContext=sp.bytes,
)


@sp.module
def main():
    class RandomOracle(sp.Contract):
        def __init__(self):
            # Admin: can change oracle key, fee, bounds, withdraw earnings.
            # Oracle: the off-chain worker's signing key — posts commits
            # and reveals preimages. fulfillRandom is permissionless.
            self.data.admin = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")
            self.data.oracle = sp.address("tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q")

            # Minimum payment per request. Operator keeps whatever's
            # actually paid (over-pay is treated as a tip).
            self.data.fee = sp.mutez(100000)        # 0.1 ꜩ default

            # Cap on draws per single request — keeps the value-derivation
            # loop in fulfillRandom gas-predictable. Hardcoded at 32 here;
            # the loop in fulfillRandom unrolls to exactly 32 iterations.
            # If you bump this, also widen the `for k in range(32)` loop.
            self.data.maxRandomsPerRequest = sp.nat(32)

            # How many blocks a commit must age before it can bind to a
            # new request. minCommitAge=1 means "the commit was on chain
            # in a prior block, so the player saw it before signing."
            # Tunable: raising it widens the attest-to-bind window, which
            # is good for cross-network audit but slows latency.
            self.data.minCommitAge = sp.nat(1)

            # Operator earnings pool — accumulates feePaid on every
            # fulfilled request, swept by admin via withdrawEarnings.
            self.data.operatorEarnings = sp.mutez(0)

            # Monotonic counters.
            self.data.currentRequestId = sp.nat(0)
            self.data.currentCommitId = sp.nat(0)

            # Commit log. Each entry: oracle's sha256(preimage), the
            # block it was posted at, and the revealed preimage (empty
            # bytes until reveal). Keyed by monotonic commitId.
            self.data.commitLog = sp.cast({}, sp.map[sp.nat, sp.record(
                hash=sp.bytes,
                postedAtBlock=sp.nat,
                revealedPreimage=sp.bytes,   # 0x until revealed
            )])

            # Requests. Stores everything needed for permissionless
            # fulfillment + post-hoc verification by anyone.
            #
            # requestStatus:
            #   0 = pending
            #   1 = fulfilled (callback invoked successfully)
            #   2 = cancelled (admin reclaim — future use)
            self.data.requests = sp.cast({}, sp.map[sp.nat, sp.record(
                requester=sp.address,
                callback=sp.address,
                callbackEntrypoint=sp.string,
                nRandoms=sp.nat,
                maxValue=sp.nat,
                feePaid=sp.mutez,
                requestStatus=sp.nat,
                requestTime=sp.timestamp,
                fulfillTime=sp.timestamp,
                randomValues=sp.list[sp.nat],
                commitId=sp.nat,              # bound commit
                userNonce=sp.bytes,           # caller-supplied entropy
                callbackContext=sp.bytes,     # echoed to callback
                requestBlock=sp.nat,          # sp.level at request time
                finalSeed=sp.bytes,           # filled at fulfill
            )])

            # Byte→nat lookup table, populated once at origination. Used
            # in fulfillRandom to interpret SHA-256 output bytes as a
            # big-endian nat for `mod (maxValue+1)`. 256 entries × ~32 B
            # ≈ 8 kB of one-time storage; the alternative (no primitive
            # for bytes→nat in current SmartPy) would be an unrolled
            # nibble-shift inline at every call site. See V3 doc.
            self.data.byteLookup = sp.cast(
                {sp.bytes('0x%02x' % i): sp.nat(i) for i in range(256)},
                sp.map[sp.bytes, sp.nat],
            )

        # ─── Funding ────────────────────────────────────────────────
        @sp.entrypoint
        def default(self):
            '''Anonymous top-up — supports the operator earnings pool.'''
            self.data.operatorEarnings += sp.amount

        # ─── Oracle: rolling commit schedule ────────────────────────
        @sp.entrypoint()
        def postCommit(self, params):
            '''Oracle-only. Append `sha256(preimage)` to the commit log.
            The off-chain worker keeps the preimage in its local journal
            (~/.tezliteapps/commits.json) and reveals it later via
            revealCommit. A commit becomes bindable for new requests
            after minCommitAge blocks. Checklist §1.1, §3.3, §8.3.'''
            sp.cast(params.hash, sp.bytes)
            assert sp.sender == self.data.oracle, "not oracle"
            empty_bytes = sp.bytes('0x')
            self.data.commitLog[self.data.currentCommitId] = sp.record(
                hash=params.hash,
                postedAtBlock=sp.as_nat(sp.level),
                revealedPreimage=empty_bytes,
            )
            sp.emit(
                [self.data.currentCommitId,
                 params.hash,
                 sp.as_nat(sp.level)],
                tag='commitPosted',
            )
            self.data.currentCommitId += 1

        @sp.entrypoint()
        def revealCommit(self, params):
            '''Oracle-only. Publish the preimage for `commitId`. The
            contract verifies sha256(preimage) matches the committed
            hash — the oracle's only safe move is to publish the same
            preimage it committed to. Once revealed, ANY caller can
            call fulfillRandom on any request bound to this commit.
            Checklist §1.1, §6.2, §7.2, §8.3.'''
            sp.cast(params.commitId, sp.nat)
            sp.cast(params.preimage, sp.bytes)
            assert sp.sender == self.data.oracle, "not oracle"
            assert self.data.commitLog.contains(params.commitId), "no such commit"
            entry = self.data.commitLog[params.commitId]
            empty_bytes = sp.bytes('0x')
            assert entry.revealedPreimage == empty_bytes, "already revealed"
            assert sp.sha256(params.preimage) == entry.hash, "preimage mismatch"
            self.data.commitLog[params.commitId].revealedPreimage = params.preimage
            sp.emit(
                [params.commitId, params.preimage],
                tag='commitRevealed',
            )

        # ─── Public: request randomness ─────────────────────────────
        @sp.entrypoint()
        def requestRandom(self, params):
            '''Bind a new randomness request to a still-sealed commit.

            Requirements:
              - sp.amount >= fee
              - 1 <= nRandoms <= maxRandomsPerRequest
              - maxValue >= 1
              - commitId exists, age >= minCommitAge, NOT yet revealed
              - userNonce: caller-supplied bytes (32 B recommended). Mixed
                into finalSeed so the oracle's commit choice can't favor
                any specific request — at commit time it didn't know
                what userNonce the requester would attach.
              - callbackContext: opaque bytes the contract echoes back in
                the callback (lets the requester correlate the response
                with its own state — gameId+phase, roundId, etc. —
                without needing a synchronous view to grab the
                auto-incremented requestId at submit time).
            Checklist §1.1, §1.4, §2.1, §3.3, §6.2, §7.2, §8.3.'''
            sp.cast(params.callback, sp.address)
            sp.cast(params.callbackEntrypoint, sp.string)
            sp.cast(params.nRandoms, sp.nat)
            sp.cast(params.maxValue, sp.nat)
            sp.cast(params.userNonce, sp.bytes)
            sp.cast(params.commitId, sp.nat)
            sp.cast(params.callbackContext, sp.bytes)
            assert sp.amount >= self.data.fee, "fee too low"
            assert params.nRandoms >= 1, "nRandoms must be >= 1"
            assert params.nRandoms <= self.data.maxRandomsPerRequest, "nRandoms too large"
            assert params.maxValue >= 1, "maxValue must be >= 1"
            assert self.data.commitLog.contains(params.commitId), "unknown commit"
            commit = self.data.commitLog[params.commitId]
            level_nat = sp.as_nat(sp.level)
            # Reject commits posted too recently to have been seen by the
            # player when they signed (defends against an oracle posting a
            # commit AFTER seeing a mempool request).
            assert level_nat >= commit.postedAtBlock + self.data.minCommitAge, "commit too fresh"
            empty_bytes = sp.bytes('0x')
            # Reject commits already revealed — binding a request to a
            # revealed commit would let any caller pre-compute the result
            # and skip the request entirely.
            assert commit.revealedPreimage == empty_bytes, "commit already revealed"

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
                commitId=params.commitId,
                userNonce=params.userNonce,
                callbackContext=params.callbackContext,
                requestBlock=level_nat,
                finalSeed=empty_bytes,
            )
            sp.emit(
                [self.data.currentRequestId,
                 params.nRandoms,
                 params.maxValue,
                 params.commitId],
                tag='randomRequested',
            )
            self.data.currentRequestId += 1

        # ─── Public: fulfill (permissionless, post-reveal) ──────────
        @sp.entrypoint()
        def fulfillRandom(self, params):
            '''Anyone (not just the oracle) can settle a pending request
            once its bound commit has been revealed. Computes finalSeed
            and derives random values deterministically from on-chain
            inputs alone, so any third party can re-derive and verify.
            Checklist §1.4, §3.3, §4.1, §6.1, §6.2, §7.2, §8.3.'''
            sp.cast(params.requestId, sp.nat)
            assert self.data.requests.contains(params.requestId), "no such request"
            r = self.data.requests[params.requestId]
            assert r.requestStatus == 0, "already settled"

            commit = self.data.commitLog[r.commitId]
            empty_bytes = sp.bytes('0x')
            assert commit.revealedPreimage != empty_bytes, "commit not yet revealed"

            # finalSeed = sha256(preimage ++ userNonce ++ pack(requestId))
            seed = sp.sha256(commit.revealedPreimage + r.userNonce + sp.pack(params.requestId))

            # Derive nRandoms values. value[0] = bytes_to_nat(seed) mod (maxValue+1).
            # value[i>=1] = bytes_to_nat(sha256(seed ++ pack(i))) mod (maxValue+1).
            # Loop is hard-bounded at compile time to maxRandomsPerRequest (32)
            # with a runtime guard `if sp.nat(k) < r.nRandoms`. Inner byte
            # loop unrolls to 32 iterations (one per SHA-256 output byte).
            divisor = r.maxValue + 1
            vals_rev = sp.cast([], sp.list[sp.nat])
            for k in range(32):
                if sp.nat(k) < r.nRandoms:
                    if k == 0:
                        chunk = seed
                    else:
                        chunk = sp.sha256(seed + sp.pack(sp.nat(k)))
                    # Big-endian 32-byte chunk → nat via byte lookup.
                    acc = sp.nat(0)
                    for j in range(32):
                        byte_bytes = sp.slice(chunk, j, 1).unwrap_some(error="slice")
                        acc = acc * 256 + self.data.byteLookup[byte_bytes]
                    vals_rev = sp.cons(acc % divisor, vals_rev)
            # cons builds reverse-order; flip once to get ascending [0..n-1].
            values = sp.cast([], sp.list[sp.nat])
            for v in vals_rev:
                values = sp.cons(v, values)

            # §4.1 — record settled state before sending or invoking
            # the callback. Credit the operator pool with feePaid.
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
                randomValues=values,
                commitId=r.commitId,
                userNonce=r.userNonce,
                callbackContext=r.callbackContext,
                requestBlock=r.requestBlock,
                finalSeed=seed,
            )

            # Invoke the requester's callback. Callback must accept:
            #   sp.record(requestId=sp.nat,
            #             randomValues=sp.list[sp.nat],
            #             callbackContext=sp.bytes)
            # Callback should also `assert sp.sender == oracleContract` so
            # nobody else can spoof results.
            callback_record = sp.record(
                requestId=params.requestId,
                randomValues=values,
                callbackContext=r.callbackContext,
            )
            callback_contract = sp.contract(
                sp.record(
                    requestId=sp.nat,
                    randomValues=sp.list[sp.nat],
                    callbackContext=sp.bytes,
                ),
                r.callback,
                entrypoint=r.callbackEntrypoint,
            ).unwrap_some(error="callback not a contract or wrong entrypoint type")
            sp.transfer(callback_record, sp.mutez(0), callback_contract)

            sp.emit(
                [params.requestId, values],
                tag='randomFulfilled',
            )

        # ─── Admin: payouts + parameter tuning ──────────────────────
        @sp.entrypoint()
        def withdrawEarnings(self, params):
            '''Send accumulated operator earnings to the admin (or any
            recipient the admin names). Resets the pool to zero.
            Checklist §1.1, §2.2.'''
            sp.cast(params.recipient, sp.address)
            assert sp.sender == self.data.admin, "not admin"
            assert self.data.operatorEarnings > sp.mutez(0), "nothing to withdraw"
            sp.send(params.recipient, self.data.operatorEarnings)
            self.data.operatorEarnings = sp.mutez(0)

        @sp.entrypoint()
        def updateAdmin(self, params):
            '''Admin-only: rotate the admin key. Single-step; the only
            recovery path if the deployer key is lost or compromised.
            Checklist §1.1, §1.2.'''
            sp.cast(params.newAdmin, sp.address)
            assert sp.sender == self.data.admin, "not admin"
            self.data.admin = params.newAdmin

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
            '''If you raise this above 32, also widen the unrolled loop
            in fulfillRandom — it currently compiles 32 branches.'''
            assert sp.sender == self.data.admin, "not admin"
            assert params.newMax <= sp.nat(32), "loop unrolled at 32; widen first"
            self.data.maxRandomsPerRequest = params.newMax

        @sp.entrypoint()
        def updateMinCommitAge(self, params):
            '''Tune how many blocks a commit must age before it can bind
            to a new request. Higher = stronger pre-publication property
            (cross-zone audit can witness the commit before any request
            binds), at the cost of latency for new requests.'''
            sp.cast(params.newAge, sp.nat)
            assert sp.sender == self.data.admin, "not admin"
            self.data.minCommitAge = params.newAge

        # ─── Storage hygiene (§3.1) ─────────────────────────────────
        @sp.entrypoint()
        def pruneRequest(self, params):
            '''Admin-only: delete a settled request record to reclaim
            storage. Emits the full pre-prune record so off-chain
            indexers can keep the audit trail. Checklist §3.1, §8.3.'''
            sp.cast(params.requestId, sp.nat)
            assert sp.sender == self.data.admin, "not admin"
            r = self.data.requests[params.requestId]
            assert r.requestStatus != 0, "request not settled"
            sp.emit(r, tag='requestPruned')
            del self.data.requests[params.requestId]

        @sp.entrypoint()
        def pruneCommit(self, params):
            '''Admin-only: delete a revealed commit to reclaim storage.
            Only revealed commits can be pruned — a pending commit might
            still bind to in-flight requests. Checklist §3.1, §8.3.'''
            sp.cast(params.commitId, sp.nat)
            assert sp.sender == self.data.admin, "not admin"
            c = self.data.commitLog[params.commitId]
            empty_bytes = sp.bytes('0x')
            assert c.revealedPreimage != empty_bytes, "commit not revealed"
            sp.emit(c, tag='commitPruned')
            del self.data.commitLog[params.commitId]


@sp.add_test()
def test():
    s = sp.test_scenario("RandomOracle v3 deploy", main)
    s.h1("Originate RandomOracle (v3 commit-reveal)")
    oracle = main.RandomOracle()
    s += oracle
