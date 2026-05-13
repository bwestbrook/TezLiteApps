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
