# TXL mainnet runbook

How to fund the TXL holder-reward manager, how holders claim, how the
oracle keeps owner records current, how to rotate keys, and how to
pause if something goes wrong.

## At a glance

- **What it is:** the v2 TXL holder-reward contract. Games (AD, Plinko,
  Squares, etc.) forward a "holder fee" tez transfer to this KT1
  every bet/round. The contract accumulates per-active-token and
  pays it out to the 271 Kalamint TXL NFT holders.
- **Distribution model:** flat accumulator. Every active NFT earns the
  same per-deposit share. Tokens currently held by the objkt
  marketplace KT1 are excluded — their share redistributes to active
  holders via the divisor (`activeSupply = 271 - objkt_owned`).
- **Two payout paths:**
  - **Pull (any holder):** call `claim(tokenIds: list[nat])` from a
    holder's wallet. Holder pays gas.
  - **Push (admin):** `settleBatch(tokenIds)` then
    `pushPayouts(addresses)`. Admin pays gas. Used for the live
    payout test and any operator-driven distribution event.

## Key contract addresses

| Network    | KT1                                          |
|------------|----------------------------------------------|
| shadownet  | check `TXL_CONTRACT_ADDRESS_SHADOWNET` in `src/constants.js` |
| mainnet    | check `TXL_CONTRACT_ADDRESS_MAINNET` in `src/constants.js`   |

`deploy.py` auto-patches these on origination. tzkt:
`https://[shadownet.]tzkt.io/<KT1>`.

## Roles

- **admin:** the deploy wallet (`tz1ZU2RLW7UgY8XXz49ccKihNy86zs6TdQ8Q`
  by default, mirrored in `constants.js` as `ADMIN_ADDRESS`). Controls
  pause/unpause, oracle rotation, push payouts, dust sweep.
- **oracle:** a separate, fresh tz1 derived from `TXL_ORACLE_MNEMONIC`
  in `.env`. The shadownet v2 oracle is
  `tz1cZCXFNV3LSogGPfEGoEPEH7t3y14Y55pz`. **Generate a new mnemonic
  before mainnet deploy** — do not reuse shadownet keys for mainnet.
  Run:
  ```
  python3 -c "from mnemonic import Mnemonic; from pytezos import Key; \
    m = Mnemonic('english').generate(strength=256); \
    print('MNEMONIC:', m); print('TZ1:', Key.from_mnemonic(m.split()).public_key_hash())"
  ```
  Add `TXL_ORACLE_MNEMONIC="..."` to `.env`. The v1 oracle seed
  hardcoded in `src/services/oracle_TXL.py` is publicly committed
  and **must not** be reused.
- **burnSentinel:** the objkt marketplace KT1
  (`KT1FvqJwEDWb1Gwc55Jd1jjTHRVWbYKUUpyq`). Hardcoded at origination,
  not rotatable.

## Funding (how tez gets into the contract)

Any game contract that holds a `txlContract` pointer forwards the
holder fee with a plain `sp.send` or `sp.transfer((), fee, holder)` to
the TXL KT1. Both hit `default()`, which:

  1. Asserts the contract is not paused.
  2. Asserts `activeSupply > 0` (so deposits revert until the oracle
     reconciles at least one real holder).
  3. Adds `floor(amount / activeSupply)` to `accPerToken`.
  4. Adds `amount mod activeSupply` to `dust`.
  5. Adds `amount` to `totalRewards`.

To fund the contract manually (e.g. for the live payout test), send a
plain tez transfer to the KT1 from any wallet:

```python
from pytezos import pytezos, Key
client = pytezos.using(shell="https://mainnet.tezos.ecadinfra.com",
                      key=Key.from_mnemonic("…".split()))
op = client.transaction(
    destination="KT1…TXL",
    amount=5_420_000,         # 5.42 ꜩ in mutez
).autofill().sign().inject(_async=False, min_confirmations=1)
```

After confirmation, verify on tzkt: `accPerToken` should have jumped
by `floor(5_420_000 / activeSupply)`, `dust` by the remainder, and
`totalRewards` by `5_420_000`.

## Holder claim (pull)

A holder calls `claim(tokenIds=[...])` from their wallet, passing the
TXL token IDs they own. The contract verifies ownership per ID,
settles each ID's accrued share into `pending[caller]`, then sends
the full pending balance to the caller. Gas is paid by the holder.

The dApp's "Claim your share" button (when built — task 18 in the
v2 brief) reads owned IDs from `idLookUp` ahead of time and prefills
the call. Until that UI ships, holders can call via
taquito/pytezos/Better Call Dev.

## Admin push (live payout)

The "single click" the operator runs to pay everyone is actually a
two-phase script driving two contract entrypoints:

1. **Settle:** `settleBatch(tokenIds: list[nat])`. Walks each ID, moves
   accrued credit from the accumulator into `pending[owner]`. Caps at
   `MAX_BATCH = 50` per op. For 271 IDs that's ~6 ops.
