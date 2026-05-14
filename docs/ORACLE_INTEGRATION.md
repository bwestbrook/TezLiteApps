# RandomOracle Integration Guide

A drop-in randomness service for Tezos dApps. Pay a small mutez fee per
request; an off-chain worker delivers cryptographically-random values
back to your contract via a callback.

- **Mainnet address**: _TBD — populated after first mainnet deploy_
- **Shadownet address**: see `ORACLE_CONTRACT_SHADOWNET` in `src/constants.js`
- **Fee**: read live from `oracle.storage().fee` — currently `0.1 ꜩ`
- **Caps**: 1 to 32 random values per request; each in `[0, maxValue]`
- **Status**: experimental; integrations welcome

## How it works

```
┌─────────────────┐                                  ┌──────────────────┐
│  Your contract  │ ───── requestRandom(...) ───────▶│   RandomOracle   │
│                 │ ◀─── (callback invoked) ─────────│  KT1…            │
└─────────────────┘                                  └──────────────────┘
                                                              ▲
                                                              │ poll + fulfill
                                                              │
                                                     ┌──────────────────┐
                                                     │  off-chain bot   │
                                                     │  (operator runs) │
                                                     └──────────────────┘
```

Two phases:

1. **Request.** You call `requestRandom` on the oracle, attaching at
   least `fee` ꜩ. Tell it which entrypoint of which contract to call
   back, how many random values you want, and the max value per draw.
2. **Fulfill.** The off-chain oracle worker observes the pending request,
   draws values, and submits `fulfillRandom`. That op atomically:
   - credits the operator with your fee,
   - records the result + auditable seed on chain,
   - invokes your callback entrypoint with the result.

If your callback fails, the whole fulfillment op fails and the worker
retries. So make sure your callback can't revert under normal
conditions.

## Contract interface

### `requestRandom`

```michelson
(pair %requestRandom
  (address %callback)
  (pair
    (string %callbackEntrypoint)
    (pair
      (nat %nRandoms)
      (nat %maxValue))))
```

| Param | Type | Meaning |
|-------|------|---------|
| `callback` | `address` | Your contract (`KT1…`) that will receive the result |
| `callbackEntrypoint` | `string` | Which entrypoint on `callback` to invoke |
| `nRandoms` | `nat` | How many values to draw (1 to 32) |
| `maxValue` | `nat` | Each value is in `[0, maxValue]` inclusive |

Attach `sp.amount >= oracle.fee`. Anything above the fee is also
collected by the operator (think of it as a tip).

### Your callback entrypoint

Must accept exactly this record:

```python
sp.record(
    requestId=sp.nat,
    randomValues=sp.list[sp.nat],
)
```

**Always verify the sender** in the callback — if you don't, anyone
could spoof a result:

```python
@sp.entrypoint
def onRandomFulfilled(self, params):
    sp.cast(params.requestId, sp.nat)
    sp.cast(params.randomValues, sp.list[sp.nat])
    assert sp.sender == self.data.oracleContract, "not oracle"
    # ... use params.randomValues ...
```

### Events you can index

- `randomRequested` — `[requestId, nRandoms, maxValue]`
- `randomFulfilled` — `[requestId, randomValues]`

## Drop-in example

`src/services/smart_contract_oracle_reference.py` is a 60-line
CoinFlip dApp that wires up both sides. Compile it in the SmartPy IDE,
deploy with `scripts/deploy.py`, then call `flip()` and watch your
contract storage update via the oracle callback in ~30 seconds.

## Cost & latency

- **Gas/storage**: a `requestRandom` op writes one storage row (~150
  mutez storage cost); `fulfillRandom` updates that row and invokes
  your callback. End-to-end ~0.005 ꜩ in gas on shadownet.
- **Latency**: under 30 seconds on shadownet (one block to confirm the
  request + one block for the fulfill op). Mainnet is similar.
- **Reliability**: the worker is a single daemon today. For production
  use cases we recommend either (a) running your own worker against
  the same RandomOracle contract, or (b) waiting for the planned
  multi-operator upgrade.

## Auditability

Every fulfillment includes a `seed` string that the worker generates
from a cryptographically-secure random source (Python `secrets`). The
seed is recorded on chain so anyone can verify the worker isn't
biasing results — if you suspect manipulation, request the same seed
from the operator and reproduce the draw.

For high-stakes use cases requiring stronger guarantees, the planned
v3 design uses a commit-reveal scheme (operator commits to a hash
before the request, reveals the preimage on fulfillment). That's not
shipped yet.

## Running your own worker

If you don't trust the default operator (fair), point a copy of
`scripts/oracle_worker.py` at the same RandomOracle:

```bash
./scripts/oracle-worker.sh --game randomness --network mainnet
```

You'll need:
- A funded tz1 key matching `oracle.storage().oracle`
- Python 3.10+ with pytezos installed
- Always-on machine (any Linux/Mac box)

The worker is stateless — restarts are safe.

## Questions / bug reports

Open an issue on the TezLiteApps repo or DM `@jamin_b` on
Telegram/Discord. Fee revenue from your contract's usage helps fund
ongoing oracle uptime.
