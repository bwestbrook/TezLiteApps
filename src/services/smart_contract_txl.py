"""
TXL holder-reward manager — v2.

v1 (smart_contract_txl.py) is moved to src/services/legacy/. Its
problems:

  A) `default()` wrote to all 271 entries every tez → unscalable gas as
     more games forward holder fees.
  B) `updateOwner` used `if sp.sender == oracle:` (silent no-op) instead
     of `assert` — wasted gas on unauthorized calls.
  C) No `updateAdmin` / `updateOracle` / `pause`.
  D) `payTxlHolder` walked all 271 entries on every claim.
  E) `sp.map` (regular) for the 271-entry ledger — serialized whole map
     on every read.
  F) Dust from `sp.split_tokens(amount, 1, 271)` was never tracked.
  G) UI copy promised inverse-rank weighting; contract distributed flat.

v2 uses a global-accumulator pattern (MasterChef-style) keyed off the
active supply, so `default()` is O(1) regardless of holder count.

Design at a glance
──────────────────
  accPerToken : mutez   running sum of per-token credit (cumulative).
                        Each deposit adds `floor(amount / activeSupply)`.
  dust        : mutez   accumulated truncation. Admin sweeps via
                        sweepDust(recipient).
  activeSupply: nat     totalSupply minus tokens currently owned by
                        burnSentinel (objkt marketplace KT1). Tokens
                        held by burnSentinel accrue NOTHING — their
                        share flows to active holders via the divisor.
  idLookUp    : big_map[token_id, (owner, lastSeenAcc)]
                        lastSeenAcc records the value of accPerToken
                        the last time this token's share was settled.
                        share = accPerToken - lastSeenAcc.
  pending     : big_map[address, mutez]
                        Credit settled but not yet sent. Both admin
                        push (settleBatch) and holder pull (claim) move
                        credit through pending. Decouples settlement
                        from send so a rejecting recipient doesn't
                        revert a whole batch's settlement work.

Distribution flow
─────────────────
  Game contract → sp.send(self.data.txlContract, fee) → default()
      → accPerToken += fee / activeSupply
      → dust += fee mod activeSupply
      → totalRewards += fee

  Owner change (oracle): batchUpdateOwner / updateOwner
      → settle OLD owner's accrued share into pending[oldOwner]
      → reassign idLookUp[token_id].owner = newOwner
      → set new owner's lastSeenAcc = accPerToken (no retroactive credit)
      → if old/new is burnSentinel, activeSupply is adjusted

  Admin push (live mainnet payout): script orchestrates
      → settleBatch(tokenIds)     credit pending[owner] for each ID
      → pushPayouts(recipients)   sp.send pending[addr] → addr
      Both bounded to MAX_BATCH per call to stay under gas limit.

  Holder pull: claim(tokenIds)
      → settle accrued share for each ID the caller owns into pending
      → sp.send pending[caller] to caller, zero it.

Initial storage
───────────────
All 271 token IDs assigned to burnSentinel at origination (activeSupply
= 0). default() reverts in this state — deposits are blocked until the
oracle assigns real owners via batchUpdateOwner. Game contracts
(smart_contractAD.py etc.) should not be repointed at this contract
until reconcile is complete and `paused` is False.

Token IDs are mirrored from src/services/txlOwners.js (TXL_TOKEN_IDS).
That JS export is the single source of truth — sync this file when
ids change.
"""

import smartpy as sp


