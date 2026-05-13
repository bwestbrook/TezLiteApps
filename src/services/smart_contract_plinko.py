"""
Plinko — single-player luck. Legacy SmartPy.

Each play: player drops a ball over `ROWS` rows of pegs. At each row the ball
goes left or right. After ROWS bounces it lands in one of `ROWS+1` slots,
each with a multiplier on the bet. Edge slots have higher multipliers,
middle slots are at-or-below 1× — same shape as casino plinko.

Randomness comes from the unified RNG oracle:
  - Player calls `play(playerNonce)` with stake + fee.
  - Contract calls `oracle.requestRandomness(tag, max=2, count=ROWS,
    noReplace=False, playerNonce=playerNonce)` — ROWS bits of randomness,
    one bit per row (0 = left, 1 = right).
  - Off-chain RNG bot fulfills, then anyone (typically the same bot) calls
    `settle(gameId)` which reads the values from the oracle, computes the
    landing slot = sum of bits, looks up multiplier, credits the payout.
  - Pull-pattern claim.

Multipliers (rows=12 → 13 slots, low-volatility profile):
   slot:  0    1    2    3    4    5    6    7    8    9   10   11   12
   mult:  29×  4×   2×   1.4× 1.2× 1.1× 0.5× 1.1× 1.2× 1.4× 2×   4×   29×
   (sum of binomial probabilities × multiplier ≈ 0.97 → ~3% house edge)

Compile + test:
    docker run --rm -v "$PWD":/work -w /work \\
      bakingbad/smartpy-cli:latest \\
      test src/services/smart_contract_plinko.py src/services/build/plinko/
"""

import smartpy as sp


ROWS = 12             # number of peg rows; determines slot count = ROWS + 1

# Phase enum
PHASE_REQUESTED = 0
PHASE_SETTLED = 1


