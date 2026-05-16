import smartpy as sp

# ─── Reference dApp: CoinFlip using RandomOracle v3 ──────────────────────
#
# Minimal end-to-end example showing how a 3rd-party contract integrates
# with the v3 RandomOracle. ~80 lines of contract + comments.
#
# v3 flow:
#   1. flip(userNonce, commitId) — user calls; we forward the oracle fee
#      plus a request for one nat in [0,1]. userNonce mixes into the seed
#      so the operator can't pre-pick a preimage that favors a result.
#      commitId picks a still-sealed commit from the oracle's commit log;
#      the dApp queries the oracle off-chain to find the newest one.
#      callbackContext echoes back to onRandomFulfilled — we use it to
#      assert "this is the response to OUR pending flip" without trusting
#      the auto-incremented requestId.
#   2. onRandomFulfilled(requestId, randomValues, callbackContext) — the
#      oracle invokes this callback once its commit is revealed. Only the
#      oracle contract address can call it (we verify sp.sender). We
#      record the result and unblock future flips.
#
# Customize the parts marked CONFIG. Everything else is the integration
# pattern you'd copy-paste into your own dApp. See docs/V3_COMMIT_REVEAL.md
# for the cryptographic model.

@sp.module
def main():
    class CoinFlipDApp(sp.Contract):
        def __init__(self):
            # ─── CONFIG ──────────────────────────────────────────────
            # Address of the deployed RandomOracle (placeholder — replace
            # with the live address from src/constants.js after first deploy).
            self.data.oracleContract = sp.address(
                "KT19V1YiyPtyCbxouhyeM96SekRTVC7Gw6qq"
            )
            # Fee you'll forward to the oracle. Must be >= oracle.fee.
            self.data.oracleFee = sp.mutez(100000)
            # ─── /CONFIG ─────────────────────────────────────────────

            # Game state.
            self.data.lastFlipper = sp.address(
                "tz1burnburnburnburnburnburnburjAYjjX"
            )
            self.data.lastResult = sp.nat(99)       # 99 = "no flip yet"
            self.data.lastRequestId = sp.nat(0)
            self.data.pending = False               # one flip at a time

        @sp.entrypoint
        def default(self):
            '''Anonymous top-ups. Useful for funding the per-flip oracle fee
            so users don't have to attach it themselves on every call.'''
            pass

        @sp.entrypoint()
        def flip(self, params):
            '''Trigger a coin flip. Forwards a request for one nat in [0,1]
            to the v3 oracle. The result lands in onRandomFulfilled later.

            Caller supplies:
              userNonce (32 bytes recommended) — mixes into the seed.
              commitId — a still-sealed commit from the oracle's commit log
                that's at least minCommitAge blocks old. dApp picks the
                newest eligible one by querying the oracle's storage.'''
            sp.cast(params.userNonce, sp.bytes)
            sp.cast(params.commitId, sp.nat)
            assert not self.data.pending, "flip already in flight"

            oracle = sp.contract(sp.record(callback=sp.address, nRandoms=sp.nat, maxValue=sp.nat, userNonce=sp.bytes, commitId=sp.nat, callbackContext=sp.bytes), self.data.oracleContract, entrypoint="requestRandom").unwrap_some(error="oracle contract not found")
            # callbackContext = pack(sender) so we can assert in the
            # callback that this is the response to OUR pending flip
            # (not someone else's stray fulfillment). Single-flight here,
            # so the pending guard alone is enough, but it shows the
            # general pattern.
            ctx = sp.pack(sp.sender)
            sp.transfer(sp.record(callback=sp.self_address, nRandoms=sp.nat(1), maxValue=sp.nat(1), userNonce=params.userNonce, commitId=params.commitId, callbackContext=ctx), self.data.oracleFee, oracle)
            self.data.lastFlipper = sp.sender
            self.data.pending = True
            sp.emit(sp.sender, tag='flipRequested')

        @sp.entrypoint()
        def onRandomFulfilled(self, params):
            '''Receive the randomness from the oracle. The oracle calls this
            with (requestId, randomValues, callbackContext).

            CRITICAL: only the oracle contract may call this — anyone else
            could spoof a result. Always sp.sender check.'''
            sp.cast(params.requestId, sp.nat)
            sp.cast(params.randomValues, sp.list[sp.nat])
            sp.cast(params.callbackContext, sp.bytes)
            assert sp.sender == self.data.oracleContract, "not oracle"
            # We requested nRandoms=1, so grab the (only) value.
            value = sp.nat(0)
            for v in params.randomValues:
                value = v
            self.data.lastResult = value
            self.data.lastRequestId = params.requestId
            self.data.pending = False
            sp.emit(sp.record(requestId=params.requestId, value=value), tag='flipResult')


@sp.add_test()
def test():
    s = sp.test_scenario("CoinFlip v3 reference dApp deploy", main)
    s.h1("Originate CoinFlipDApp (v3)")
    c = main.CoinFlipDApp()
    s += c
