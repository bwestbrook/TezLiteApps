import smartpy as sp

# ─── Reference dApp: CoinFlip using RandomOracle ─────────────────────────
#
# Minimal end-to-end example showing how a 3rd-party contract integrates
# with the TezLiteApps RandomOracle. ~60 lines of contract + comments.
#
# Flow:
#   1. flip() — user calls; we forward the oracle fee plus a request for
#      one nat in [0, 1]. We block further flips until the result lands.
#   2. onRandomFulfilled(...) — the oracle invokes this callback with our
#      result. Only the oracle contract can call it (we verify sp.sender).
#      We record the result and unblock future flips.
#
# Customize the parts marked CONFIG. Everything else is the integration
# contract you'd copy-paste into your own dApp.

@sp.module
def main():
    class CoinFlipDApp(sp.Contract):
        def __init__(self):
            # ─── CONFIG ──────────────────────────────────────────────
            # Address of the deployed RandomOracle (shadownet here —
            # replace with the mainnet address when shipping):
            self.data.oracleContract = sp.address(
                "KT19V1YiyPtyCbxouhyeM96SekRTVC7Gw6qq"
            )
            # Fee you'll forward to the oracle. Must be >= oracle.fee.
            self.data.oracleFee = sp.mutez(100000)
            # The oracle's tz1 key — we use this for an extra
            # "only the oracle contract can call our callback" check.
            # (sp.sender == oracleContract address is the real guard;
            # this is purely informational.)
            self.data.oracleAddress = sp.address(
                "KT19V1YiyPtyCbxouhyeM96SekRTVC7Gw6qq"
            )
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
        def flip(self):
            '''Trigger a coin flip. Requests one nat in [0, 1] from the
            oracle. The result lands in onRandomFulfilled() asynchronously.'''
            assert not self.data.pending, "flip already in flight"
            # Forward the fee + our callback details to the oracle.
            oracle = sp.contract(
                sp.record(
                    callback=sp.address,
                    callbackEntrypoint=sp.string,
                    nRandoms=sp.nat,
                    maxValue=sp.nat,
                ),
                self.data.oracleContract,
                entrypoint="requestRandom",
            ).unwrap_some(error="oracle contract not found")
            sp.transfer(
                sp.record(
                    callback=sp.self_address,
                    callbackEntrypoint="onRandomFulfilled",
                    nRandoms=1,
                    maxValue=1,             # 0 or 1 — actual coin flip
                ),
                self.data.oracleFee,
                oracle,
            )
            self.data.lastFlipper = sp.sender
            self.data.pending = True
            sp.emit(sp.sender, tag='flipRequested')

        @sp.entrypoint()
        def onRandomFulfilled(self, params):
            '''Receive the randomness from the oracle. The oracle contract
            calls this with the agreed shape: (requestId, randomValues).

            CRITICAL: only the oracle contract may call this — anyone else
            could spoof a result. Always sp.sender check.'''
            sp.cast(params.requestId, sp.nat)
            sp.cast(params.randomValues, sp.list[sp.nat])
            assert sp.sender == self.data.oracleContract, "not oracle"
            # We requested nRandoms=1, so grab the first (and only) value.
            value = sp.nat(0)
            for v in params.randomValues:
                value = v
            self.data.lastResult = value
            self.data.lastRequestId = params.requestId
            self.data.pending = False
            sp.emit([params.requestId, value], tag='flipResult')


@sp.add_test()
def test():
    s = sp.test_scenario("CoinFlip reference dApp deploy", main)
    s.h1("Originate CoinFlipDApp")
    c = main.CoinFlipDApp()
    s += c