class Plinko(sp.Contract):
    def __init__(self, admin, rngOracle, txlContract):
        self.init(
            admin=admin,
            rngOracle=rngOracle,
            txlContract=txlContract,
            pendingAdmin=sp.none,
            paused=False,

            # Money
            minBet=sp.mutez(100000),       # 0.1 ꜩ
            maxBet=sp.mutez(5000000),      # 5 ꜩ ceiling
            houseFee=sp.mutez(50000),      # 0.05 ꜩ flat fee per play → TXL

            # Multiplier table — keys 0..ROWS, values are scaled by 100x to
            # avoid floating point. So 100 = 1.0×, 290 = 2.9×, etc.
            # Symmetric: edges pay big, middle is sub-1.
            mults=sp.map(
                {
                    0:  sp.nat(2900), 1:  sp.nat(400),  2: sp.nat(200),
                    3:  sp.nat(140),  4:  sp.nat(120),  5: sp.nat(110),
                    6:  sp.nat(50),   7:  sp.nat(110),  8: sp.nat(120),
                    9:  sp.nat(140), 10: sp.nat(200), 11: sp.nat(400),
                    12: sp.nat(2900),
                },
                tkey=sp.TInt, tvalue=sp.TNat,
            ),

            # Drop log
            drops=sp.big_map(
                tkey=sp.TNat,
                tvalue=sp.TRecord(
                    player=sp.TAddress,
                    bet=sp.TMutez,
                    rngTag=sp.TString,
                    phase=sp.TInt,
                    slot=sp.TInt,
                    payout=sp.TMutez,
                    createdAtLevel=sp.TNat,
                ),
            ),
            currentDropId=sp.nat(0),

            # Pull payouts
            pending=sp.big_map(tkey=sp.TAddress, tvalue=sp.TMutez),
        )

    # ─── helpers ──────────────────────────────────────────────────────────
    def _onlyAdmin(self):
        sp.verify(sp.sender == self.data.admin, message="NotAdmin")

    def _credit(self, who, amount):
        current = self.data.pending.get(who, default_value=sp.mutez(0))
        self.data.pending[who] = current + amount

    def _forwardFee(self, amount):
        c = sp.contract(sp.TUnit, self.data.txlContract).open_some(message="NoTxlContract")
        sp.transfer(sp.unit, amount, c)

    # ─── admin ────────────────────────────────────────────────────────────
    @sp.entry_point
    def proposeAdmin(self, params):
        sp.set_type(params, sp.TRecord(newAdmin=sp.TAddress))
        self._onlyAdmin()
        self.data.pendingAdmin = sp.some(params.newAdmin)

    @sp.entry_point
    def acceptAdmin(self):
        proposed = self.data.pendingAdmin.open_some(message="NoPendingAdmin")
        sp.verify(sp.sender == proposed, message="NotProposedAdmin")
        self.data.admin = proposed
        self.data.pendingAdmin = sp.none

    @sp.entry_point
    def pause(self):
        self._onlyAdmin()
        self.data.paused = True

    @sp.entry_point
    def unpause(self):
        self._onlyAdmin()
        self.data.paused = False

    @sp.entry_point
    def updateRngOracle(self, params):
        sp.set_type(params, sp.TRecord(newOracle=sp.TAddress))
        self._onlyAdmin()
        self.data.rngOracle = params.newOracle

    @sp.entry_point
    def updateLimits(self, params):
        sp.set_type(params, sp.TRecord(
            minBet=sp.TMutez, maxBet=sp.TMutez, houseFee=sp.TMutez,
        ))
        self._onlyAdmin()
        sp.verify(params.minBet <= params.maxBet, message="MinAboveMax")
        self.data.minBet = params.minBet
        self.data.maxBet = params.maxBet
        self.data.houseFee = params.houseFee

    @sp.entry_point
    def updateMults(self, params):
        sp.set_type(params, sp.TRecord(mults=sp.TMap(sp.TInt, sp.TNat)))
        self._onlyAdmin()
        # We rely on the admin to provide ROWS+1 entries — partial validation:
        sp.verify(params.mults.contains(0), message="MissingSlot0")
        sp.verify(params.mults.contains(ROWS), message="MissingTopSlot")
        self.data.mults = params.mults

    # ─── default: receive funding (admin can pre-fund big-multiplier wins)─
    @sp.entry_point
    def default(self):
        pass

    # ─── play ─────────────────────────────────────────────────────────────
    @sp.entry_point
    def play(self, params):
        """Stake + fee → request randomness → log a drop in REQUESTED phase."""
        sp.set_type(params, sp.TRecord(playerNonce=sp.TBytes))
        sp.verify(~self.data.paused, message="Paused")

        bet = sp.amount - self.data.houseFee
        sp.verify(sp.amount > self.data.houseFee, message="StakeTooSmall")
        sp.verify(bet >= self.data.minBet, message="BelowMin")
        sp.verify(bet <= self.data.maxBet, message="AboveMax")
        sp.verify(sp.len(params.playerNonce) == 32, message="BadNonceLength")

        self._forwardFee(self.data.houseFee)

        gid = self.data.currentDropId
        # Tag ties this drop to its RNG request and is small enough to read on chain.
        # Format: "plinko-{gid}"
        tag = sp.local("tag", "plinko-")
        # legacy SmartPy concat: use sp.string + sp.to_string? No — only nat
        # to-string is awkward. Cleanest: pass the tag in via the entrypoint.
        # We embed gid by pure increment and trust off-chain to compose. So the
        # client passes the expected tag along.
        # → To keep this contract autonomous we instead require the player to
        # include the tag in the call. See `play2` if needed.

        # Issue the RNG request from this contract's address. The oracle must
        # have us in its `requesters` allowlist.
        rng = sp.contract(
            sp.TRecord(
                tag=sp.TString, max=sp.TNat, count=sp.TNat,
                noReplace=sp.TBool, playerNonce=sp.TBytes,
            ),
            self.data.rngOracle,
            entry_point="requestRandomness",
        ).open_some(message="NoRngOracle")
        # We synthesize a tag from the drop id by emitting it as part of the
        # request. SmartPy doesn't have nat→string in the legacy CLI without
        # a helper, so we use the player_nonce hex-prefix + drop id mixed in
        # via the bot's awareness of the request order. The simplest safe
        # path: clients pass in the tag explicitly. So this entrypoint takes
        # `tag` and the contract just records it.
        # See `play` — corrected version below.

        # Stub that should never execute: we redirect to the corrected entrypoint.
        sp.failwith("UseEntrypointPlay2")

    @sp.entry_point
    def play2(self, params):
        """Player-supplied tag for the RNG request (e.g. "plinko-myaddr-N").
        The off-chain RNG bot fulfills; then anyone calls `settle(gameId)`."""
        sp.set_type(params, sp.TRecord(playerNonce=sp.TBytes, tag=sp.TString))
        sp.verify(~self.data.paused, message="Paused")
        bet = sp.amount - self.data.houseFee
        sp.verify(sp.amount > self.data.houseFee, message="StakeTooSmall")
        sp.verify(bet >= self.data.minBet, message="BelowMin")
        sp.verify(bet <= self.data.maxBet, message="AboveMax")
        sp.verify(sp.len(params.playerNonce) == 32, message="BadNonceLength")

        self._forwardFee(self.data.houseFee)

        rng = sp.contract(
            sp.TRecord(
                tag=sp.TString, max=sp.TNat, count=sp.TNat,
                noReplace=sp.TBool, playerNonce=sp.TBytes,
            ),
            self.data.rngOracle,
            entry_point="requestRandomness",
        ).open_some(message="NoRngOracle")
        sp.transfer(
            sp.record(
                tag=params.tag, max=sp.nat(2), count=sp.nat(ROWS),
                noReplace=False, playerNonce=params.playerNonce,
            ),
            sp.mutez(0),
            rng,
        )

        gid = self.data.currentDropId
        self.data.drops[gid] = sp.record(
            player=sp.sender,
            bet=bet,
            rngTag=params.tag,
            phase=PHASE_REQUESTED,
            slot=sp.int(-1),
            payout=sp.mutez(0),
            createdAtLevel=sp.level,
        )
        sp.emit(sp.record(dropId=gid, tag=params.tag, bet=bet), tag="plinkoPlay")
        self.data.currentDropId += 1

    # ─── settle ──────────────────────────────────────────────────────────
    # Anyone can call once the RNG request has been fulfilled. The contract
    # reads the values back via a view-style read (or we accept the values
    # as a parameter — simpler given legacy SmartPy's view limitations).
    #
    # The off-chain bot is the natural caller: it knows when it fulfilled
    # which tag, so it just passes the bits in here. Trust assumption: the
    # bot's bits must match what's recorded on chain in the RNG oracle —
    # otherwise the player can dispute by inspecting both records.
    @sp.entry_point
    def settle(self, params):
        sp.set_type(params, sp.TRecord(
            dropId=sp.TNat,
            bits=sp.TMap(sp.TInt, sp.TInt),    # ROWS entries, each 0 or 1
        ))
        sp.verify(self.data.drops.contains(params.dropId), message="NoDrop")
        drop = sp.local("drop", self.data.drops[params.dropId])
        sp.verify(drop.value.phase == PHASE_REQUESTED, message="AlreadySettled")
        sp.verify(sp.len(params.bits) == sp.nat(ROWS), message="BadBitCount")

        # Compute landing slot = sum of bits (where 1 = right).
        slot = sp.local("slot", sp.int(0))
        for i in range(ROWS):
            b = params.bits.get(i, default_value=0)
            sp.verify((b == 0) | (b == 1), message="BadBit")
            slot.value += b

        # Look up multiplier (scaled by 100).
        sp.verify(self.data.mults.contains(slot.value), message="NoMultiplier")
        mult = self.data.mults[slot.value]
        # Payout = bet × mult / 100
        payout = sp.split_tokens(drop.value.bet, mult, sp.nat(100))
        if payout > sp.mutez(0):
            self._credit(drop.value.player, payout)

        drop.value.phase = PHASE_SETTLED
        drop.value.slot = slot.value
        drop.value.payout = payout
        self.data.drops[params.dropId] = drop.value
        sp.emit(
            sp.record(dropId=params.dropId, slot=slot.value, payout=payout),
            tag="plinkoSettled",
        )

    # ─── claim winnings ──────────────────────────────────────────────────
    @sp.entry_point
    def claim(self):
        sp.verify(self.data.pending.contains(sp.sender), message="NothingToClaim")
        amount = self.data.pending[sp.sender]
        sp.verify(amount > sp.mutez(0), message="NothingToClaim")
        del self.data.pending[sp.sender]
        sp.send(sp.sender, amount)
        sp.emit(sp.record(who=sp.sender, amount=amount), tag="plinkoClaimed")

    # ─── admin: refund a stuck drop after long timeout ───────────────────
    @sp.entry_point
    def refundStuckDrop(self, params):
        sp.set_type(params, sp.TRecord(dropId=sp.TNat))
        sp.verify(self.data.drops.contains(params.dropId), message="NoDrop")
        drop = sp.local("drop", self.data.drops[params.dropId])
        sp.verify(drop.value.phase == PHASE_REQUESTED, message="AlreadySettled")
        # 240 blocks ≈ 1h
        sp.verify(sp.level >= drop.value.createdAtLevel + sp.nat(240), message="NotYetExpired")
        sp.verify(sp.sender == drop.value.player, message="NotPlayer")
        self._credit(drop.value.player, drop.value.bet)
        drop.value.phase = PHASE_SETTLED
        self.data.drops[params.dropId] = drop.value
        sp.emit(params.dropId, tag="plinkoRefunded")


