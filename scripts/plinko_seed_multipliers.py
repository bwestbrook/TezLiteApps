#!/usr/bin/env python3
"""Seed the Plinko contract's multiplier table.

Run once after `./scripts/deploy.py plinko --network shadownet`.

The contract stores payouts as basis-of-100 nats (1.0× = 100, 5.6× = 560,
29× = 2900). This script calls `setMultiplierRow` for every (rows, risk)
combo so the table is fully populated.

Usage:
    .venv/bin/python scripts/plinko_seed_multipliers.py
    .venv/bin/python scripts/plinko_seed_multipliers.py --network mainnet
    .venv/bin/python scripts/plinko_seed_multipliers.py --address KT1...
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.js"

# ─── Payout tables ────────────────────────────────────────────────────────
# Source: standard Stake-style Plinko multipliers. Symmetric: edges pay big,
# middle pays tiny. Values are floats; converted to bp (×100) below.
TABLES: dict[tuple[int, int], list[float]] = {
    # 8 rows ─ 9 buckets
    (8, 0): [5.6, 2.1, 1.1, 1.0, 0.5, 1.0, 1.1, 2.1, 5.6],
    (8, 1): [13.0, 3.0, 1.3, 0.7, 0.4, 0.7, 1.3, 3.0, 13.0],
    (8, 2): [29.0, 4.0, 1.5, 0.3, 0.2, 0.3, 1.5, 4.0, 29.0],
    # 12 rows ─ 13 buckets
    (12, 0): [10.0, 3.0, 1.6, 1.4, 1.1, 1.0, 0.5, 1.0, 1.1, 1.4, 1.6, 3.0, 10.0],
    (12, 1): [33.0, 11.0, 4.0, 2.0, 1.1, 0.6, 0.3, 0.6, 1.1, 2.0, 4.0, 11.0, 33.0],
    (12, 2): [76.0, 18.0, 5.0, 1.9, 0.4, 0.2, 0.2, 0.2, 0.4, 1.9, 5.0, 18.0, 76.0],
    # 16 rows ─ 17 buckets
    (16, 0): [16.0, 9.0, 2.0, 1.4, 1.4, 1.2, 1.1, 1.0, 0.5, 1.0, 1.1, 1.2, 1.4, 1.4, 2.0, 9.0, 16.0],
    (16, 1): [110.0, 41.0, 10.0, 5.0, 3.0, 1.5, 1.0, 0.5, 0.3, 0.5, 1.0, 1.5, 3.0, 5.0, 10.0, 41.0, 110.0],
    (16, 2): [1000.0, 130.0, 26.0, 9.0, 4.0, 2.0, 0.2, 0.2, 0.2, 0.2, 0.2, 2.0, 4.0, 9.0, 26.0, 130.0, 1000.0],
}


def to_bp(row: list[float]) -> dict[int, int]:
    """Convert a floats-row to {slot: bp_int} for setMultiplierRow."""
    return {slot: int(round(mult * 100)) for slot, mult in enumerate(row)}


def lookup_address(network: str) -> str:
    """Read PLINKO_CONTRACT_ADDRESS_<NETWORK> out of src/constants.js."""
    text = CONSTANTS_PATH.read_text()
    var = f"PLINKO_CONTRACT_ADDRESS_{network.upper()}"
    m = re.search(rf"{var}\s*=\s*'([^']+)'", text)
    if not m:
        sys.exit(f"Could not find {var} in {CONSTANTS_PATH}")
    addr = m.group(1)
    if addr.startswith("KT1XXXX"):
        sys.exit(f"{var} is still the placeholder — deploy Plinko first.")
    return addr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", default="shadownet",
                        choices=["shadownet", "mainnet"])
    parser.add_argument("--address",
                        help="Override the Plinko contract address.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be sent, don't sign.")
    args = parser.parse_args()

    # Load .env so DEPLOY_MNEMONIC (etc.) are picked up. deploy.py lives
    # next to this script, so make sure scripts/ is on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from deploy import load_dotenv, NETWORK_RPCS, load_key, ensure_revealed  # noqa: E402
    load_dotenv()

    from pytezos import pytezos  # noqa: E402

    rpc = NETWORK_RPCS[args.network]
    address = args.address or lookup_address(args.network)
    print(f"Plinko @ {address}  ({args.network})")

    client = pytezos.using(shell=rpc, key=load_key(os.environ.get("DEPLOY_KEY")))
    ensure_revealed(client)
    contract = client.contract(address)

    for (rows, risk), values in TABLES.items():
        bp = to_bp(values)
        label = f"rows={rows} risk={risk}"
        if args.dry_run:
            print(f"[dry-run] setMultiplierRow {label}: {bp}")
            continue
        print(f"→ {label}: {bp}")
        op = contract.setMultiplierRow(rows=rows, risk=risk, values=bp).send(
            min_confirmations=1,
        )
        print(f"  injected {op.hash()[:12]}…")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
