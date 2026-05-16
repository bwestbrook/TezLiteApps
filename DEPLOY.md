# Deploying TezLiteApps contracts

`scripts/deploy.py` compiles a SmartPy source, originates it on a chosen
Tezos network, and patches `src/constants.js` so the front-end picks up
the new address.

This document walks through the **oracle on shadownet** as the first deploy.
Every other contract follows the same pattern — just change the contract
id.

---

## 0. Heads up on the old script

The previous `src/services/deployContract.py` contained a hardcoded
24-word mnemonic. Anyone who's cloned the repo or seen git history has
that mnemonic. **Treat the account it controlled as compromised** and
move any funds out before you do anything else. The new `scripts/deploy.py`
never reads keys from source — only env vars or a key file.

---

## 1. One-time prerequisites

You only need **Python 3.10+**. Everything else is installed automatically
into a project-local virtualenv by `scripts/setup.sh`. No `pipx`, no global
pip installs, no clutter on your system Python.

Check your Python:

```
python3 --version    # must report 3.10 or higher
```

If it's missing or too old:
- **macOS:** `brew install python@3.12`
- **Linux:** `sudo apt install python3.12 python3.12-venv`
- **Or download:** https://www.python.org/downloads/

Then run the setup script from the repo root:

```
./scripts/setup.sh
```

It will:
- Create `.venv/` (gitignored).
- Install `pytezos` + `smartpy` into the venv.
- Verify both are usable.
- Scaffold a `.env` from `.env.example` if one doesn't exist.

Re-running is safe — it reuses the existing venv.

---

## 2. Get a shadownet account funded

Shadownet is the current Tezos testnet (Ghostnet was decommissioned in 2026).

1. Generate (or reuse) a Tezos wallet. In Temple Wallet:
   - Settings → Reveal seed phrase. Copy the 24 words.
2. Tell your wallet about shadownet so you can see balance:
   - Add custom network: `https://rpc.shadownet.teztnets.com`
3. Fund the account from the shadownet faucet:
   - https://faucet.shadownet.teztnets.com
   - Paste your `tz1...` address. The faucet drops ~6,000 testnet ꜩ.

Plenty for a few hundred originations.

---

## 3. Wire your key into the repo

Copy the template and fill in your mnemonic:

```
cp .env.example .env
# edit .env — paste your 24 words inside the quotes
```

`.env` is already in `.gitignore`. **Never commit it.**

If you'd rather use an encoded secret key file, set `DEPLOY_SK=edsk...`
in `.env` instead, or pass `--key /path/to/key.edsk` on the command line.

---

## 4. Deploy the oracle

From the repo root:

```
./scripts/deploy.sh oracle
```

(That's a thin wrapper that activates `.venv/` and calls
`scripts/deploy.py`. If you'd rather call Python directly:
`.venv/bin/python scripts/deploy.py oracle` works too.)

That defaults to shadownet. The script will:

1. Run `smartpy compile src/services/smart_contract_oracle.py` into
   `src/services/build/oracle/`. Output is gitignored.
2. Read the deployer key from `.env` (or `--key`).
3. Show the deployer address + balance. Bails loudly if you're broke.
4. Build an origination operation, autofill fees, sign, inject, wait
   for one confirmation.
5. Print the new `KT1…` address and the matching tzkt explorer link.
6. Patch `ORACLE_CONTRACT` in `src/constants.js` to the new address.

Expected output (abridged):

```
============================================================
Deploying oracle → shadownet
============================================================
Compiling src/services/smart_contract_oracle.py → src/services/build/oracle/
  code:    src/services/build/oracle/step_000_cont_0_RandomOracle.tz
  storage: src/services/build/oracle/step_000_cont_0_RandomOracle_storage.tz
Connecting to shadownet at https://rpc.shadownet.teztnets.com
Deployer: tz1...
Balance:  5912.3421 ꜩ
Originating oracle…
✓ oracle originated at KT1AbCdEfGhIjKlMnOpQrStUvWxYzAbCd
  https://shadownet.tzkt.io/KT1AbCdEfGhIjKlMnOpQrStUvWxYzAbCd
Updated ORACLE_CONTRACT in src/constants.js → KT1Ab…
Done.
```

If anything goes wrong (compile error, low balance, RPC down, etc.), the
script bails with a specific message. Re-run after fixing.

---

## 5. Verify the deploy

```
git diff src/constants.js
```