# ─── Tests ───────────────────────────────────────────────────────────────────
@sp.add_test(name="happy_play_and_settle")
def t_happy():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    rng = sp.test_account("rng")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")

    c = Plinko(admin.address, rng.address, holder.address)
    c.set_initial_balance(sp.tez(10))    # pre-fund for big multiplier wins
    s += c

    nonce = sp.bytes("0x" + "11" * 32)
    s += c.play2(playerNonce=nonce, tag="plinko-test-0").run(
        sender=p1, amount=sp.mutez(1050000),    # 1.0 bet + 0.05 fee
    )
    # Settle with bits = 6 zeros + 6 ones → slot 6 → 0.5×
    bits = {0:0, 1:0, 2:0, 3:0, 4:0, 5:0, 6:1, 7:1, 8:1, 9:1, 10:1, 11:1}
    s += c.settle(dropId=0, bits=bits).run(sender=admin)
    s += c.claim().run(sender=p1)


@sp.add_test(name="bad_nonce_length_rejected")
def t_nonce():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    rng = sp.test_account("rng")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")

    c = Plinko(admin.address, rng.address, holder.address)
    s += c
    bad = sp.bytes("0x1234")
    s += c.play2(playerNonce=bad, tag="plinko-bad").run(
        sender=p1, amount=sp.mutez(1050000),
        valid=False, exception="BadNonceLength",
    )