# ── Canonical TXL token IDs (mirror of src/services/txlOwners.js) ──────
# Kalamint FA2 token IDs the TXL manager tracks. Bake into __init__ so
# big_map entries are pre-populated at origination — oracle never needs
# to "register" a new token; it only reassigns owners.
TXL_TOKEN_IDS = [
    60199, 60200, 60201, 60202, 60203, 60204, 60206, 60207, 60208, 60209,
    60210, 60211, 60212, 60213, 60215, 60216, 60218, 60219, 60220, 60221,
    60224, 60225, 60226, 60227, 60228, 60230, 60231, 60233, 60234, 60235,
    60236, 60237, 60238, 60239, 60240, 60241, 60242, 60243, 60244, 60245,
    60246, 60247, 60248, 60249, 60250, 60251, 60252, 60253, 60254, 60255,
    60256, 60257, 60258, 60259, 60260, 60338, 60339, 60340, 60344, 60346,
    60348, 60349, 60350, 60354, 60355, 60356, 60357, 60358, 60359, 60361,
    60362, 60363, 60366, 60367, 60368, 60369, 60370, 60371, 60372, 60373,
    60374, 60375, 60377, 60379, 60380, 60381, 60382, 60383, 60384, 60386,
    60387, 60388, 60389, 60391, 60392, 60393, 60394, 60395, 60396, 60397,
    60399, 60401, 60403, 60404, 60406, 60407, 60413, 60414, 60416, 60418,
    60429, 60432, 60433, 60434, 60436, 60437, 60438, 60439, 60440, 60441,
    60442, 60443, 60444, 60445, 60446, 60447, 60448, 60449, 60450, 60451,
    60452, 60453, 60454, 60455, 60456, 60457, 60458, 60459, 60460, 60461,
    60462, 60463, 60464, 60465, 60466, 60467, 60468, 60469, 60470, 60471,
    60472, 60473, 60474, 60475, 60476, 60477, 60478, 60479, 60480, 60481,
    60483, 60486, 60487, 60489, 60491, 60492, 60493, 60494, 60495, 60496,
    60497, 60498, 60499, 60500, 60501, 60502, 60534, 60535, 60536, 60537,
    60545, 60546, 60547, 60548, 60549, 60550, 60551, 60552, 60553, 60554,
    60560, 60561, 60562, 60563, 60564, 60565, 60566, 60567, 60571, 60572,
    60573, 60575, 60576, 60577, 60578, 60580, 60581, 60582, 60583, 60584,
    60585, 60586, 60587, 60589, 60590, 60593, 60595, 60596, 60597, 60599,
    60600, 60601, 60603, 60605, 60606, 60607, 60608, 60612, 60613, 60614,
    60615, 60616, 60617, 60618, 60619, 60620, 60621, 60622, 60623, 60624,
    60625, 60626, 60627, 60628, 60629, 60630, 60631, 60632, 60633, 60636,
    60637, 60638, 60639, 60640, 60641, 60642, 60643, 60644, 60645, 60646,
    60647, 60648, 60649, 60650, 60651, 60688, 60690, 60692, 60693, 60694,
    60696,
]
# Drift guard: the literal `sp.nat(271)` in __init__ must match the
# list length. If you add/remove IDs, bump both — SmartPy's parser
# won't accept `sp.nat(len(TXL_TOKEN_IDS))` in the contract body.
assert len(TXL_TOKEN_IDS) == 271, (
    f"TXL_TOKEN_IDS count drift: have {len(TXL_TOKEN_IDS)}, "
    f"contract __init__ bakes 271"
)

# objkt.com marketplace contract — Kalamint NFTs listed for sale sit
# here as the "owner" until purchased. v2 treats this as a burn-sentinel:
# tokens owned by this address accrue NOTHING and don't count toward
# activeSupply (so their share redistributes to active holders).
OBJKT_MARKETPLACE = "KT1FvqJwEDWb1Gwc55Jd1jjTHRVWbYKUUpyq"

# Default admin = the deploy wallet (matches ADMIN_ADDRESS in constants.js).
# Same key the off-chain oracle worker derives. Distinct from the TXL
# oracle key for admin/oracle separation of duties.
DEFAULT_ADMIN = "tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q"