Should show exactly one line changed: `ORACLE_CONTRACT`.

Click the tzkt link from the script output — you should see the contract
storage with `admin = your address`, `oracle = tz1XbrvTM…` (the oracle
worker address baked into the source), the empty `requests` map, and so on.

---

## 6. Mainnet deploy when ready

Same command, different flag:

```
./scripts/deploy.sh oracle --network mainnet
```

The script will refuse to run if your deployer balance is under 1 ꜩ
(mainnet origination + initial storage typically costs around 0.5–1 ꜩ).

---

## 7. Deploying the rest

Once the oracle is live and you've copied its address into any games that
depend on it (each game contract has an `oracleContract` field in its
`__init__`), repeat the recipe for the other contracts:

```
python scripts/deploy.py acey-duecey
python scripts/deploy.py ttt
python scripts/deploy.py squares
```

Each one patches its own constants.js variable on success.

---

## 8. Flip the kill switch

While the placeholders were in `constants.js` we kept all on-chain polling
behind `BLOCKCHAIN_ENABLED = false`. Once every contract you care about
is deployed and addressed, flip:

```js
// src/constants.js
export const BLOCKCHAIN_ENABLED = true
```

Restart the dev server, hard-refresh, and the UI starts polling for real
game state from your new contracts.

---

## 9. Compiling without local SmartPy (online IDE fallback)

If `setup.sh` couldn't install SmartPy on your machine (smartpy.io
unreachable, exotic platform, etc.), you can compile each contract once
via the online IDE and skip local compilation:

1. Open https://smartpy.io/ide
2. File → Open → paste in `src/services/smart_contract_oracle.py`
   (or whichever contract you're deploying).
3. Click **Run**. The right panel should show "Contract compiled
   successfully".
4. Click **Compiled Contract** → **Download**. You'll get a zip
   with `.tz`, `_storage.tz`, and metadata files.
5. Unzip into `src/services/build/oracle/` so the structure is:
   ```
   src/services/build/oracle/
     ├ step_000_cont_0_RandomOracle.tz
     └ step_000_cont_0_RandomOracle_storage.tz
   ```
6. Run with `--skip-compile`:
   ```
   ./scripts/deploy.sh oracle --skip-compile
   ```

`scripts/deploy.py` will read the local `.tz` files and originate them
against the network. No SmartPy needed locally.


## 10. Common gotchas

- **`SmartPy compiler not found`** — re-run `./scripts/setup.sh`; the
  pip-install path is the most likely to succeed. If it can't, use the
  online IDE workflow above. You can also set `SMARTPY_CLI` in `.env`
  to either a path or a full command, e.g.:
  ```
  SMARTPY_CLI=/usr/local/bin/SmartPy.sh
  # or
  SMARTPY_CLI=docker run --rm -v $PWD:/work smartpy/cli
  ```
- **"Counter already used"** — you have two outstanding operations from
  the same address. Wait ~30 s and rerun.
- **"empty implicit contract"** — your deployer account is empty. Fund
  it from the faucet again (shadownet only).
- **Origination hangs at "waiting for confirmation"** — shadownet RPCs
  occasionally rate-limit. Re-run; the operation was likely accepted.
- **Compiled successfully but no .tz files found** — SmartPy may have
  written under a different scenario name. `ls src/services/build/<id>/`
  to see what's there, then update the `find_artifacts` glob in
  `scripts/deploy.py` if needed.


## 11. Squares: shadownet end-to-end smoke test

A focused checklist for exercising a freshly-originated squares contract
against a real ESPN game on shadownet. Run before promoting to mainnet —
the contract's interesting paths (axis randomisation, per-quarter payout,
pull-pattern claim) only get hit by a full game lifecycle. Two paths
below; pick whichever fits the situation.

Prereqs (one-time):
- Shadownet squares contract originated — `SQUARES_CONTRACT_ADDRESS_SHADOWNET`
  in `src/constants.js` is a real `KT1…`.