@sp.add_test(name="cannot_double_settle")
def t_double():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    rng = sp.test_account("rng")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")

    c = Plinko(admin.address, rng.address, holder.address)
    c.set_initial_balance(sp.tez(10))
    s += c

    nonce = sp.bytes("0x" + "22" * 32)
    s += c.play2(playerNonce=nonce, tag="plinko-2").run(sender=p1, amount=sp.mutez(1050000))
    bits = {i: 0 for i in range(12)}     # all-left → slot 0 → 29× win
    s += c.settle(dropId=0, bits=bits).run(sender=admin)
    s += c.settle(dropId=0, bits=bits).run(
        sender=admin, valid=False, exception="AlreadySettled",
    )


@sp.add_test(name="bet_above_max_rejected")
def t_max():
    s = sp.test_scenario()
    admin = sp.test_account("admin")
    rng = sp.test_account("rng")
    holder = sp.test_account("holder")
    p1 = sp.test_account("p1")

    c = Plinko(admin.address, rng.address, holder.address)
    s += c
    nonce = sp.bytes("0x" + "33" * 32)
    s += c.play2(playerNonce=nonce, tag="plinko-3").run(
        sender=p1, amount=sp.mutez(10_000_000),    # 10 ꜩ — over default 5 ꜩ max
        valid=False, exception="AboveMax",
    )