# Default oracle = the mainnet oracle key derived from
# TXL_ORACLE_MNEMONIC_MAINNET in .env. Generated fresh for v2 (the v1
# seed in oracle_TXL.py was publicly committed and must not be reused).
#
# The shadownet origination (KT1JukrFQ2DtKPDRDBq4j3Z6HkXtXxuF2Evd) was
# done before this swap and has the previous shadownet-only oracle key
# tz1cZCXFNV3LSogGPfEGoEPEH7t3y14Y55pz baked in — if shadownet ever
# needs redeploying, admin can `updateOracle` post-origination.
DEFAULT_ORACLE = "tz1QtpR6hraURtjP9V1rMMYnrqfyaicJFPWv"


@sp.module
def main():
    # Per-batch upper bound for batchUpdateOwner, settleBatch,
    # pushPayouts, and claim. Tuned to stay comfortably under the
    # per-op gas cap (~1.04M). Off-chain scripts iterate the contract
    # in chunks of this size.
    MAX_BATCH = 50

    class TxlManager(sp.Contract):
        def __init__(self, admin, oracle, burnSentinel):
            # ── Roles ────────────────────────────────────────────────
            self.data.admin = admin
            self.data.oracle = oracle
            # Address of the objkt marketplace KT1 (or any other
            # contract that should be excluded from accrual). Tokens
            # with owner == burnSentinel are skipped during deposit
            # math and don't count toward activeSupply.
            self.data.burnSentinel = burnSentinel
            self.data.pendingAdmin = sp.cast(None, sp.option[sp.address])

            # ── Circuit breaker ──────────────────────────────────────
            # When True: default / settleBatch / pushPayouts / claim
            # all revert. Oracle updateOwner + admin role ops continue
            # to work (they don't move tez and we want to keep the
            # owner ledger current even during incident response).
            self.data.paused = False

            # ── Supply ───────────────────────────────────────────────
            # totalSupply is informational — the canonical Kalamint
            # TXL count. idLookUp grows lazily as the oracle registers
            # each token, so its size can be < totalSupply until the
            # first reconcile pass completes. activeSupply counts only
            # tokens currently owned by a real (non-burn) address.
            self.data.totalSupply = sp.nat(271)
            self.data.activeSupply = sp.nat(0)

            # ── Accumulator ──────────────────────────────────────────
            self.data.accPerToken = sp.mutez(0)
            self.data.dust = sp.mutez(0)
            self.data.totalRewards = sp.mutez(0)

            # ── Ledger ───────────────────────────────────────────────
            # Token IDs are registered LAZILY by the oracle. The first
            # updateOwner / batchUpdateOwner for a given txlId creates
            # the entry with the supplied owner and lastSeenAcc=
            # accPerToken (so the new owner only earns from future
            # deposits). Pre-populating wasn't workable: SmartPy
            # @sp.module bodies can't construct big_maps with content
            # at origination time (sp.big_map() takes no args, sp.cast
            # won't promote a sp.map, dict comprehensions are
            # rejected). Lazy-create gives the same end state after
            # the oracle's first reconcile pass.
            #
            # default() reverts while activeSupply == 0, so deposits
            # are blocked until the oracle starts populating real
            # owners. Game contracts shouldn't be repointed at the
            # new TXL until that's done.
            self.data.idLookUp = sp.big_map()
            # Pending claims: address → mutez owed. Type inferred
            # from the first insertion in updateOwner.
            self.data.pending = sp.big_map()

        # ── Default: receive funding from any game contract ─────────
        @sp.entrypoint
        def default(self):
            """Routed to from every game's holder-fee transfer. O(1):
            updates only the accumulator + dust + totalRewards
            (regardless of how many holders exist). Reverts if paused
            or if no tokens are currently held by real owners."""
            assert not self.data.paused, "paused"
            assert sp.amount > sp.mutez(0), "zeroAmount"
            assert self.data.activeSupply > sp.nat(0), "noActiveHolders"

            # floor-divide amount by activeSupply.
            #   sp.ediv(mutez, nat) → option[pair[mutez, mutez]]
            # First element is the quotient (mutez per active token).
            # Second element is the remainder (dust mutez).
            ed = sp.ediv(sp.amount, self.data.activeSupply).unwrap_some(
                error="divError"
            )
            self.data.accPerToken += sp.fst(ed)
            self.data.dust += sp.snd(ed)
            self.data.totalRewards += sp.amount
            sp.emit(
                sp.record(
                    amount=sp.amount,
                    perToken=sp.fst(ed),
                    dust=sp.snd(ed),
                ),
                tag="deposit",
            )

        # ── Admin handover (two-step) ────────────────────────────────
        @sp.entrypoint
        def proposeAdmin(self, params):
            sp.cast(params.newAdmin, sp.address)
            assert sp.sender == self.data.admin, "notAdmin"
            self.data.pendingAdmin = sp.Some(params.newAdmin)

        @sp.entrypoint
        def acceptAdmin(self):
            proposed = self.data.pendingAdmin.unwrap_some(
                error="noPendingAdmin"
            )
            assert sp.sender == proposed, "notProposedAdmin"
            self.data.admin = proposed
            self.data.pendingAdmin = sp.cast(None, sp.option[sp.address])

        # ── Admin: rotate oracle key ────────────────────────────────
        @sp.entrypoint
        def updateOracle(self, params):
            sp.cast(params.newOracle, sp.address)
            assert sp.sender == self.data.admin, "notAdmin"
            self.data.oracle = params.newOracle

        # ── Admin: circuit breaker ──────────────────────────────────
        @sp.entrypoint
        def pause(self):
            assert sp.sender == self.data.admin, "notAdmin"
            self.data.paused = True

        @sp.entrypoint
        def unpause(self):
            assert sp.sender == self.data.admin, "notAdmin"
            self.data.paused = False

        # ── Admin: sweep accumulated dust ───────────────────────────
        @sp.entrypoint
        def sweepDust(self, params):
            """Drain `dust` to the named recipient. Recipient is a
            parameter (NOT sp.sender) so a compromised admin key can't
            silently redirect dust to itself — every sweep is auditable
            with the recipient in the operation params."""
            sp.cast(params.recipient, sp.address)
            assert sp.sender == self.data.admin, "notAdmin"
            amount = self.data.dust
            assert amount > sp.mutez(0), "noDust"
            self.data.dust = sp.mutez(0)
            sp.send(params.recipient, amount)
            sp.emit(
                sp.record(recipient=params.recipient, amount=amount),
                tag="dustSwept",
            )

        # ── Oracle: single owner update ─────────────────────────────
        # Owner-change logic is inlined here (and again in
        # batchUpdateOwner). Factoring it into an @sp.private helper
        # would have been cleaner but SmartPy 0.20's parser balks on
        # multi-arg private invocations used as statements; the
        # duplicated block keeps the contract one-pass-parseable.
        # Invariants:
        #   - First-touch creates the entry with lastSeenAcc =
        #     current accPerToken; new owner only earns from future
        #     deposits.
        #   - Subsequent owner changes settle the OLD owner's accrued
        #     share into pending before reassigning, so the NEW owner
        #     doesn't get credit for deposits that happened before
        #     they took possession.
        #   - activeSupply tracks tokens with a non-burn owner;
        #     transitions across the burn boundary adjust it.
        @sp.entrypoint
        def updateOwner(self, params):
            """Register or reassign one token_id."""
            sp.cast(params.txlId, sp.nat)
            sp.cast(params.newOwner, sp.address)
            assert sp.sender == self.data.oracle, "notOracle"

            burn = self.data.burnSentinel
            newIsBurn = params.newOwner == burn
            if params.txlId in self.data.idLookUp:
                entry = self.data.idLookUp[params.txlId]
                oldOwner = entry.owner
                if oldOwner != params.newOwner:
                    oldIsBurn = oldOwner == burn
                    if not oldIsBurn:
                        share = self.data.accPerToken - entry.lastSeenAcc
                        if share > sp.mutez(0):
                            current = self.data.pending.get(
                                oldOwner, default=sp.mutez(0)
                            )
                            self.data.pending[oldOwner] = current + share
                    if oldIsBurn:
                        if not newIsBurn:
                            self.data.activeSupply += sp.nat(1)
                    else:
                        if newIsBurn:
                            self.data.activeSupply = sp.as_nat(
                                self.data.activeSupply - sp.nat(1)
                            )
                    self.data.idLookUp[params.txlId] = sp.record(
                        owner=params.newOwner,
                        lastSeenAcc=self.data.accPerToken,
                    )
                    sp.emit(
                        sp.record(
                            txlId=params.txlId,
                            oldOwner=oldOwner,
                            newOwner=params.newOwner,
                        ),
                        tag="ownerChanged",
                    )
            else:
                # First-touch: register the entry. activeSupply only
                # bumps if the new owner is a real (non-burn) holder.
                if not newIsBurn:
                    self.data.activeSupply += sp.nat(1)
                self.data.idLookUp[params.txlId] = sp.record(
                    owner=params.newOwner,
                    lastSeenAcc=self.data.accPerToken,
                )
                sp.emit(
                    sp.record(
                        txlId=params.txlId,
                        newOwner=params.newOwner,
                    ),
                    tag="ownerRegistered",
                )

        # ── Oracle: batched owner updates ───────────────────────────
        @sp.entrypoint
        def batchUpdateOwner(self, params):
            """Same as updateOwner for each entry in `updates`. Caps
            list length to MAX_BATCH so a runaway batch can't get
            stuck under the per-op gas limit."""
            sp.cast(
                params.updates,
                sp.list[sp.record(txlId=sp.nat, newOwner=sp.address)],
            )
            assert sp.sender == self.data.oracle, "notOracle"
            assert sp.len(params.updates) <= MAX_BATCH, "batchTooLarge"
            burn = self.data.burnSentinel
            for u in params.updates:
                newIsBurn = u.newOwner == burn
                if u.txlId in self.data.idLookUp:
                    entry = self.data.idLookUp[u.txlId]
                    oldOwner = entry.owner
                    if oldOwner != u.newOwner:
                        oldIsBurn = oldOwner == burn
                        if not oldIsBurn:
                            share = self.data.accPerToken - entry.lastSeenAcc
                            if share > sp.mutez(0):
                                current = self.data.pending.get(
                                    oldOwner, default=sp.mutez(0)
                                )
                                self.data.pending[oldOwner] = current + share
                        if oldIsBurn:
                            if not newIsBurn:
                                self.data.activeSupply += sp.nat(1)
                        else:
                            if newIsBurn:
                                self.data.activeSupply = sp.as_nat(
                                    self.data.activeSupply - sp.nat(1)
                                )
                        self.data.idLookUp[u.txlId] = sp.record(
                            owner=u.newOwner,
                            lastSeenAcc=self.data.accPerToken,
                        )
                        sp.emit(
                            sp.record(
                                txlId=u.txlId,
                                oldOwner=oldOwner,
                                newOwner=u.newOwner,
                            ),
                            tag="ownerChanged",
                        )
                else:
                    if not newIsBurn:
                        self.data.activeSupply += sp.nat(1)
                    self.data.idLookUp[u.txlId] = sp.record(
                        owner=u.newOwner,
                        lastSeenAcc=self.data.accPerToken,
                    )
                    sp.emit(
                        sp.record(
                            txlId=u.txlId,
                            newOwner=u.newOwner,
                        ),
                        tag="ownerRegistered",
                    )

        # ── Admin: settle accrued shares into `pending` ─────────────
        @sp.entrypoint
        def settleBatch(self, params):
            """For each token_id in the list, move its accrued share
            from the accumulator into pending[owner]. Bumps the token's
            lastSeenAcc so the same share isn't credited twice. Does
            NOT send tez (use pushPayouts to actually move funds)."""
            sp.cast(params.tokenIds, sp.list[sp.nat])
            assert sp.sender == self.data.admin, "notAdmin"
            assert not self.data.paused, "paused"
            assert sp.len(params.tokenIds) <= MAX_BATCH, "batchTooLarge"
            for token_id in params.tokenIds:
                assert token_id in self.data.idLookUp, "unknownToken"
                entry = self.data.idLookUp[token_id]
                if entry.owner != self.data.burnSentinel:
                    share = self.data.accPerToken - entry.lastSeenAcc
                    if share > sp.mutez(0):
                        current = self.data.pending.get(
                            entry.owner, default=sp.mutez(0)
                        )
                        self.data.pending[entry.owner] = current + share
                        self.data.idLookUp[token_id] = sp.record(
                            owner=entry.owner,
                            lastSeenAcc=self.data.accPerToken,
                        )

        # ── Admin: drain pending → recipients ───────────────────────
        @sp.entrypoint
        def pushPayouts(self, params):
            """sp.send each recipient their full pending balance.
            Atomic — if any recipient rejects tez, the whole batch
            reverts. Admin script should pre-filter to addresses
            known to accept tez. For a stuck contract holder, route
            via the burn sentinel before payout (oracle reassigns to
            burnSentinel; that token's accrued credit stops moving)."""
            sp.cast(params.recipients, sp.list[sp.address])
            assert sp.sender == self.data.admin, "notAdmin"
            assert not self.data.paused, "paused"
            assert sp.len(params.recipients) <= MAX_BATCH, "batchTooLarge"
            for addr in params.recipients:
                # Silently skip addresses with no pending — keeps the
                # batch tolerant of stale lists.
                if addr in self.data.pending:
                    amount = self.data.pending[addr]
                    if amount > sp.mutez(0):
                        del self.data.pending[addr]
                        sp.send(addr, amount)
                        sp.emit(
                            sp.record(recipient=addr, amount=amount),
                            tag="pushed",
                        )

        # ── Holder: pull-claim across owned token IDs ───────────────
        @sp.entrypoint
        def claim(self, params):
            """Caller passes the token IDs they believe they own. For
            each, the contract verifies ownership, settles the accrued
            share, then sends the caller their full pending balance.
            The dApp queries idLookUp ahead of time to populate the
            list; on-chain we verify so a forged list reverts."""
            sp.cast(params.tokenIds, sp.list[sp.nat])
            assert not self.data.paused, "paused"
            assert sp.len(params.tokenIds) <= MAX_BATCH, "batchTooLarge"
            for token_id in params.tokenIds:
                assert token_id in self.data.idLookUp, "unknownToken"
                entry = self.data.idLookUp[token_id]
                assert entry.owner == sp.sender, "notOwner"
                share = self.data.accPerToken - entry.lastSeenAcc
                if share > sp.mutez(0):
                    current = self.data.pending.get(
                        sp.sender, default=sp.mutez(0)
                    )
                    self.data.pending[sp.sender] = current + share
                    self.data.idLookUp[token_id] = sp.record(
                        owner=sp.sender,
                        lastSeenAcc=self.data.accPerToken,
                    )

            # Drain pending for the caller. Reentrancy belt-and-
            # suspenders: zero pending BEFORE sp.send.
            assert sp.sender in self.data.pending, "nothingToClaim"
            amount = self.data.pending[sp.sender]
            assert amount > sp.mutez(0), "nothingToClaim"
            del self.data.pending[sp.sender]
            sp.send(sp.sender, amount)
            sp.emit(
                sp.record(who=sp.sender, amount=amount),
                tag="claimed",
            )


