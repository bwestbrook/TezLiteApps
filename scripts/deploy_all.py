#!/usr/bin/env python3
"""
Multi-contract deploy + wiring.

Originates every TezLiteApps contract in the right order and wires them
together (RNG oracle's `requesters` allowlist, etc.). Reads compiled
artifacts from `src/services/build/<contract>/`.

Order:
    1. RNG oracle              — needed by Plinko + (eventually) Squares + TTT
    2. Squares                  — depends on RNG oracle KT1
    3. Plinko                   — depends on RNG oracle KT1
    4. Reversi                  — independent
    5. Chess                    — independent
    6. Acey Duecey (secure)     — independent (has its own oracle pattern)

After origination:
    7. RNG.addRequester(squares)
    8. RNG.addRequester(plinko)
    9. Write every new KT1 into src/constants.js

Defaults to dry-run; pass --commit to broadcast. Writes the new addresses
to src/constants.js automatically when --commit succeeds.

Usage:
    python3 scripts/deploy_all.py
    python3 scripts/deploy_all.py --commit
    python3 scripts/deploy_all.py --commit --network shadownet
    python3 scripts/deploy_all.py --commit --only chess --only reversi
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from textwrap import dedent

try:
    from pytezos import pytezos
    from pytezos.crypto.key import Key
except ImportError:
    sys.exit("pytezos missing. Install with:  pip3 install pytezos")


ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / ".deploy_key"
BUILD = ROOT / "src" / "services" / "build"
CONSTANTS = ROOT / "src" / "constants.js"

NETWORKS = {
    "mainnet":   {"rpc": "https://mainnet.tezos.ecadinfra.com", "explorer": "https://tzkt.io"},
    "shadownet": {"rpc": "https://rpc.shadownet.teztnets.com",  "explorer": "https://shadownet.tzkt.io"},
}

# Each entry:
#   key:   the --only flag name (also the build subdir)
#   const: the constants.js identifier we write the KT1 into
#   needs: list of dependencies; their KT1s are passed into __init__ via storage
CONTRACTS = [
    {
        "key": "rng",
        "const": "RNG_ORACLE_CONTRACT_ADDRESS",
        "build_dir": "rng",
        "needs": [],
    },
    {
        "key": "squares",
        "const": "SQUARES_CONTRACT_ADDRESS",
        "build_dir": "squares",
        "needs": ["rng"],
    },
    {
        "key": "plinko",
        "const": "PLINKO_CONTRACT_ADDRESS",
        "build_dir": "plinko",
        "needs": ["rng"],
    },
    {
        "key": "reversi",
        "const": "REVERSI_CONTRACT_ADDRESS",
        "build_dir": "reversi",
        "needs": [],
    },
    {
        "key": "chess",
        "const": "CHESS_CONTRACT_ADDRESS",
        "build_dir": "chess",
        "needs": [],
    },
    {
        "key": "ad_secure",
        "const": "AD_CONTRACT_ADDRESS",
        "build_dir": "aceyDuecey-secure",
        "needs": [],
    },
]


def load_key() -> Key:
    if not KEY_FILE.exists():
        sys.exit(f"❌ {KEY_FILE} missing. Save your edsk... key there.")
    sk = KEY_FILE.read_text().strip()
    if not sk.startswith("edsk"):
        sys.exit("❌ key file does not look like a Tezos edsk... key.")
    return Key.from_encoded_key(sk)


def load_compiled(build_subdir: str) -> tuple[str, str]:
    d = BUILD / build_subdir
    code_file = d / "step_000_cont_0_contract.tz"
    storage_file = d / "step_000_cont_0_storage.tz"
    if not code_file.exists() or not storage_file.exists():
        sys.exit(
            f"❌ compiled artifacts missing in {d}\n"
            f"   Run:  docker run --rm -v $PWD:/work -w /work bakingbad/smartpy-cli:latest \\\n"
            f"           test src/services/<contract>.py {d.relative_to(ROOT)}/"
        )
    return code_file.read_text(), storage_file.read_text()


def update_constant(name: str, value: str) -> None:
    text = CONSTANTS.read_text()
    pattern = re.compile(rf"(export const {name} = ')[^']+(')")
    new, n = pattern.subn(rf"\g<1>{value}\g<2>", text)
    if n:
        CONSTANTS.write_text(new)
        print(f"  → wrote {name} = {value} into src/constants.js")
    else:
        print(f"  ⚠ couldn't find {name} in constants.js — please update manually")


def confirm(prompt: str) -> bool:
    return input(f"{prompt} [yes/NO] ").strip().lower() in ("yes", "y")


def estimate_cost(op):
    fees = op.contents[0]
    fee_mu = int(fees.get("fee", 0))
    burn_mu = int(fees.get("storage_limit", 0)) * 250
    return fee_mu + burn_mu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--network", default="mainnet", choices=list(NETWORKS.keys()))
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--only", action="append", default=None,
                    help="Limit to specific contract keys (repeatable)")
    args = ap.parse_args()

    net = NETWORKS[args.network]
    key = load_key()
    pt = pytezos.using(shell=net["rpc"], key=key)
    src = pt.key.public_key_hash()
    bal_mu = int(pt.account()["balance"])
    print(dedent(f"""
        ─── TezLiteApps deploy ──────────────────────────────────
          network        : {args.network}
          deploy address : {src}
          balance        : {bal_mu / 1_000_000:.4f} ꜩ
        ─────────────────────────────────────────────────────────
    """).strip())

    targets = [c for c in CONTRACTS if not args.only or c["key"] in args.only]
    print(f"Will originate: {[c['key'] for c in targets]}")

    deployed: dict[str, str] = {}
    total_cost = 0
    for c in targets:
        print(f"\n── {c['key']} ──")
        try:
            code, storage = load_compiled(c["build_dir"])
        except SystemExit as e:
            print(f"  skipping ({e})")
            continue

        op = pt.origination(script={
            "code": pt.michelson_to_micheline(code),
            "storage": pt.michelson_to_micheline(storage),
        })
        try:
            sim = op.autofill()
            cost = estimate_cost(sim)
            print(f"  estimated cost: {cost / 1_000_000:.4f} ꜩ")
            total_cost += cost
        except Exception as e:
            print(f"  ⚠ simulation failed: {e}")
            continue

        if not args.commit:
            continue

        if not confirm(f"  originate {c['key']} for {cost / 1_000_000:.4f} ꜩ?"):
            print("  skipped")
            continue

        result = op.autofill().sign().inject(_async=False)
        op_hash = result["hash"] if isinstance(result, dict) else result
        print(f"  op: {op_hash}")
        pt.wait(result)

        # Find the originated KT1
        op_data = pt.shell.blocks[-5:].find_operation(op_hash)
        new = None
        for src_op in op_data["contents"]:
            res = src_op.get("metadata", {}).get("operation_result", {})
            for kt in res.get("originated_contracts", []):
                new = kt
                break
            if new:
                break
        if not new:
            print(f"  ⚠ could not parse new KT1 — check {net['explorer']}/{op_hash}")
            continue

        deployed[c["key"]] = new
        print(f"  ✅ {c['key']} → {new}")
        update_constant(c["const"], new)

    print()
    print("==============================================")
    if not args.commit:
        print(f"Dry run total estimate: ~{total_cost / 1_000_000:.4f} ꜩ")
        print("Pass --commit to actually originate.")
        return 0

    # Wire up the RNG oracle's requesters allowlist
    if "rng" in deployed:
        rng = pt.contract(deployed["rng"])
        for consumer_key in ("squares", "plinko"):
            if consumer_key in deployed:
                print(f"\nWiring {consumer_key} → RNG.addRequester({deployed[consumer_key]})")
                op = (rng.addRequester(addr=deployed[consumer_key])
                      .as_transaction().autofill().sign().inject(_async=False))
                op_hash = op["hash"] if isinstance(op, dict) else op
                pt.wait(op)
                print(f"  done — {op_hash}")

    print(f"\n✅ All done. New addresses in src/constants.js.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
