#!/usr/bin/env bash
# rotate_oracle.sh — rotate the on-chain oracle address on every game
# contract that exposes an admin-gated updateOracle(newOracle).
#
# Usage:
#   ./scripts/rotate_oracle.sh <new_tz1> [--network shadownet|mainnet] [--execute]
#
# DRY RUN BY DEFAULT. Without --execute the script only reads each
# contract's current storage.oracle and prints what it *would* change —
# it sends nothing. Pass --execute to actually submit the updateOracle
# operations. Rotating an oracle key is sensitive; the dry run is the
# safety net, so look at its output before you commit.
#
# Auth: signs with the same key deploy.py uses (DEPLOY_MNEMONIC or
# DEPLOY_KEY_FILE from .env). That key MUST be the admin of every
# contract listed below — updateOracle is admin-gated (checklist §1.1).
# If admin and oracle have been split, this is the admin key.
#
# Grew out of the XC-3 stub in docs/SECURITY_FIXES.md; see also §12.3
# (rotate at least quarterly, or after any oracle-worker host incident).
set -euo pipefail
cd "$(dirname "$0")/.."

NEW="${1:-}"
NETWORK="shadownet"
EXECUTE=0
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --network) NETWORK="${2:-}"; shift 2 ;;
    --execute) EXECUTE=1; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$NEW" || "$NEW" != tz1* ]]; then
  echo "usage: $0 <new_tz1> [--network shadownet|mainnet] [--execute]" >&2
  exit 2
fi

# Prefer the project venv (has pytezos); fall back to system python3.
PY="${SMARTPY_VENV:-.venv}/bin/python"
[[ -x "$PY" ]] || PY="python3"

NEW="$NEW" NETWORK="$NETWORK" EXECUTE="$EXECUTE" "$PY" - <<'PYEOF'
import os, re, sys
from pathlib import Path

# deploy.py owns the contract registry, the .env loader, the key loader
# and the constants.js path — reuse all of it instead of re-deriving.
sys.path.insert(0, "scripts")
import deploy  # noqa: E402

NEW     = os.environ["NEW"]
NETWORK = os.environ["NETWORK"]
EXECUTE = os.environ["EXECUTE"] == "1"

deploy.load_dotenv()
if NETWORK not in deploy.NETWORK_RPCS:
    sys.exit(f"unknown network: {NETWORK} (known: {sorted(deploy.NETWORK_RPCS)})")
rpc       = deploy.NETWORK_RPCS[NETWORK]
constants = deploy.CONSTANTS_PATH.read_text()
suffix    = "_" + NETWORK.upper()

# Game contracts that expose an admin-gated updateOracle(newOracle).
# The XC-3 stub also listed `squares`, but smart_contract_squares_v2.py
# has no `oracle` storage field / updateOracle entrypoint — it isn't an
# oracle-consuming contract in this sense — so it's excluded here. The
# oracle / txl / oracle-reference contracts are excluded for the same
# reason. If a contract gains an oracle later, add its deploy.py id.
GAME_IDS = ["acey-duecey", "plinko", "war", "reversi", "chess", "ttt"]

def address_for(spec):
    var = spec.constants_var + suffix          # e.g. AD_CONTRACT_ADDRESS_SHADOWNET
    m = re.search(rf"export const {re.escape(var)}\s*=\s*'([^']+)'", constants)
    return m.group(1) if m else None

from pytezos import pytezos
key    = deploy.load_key(None)                 # DEPLOY_MNEMONIC / DEPLOY_KEY_FILE
client = pytezos.using(shell=rpc, key=key)

print(f"signer  : {client.key.public_key_hash()}  (must be admin of each contract)")
print(f"network : {NETWORK}  ({rpc})")
print(f"oracle  : -> {NEW}")
print(f"mode    : {'EXECUTE — sending ops' if EXECUTE else 'DRY RUN — pass --execute to send'}")
print()

rc = 0
for gid in GAME_IDS:
    spec = deploy.CONTRACTS.get(gid)
    if spec is None:
        print(f"  ! {gid}: not in deploy.CONTRACTS — skipped")
        rc = 1
        continue
    addr = address_for(spec)
    if not addr or "XXXX" in addr:
        print(f"  - {gid}: no {NETWORK} address in constants.js — skipped")
        continue
    try:
        ct  = client.contract(addr)
        cur = ct.storage["oracle"]()
    except Exception as e:                     # noqa: BLE001 — surface, don't abort
        print(f"  ! {gid} ({addr}): couldn't read storage.oracle — {e}")
        rc = 1
        continue
    if cur == NEW:
        print(f"  = {gid} ({addr}): already {NEW} — skipped")
        continue
    if not EXECUTE:
        print(f"  · {gid} ({addr}): would rotate {cur} -> {NEW}")
        continue
    try:
        # updateOracle takes a one-field record (params.newOracle); pytezos
        # flattens that to a single positional arg, same as deploy/exercise.
        op = ct.updateOracle(NEW).send(min_confirmations=1)
        print(f"  ✓ {gid} ({addr}): rotated {cur} -> {NEW}  (op {op.hash()})")
    except Exception as e:                     # noqa: BLE001
        print(f"  ✗ {gid} ({addr}): updateOracle failed — {e}")
        rc = 1

print()
if rc:
    print("Completed with errors — review the lines marked ! / ✗ above.")
elif not EXECUTE:
    print("Dry run clean. Re-run with --execute to send the rotation ops.")
else:
    print("All contracts rotated. Restart the oracle worker so it picks up the new key.")
sys.exit(rc)
PYEOF
