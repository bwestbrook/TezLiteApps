import smartpy as sp

# ─── RandomOracle (v3 — commit-reveal + user-contributed entropy) ─────────
#
# Trustless randomness service for Tezos. Three-phase commit-reveal:
#
#   0. (continuous)  oracle posts hash(preimage) commits on a rolling
#      schedule via postCommit(). Each commit becomes binding for new
#      requests after `minCommitAge` blocks.
#   1. requester contract calls requestRandom(callback, nRandoms, maxValue,
#      userNonce, commitId, callbackContext) and attaches at least `fee` ꜩ.
#      The callback contract MUST expose an entrypoint named
#      `onRandomFulfilled` — the name is fixed at the contract level
#      because SmartPy's `sp.contract(..., entrypoint=…)` requires a
#      compile-time string literal. The request binds to `commitId` which
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
            # NOTE: mainnet build. Mirrors TXL's split-key pattern —
            # admin (cold/deploy key) ≠ oracle (hot worker key). Revert
            # this line to admin's address before any shadownet rebuild
            # so shadownet doesn't ship the mainnet worker key as oracle.
            # See task 12 in the AD deploy plan.
            self.data.oracle = sp.address("tz1QtpR6hraURtjP9V1rMMYnrqfyaicJFPWv")

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
                callback=sp.address,          # must expose `onRandomFulfilled`
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
            # for bytes→nat in current SmartPy and no dict comprehensions
            # accepted inside @sp.module) would be an unrolled nibble
            # decoder inline at every call site. See V3 doc.
            self.data.byteLookup = {
                sp.bytes('0x00'): sp.nat(  0), sp.bytes('0x01'): sp.nat(  1), sp.bytes('0x02'): sp.nat(  2), sp.bytes('0x03'): sp.nat(  3),
                sp.bytes('0x04'): sp.nat(  4), sp.bytes('0x05'): sp.nat(  5), sp.bytes('0x06'): sp.nat(  6), sp.bytes('0x07'): sp.nat(  7),
                sp.bytes('0x08'): sp.nat(  8), sp.bytes('0x09'): sp.nat(  9), sp.bytes('0x0a'): sp.nat( 10), sp.bytes('0x0b'): sp.nat( 11),
                sp.bytes('0x0c'): sp.nat( 12), sp.bytes('0x0d'): sp.nat( 13), sp.bytes('0x0e'): sp.nat( 14), sp.bytes('0x0f'): sp.nat( 15),
                sp.bytes('0x10'): sp.nat( 16), sp.bytes('0x11'): sp.nat( 17), sp.bytes('0x12'): sp.nat( 18), sp.bytes('0x13'): sp.nat( 19),
                sp.bytes('0x14'): sp.nat( 20), sp.bytes('0x15'): sp.nat( 21), sp.bytes('0x16'): sp.nat( 22), sp.bytes('0x17'): sp.nat( 23),
                sp.bytes('0x18'): sp.nat( 24), sp.bytes('0x19'): sp.nat( 25), sp.bytes('0x1a'): sp.nat( 26), sp.bytes('0x1b'): sp.nat( 27),
                sp.bytes('0x1c'): sp.nat( 28), sp.bytes('0x1d'): sp.nat( 29), sp.bytes('0x1e'): sp.nat( 30), sp.bytes('0x1f'): sp.nat( 31),
                sp.bytes('0x20'): sp.nat( 32), sp.bytes('0x21'): sp.nat( 33), sp.bytes('0x22'): sp.nat( 34), sp.bytes('0x23'): sp.nat( 35),
                sp.bytes('0x24'): sp.nat( 36), sp.bytes('0x25'): sp.nat( 37), sp.bytes('0x26'): sp.nat( 38), sp.bytes('0x27'): sp.nat( 39),
                sp.bytes('0x28'): sp.nat( 40), sp.bytes('0x29'): sp.nat( 41), sp.bytes('0x2a'): sp.nat( 42), sp.bytes('0x2b'): sp.nat( 43),
                sp.bytes('0x2c'): sp.nat( 44), sp.bytes('0x2d'): sp.nat( 45), sp.bytes('0x2e'): sp.nat( 46), sp.bytes('0x2f'): sp.nat( 47),
                sp.bytes('0x30'): sp.nat( 48), sp.bytes('0x31'): sp.nat( 49), sp.bytes('0x32'): sp.nat( 50), sp.bytes('0x33'): sp.nat( 51),
                sp.bytes('0x34'): sp.nat( 52), sp.bytes('0x35'): sp.nat( 53), sp.bytes('0x36'): sp.nat( 54), sp.bytes('0x37'): sp.nat( 55),
                sp.bytes('0x38'): sp.nat( 56), sp.bytes('0x39'): sp.nat( 57), sp.bytes('0x3a'): sp.nat( 58), sp.bytes('0x3b'): sp.nat( 59),
                sp.bytes('0x3c'): sp.nat( 60), sp.bytes('0x3d'): sp.nat( 61), sp.bytes('0x3e'): sp.nat( 62), sp.bytes('0x3f'): sp.nat( 63),
                sp.bytes('0x40'): sp.nat( 64), sp.bytes('0x41'): sp.nat( 65), sp.bytes('0x42'): sp.nat( 66), sp.bytes('0x43'): sp.nat( 67),
                sp.bytes('0x44'): sp.nat( 68), sp.bytes('0x45'): sp.nat( 69), sp.bytes('0x46'): sp.nat( 70), sp.bytes('0x47'): sp.nat( 71),
                sp.bytes('0x48'): sp.nat( 72), sp.bytes('0x49'): sp.nat( 73), sp.bytes('0x4a'): sp.nat( 74), sp.bytes('0x4b'): sp.nat( 75),
                sp.bytes('0x4c'): sp.nat( 76), sp.bytes('0x4d'): sp.nat( 77), sp.bytes('0x4e'): sp.nat( 78), sp.bytes('0x4f'): sp.nat( 79),
                sp.bytes('0x50'): sp.nat( 80), sp.bytes('0x51'): sp.nat( 81), sp.bytes('0x52'): sp.nat( 82), sp.bytes('0x53'): sp.nat( 83),
                sp.bytes('0x54'): sp.nat( 84), sp.bytes('0x55'): sp.nat( 85), sp.bytes('0x56'): sp.nat( 86), sp.bytes('0x57'): sp.nat( 87),
                sp.bytes('0x58'): sp.nat( 88), sp.bytes('0x59'): sp.nat( 89), sp.bytes('0x5a'): sp.nat( 90), sp.bytes('0x5b'): sp.nat( 91),
                sp.bytes('0x5c'): sp.nat( 92), sp.bytes('0x5d'): sp.nat( 93), sp.bytes('0x5e'): sp.nat( 94), sp.bytes('0x5f'): sp.nat( 95),
                sp.bytes('0x60'): sp.nat( 96), sp.bytes('0x61'): sp.nat( 97), sp.bytes('0x62'): sp.nat( 98), sp.bytes('0x63'): sp.nat( 99),
                sp.bytes('0x64'): sp.nat(100), sp.bytes('0x65'): sp.nat(101), sp.bytes('0x66'): sp.nat(102), sp.bytes('0x67'): sp.nat(103),
                sp.bytes('0x68'): sp.nat(104), sp.bytes('0x69'): sp.nat(105), sp.bytes('0x6a'): sp.nat(106), sp.bytes('0x6b'): sp.nat(107),
                sp.bytes('0x6c'): sp.nat(108), sp.bytes('0x6d'): sp.nat(109), sp.bytes('0x6e'): sp.nat(110), sp.bytes('0x6f'): sp.nat(111),
                sp.bytes('0x70'): sp.nat(112), sp.bytes('0x71'): sp.nat(113), sp.bytes('0x72'): sp.nat(114), sp.bytes('0x73'): sp.nat(115),
                sp.bytes('0x74'): sp.nat(116), sp.bytes('0x75'): sp.nat(117), sp.bytes('0x76'): sp.nat(118), sp.bytes('0x77'): sp.nat(119),
                sp.bytes('0x78'): sp.nat(120), sp.bytes('0x79'): sp.nat(121), sp.bytes('0x7a'): sp.nat(122), sp.bytes('0x7b'): sp.nat(123),
                sp.bytes('0x7c'): sp.nat(124), sp.bytes('0x7d'): sp.nat(125), sp.bytes('0x7e'): sp.nat(126), sp.bytes('0x7f'): sp.nat(127),
                sp.bytes('0x80'): sp.nat(128), sp.bytes('0x81'): sp.nat(129), sp.bytes('0x82'): sp.nat(130), sp.bytes('0x83'): sp.nat(131),
                sp.bytes('0x84'): sp.nat(132), sp.bytes('0x85'): sp.nat(133), sp.bytes('0x86'): sp.nat(134), sp.bytes('0x87'): sp.nat(135),
                sp.bytes('0x88'): sp.nat(136), sp.bytes('0x89'): sp.nat(137), sp.bytes('0x8a'): sp.nat(138), sp.bytes('0x8b'): sp.nat(139),
                sp.bytes('0x8c'): sp.nat(140), sp.bytes('0x8d'): sp.nat(141), sp.bytes('0x8e'): sp.nat(142), sp.bytes('0x8f'): sp.nat(143),
                sp.bytes('0x90'): sp.nat(144), sp.bytes('0x91'): sp.nat(145), sp.bytes('0x92'): sp.nat(146), sp.bytes('0x93'): sp.nat(147),
                sp.bytes('0x94'): sp.nat(148), sp.bytes('0x95'): sp.nat(149), sp.bytes('0x96'): sp.nat(150), sp.bytes('0x97'): sp.nat(151),
                sp.bytes('0x98'): sp.nat(152), sp.bytes('0x99'): sp.nat(153), sp.bytes('0x9a'): sp.nat(154), sp.bytes('0x9b'): sp.nat(155),
                sp.bytes('0x9c'): sp.nat(156), sp.bytes('0x9d'): sp.nat(157), sp.bytes('0x9e'): sp.nat(158), sp.bytes('0x9f'): sp.nat(159),
                sp.bytes('0xa0'): sp.nat(160), sp.bytes('0xa1'): sp.nat(161), sp.bytes('0xa2'): sp.nat(162), sp.bytes('0xa3'): sp.nat(163),
                sp.bytes('0xa4'): sp.nat(164), sp.bytes('0xa5'): sp.nat(165), sp.bytes('0xa6'): sp.nat(166), sp.bytes('0xa7'): sp.nat(167),
                sp.bytes('0xa8'): sp.nat(168), sp.bytes('0xa9'): sp.nat(169), sp.bytes('0xaa'): sp.nat(170), sp.bytes('0xab'): sp.nat(171),
                sp.bytes('0xac'): sp.nat(172), sp.bytes('0xad'): sp.nat(173), sp.bytes('0xae'): sp.nat(174), sp.bytes('0xaf'): sp.nat(175),
                sp.bytes('0xb0'): sp.nat(176), sp.bytes('0xb1'): sp.nat(177), sp.bytes('0xb2'): sp.nat(178), sp.bytes('0xb3'): sp.nat(179),
                sp.bytes('0xb4'): sp.nat(180), sp.bytes('0xb5'): sp.nat(181), sp.bytes('0xb6'): sp.nat(182), sp.bytes('0xb7'): sp.nat(183),
                sp.bytes('0xb8'): sp.nat(184), sp.bytes('0xb9'): sp.nat(185), sp.bytes('0xba'): sp.nat(186), sp.bytes('0xbb'): sp.nat(187),
                sp.bytes('0xbc'): sp.nat(188), sp.bytes('0xbd'): sp.nat(189), sp.bytes('0xbe'): sp.nat(190), sp.bytes('0xbf'): sp.nat(191),
                sp.bytes('0xc0'): sp.nat(192), sp.bytes('0xc1'): sp.nat(193), sp.bytes('0xc2'): sp.nat(194), sp.bytes('0xc3'): sp.nat(195),
                sp.bytes('0xc4'): sp.nat(196), sp.bytes('0xc5'): sp.nat(197), sp.bytes('0xc6'): sp.nat(198), sp.bytes('0xc7'): sp.nat(199),
                sp.bytes('0xc8'): sp.nat(200), sp.bytes('0xc9'): sp.nat(201), sp.bytes('0xca'): sp.nat(202), sp.bytes('0xcb'): sp.nat(203),
                sp.bytes('0xcc'): sp.nat(204), sp.bytes('0xcd'): sp.nat(205), sp.bytes('0xce'): sp.nat(206), sp.bytes('0xcf'): sp.nat(207),
                sp.bytes('0xd0'): sp.nat(208), sp.bytes('0xd1'): sp.nat(209), sp.bytes('0xd2'): sp.nat(210), sp.bytes('0xd3'): sp.nat(211),
                sp.bytes('0xd4'): sp.nat(212), sp.bytes('0xd5'): sp.nat(213), sp.bytes('0xd6'): sp.nat(214), sp.bytes('0xd7'): sp.nat(215),
                sp.bytes('0xd8'): sp.nat(216), sp.bytes('0xd9'): sp.nat(217), sp.bytes('0xda'): sp.nat(218), sp.bytes('0xdb'): sp.nat(219),
                sp.bytes('0xdc'): sp.nat(220), sp.bytes('0xdd'): sp.nat(221), sp.bytes('0xde'): sp.nat(222), sp.bytes('0xdf'): sp.nat(223),
                sp.bytes('0xe0'): sp.nat(224), sp.bytes('0xe1'): sp.nat(225), sp.bytes('0xe2'): sp.nat(226), sp.bytes('0xe3'): sp.nat(227),
                sp.bytes('0xe4'): sp.nat(228), sp.bytes('0xe5'): sp.nat(229), sp.bytes('0xe6'): sp.nat(230), sp.bytes('0xe7'): sp.nat(231),
                sp.bytes('0xe8'): sp.nat(232), sp.bytes('0xe9'): sp.nat(233), sp.bytes('0xea'): sp.nat(234), sp.bytes('0xeb'): sp.nat(235),
                sp.bytes('0xec'): sp.nat(236), sp.bytes('0xed'): sp.nat(237), sp.bytes('0xee'): sp.nat(238), sp.bytes('0xef'): sp.nat(239),
                sp.bytes('0xf0'): sp.nat(240), sp.bytes('0xf1'): sp.nat(241), sp.bytes('0xf2'): sp.nat(242), sp.bytes('0xf3'): sp.nat(243),
                sp.bytes('0xf4'): sp.nat(244), sp.bytes('0xf5'): sp.nat(245), sp.bytes('0xf6'): sp.nat(246), sp.bytes('0xf7'): sp.nat(247),
                sp.bytes('0xf8'): sp.nat(248), sp.bytes('0xf9'): sp.nat(249), sp.bytes('0xfa'): sp.nat(250), sp.bytes('0xfb'): sp.nat(251),
                sp.bytes('0xfc'): sp.nat(252), sp.bytes('0xfd'): sp.nat(253), sp.bytes('0xfe'): sp.nat(254), sp.bytes('0xff'): sp.nat(255),
            }

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
                postedAtBlock=sp.level,
                revealedPreimage=empty_bytes,
            )
            sp.emit(
                sp.record(
                    commitId=self.data.currentCommitId,
                    hash=params.hash,
                    postedAtBlock=sp.level,
                ),
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
            assert params.commitId in self.data.commitLog, "no such commit"
            entry = self.data.commitLog[params.commitId]
            empty_bytes = sp.bytes('0x')
            assert entry.revealedPreimage == empty_bytes, "already revealed"
            assert sp.sha256(params.preimage) == entry.hash, "preimage mismatch"
            self.data.commitLog[params.commitId].revealedPreimage = params.preimage
            sp.emit(
                sp.record(commitId=params.commitId, preimage=params.preimage),
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
              - callback must expose `onRandomFulfilled` entrypoint with
                signature (requestId=nat, randomValues=list[nat],
                callbackContext=bytes). The name is fixed at this
                contract level because SmartPy requires a compile-time
                literal for sp.contract(..., entrypoint=…).
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
            sp.cast(params.nRandoms, sp.nat)
            sp.cast(params.maxValue, sp.nat)
            sp.cast(params.userNonce, sp.bytes)
            sp.cast(params.commitId, sp.nat)
            sp.cast(params.callbackContext, sp.bytes)
            assert sp.amount >= self.data.fee, "fee too low"
            assert params.nRandoms >= 1, "nRandoms must be >= 1"
            assert params.nRandoms <= self.data.maxRandomsPerRequest, "nRandoms too large"
            assert params.maxValue >= 1, "maxValue must be >= 1"
            assert params.commitId in self.data.commitLog, "unknown commit"
            commit = self.data.commitLog[params.commitId]
            level_nat = sp.level
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
            assert params.requestId in self.data.requests, "no such request"
            r = self.data.requests[params.requestId]
            assert r.requestStatus == 0, "already settled"

            commit = self.data.commitLog[r.commitId]
            empty_bytes = sp.bytes('0x')
            assert commit.revealedPreimage != empty_bytes, "commit not yet revealed"

            # finalSeed = sha256(preimage ++ userNonce ++ pack(requestId))
            seed = sp.sha256(commit.revealedPreimage + r.userNonce + sp.pack(params.requestId))

            # Derive nRandoms values, uniformly:
            #   value[k] = bytes_to_nat(sha256(seed ++ pack(k))) mod (maxValue+1)
            # for k in [0, nRandoms). Uniform per-index hashing (instead of
            # the brief's "value[0] uses raw seed" variant) keeps the loop
            # uniform under SmartPy's compile-time unrolling — see V3 doc
            # for the derivation choice + rationale. Loop is hard-bounded
            # at compile time to maxRandomsPerRequest (32) with a runtime
            # guard `if k < r.nRandoms`. Inner byte loop unrolls 32
            # iterations (one per SHA-256 output byte).
            divisor = r.maxValue + 1
            vals_rev = sp.cast([], sp.list[sp.nat])
            for k in range(32):
                if k < r.nRandoms:
                    # k is a Python loop var (compile-time int) — sp.pack(k)
                    # bakes a constant per unrolled iteration.
                    chunk = sp.sha256(seed + sp.pack(k))
                    # Big-endian 32-byte chunk → nat via byte lookup.
                    acc = sp.nat(0)
                    for j in range(32):
                        byte_bytes = sp.slice(j, 1, chunk).unwrap_some(error="slice")
                        acc = acc * 256 + self.data.byteLookup[byte_bytes]
                    vals_rev = sp.cons(sp.mod(acc, divisor), vals_rev)
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
            callback_contract = sp.contract(sp.record(requestId=sp.nat, randomValues=sp.list[sp.nat], callbackContext=sp.bytes), r.callback, entrypoint="onRandomFulfilled").unwrap_some(error="callback not a contract or wrong entrypoint type")
            sp.transfer(callback_record, sp.mutez(0), callback_contract)

            sp.emit(
                sp.record(requestId=params.requestId, randomValues=values),
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
