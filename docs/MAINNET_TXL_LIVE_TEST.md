# TXL v2 — mainnet live payout test

**Date:** 2026-05-16 (UTC)
**Contract:** `KT1TYgt7SphtEQHLk4GySkXckhSctJww5hdj`
**Recipient:** `tz1Vq5mYKXw1dD9js26An8dXdASuzo3bfE2w` (jamin_b's TXL-holder wallet)
**Result:** ✅ End-to-end round-trip verified. 1 ꜩ deposited → 1 ꜩ received.

## Scope

Self-test scoped to the operator's own holder wallet so the test path
exercises every entrypoint without distributing real claimable shares
to other holders. The broader 271-token reconcile + multi-holder push
is staged separately.

Only the 16 token IDs owned by `tz1Vq5m…E2w` were registered. With
`activeSupply = 16`, the math works out 1:1 — a 1 ꜩ deposit splits as
62,500 mutez × 16 tokens → 1 ꜩ owed to the sole holder.

## Ops

| Step | Op hash | Signer | What |
|------|---------|--------|------|
| 0 | [`oo2cSaL1wY…fjgHjUS`](https://tzkt.io/oo2cSaL1wYjemTDbhGepsAzVM7JZntLcPjDVjMzNKJtYfjgHjUS) | oracle | Reveal oracle public key (first op from wallet) |
| 1 | [`ooXkFTey3w…GvyXFNTm`](https://tzkt.io/ooXkFTey3w1X64a6hp173nUPpNcDSFb7URSC25KF3amGvyXFNTm) | oracle | `batchUpdateOwner` for 16 IDs → `tz1Vq5m…E2w` |
| 2 | [`ooLA6zaUVV…NosLnxG`](https://tzkt.io/ooLA6zaUVVSyGSZNqMwZozg6CGABRQAfx5uQkNQN4ywxNosLnxG) | deploy | Plain transfer 1 ꜩ → TXL KT1 (hits `default()`) |
| 3 | [`oovCqHg5z3…K4TZM7H`](https://tzkt.io/oovCqHg5z3BtJmBV35YEuhP8EeTZXQct3AK8z5suiG18K4TZM7H) | admin | `settleBatch(16 tokenIds)` |
| 4 | [`onkyzYzzP8…YaPCxeY`](https://tzkt.io/onkyzYzzP8EGbSVunfACccELynCpsTzDzUfZ1EQpSYX1YaPCxeY) | admin | `pushPayouts([tz1Vq5m…E2w])` |

## Storage diff

After step 1 (registration):
```
activeSupply: 0 → 16
idLookUp:     {} → { 60338→tz1Vq5m..., 60363→tz1Vq5m..., … }  (16 entries)
```

After step 2 (deposit of 1,000,000 mutez):
```
accPerToken:  0 → 62,500          # = 1,000,000 / 16
dust:         0                   # 1,000,000 mod 16 = 0
totalRewards: 0 → 1,000,000
```

After step 3 (settle):
```
idLookUp[*].lastSeenAcc: 0 → 62,500          (all 16 entries)
pending[tz1Vq5m…E2w]:    ∅ → 1,000,000        # 16 × 62,500
```

After step 4 (push):
```
pending[tz1Vq5m…E2w]:    1,000,000 → ∅
```

Final state:
```
accPerToken:  62,500
totalRewards: 1,000,000
activeSupply: 16
dust:         0
contract balance: 0 ꜩ          (1 ꜩ in, 1 ꜩ out)
```

## Balance changes

| Wallet | Before | After | Δ | Notes |
|--------|--------|-------|---|-------|
| Deploy (`tz1ZU2RL…TdQ8Q`) | 8.7477 ꜩ | 7.7185 ꜩ | −1.029 ꜩ | 1 ꜩ deposit + ~0.03 ꜩ gas across ops 3+4 |
| Oracle (`tz1QtpR6…JFPWv`) | 10.0000 ꜩ | (~9.85 ꜩ) | ~−0.15 ꜩ | reveal + 16-entry batchUpdateOwner gas |
| Holder (`tz1Vq5m…E2w`) | 80.5323 ꜩ | 81.5323 ꜩ | **+1.000 ꜩ** | Push payout landed exactly |
| TXL contract | 0 ꜩ | 0 ꜩ | 0 | Funds passed through cleanly |

## What this proves

1. **Oracle key works** — fresh `TXL_ORACLE_MNEMONIC_MAINNET` derives to
   the expected tz1, signs ops accepted by the contract.
2. **Lazy-create works** — first-touch `batchUpdateOwner` populated the
   ledger and bumped `activeSupply` correctly.
3. **`default()` works** — plain `sp.send` to KT1 is the deposit path.
4. **Accumulator math is bit-exact** — `accPerToken = amount /
   activeSupply` for clean divides, dust tracked separately.
5. **Two-phase admin push works** — `settleBatch` moves credit;
   `pushPayouts` releases tez. No reverts.
6. **No leakage** — contract balance back to 0, no orphaned `pending`.

## Followups

- Broader reconcile (all 271 IDs, `activeSupply → 159`) — Phase 2.
- Re-point game contracts' `txlContract` to the new mainnet KT1 —
  Phase 3, one `updateTxlContract` per game.
- `public/txl-owners-snapshot.json` regen post-broader-reconcile.
- "Claim your share" UI in `browseNFTs.vue` (task 18 in v2 brief) —
  pre-condition for any multi-holder rollout.
