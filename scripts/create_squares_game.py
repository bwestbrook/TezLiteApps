#!/usr/bin/env python3
"""
create_squares_game.py — call createGame on the deployed Squares contract.

Squares' createGame is open to anyone (the contract gates only scoring +
axis randomization to admin), so this just needs a funded key. Same auth
as deploy.py: DEPLOY_MNEMONIC / DEPLOY_SK in .env, or --key.

The on-chain `name` is the linkage to a real sporting event: a name like
"ESPN:401871338 · DET @ CLE" carries an ESPN event-id tag that the oracle
(scripts/oracle_worker.py SquaresHandler) and the UI both parse — see
scripts/sports_api.py for the convention.

Usage:
    python scripts/create_squares_game.py --name "ESPN:401871338 · DET @ CLE"
    python scripts/create_squares_game.py --name "Friday pool" --ticket 0.5 --fee 0.05
    python scripts/create_squares_game.py --name "..." --network mainnet
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.js"

NETWORK_RPCS = {
    "shadownet": "https://rpc.shadownet.teztnets.com",
    "mainnet":   "https://mainnet.tezos.ecadinfra.com",
}
TZKT_HOSTS = {
    "shadownet": "shadownet.tzkt.io",
    "mainnet":   "tzkt.io",
}

# Standard Super-Bowl-Squares quarter split; the contract enforces sum == 100.
QUARTER_WEIGHTS = {0: 15, 1: 15, 2: 15, 3: 55}


def die(msg: str, code: int = 1):
    sys.stderr.write("\n" + msg.rstrip() + "\n\n")
    sys.exit(code)


def load_dotenv():
    """Load KEY=VALUE pairs from .env without clobbering real env vars."""
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def read_constant(name: str) -> str | None:
    """Return the string literal for `export const <name> = '...'`."""
    if not CONSTANTS_PATH.exists():
        return None
    m = re.search(
        rf"export const {re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]",
        CONSTANTS_PATH.read_text(),
    )
    return m.group(1) if m else None


def load_key(key_arg: str | None):
    """Build a pytezos Key from --key, DEPLOY_MNEMONIC, or DEPLOY_SK."""
    from pytezos import Key

    passphrase = os.environ.get("DEPLOY_PASSWORD", "")
    if key_arg:
        key_path = Path(key_arg).expanduser()
        if not key_path.exists():
            die(f"--key file not found: {key_path}")
        return Key.from_encoded_key(key_path.read_text().strip(), passphrase=passphrase)

    mnemonic = os.environ.get("DEPLOY_MNEMONIC", "").strip()
    if mnemonic:
        return Key.from_mnemonic(mnemonic.split(), passphrase=passphrase)

    sk = os.environ.get("DEPLOY_SK", "").strip()
    if sk:
        return Key.from_encoded_key(sk, passphrase=passphrase)

    die(
        "No key configured. Provide one of:\n"
        "  --key /path/to/key.edsk\n"
        "  export DEPLOY_MNEMONIC=\"word1 ... word24\"\n"
        "  export DEPLOY_SK=edsk...\n"
        "Or put DEPLOY_MNEMONIC=... in a .env at the repo root."
    )


def main():
    load_dotenv()

    p = argparse.ArgumentParser(description="Create a Squares pool on-chain.")
    p.add_argument("--name", required=True,
                   help='Pool name. Use an "ESPN:<id> · ..." tag to bind it '
                        'to a real game (the oracle auto-reports quarters).')
    p.add_argument("--ticket", type=float, default=1.0,
                   help="Ticket price in ꜩ (default: 1.0)")
    p.add_argument("--fee", type=float, default=0.05,
                   help="Per-ticket holder fee in ꜩ (default: 0.05)")
    p.add_argument("--network", choices=sorted(NETWORK_RPCS.keys()),
                   default="shadownet", help="Target network (default: shadownet)")
    p.add_argument("--key", help="Path to an .edsk key file (alternative to env)")
    args = p.parse_args()

    # Michelson strings are ASCII-only — strip anything outside printable
    # ASCII (a stray "·" or em-dash would otherwise revert the tx with an
    # opaque "unicode symbols are not allowed" error). 64-char cap matches
    # the UI's createGame() slice.
    name = "".join(c for c in args.name if 0x20 <= ord(c) <= 0x7E)[:64]
    if not name:
        die("--name is empty after stripping non-ASCII characters")
    ticket_mutez = round(args.ticket * 1_000_000)
    fee_mutez = round(args.fee * 1_000_000)
    if ticket_mutez <= 0:
        die("--ticket must be > 0")

    suffix = "_MAINNET" if args.network == "mainnet" else "_SHADOWNET"
    address = read_constant(f"SQUARES_CONTRACT_ADDRESS{suffix}")
    if not address or address.startswith("KT1XXX"):
        die(f"No deployed Squares address for {args.network} in constants.js "
            f"(found: {address!r}). Deploy it first with scripts/deploy.py.")

    from pytezos import pytezos

    rpc = NETWORK_RPCS[args.network]
    key = load_key(args.key)
    client = pytezos.using(shell=rpc, key=key)

    print(f"  Network:  {args.network} ({rpc})")
    print(f"  Contract: {address}")
    print(f"  Sender:   {key.public_key_hash()}")
    print(f"  Name:     {name!r}")
    print(f"  Ticket:   {args.ticket} ꜩ  ·  Fee: {args.fee} ꜩ  ·  Split: 15/15/15/55")

    ci = client.contract(address)
    op = ci.createGame(
        name=name,
        ticketPrice=ticket_mutez,
        holderFee=fee_mutez,
        quarterWeights=QUARTER_WEIGHTS,
    ).send(min_confirmations=1)

    # pytezos exposes the injected hash as the .hash() method on the
    # returned OperationGroup; fall back to opg_hash on older versions.
    try:
        op_hash = op.hash()
    except Exception:
        op_hash = getattr(op, "opg_hash", None) or "(see tzkt)"
    print(f"\n  ✓ createGame submitted: {op_hash}")
    print(f"    https://{TZKT_HOSTS[args.network]}/{op_hash}")


if __name__ == "__main__":
    main()
