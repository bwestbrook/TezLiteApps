# TXL owner reconciliation

## What this is

The TXL manager contract `KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy` (ghostnet) maintains
a big_map `idLookUp` that maps each of 271 Kalamint NFT IDs (60199 - 60696, with
gaps) to a `{owner, balance}` record. The `default` entrypoint splits incoming tez
across the 271 token balances; `payTxlHolder` lets a current Kalamint holder claim
their share. For this to work, `idLookUp[id].owner` has to match the actual
Kalamint owner on mainnet.

The existing `src/services/oracle_TXL.py` runs as a forever-loop watcher: every
hour it walks `idLookUp` and calls the `updateOwner` entrypoint (oracle-only) when
it spots a sale. This task asks for a *one-shot* reconciliation instead.

## What I produced

`src/services/reconcile_txl_owners.py` — a single-pass version of the same loop:

- **Dry run by default.** Reads ghostnet storage, queries Kalamint big_map 857 on
  mainnet for every token, writes a CSV + markdown diff to `reports/`, and exits.
- **`--execute` flag** signs and sends `updateOwner` ops in batches (default 25
  per group), using the oracle key. Mnemonic is read from
  `$TXL_ORACLE_MNEMONIC` if set, otherwise falls back to the same one hardcoded
  in `oracle_TXL.py`.
- **`--token-ids 60199,60200`** to scope a run to a subset (useful for spot-checks).
- Reports include rows where `current_owner` is `None` (no active value=1 holder
  in big_map 857 — burned, transferred away from the canonical ledger, or token
  never minted).

## Why this isn't run here

This sandbox can only reach `api.anthropic.com`; it can't talk to `api.tzkt.io`
or any RPC. So actually fetching the 271 owners and signing on-chain ops has to
happen from your machine, where `oracle_TXL.py` already runs.

## How to use

```bash
cd ~/Repositories/TezLiteApps
pip install pytezos requests

# Inspect — produces reports/txl-owners-<ts>.csv and .md
python src/services/reconcile_txl_owners.py

# Review the markdown report; if it looks right, sign + inject:
python src/services/reconcile_txl_owners.py --execute

# Or just check one token first:
python src/services/reconcile_txl_owners.py --token-ids 60199 --execute
```

## Notes on the contract

- `updateOwner` is gated to `sp.sender == self.data.oracle`
  (`tz1XbrvTMVa5dWQQBSCn2jgX7BPZyLRhgtKS`).
- The batched send uses `pytezos.bulk(...)`, which packages all the
  `updateOwner` ops into a single signed operation group. That's the cheapest
  way to push N updates and also makes it atomic per batch (all-or-nothing
  inside one block).
- `oracle_TXL.py` queries mainnet tzkt for ownership but the manager contract
  lives on ghostnet — that's intentional and unchanged here.
- The mnemonic is the same one already committed in `oracle_TXL.py`. Treat that
  as compromised regardless of network — anyone with read access to the repo
  can sign as the oracle. Rotating it would mean redeploying the manager
  contract (the oracle is set in storage at origination time), so the practical
  fix is just keeping ghostnet-only and never wiring the same key to mainnet.
