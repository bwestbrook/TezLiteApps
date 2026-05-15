# TXL owners data — for the explorer UI

This is the canonical pointer if you (or a Claude Code session) need to load
"current owners" of the 271 Kalamint NFTs the TXL manager tracks.

## TL;DR

```js
import { loadOwners } from '@/services/txlOwners'

loadOwners().then(({ owners, topHolders, distinctHolders, onMarketplace }) => {
  // owners            : { '60199': 'tz1...', ... }   keyed by Kalamint nat ID
  // topHolders        : [['tz1...', 16], ...]         sorted desc
  // distinctHolders   : number
  // onMarketplace     : number sitting in objkt.com escrow (KT1FvqJ...UUpyq)
})
```

## Where the data lives

| What | Where | Refresh cadence |
|---|---|---|
| Static snapshot (fast paint) | `public/txl-owners-snapshot.json` (served at `/txl-owners-snapshot.json`) | Manual — regenerate when stale |
| Live source | tzkt mainnet `bigmaps/857/keys?active=true&value.eq=1&key.nat.in=<ids>` | On every page load via `fetchLive()` |
| Helper module | `src/services/txlOwners.js` | — |
| Underlying tzkt wrapper | `src/services/tzkt.js` (`tzktGet`, `getBigmapKey`) | — |

The 271 token IDs are hard-coded once in `txlOwners.js` as `TXL_TOKEN_IDS`,
and the same set lives in `idLookUp` inside `browseNFTs.vue` (which keys by
position 1..271 → kalaId) and in `src/services/smart_contract_txl.py` (the
contract source). All three must stay in sync if the TXL set ever changes.

## Refreshing the snapshot

The snapshot is just a copy of `reports/txl-current-owners.json`. To
regenerate from scratch:

```bash
python src/services/reconcile_txl_owners.py            # writes reports/txl-owners-<ts>.{csv,md}
# then update the snapshot the explorer ships with:
cp reports/txl-current-owners.json public/txl-owners-snapshot.json
```

(Or wire `reconcile_txl_owners.py` to also write `public/txl-owners-snapshot.json`
directly — see the `write_reports` function.)

## Schema

`public/txl-owners-snapshot.json`:

```json
{
  "contract": "KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy",
  "kalamint_bigmap": 857,
  "expected_count": 271,
  "returned_count": 271,
  "missing_ids": [],
  "owners": { "60199": "tz1W9ThvCcY7BDtEiSvdBuKPWuD9K8W89noh", ... },
  "top_holders": [["KT1FvqJwEDWb1Gwc55Jd1jjTHRVWbYKUUpyq", 112], ...]
}
```

## Notable holders to handle in the UI

- `KT1FvqJwEDWb1Gwc55Jd1jjTHRVWbYKUUpyq` — the **objkt.com marketplace**
  contract. Tokens parked here are *listed for sale*, not owned by an EOA.
  As of the current snapshot, **112 of 271** TXLs sit here. Worth labelling
  these as "for sale on objkt" in the UI rather than showing the raw KT1.
- `tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w` — `jamin_b` (the deployer).

`txlOwners.js` exports `OBJKT_MARKETPLACE` (the marketplace KT1) — compare an
owner address against it to flip the label to `'PRIMARY - OBJKT.COM'`.
`browseNFTs.vue` does this in `labelForOwner()`; new views (lists,
leaderboards) should use the same constant and label conventionally.

## Mainnet vs testnet reminder

> ⚠️ Ghostnet was decommissioned in 2026 (along with Baking Bad's
> TzKT Ghostnet API). The TXL manager + the snapshot oracle that used
> to live there are stale. The shadownet equivalent is what
> `TXL_CONTRACT_ADDRESS_SHADOWNET` points at in `src/constants.js`,
> read live by `src/components/mainBody.vue` for the holder pool /
> Unclaimed / Your Share chips. Anything in this folder still
> referencing `api.ghostnet.tzkt.io` (e.g. `oracle_TXL.py`,
> `reconcile_txl_owners.py`) is dead historical code until ported.

Ownership of the underlying Kalamint NFTs lives on **mainnet** (Kalamint
FA2 `KT1EpGgjQs73QfFJs9z7m1Mxm5MTnpC2tqse`, big_map 857). The browse-NFTs
explorer reads ownership from mainnet directly — `tzkt.js` accepts a
`{ network }` override for exactly this reason, and `txlOwners.js`
always passes `'mainnet'`.
