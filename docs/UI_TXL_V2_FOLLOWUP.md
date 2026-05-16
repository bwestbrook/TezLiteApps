# UI ↔ TXL v2 incompatibility — RESOLVED

**Status:** Resolved in commit `a168a49` *(fix(txl-ui): rewire mainBody
for TXL v2 accumulator + big_map storage)* — May 16 2026.

Surfaced during AD mainnet deploy prep. The TXL contract was rewritten
from v1 → v2 (`src/services/smart_contract_txl.py`, v1 moved to
`src/services/legacy/smart_contract_txl_v1.py`) and re-originated:

- shadownet: `KT1JukrFQ2DtKPDRDBq4j3Z6HkXtXxuF2Evd`
- mainnet:   `KT1TYgt7SphtEQHLk4GySkXckhSctJww5hdj`

`src/components/mainBody.vue` was still wired to the v1 storage shape
and the v1 holder-claim entrypoint, so the holder banner read 0 and the
Cash Out button would have reverted with "no such entrypoint" against
either v2 KT1. AD itself was unaffected (no direct TXL refs in
`aceyDuecey.vue`; AD's fee-forwarding is the chain-level `sp.send`).

## What broke + what was done

### Break 1 — `refreshTxlContract` iterated a big_map as if it were a map

In v1, `idLookUp` was an inline `sp.map[nat, record(owner, balance)]`
that Taquito returned as an object. In v2 it's an `sp.big_map[nat,
record(owner, lastSeenAcc)]` — Taquito returns a numeric big_map ID
(e.g. `808955` on mainnet), so `Object.values(<int>)` yielded zero
entries. "Your Claimable Share" always read `0.000000 ꜩ`.

**Fix in `mainBody.vue:refreshTxlContract`:** pull
`/v1/bigmaps/<idLookUp_id>/keys?value.owner=<address>&active=true` via
the existing `tzktGet` helper; for each owned entry compute `share =
accPerToken − lastSeenAcc`; add `pending[address]` from the pending
big_map (queried via `getBigmapKey`) for already-settled-but-not-yet-
sent credit. Sum surfaces as `txlShare`; the owned token-id list is
stashed in new data property `txlOwnedTokenIds` for Break 2 to consume.
`storage.totalRewards` keeps powering the "Unclaimed pool" chip
unchanged.

### Break 2 — `payNftHolderBC` called a removed entrypoint

v2 dropped `payTxlHolder()` (the v1 implementation walked all 271
entries on every claim — see v2 source's design notes). The replacement
is `claim(tokenIds: list[nat])` which settles + sends only the IDs
passed in.

**Fix in `mainBody.vue:payNftHolderBC`:** short-circuits with "No TXL
tokens owned" when `txlOwnedTokenIds` is empty; otherwise iterates
`txlOwnedTokenIds` in chunks of 50 (the contract's `MAX_BATCH`) and
calls `contract.methods.claim(chunk).send()` per batch. Uses `.methods`
instead of `.methodsObject` because v2 `claim`'s parameter is a bare
`list nat` (SmartPy unwraps the single-field record).

## What's still worth verifying

- **Mainnet reconcile is in progress** (as of May 16 2026, 20:00 UTC):
  `activeSupply=16/271`, `accPerToken=62500`, `totalRewards=1 ꜩ` — the
  first deposit has flowed and one of the 16 reconciled holders is
  jamin_b's wallet (`tz1Vq5mY…`). That makes the UI fix **visually
  testable on mainnet now**: connect jamin_b, the holder banner should
  show owned token IDs from the sample (60694, 60491, 60367, …) and a
  claimable share derived from `accPerToken − lastSeenAcc` per token.
- **Shadownet reconcile hasn't started yet** (`activeSupply=0`,
  `accPerToken=0`). The UI fix is exercised but can't be visually
  validated on shadownet until the TXL agent populates `idLookUp` there
  too. The fix gracefully handles the empty case (zero owned → "No TXL
  tokens owned" status, no revert).
- **Other game UIs.** Greppable via `payTxlHolder` and `idLookUp` —
  none found at fix time (only `mainBody.vue` referenced TXL UI flows),
  but worth a fresh grep after any future migration.
- **Shadownet squares `txlContract`** was simultaneously realigned in
  commit `7df37c1` from the v1 distributor (`KT1Ro63…`) to v2
  (`KT1JukrFQ2…`) so newly-bought squares' holder fees actually feed
  the v2 accumulator the UI now reads from.