2. **Push:** `pushPayouts(recipients: list[address])`. Sends each
   recipient their full pending balance. Atomic per op — a recipient
   that rejects tez aborts that batch (split into smaller batches to
   skip the bad address; or route them to burnSentinel and the
   share stays parked in pending).

Why split: if a single contract-holder rejects tez during a unified
"settle+send" op, the whole storage update reverts. The split lets
settlement complete even when one push fails.

Reference flow (admin's wrapper script — TBD):
```
for chunk in chunks(all_token_ids, 50):
    contract.settleBatch(tokenIds=chunk).send()

# Read pending big_map via tzkt to get the addresses+amounts
pending = fetch_pending_big_map_via_tzkt(...)

for chunk in chunks(list(pending.keys()), 50):
    contract.pushPayouts(recipients=chunk).send()
```

## Oracle reconcile (keeping owners current)

`src/services/reconcile_txl_owners.py` is the only oracle entrypoint
going forward. It:

  1. Reads every TXL token's current owner from the Kalamint FA2
     ledger (mainnet big_map 857) — same source the explorer UI
     uses.
  2. Diffs against the on-chain `idLookUp` big_map.
  3. Submits `batchUpdateOwner` ops (50/op) to bring the on-chain
     ledger current. Objkt-marketplace-held tokens are routed to
     `burnSentinel` (which IS the objkt KT1 in v2).

Usage:
```
# Dry run, writes a markdown + CSV diff under reports/
python src/services/reconcile_txl_owners.py --network shadownet
python src/services/reconcile_txl_owners.py --network mainnet

# Apply the diff (signs with TXL_ORACLE_MNEMONIC, sends ops)
python src/services/reconcile_txl_owners.py --network mainnet --execute
```

Schedule cadence: hourly is fine for now (matches v1's loop). A cron
or scripts/oracle_worker.py wrapper can drive it.

## Pause / unpause

`pause()` halts deposits (`default`), holder claims, and admin pushes.
Oracle ops (`updateOwner`, `batchUpdateOwner`) still work — keeping
the owner ledger current during incident response is desirable.
Admin role ops (`proposeAdmin`, `updateOracle`, `unpause`, `sweepDust`)
also still work.

```
contract.pause().send()
# do incident response
contract.unpause().send()
```

## Rotate the oracle key

If `TXL_ORACLE_MNEMONIC` is suspected compromised:

1. Generate a fresh mnemonic (see "Roles" above).
2. Update `.env` locally (and on any operator host running the
   reconcile script).
3. From the admin wallet:
   ```
   contract.updateOracle(newOracle="tz1<new oracle tz1>").send()
   ```
4. Verify on tzkt that storage `oracle` now points at the new tz1.

## Rotate the admin key (two-step)

`proposeAdmin(newAdmin)` from old admin, then `acceptAdmin()` from the
new admin. The two-step prevents a typo from locking the contract.

## Sweep dust

Truncation accumulates in `dust` after each `default()` deposit. Admin
drains via:
```
contract.sweepDust(recipient="tz1...").send()
```
Recipient is a parameter (not `sp.sender`) so every sweep is auditable
with the destination on-chain.

## Mainnet deploy checklist

Before originating on mainnet:

- [ ] Generate a fresh `TXL_ORACLE_MNEMONIC`, add to `.env`. Do not
      reuse the shadownet mnemonic.
- [ ] Update `DEFAULT_ORACLE` in `src/services/smart_contract_txl.py`
      to the new tz1.
- [ ] Run `./scripts/compile.sh txl --no-deploy` and confirm the
      `step_002_cont_0_storage.tz` has the new oracle address.
- [ ] Copy fresh artifacts into `contracts/txl/`:
      ```
      cp src/services/build/txl/step_002_cont_0_contract.tz contracts/txl/code.tz
      cp src/services/build/txl/step_002_cont_0_contract.json contracts/txl/code.json
      cp src/services/build/txl/step_002_cont_0_storage.json contracts/txl/storage.json
      ```
- [ ] Deploy: `./scripts/deploy.sh txl --network mainnet`.
- [ ] tzkt: confirm `admin`, `oracle`, `burnSentinel`, `paused`,
      `totalSupply=271`, `activeSupply=0`, empty `idLookUp`/`pending`.
- [ ] Run reconcile dry-run against mainnet, review report, then
      execute.
- [ ] Verify `activeSupply` matches `271 - objkt_owned` from the
      report.
- [ ] Re-point each game contract's `txlContract` to the new KT1
      (one `updateTxlContract` op per game).

## Mainnet payout test (the live test)

See `docs/MAINNET_TXL_LIVE_TEST.md` (created on the day of the test)
for the actual op hashes + screenshots. Procedure:

1. Pick a known funding amount (e.g. 5.42 ꜩ — clean divisor with
   ~160 active holders).
2. Send the tez transfer from the deploy wallet to the TXL KT1.
3. Verify storage: `accPerToken += amount / activeSupply`,
   `totalRewards += amount`.
4. Run the admin push flow (settleBatch → pushPayouts) against all
   active holders. Capture each op hash.
5. Spot-check 2-3 recipients on tzkt — confirm they received
   `(holdings_count) * accPerToken_delta`.
