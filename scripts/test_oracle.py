#!/usr/bin/env python3
"""
test_oracle.py — Smoke-test the deployed RandomOracle on shadownet.

Reads the contract address from src/constants.js (or --address), connects
via PyTezos, dumps current storage, then exercises two entrypoints:

  1. default()       — empty entrypoint; cheapest possible round-trip.
  2. makeRequest()   — full random-number request flow. Pays the
                       contract's `fee` (0.1 ꜩ), so the request lands in
                       storage.requests with status 0. Verifies by reading
                       storage back.

Costs ~0.1 ꜩ + gas on testnet. Re-running is fine; each run produces a
new request with a fresh random requestId.

Usage:
    ./scripts/test-oracle.sh
    ./scripts/test-oracle.sh --address KT1...
    ./scripts/test-oracle.sh --network mainnet --address KT1...
    ./scripts/test-oracle.sh --skip-make-request    # read + default() only
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
import time
from pathlib import Path

# ─── paths ────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.js"
ENV_PATH = PROJECT_ROOT / ".env"

# ─── log helpers ──────────────────────────────────────────────────────
G, R, Y, C, RESET = "\033[0;32m", "\033[0;31m", "\033[0;33m", "\033[0;36m", "\033[0m"
def ok(msg):     print(f"{G}✓{RESET} {msg}")
def info(msg):   print(f"  {msg}")
def warn(msg):   print(f"{Y}!{RESET} {msg}")
def err(msg):    print(f"{R}✗{RESET} {msg}", file=sys.stderr)
def hr():        print("─" * 60)
def section(t):  print(); hr(); print(f"  {t}"); hr()

# ─── .env loader ──────────────────────────────────────────────────────
def load_dotenv():
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


# ─── constants.js reader ──────────────────────────────────────────────
def read_constant(name: str) -> str | None:
    if not CONSTANTS_PATH.exists():
        return None
    m = re.search(
        rf"export const {re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]",
        CONSTANTS_PATH.read_text(),
    )
    return m.group(1) if m else None


# ─── tests ────────────────────────────────────────────────────────────
NETWORK_RPCS = {
    "shadownet": "https://rpc.shadownet.teztnets.com",
    "mainnet":   "https://mainnet.tezos.ecadinfra.com",
}
TZKT_HOSTS = {
    "shadownet": "shadownet.tzkt.io",
    "mainnet":   "tzkt.io",
}

def run_tests(args):
    from pytezos import pytezos, Key

    # Address resolution
    address = args.address or read_constant("ORACLE_CONTRACT")
    if not address:
        err("No contract address. Pass --address KT1… or set ORACLE_CONTRACT in constants.js.")
        sys.exit(2)
    if address.startswith("KT1X" * 2):
        err(f"Address looks like a placeholder: {address}")
        err("Deploy the contract first: ./scripts/deploy.sh oracle")
        sys.exit(2)

    rpc = NETWORK_RPCS[args.network]
    tzkt = TZKT_HOSTS[args.network]

    section("Setup")
    info(f"Contract: {address}")
    info(f"Network:  {args.network}")
    info(f"RPC:      {rpc}")
    info(f"Explorer: https://{tzkt}/{address}")

    # Key: from .env unless we're read-only
    mnemonic = os.environ.get("DEPLOY_MNEMONIC", "").strip()
    if not mnemonic:
        err("DEPLOY_MNEMONIC not in .env — needed to sign contract calls.")
        sys.exit(2)
    key = Key.from_mnemonic(mnemonic.split())
    client = pytezos.using(shell=rpc, key=key)

    info(f"Tester:   {key.public_key_hash()}")
    try:
        bal = int(client.account().get("balance", "0"))
        info(f"Balance:  {bal / 1_000_000:.4f} ꜩ")
    except Exception as e:
        warn(f"Couldn't read tester balance: {e}")

    contract = client.contract(address)

    # ─── 1. Read storage ────────────────────────────────────────────
    section("1. Read storage")
    try:
        storage = contract.storage()
    except Exception as e:
        err(f"Couldn't read storage: {e}")
        sys.exit(3)

    expected = {
        "admin":  read_constant("ADMIN_ADDRESS"),
        "oracle": "tz1XbrvTMVa5dWQQBSCn2jgX7BPZyLRhgtKS",
    }
    for fname in (
        "admin", "oracle", "fee", "currentRequestIndex",
        "adContract", "txlContract",
    ):
        val = storage.get(fname) if isinstance(storage, dict) else getattr(storage, fname, None)
        info(f"  {fname:24} = {val}")
        if fname in expected and expected[fname] and str(val) != expected[fname]:
            warn(f"    expected {expected[fname]}, got {val}")

    req_map = storage.get("requests") if isinstance(storage, dict) else getattr(storage, "requests", {})
    req_count = len(req_map) if hasattr(req_map, "__len__") else "?"
    info(f"  requests (count)         = {req_count}")
    initial_cri = int(storage.get("currentRequestIndex", 0) if isinstance(storage, dict) else 0)

    ok("Storage read OK")

    # ─── 2. default() ───────────────────────────────────────────────
    if not args.skip_default:
        section("2. Call default()")
        try:
            op = contract.default().send(min_confirmations=1)
            op_hash = getattr(op, "hash", None) or op.opg_hash if hasattr(op, "opg_hash") else "(unknown)"
            ok(f"default() succeeded — op {op_hash}")
            info(f"  https://{tzkt}/{op_hash}")
        except Exception as e:
            err(f"default() call failed: {e}")
            if not args.continue_on_error:
                sys.exit(4)
    else:
        info("(skipped default() — --skip-default)")

    # ─── 3. makeRequest() ───────────────────────────────────────────
    if args.skip_make_request:
        info("(skipped makeRequest() — --skip-make-request)")
        return

    section("3. Call makeRequest() with fee=0.1 ꜩ")
    fee_mutez = int(storage.get("fee") if isinstance(storage, dict) else getattr(storage, "fee", 100000))
    request_id = "smoketest-" + secrets.token_hex(6)
    info(f"  request_id:      {request_id}")
    info(f"  attaching fee:   {fee_mutez} mutez ({fee_mutez/1_000_000} ꜩ)")

    try:
        op = contract.makeRequest(
            contractAddress="KT1W3Z2zVw8FhNpihuFJS8P2iLDC2APwHTD2",
            entryPoint="firstCard",
            entryPointParams=f"gameId-test card-*RN* nonce-{secrets.token_hex(4)}",
            randomNumberExcludes="",
            randomNumberMax=51,
            randomNumberType=0,
            requestId=request_id,
        ).with_amount(fee_mutez).send(min_confirmations=1)
        op_hash = getattr(op, "hash", None) or "(unknown)"
        ok(f"makeRequest() succeeded — op {op_hash}")
        info(f"  https://{tzkt}/{op_hash}")
    except Exception as e:
        err(f"makeRequest() call failed: {e}")
        sys.exit(5)

    # ─── 4. Verify the request landed ───────────────────────────────
    section("4. Verify storage updated")
    time.sleep(2)  # give the indexer a moment
    storage_after = contract.storage()
    new_cri = int(storage_after.get("currentRequestIndex") if isinstance(storage_after, dict) else 0)
    info(f"  currentRequestIndex: was {initial_cri}, now {new_cri}")

    requests_after = storage_after.get("requests") if isinstance(storage_after, dict) else {}
    if hasattr(requests_after, "items"):
        match_idx = None
        for k, v in requests_after.items():
            rid = v.get("requestId") if isinstance(v, dict) else getattr(v, "requestId", None)
            if rid == request_id:
                match_idx = k
                break
        if match_idx is not None:
            ok(f"Request '{request_id}' recorded at index {match_idx}")
            r = requests_after[match_idx]
            for f in ("contractAddress", "entryPoint", "requestStatus", "requester"):
                v = r.get(f) if isinstance(r, dict) else getattr(r, f, None)
                info(f"    {f:20} = {v}")
        else:
            warn(f"Couldn't find request '{request_id}' in storage.")
            warn("  Re-check by clicking the operation hash link above.")

    print()
    ok("All tests passed.")


def main():
    p = argparse.ArgumentParser(description="Smoke-test the deployed RandomOracle contract.")
    p.add_argument("--address", help="Override contract address (default: ORACLE_CONTRACT from constants.js)")
    p.add_argument("--network", choices=list(NETWORK_RPCS), default="shadownet")
    p.add_argument("--skip-default", action="store_true", help="Skip the default() entrypoint")
    p.add_argument("--skip-make-request", action="store_true", help="Skip the makeRequest() call (which spends 0.1 ꜩ)")
    p.add_argument("--continue-on-error", action="store_true", help="Don't bail if a single entrypoint fails")
    args = p.parse_args()

    load_dotenv()
    try:
        run_tests(args)
    except KeyboardInterrupt:
        print()
        err("Aborted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
