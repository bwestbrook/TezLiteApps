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

# ─── Payout tables — 3D Plinko, RING-indexed ──────────────────────────────
# Index = Chebyshev ring distance from centre (0 = dead-centre bin, worst
# payout; rows/2 = outer corner ring, best). Radially symmetric, so the
# table is just rows/2 + 1 entries per (rows, risk).
#
# These were scaled (see SHAPES + ring-probability math, below the comment
# in git history of this file) so each profile pays ~97% RTP against the
# TRUE 3D ring distribution — P(ring=r) = q(r)² − q(r−1)², where q(r) is
# P(|finalX − rows/2| ≤ r) and the two axes are independent Binomials.
#
# Must mirror PLINKO_MULTIPLIERS in src/constants.js.
TABLES: dict[tuple[int, int], list[float]] = {
    # 8 rows ─ rings 0..4
    (8, 0): [0.4, 0.81, 0.89, 1.69, 4.52],
    (8, 1): [0.29, 0.5, 0.93, 2.14, 9.27],
    (8, 2): [0.12, 0.18, 0.9, 2.4, 17.43],
    # 12 rows ─ rings 0..6
    (12, 0): [0.42, 0.84, 0.92, 1.17, 1.34, 2.51, 8.38],
    (12, 1): [0.21, 0.42, 0.76, 1.38, 2.77, 7.61, 22.83],
    (12, 2): [0.16, 0.16, 0.33, 1.55, 4.09, 14.71, 62.12],
    # 16 rows ─ rings 0..8
    (16, 0): [0.43, 0.86, 0.94, 1.03, 1.2, 1.2, 1.72, 7.72, 13.72],
    (16, 1): [0.21, 0.34, 0.69, 1.03, 2.06, 3.43, 6.85, 28.1, 75.39],
    (16, 2): [0.12, 0.12, 0.12, 1.15, 2.3, 5.18, 14.96, 74.81, 575.44],
}


def to_bp(row: list[float]) -> dict[int, int]:
    """Convert a floats-row to {ring: bp_int} for setMultiplierRow."""
    return {ring: int(round(mult * 100)) for ring, mult in enumerate(row)}


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