# ── Compile-only origination test ──────────────────────────────────────
# Minimal scenario the SmartPy compiler needs to emit Michelson. Bakes
# the production admin + oracle addresses into initial storage. If you
# need to inspect the contract under SmartPy's expanded scenario,
# uncomment the behavior_flow test below.
@sp.add_test()
def deployment():
    # Scenario name starts with "a " so this scenario's artifact
    # subdirectory sorts before any behavior-flow tests. compile.sh
    # flattens subdirs in sorted order and skips files already claimed
    # by an earlier sibling — this is how it picks which scenario's
    # initial storage becomes the canonical origination storage.
    # Without the "a " prefix, "txl v2 behavior flow" sorts before
    # "txl v2 deployment" and bakes test_account stub addresses into
    # storage instead of the real admin/oracle/burn addresses.
    s = sp.test_scenario("txl v2 a deployment", main)
    s.h1("Originate TxlManager v2")
    txl = main.TxlManager(
        admin=sp.address(DEFAULT_ADMIN),
        oracle=sp.address(DEFAULT_ORACLE),
        burnSentinel=sp.address(OBJKT_MARKETPLACE),
    )
    s += txl


# ── Behavior flow simulation ──────────────────────────────────────────
# End-to-end happy path exercising the accumulator math, owner-change
# settlement, push payout flow, and the holder-pull claim. Covers the
# audit checklist from the v2 brief (deposit guards, batch caps,
# access reverts, pause gates, dust path).
@sp.add_test()
def behavior_flow():
    # Scenario name leads with a digit so its sanitized subdir sorts
    # BEFORE the deployment scenario (`txl_v2_a_deployment`).
    # compile.sh's flatten uses plain `mv` which overwrites — and the
    # LATER iteration wins. We want deployment's real addresses to be
    # the winner, so behavior-flow has to land first (early =
    # overwritten). See the matching comment on the deployment
    # scenario name.
    s = sp.test_scenario("0 txl v2 behavior flow", main)

    admin = sp.test_account("admin")
    oracle = sp.test_account("oracle")
    burn = sp.test_account("burn")
    alice = sp.test_account("alice")
    bob = sp.test_account("bob")
    carol = sp.test_account("carol")
    sweeper = sp.test_account("sweeper")
    intruder = sp.test_account("intruder")

    c = main.TxlManager(
        admin=admin.address,
        oracle=oracle.address,
        burnSentinel=burn.address,
    )
    s += c

    s.h1("Origination state: activeSupply=0, default reverts")
    c.default(
        _amount=sp.tez(1),
        _valid=False,
        _exception="noActiveHolders",
    )

    s.h1("Oracle assigns 3 IDs: alice=2 (60199, 60200), bob=1 (60201)")
    c.batchUpdateOwner(
        updates=[
            sp.record(txlId=60199, newOwner=alice.address),
            sp.record(txlId=60200, newOwner=alice.address),
            sp.record(txlId=60201, newOwner=bob.address),
        ],
        _sender=oracle,
    )
    # activeSupply should be 3 now. Two more IDs to carol, one to burn.
    c.batchUpdateOwner(
        updates=[
            sp.record(txlId=60202, newOwner=carol.address),
            sp.record(txlId=60203, newOwner=carol.address),
            sp.record(txlId=60204, newOwner=burn.address),  # no-op (already burn)
        ],
        _sender=oracle,
    )
    # activeSupply now 5 (60199, 60200, 60201, 60202, 60203).

    s.h1("Non-oracle updateOwner reverts")
    c.updateOwner(
        txlId=60199,
        newOwner=intruder.address,
        _sender=intruder,
        _valid=False,
        _exception="notOracle",
    )

    s.h1("default(5000000 mutez = 5 ꜩ) → accPerToken += 1 ꜩ each")
    # 5 active tokens, 5 ꜩ in → 1 ꜩ per token, 0 dust.
    c.default(_amount=sp.tez(5), _sender=intruder)
    # accPerToken == 1_000_000 mutez, dust == 0, totalRewards == 5 ꜩ.

    s.h1("default(5000007 mutez) → 1 mutez per token, 2 mutez dust")
    c.default(_amount=sp.mutez(5_000_007), _sender=intruder)
    # accPerToken now 1_000_000 + 1_000_001 = 2_000_001 mutez/token.
    # dust = 2 mutez (5_000_007 - 5 * 1_000_001).

    s.h1("Admin settleBatch for alice's + bob's IDs → pending populated")
    c.settleBatch(
        tokenIds=[60199, 60200, 60201],
        _sender=admin,
    )

    s.h1("Admin pushPayouts to alice + bob → tez moves, pending zeroes")
    c.pushPayouts(
        recipients=[alice.address, bob.address],
        _sender=admin,
    )
    # alice gets 2 * 2_000_001 = 4_000_002 mutez.
    # bob gets 1 * 2_000_001 = 2_000_001 mutez.

    s.h1("Carol uses holder-pull claim(60202, 60203)")
    c.claim(
        tokenIds=[60202, 60203],
        _sender=carol,
    )
    # carol gets 2 * 2_000_001 = 4_000_002 mutez.

    s.h1("Claim with no pending reverts")
    c.claim(
        tokenIds=[60202, 60203],
        _sender=carol,
        _valid=False,
        _exception="nothingToClaim",
    )

    s.h1("Forged claim — intruder claims alice's NFTs → notOwner")
    c.claim(
        tokenIds=[60199],
        _sender=intruder,
        _valid=False,
        _exception="notOwner",
    )

    s.h1("Pause blocks default + claim + push, oracle still works")
    c.pause(_sender=admin)
    c.default(
        _amount=sp.tez(1),
        _sender=intruder,
        _valid=False,
        _exception="paused",
    )
    c.claim(
        tokenIds=[60199],
        _sender=alice,
        _valid=False,
        _exception="paused",
    )
    # Oracle ops still allowed even when paused.
    c.updateOwner(
        txlId=60199,
        newOwner=bob.address,
        _sender=oracle,
    )
    c.unpause(_sender=admin)

    s.h1("Owner change settles old owner — alice's accrued moves to pending")
    # After the above updateOwner, 60199 moved from alice → bob. Bob
    # already drained his pending; the share now in pending[alice]
    # equals whatever alice had accrued on 60199 since her last settle
    # (which was 0 — she'd already been settled in pushPayouts above).
    # So nothing should move here. Confirm by a no-op claim.
    c.claim(
        tokenIds=[60199],
        _sender=bob,
        _valid=False,
        _exception="nothingToClaim",
    )

    s.h1("Batch too large → batchTooLarge")
    # 51 entries > MAX_BATCH (50).
    big_batch = [
        sp.record(txlId=TXL_TOKEN_IDS[i], newOwner=alice.address)
        for i in range(51)
    ]
    c.batchUpdateOwner(
        updates=big_batch,
        _sender=oracle,
        _valid=False,
        _exception="batchTooLarge",
    )

    s.h1("sweepDust by non-admin → notAdmin")
    c.sweepDust(
        recipient=sweeper.address,
        _sender=intruder,
        _valid=False,
        _exception="notAdmin",
    )

    s.h1("sweepDust by admin → 2 mutez goes to sweeper")
    c.sweepDust(
        recipient=sweeper.address,
        _sender=admin,
    )

    s.h1("sweepDust again → noDust (already drained)")
    c.sweepDust(
        recipient=sweeper.address,
        _sender=admin,
        _valid=False,
        _exception="noDust",
    )

    s.h1("Admin handover two-step")
    c.proposeAdmin(newAdmin=carol.address, _sender=admin)
    c.acceptAdmin(
        _sender=intruder,
        _valid=False,
        _exception="notProposedAdmin",
    )
    c.acceptAdmin(_sender=carol)
    # carol is admin now; old admin (sp.test_account "admin") is not.
    c.pause(
        _sender=admin,
        _valid=False,
        _exception="notAdmin",
    )
    c.pause(_sender=carol)
    c.unpause(_sender=carol)