- `.env` has `DEPLOY_MNEMONIC` funded on shadownet (faucet:
  https://faucet.shadownet.teztnets.com — ~6 000 ꜩ per drip).
- The squares contract's `admin` in storage matches the
  `DEPLOY_MNEMONIC` key (the oracle worker won't authorise otherwise).

### Path A — emulator (single-shot, ~5 min)

`scripts/emulate_squares.py` drives the entire lifecycle from a wallet
that has the `admin` key, against a *finished* NBA/WNBA/NFL game it
picks off ESPN. It buys the grid out across two wallets (a deterministic
secondary derived from `DEPLOY_MNEMONIC` + a fixed salt), randomises
axes, reports each quarter from the real linescore, and prints the
pending winnings. Useful when you need a green check that the contract
behaves end-to-end without waiting for a live game.

```
.venv/bin/python scripts/emulate_squares.py                       # latest NBA final
.venv/bin/python scripts/emulate_squares.py --league WNBA
.venv/bin/python scripts/emulate_squares.py --league NFL --event-id 401671234
.venv/bin/python scripts/emulate_squares.py --dry-run             # no signed ops
```

What to look for in the output:
- `createGame` op hash and a tzkt link.
- 98 successful `buySquare` ops alternating between the two wallets.
- Phase transitions: `SELLING → LOCKED → AXES_SET → COMPLETE`.
- Four `reportQuarter` ops with the real per-quarter scores.
- Pending winnings printed per wallet at the end.

If anything reverts: the script prints the on-chain error string. The
common ones are `NotAdmin` (admin mismatch), `BadAmount` (ticket price
+ holder fee disagreement), and `NotPlayable` (script tried to report
a quarter before setAxes ran). Each error tells you which test-scenario
constant drifted.

### Path B — live worker (closer to prod, ~15 min)

Drives the actual oracle worker, the same code path that runs in
production. Use this when you want to validate the worker logs / poll
cadence / authorisation check, not just the contract.

1. Pick an ESPN event id whose quarters are imminent (or freshly final).
   Browse https://www.espn.com/nba/scoreboard, click the matchup, copy
   the `gameId=...` from the URL.

2. Create the pool, tagging the event id in the `name` so the worker
   knows which ESPN game to follow (see `scripts/sports_api.parse_espn_id`
   for the format):
   ```
   .venv/bin/python scripts/create_squares_game.py \
       --name "ESPN:401871337 · CLE @ DET" \
       --network shadownet
   ```

3. Sell the pool out so it can flip to `PHASE_LOCKED`. Either buy
   squares manually through the UI (98 cells × the ticket price), or
   reuse the emulator's buyout helpers, or call `closeSales` from the
   admin key to skip ahead:
   ```
   .venv/bin/python -c "
   from pytezos import pytezos, Key
   import os, pathlib
   for line in pathlib.Path('.env').read_text().splitlines():
       if '=' in line and not line.strip().startswith('#'):
           k, v = line.split('=', 1)
           os.environ.setdefault(k.strip(), v.strip().strip('\"').strip(\"'\"))
   key = Key.from_mnemonic(os.environ['DEPLOY_MNEMONIC'].split())
   p = pytezos.using(shell='https://rpc.shadownet.teztnets.com', key=key)
   addr = '<SQUARES_CONTRACT_ADDRESS_SHADOWNET from constants.js>'
   p.contract(addr).closeSales(gameId=0).send(min_confirmations=1)
   "
   ```

4. Start the worker:
   ```
   ./scripts/oracle-worker.sh --game squares --network shadownet
   ```
   First tick should log `authorised as oracle` (it actually checks
   `storage.admin == my key` for squares — see SquaresHandler in
   `scripts/oracle_worker.py`). Next tick should call `setAxes` with
   two `[0..9]` permutations and flip the phase to `AXES_SET`.

5. As ESPN finalises each period (or immediately, for an already-
   finished game), the worker should call `reportQuarter` four times in
   sequence. Watch for:
   - `game N → reportQuarter(q=…, HOME=…, AWAY=…) · ESPN:<id>`
   - tzkt link in the log for each op
   - the contract's `quartersDone` advancing 0 → 4 and `phase` landing
     on `COMPLETE`.

6. From a wallet that won a quarter, call `claim()`:
   ```
   <winning-wallet client>.contract(addr).claim().send(min_confirmations=1)
   ```
   Verify the payout lands by diffing the wallet balance, or watching
   `pending[<your tz1>]` drop to zero in storage.

If a step stalls, the worker keeps re-trying on its poll cycle. A
genuine block is usually one of:
- Worker key has no shadownet ꜩ (faucet again).
- Worker's `storage.admin` check failed — admin baked into storage
  doesn't match `DEPLOY_MNEMONIC`. Fix the test scenario in
  `src/services/smart_contract_squares_v2.py` and redeploy.
- ESPN returned nothing for the event id — confirm the id in a browser
  first.
