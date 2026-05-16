import smartpy as sp


# Mint Time — one NFT per UTC minute on planet Earth.
#
# A buyer can claim a contiguous run of 1–15 minutes in a single mint. The
# whole run is captured as ONE NFT (start_minute + duration), so listing /
# trading is per-capsule, not per-minute. Each individual minute is still
# globally unique: the contract refuses to mint if ANY minute in the
# requested range is already claimed.
#
# Storage shape is deliberately simple (TXL-style, not full FA2). Owners
# can transfer; an admin can pause minting, change the per-minute price,
# and withdraw the contract's tez balance to the holder pool.

@sp.module
def main():
    class MintTime(sp.Contract):

        def __init__(self, admin, price_per_minute_mutez):
            self.data.admin = admin
            self.data.paused = False
            # Fixed XTZ per minute — total mint cost = price * duration.
            # Stored as mutez so we can multiply by `duration` (a nat) on-chain
            # via sp.split_tokens(price, duration, 1).
            self.data.price_per_minute_mutez = price_per_minute_mutez

            # Token registry. `tokens` is the canonical store; `owners` is a
            # parallel index for cheap transfer/lookup without unpacking the
            # full record. (SmartPy big_map values can't be partially
            # updated, so duplicating the owner field is cheaper than
            # rewriting the whole record on transfer.)
            self.data.next_token_id = 0
            self.data.tokens = sp.cast(
                sp.big_map(),
                sp.big_map[
                    sp.nat,
                    sp.record(
                        owner=sp.address,
                        start_minute=sp.nat,
                        duration=sp.nat,
                        frame_id=sp.nat,
                        text=sp.string,
                        image_ipfs=sp.string,
                        minted_at=sp.timestamp,
                    ),
                ],
            )
            self.data.owners = sp.cast(sp.big_map(), sp.big_map[sp.nat, sp.address])

            # Uniqueness ledger: minute (UTC epoch minute) -> token_id that
            # owns it. Lets us reject overlapping mints in O(duration).
            self.data.claimed_minutes = sp.cast(
                sp.big_map(), sp.big_map[sp.nat, sp.nat]
            )

            self.data.total_minted = 0

        # ── helpers ──────────────────────────────────────────────────────

        @sp.private(with_storage="read-only")
        def _is_admin(self):
            return sp.sender == self.data.admin

        # ── public entrypoints ───────────────────────────────────────────

        @sp.entrypoint
        def mint(self, params):
            """Claim a 1–15 minute capsule. Payable: price_per_minute * duration."""
            sp.cast(
                params,
                sp.record(
                    start_minute=sp.nat,
                    duration=sp.nat,
                    frame_id=sp.nat,
                    text=sp.string,
                    image_ipfs=sp.string,
                ),
            )

            assert not self.data.paused, "Paused"
            assert params.duration >= 1, "DurationTooLow"
            assert params.duration <= 15, "DurationTooHigh"
            assert params.frame_id < 6, "InvalidFrame"
            assert sp.len(params.text) <= 280, "TextTooLong"
            # IPFS CIDv0 is 46 chars, v1 base32 up to ~64. 96 is a comfortable
            # ceiling that still rejects accidental URLs / data: blobs.
            assert sp.len(params.image_ipfs) <= 96, "ImageRefTooLong"

            # Price check: total = price_per_minute * duration.
            # sp.split_tokens(amount, num, den) = amount * num / den, so
            # split_tokens(price, duration, 1) gives price*duration in mutez.
            required = sp.split_tokens(
                self.data.price_per_minute_mutez, params.duration, 1
            )
            assert sp.amount == required, "WrongPayment"

            # Uniqueness sweep: every minute in [start, start+duration) must
            # be unclaimed. We do two passes (check then claim) so a partial
            # failure can't leave half-marked state — SmartPy reverts on
            # assert, but explicit is safer than relying on rollback for
            # multi-minute marking.
            i = sp.nat(0)
            while i < params.duration:
                minute = params.start_minute + i
                assert not (minute in self.data.claimed_minutes), "MinuteTaken"
                i += 1

            token_id = self.data.next_token_id

            j = sp.nat(0)
            while j < params.duration:
                minute = params.start_minute + j
                self.data.claimed_minutes[minute] = token_id
                j += 1

            self.data.tokens[token_id] = sp.record(
                owner=sp.sender,
                start_minute=params.start_minute,
                duration=params.duration,
                frame_id=params.frame_id,
                text=params.text,
                image_ipfs=params.image_ipfs,
                minted_at=sp.now,
            )
            self.data.owners[token_id] = sp.sender
            self.data.next_token_id = token_id + 1
            self.data.total_minted += 1

            sp.emit(
                sp.record(
                    token_id=token_id,
                    owner=sp.sender,
                    start_minute=params.start_minute,
                    duration=params.duration,
                ),
                tag="Minted",
            )

        @sp.entrypoint
        def transfer(self, params):
            """Owner-initiated transfer. No operator/approval model — keep it simple."""
            sp.cast(params, sp.record(token_id=sp.nat, to_=sp.address))
            assert (params.token_id in self.data.tokens), "UnknownToken"
            tok = self.data.tokens[params.token_id]
            assert tok.owner == sp.sender, "NotOwner"

            updated = sp.record(
                owner=params.to_,
                start_minute=tok.start_minute,
                duration=tok.duration,
                frame_id=tok.frame_id,
                text=tok.text,
                image_ipfs=tok.image_ipfs,
                minted_at=tok.minted_at,
            )
            self.data.tokens[params.token_id] = updated
            self.data.owners[params.token_id] = params.to_

            sp.emit(
                sp.record(
                    token_id=params.token_id,
                    from_=sp.sender,
                    to_=params.to_,
                ),
                tag="Transferred",
            )

        # ── admin ────────────────────────────────────────────────────────

        @sp.entrypoint
        def set_price(self, new_price):
            sp.cast(new_price, sp.mutez)
            assert self._is_admin(), "NotAdmin"
            self.data.price_per_minute_mutez = new_price

        @sp.entrypoint
        def set_paused(self, p):
            sp.cast(p, sp.bool)
            assert self._is_admin(), "NotAdmin"
            self.data.paused = p

        @sp.entrypoint
        def set_admin(self, new_admin):
            sp.cast(new_admin, sp.address)
            assert self._is_admin(), "NotAdmin"
            self.data.admin = new_admin

        @sp.entrypoint
        def withdraw(self, params):
            """Admin sweep — routes contract balance to the holder pool / TXL contract."""
            sp.cast(params, sp.record(amount=sp.mutez, to_=sp.address))
            assert self._is_admin(), "NotAdmin"
            sp.send(params.to_, params.amount)

        @sp.entrypoint
        def default(self):
            """Accept anonymous funding (top-ups). No accounting — admin sweeps it."""
            pass


@sp.add_test()
def test():
    """Originate-only scenario. Behavioral tests can land alongside the contract
    once it's deployed; the compile script only needs this to emit Michelson."""
    s = sp.test_scenario("MintTime deployment", main)
    s.h1("Originate MintTime")
    admin = sp.address("tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w")
    mt = main.MintTime(admin=admin, price_per_minute_mutez=sp.mutez(500000))  # 0.5 ꜩ / min
    s += mt
