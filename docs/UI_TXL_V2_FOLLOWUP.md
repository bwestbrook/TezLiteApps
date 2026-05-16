# UI ↔ TXL v2 incompatibility — follow-up

Surfaced during the AD mainnet deploy prep (May 2026). The TXL contract
was rewritten from v1 → v2 (`src/services/smart_contract_txl.py`, with
v1 moved to `src/services/legacy/smart_contract_txl_v1.py`) and
re-originated on both networks:

- shadownet: `KT1JukrFQ2DtKPDRDBq4j3Z6HkXtXxuF2Evd`
- mainnet:   `KT1TYgt7SphtEQHLk4GySkXckhSctJww5hdj`

The UI in `src/components/mainBody.vue` still queries the v1 storage
shape and calls a v1-only entrypoint, so the holder-banner is broken
against any KT1 running v2. AD itself is unaffected (no direct TXL
references in `src/components/aceyDuecey.vue`), but this needs to land
before the mainnet AD launch is user-visible if the banner sits on the
same page.

## Break 1 — `refreshTxlContract` iterates a big_map as if it were a map

`mainBody.vue:199-230`

```js
const storage = await getContractStorage(TXL_CONTRACT_ADDRESS)
// ...
for (const entry of Object.values(storage.idLookUp || {})) {
  if (entry?.owner === address) { ... }
}
```

In v1, `idLookUp` was an `sp.map[nat, record(owner, balance)]` — Taquito
returned it as an object whose values you could iterate. In v2 it's an
`sp.big_map[nat, record(owner, lastSeenAcc)]` — Taquito returns a
**numeric big_map ID** (`808955` on mainnet right now), and
`Object.values(808955)` yields nothing. Result: "Your Claimable Share"
always shows `0.000000 ꜩ` even when the wallet owns TXL NFTs.

### Fix

The wallet's owned token IDs aren't enumerable from a big_map directly
on chain. Three options:

1. **Query tzkt for big_map entries** (preferred — matches existing
   `getContractStorage` pattern). Pull
   `/v1/bigmaps/<idLookUp_id>/keys?value.owner.eq=<address>&active=true`
   and use the resulting key list. Then for each owned token ID, fetch
   `pending[<address>]` to compute the claimable share.
2. Walk the FA2 ledger (Kalamint bigmap 857) like
   `reconcile_txl_owners.py` does, then look up each ID in `idLookUp`
   to confirm registration. Heavier.
3. Read `storage.pending[<address>]` directly (also a big_map → tzkt
   lookup). This gives the *settled* share but misses
   accrued-but-not-yet-settled amounts.

Recommended: option 1 for the share calculation, plus option 3 to also
display pending (settled) separately.

### What stays the same

`storage.totalRewards` is still a top-level mutez field in v2
(`mainBody.vue:206`), so the "Unclaimed pool" banner keeps working
without changes.

## Break 2 — `payNftHolderBC` calls a removed entrypoint

`mainBody.vue:233-254`

```js
await this.tezos.wallet
  .at(TXL_CONTRACT_ADDRESS)
  .then((contract) => contract.methodsObject.payTxlHolder().send())
```

v2 removed `payTxlHolder` (which walked all 271 entries on every claim
— see the v2 source's design notes). The replacement is
`claim(tokenIds: list[nat])` which settles + pays only the IDs passed
in. The caller must therefore know which IDs they own.

### Fix

Replace the `.payTxlHolder()` call with a `.claim(tokenIds)` call,
where `tokenIds` is the same list discovered in the Break-1 fix. Same
button label, same UX from the user's perspective. The
op-confirmation/cash-out-status state machine in `payNftHolderBC` is
otherwise reusable.

## What's still correct

- `mainBody.vue:204` `getContractStorage(TXL_CONTRACT_ADDRESS)` —
  storage call still returns valid data; just need to interpret the new
  shape.
- `mainBody.vue:206` `storage.totalRewards` — unchanged.
- `src/components/aceyDuecey.vue` — no direct TXL references; AD's
  fee-forwarding is entirely on-chain via `sp.send(self.data.txlContract, ...)`,
  which is unaffected by UI code.
- Other game UIs (Plinko, War, etc.) need an audit pass too. Greppable
  via `payTxlHolder` and `idLookUp` references.

## Cross-check before fixing

Confirm `tz1cZCXFNV3LSogGPfEGoEPEH7t3y14Y55pz` (shadownet TXL `oracle`
key) is reconciling the shadownet idLookUp before relying on it for
test data. As of this writing both shadownet and mainnet TXL have
`activeSupply=0` (no reconcile yet), so the UI fix can't even
end-to-end test until the TXL agent's reconcile pass runs.
