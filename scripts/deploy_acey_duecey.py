#!/usr/bin/env python3
"""
Deploy the Acey Duecey contract using pytezos.

Workflow:
  1. Compile `src/services/smart_contractAD_v2.py` to Michelson (via SmartPy
     IDE or CLI — see README at the bottom of this file).
  2. Drop the compiled `.tz` (Michelson code) and `.tz` (initial storage) into
     `src/services/build/aceyDuecey/`.
  3. Put your private key in `.deploy_key` next to this script (gitignored).
  4. Run:
        python3 scripts/deploy_acey_duecey.py            # dry-run (estimate only)
        python3 scripts/deploy_acey_duecey.py --commit   # actually broadcast

The script:
  - Estimates cost first and shows you the bill.
  - Asks for explicit confirmation before broadcasting.
  - On success, prints the new KT1 and offers to write it into
    src/constants.js automatically.

Requirements:
    pip3 install pytezos
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from textwrap import dedent

try:
    from pytezos import pytezos, Key
except ImportError:
    sys.exit(
        "pytezos is not installed. Run:  pip3 install pytezos\n"
        "(on Apple Silicon you may also need:  brew install libsodium gmp)"
    )


# ─── Config ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = ROOT / ".deploy_key"               # plaintext edsk... (gitignored)
BUILD_DIR = ROOT / "src" / "services" / "build" / "aceyDuecey"
CODE_FILE = BUILD_DIR / "step_000_cont_0_contract.tz"   # SmartPy default name
STORAGE_FILE = BUILD_DIR / "step_000_cont_0_storage.tz"  # SmartPy default name
CONSTANTS_FILE = ROOT / "src" / "constants.js"

NETWORKS = {
    "mainnet":   {"rpc": "https://mainnet.tezos.ecadinfra.com",   "explorer": "https://tzkt.io"},
    "shadownet": {"rpc": "https://rpc.shadownet.teztnets.com",    "explorer": "https://shadownet.tzkt.io"},
}


# ─── Helpers ─────────────────────────────────────────────────────────────────
def load_secret_key() -> str:
    if not KEY_FILE.exists():
        sys.exit(
            f"❌ {KEY_FILE} not found.\n"
            "   Save your edsk... private key (single line, no quotes) there.\n"
            "   Get it from Temple → Settings → Reveal Private Key.\n"
            "   The file is gitignored via .env* in .gitignore."
        )
    sk = KEY_FILE.read_text().strip()
    if not sk.startswith("edsk"):
        sys.exit("❌ key file does not look like a Tezos edsk... key.")
    return sk


def load_compiled() -> tuple[str, str]:
    if not CODE_FILE.exists() or not STORAGE_FILE.exists():
        sys.exit(
            f"❌ compiled contract not found in {BUILD_DIR}\n"
            "   Compile smart_contractAD_v2.py first — see the README block\n"
            "   at the bottom of this script."
        )
    code = CODE_FILE.read_text()
    storage = STORAGE_FILE.read_text()
    return code, storage


def update_constants_js(new_address: str) -> None:
    if not CONSTANTS_FILE.exists():
        return
    text = CONSTANTS_FILE.read_text()
    pattern = re.compile(
        r"(export const AD_CONTRACT_ADDRESS = ')[^']+(' // TODO: redeploy)"
    )
    if not pattern.search(text):
        # Allow the line whether or not the TODO comment is still there.
        pattern = re.compile(r"(export const AD_CONTRACT_ADDRESS = ')[^']+(')")
    new_text, n = pattern.subn(rf"\g<1>{new_address}\g<2>", text)
    if n == 0:
        print(f"⚠️  Could not find AD_CONTRACT_ADDRESS line in {CONSTANTS_FILE}")
        return
    CONSTANTS_FILE.write_text(new_text)
    print(f"✅ Updated AD_CONTRACT_ADDRESS in {CONSTANTS_FILE.relative_to(ROOT)}")


def confirm(prompt: str) -> bool:
    answer = input(f"{prompt} [yes/NO] ").strip().lower()
    return answer in ("yes", "y")


# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Originate the Acey Duecey contract.")
    parser.add_argument("--network", default="mainnet", choices=list(NETWORKS.keys()))
    parser.add_argument("--commit", action="store_true",
                        help="actually broadcast (default: dry-run estimate only)")
    parser.add_argument("--admin", help="admin address (default: deploy account)")
    parser.add_argument("--oracle", help="oracle address (default: deploy account)")
    parser.add_argument("--txl-contract",
                        help="TXL holder contract (default: deploy account — you can update later)")
    args = parser.parse_args()

    net = NETWORKS[args.network]

    # Load secret key + connect
    secret_key = load_secret_key()
    pt = pytezos.using(shell=net["rpc"], key=secret_key)
    src_address = pt.key.public_key_hash()
    balance_mutez = pt.account()["balance"]
    balance_tez = int(balance_mutez) / 1_000_000

    admin = args.admin or src_address
    oracle = args.oracle or src_address
    txl_contract = args.txl_contract or src_address

    # Compiled artefacts
    code, storage = load_compiled()

    # Header
    print(dedent(f"""
        ─── Acey Duecey deploy ──────────────────────────────────────
          network        : {args.network}
          rpc            : {net["rpc"]}
          deploy address : {src_address}
          balance        : {balance_tez:.4f} ꜩ
          admin          : {admin}{"  (= deploy)" if admin == src_address else ""}
          oracle         : {oracle}{"  (= deploy)" if oracle == src_address else ""}
          txlContract    : {txl_contract}{"  (= deploy)" if txl_contract == src_address else ""}
        ─────────────────────────────────────────────────────────────
    """).strip())

    if balance_tez < 1.0:
        print(f"\n⚠️  Balance is low ({balance_tez:.4f} ꜩ). Originations typically cost ~0.5 ꜩ in storage burn.")

    # Build the operation. Note: SmartPy emits the Michelson with the storage
    # constructor expecting (admin, oracle, txlContract) — so we splice them in
    # by using the on-chain origination helper, passing the compiled code +
    # storage as-is. If your SmartPy entrypoint __init__ takes parameters, the
    # storage file already includes the resolved storage from compile-time
    # arguments. To inject the addresses at deploy time instead, re-compile with
    # those values, OR adjust this script to substitute them in the storage
    # Michelson (search for "self.data.admin" in the .tz output).
    op = pt.origination(script={"code": pt.michelson_to_micheline(code),
                                "storage": pt.michelson_to_micheline(storage)})

    # Estimate cost (dry-run via simulation)
    print("\nSimulating origination to estimate cost...")
    try:
        sim = op.autofill().run_operation()
    except Exception as e:
        sys.exit(f"❌ simulation failed: {e}")

    fees = op.autofill().contents[0]
    fee_mutez = int(fees.get("fee", 0))
    burn_mutez = int(fees.get("storage_limit", 0)) * 250  # 250 mutez / byte at protocol 18+
    total_mutez = fee_mutez + burn_mutez

    print(dedent(f"""
        Estimated cost:
          gas fee      : {fee_mutez / 1_000_000:.6f} ꜩ
          storage burn : ~{burn_mutez / 1_000_000:.6f} ꜩ
          total        : ~{total_mutez / 1_000_000:.6f} ꜩ
    """).strip())

    if not args.commit:
        print("\nDry run — pass --commit to actually broadcast.")
        return 0

    print()
    if not confirm(f"Originate to {args.network} for ~{total_mutez / 1_000_000:.4f} ꜩ from {src_address}?"):
        print("Aborted.")
        return 1

    # Broadcast
    print("\nBroadcasting...")
    result = op.autofill().sign().inject(_async=False)
    op_hash = result["hash"] if isinstance(result, dict) else result
    print(f"  op hash: {op_hash}")
    print(f"  watch:  {net['explorer']}/{op_hash}")

    print("\nWaiting for confirmation (this can take ~30s)...")
    pt.wait(result)

    # Find the new KT1
    contracts = pt.shell.head.context.contracts()  # this is huge; better to inspect the op
    op_data = pt.shell.blocks[-5:].find_operation(op_hash)
    new_address = next(
        (
            c["originated_contract"]
            for c in op_data["contents"][0]["metadata"]["operation_result"].get("originated_contracts", [])
        ),
        None,
    ) or next(
        (
            r["originated_contract"]
            for r in op_data["contents"][0]["metadata"]["internal_operation_results"]
            if r["kind"] == "origination" and r.get("result", {}).get("originated_contracts")
        ),
        None,
    )

    if not new_address:
        print("⚠️  Could not parse new KT1 from op metadata — check the explorer link above.")
        return 0

    print(f"\n✅ Originated: {new_address}")
    print(f"   {net['explorer']}/{new_address}")

    if confirm("Update src/constants.js with this address?"):
        update_constants_js(new_address)

    return 0


if __name__ == "__main__":
    sys.exit(main())


# ─── README ──────────────────────────────────────────────────────────────────
# How to compile smart_contractAD_v2.py to Michelson
#
# Easiest path — SmartPy online IDE:
#   1. Open https://smartpy.io/ide
#   2. Paste src/services/smart_contractAD_v2.py
#   3. Click "Run" (top-right). The tests on the right side should pass.
#   4. Below the test output, find the contract step.
#      Click "Compiled contract" → download the .tz files.
#   5. Copy step_000_cont_0_contract.tz   →  src/services/build/aceyDuecey/
#      Copy step_000_cont_0_storage.tz    →  src/services/build/aceyDuecey/
#
# CLI path (one-time install):
#   curl -s https://smartpy.io/cli/install.sh | sh -s -- local-install ~/smartpy-cli
#   ~/smartpy-cli/SmartPy.sh compile \
#     src/services/smart_contractAD_v2.py \
#     src/services/build/aceyDuecey/
#
# Now run:
#   python3 scripts/deploy_acey_duecey.py            # dry-run, prints estimate
#   python3 scripts/deploy_acey_duecey.py --commit   # actually deploys
