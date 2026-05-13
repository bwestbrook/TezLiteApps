#!/usr/bin/env python3
"""
new_test_wallet.py — Bootstrap a shadownet deploy wallet end-to-end.

Steps the script walks you through:
  1. Generate a fresh 24-word BIP39 mnemonic + the matching tz1 address.
  2. Show you the address (and the mnemonic — back it up if you want).
  3. Tell you the faucet URL. You paste the address in the browser and
     request testnet ꜩ.
  4. Poll the shadownet RPC every few seconds until the funds land.
  5. Save DEPLOY_MNEMONIC into .env (overwriting only after confirmation
     if a non-placeholder mnemonic is already there).
  6. Optionally chain into `deploy.py oracle` so the oracle ships in the
     same session.

Prereqs:
  ./scripts/setup.sh must have been run first (creates .venv with pytezos).
"""

from __future__ import annotations

import os
import re
import secrets
import sys
import time
from pathlib import Path

# ─── paths ────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
ENV_PATH = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
VENV_PY = PROJECT_ROOT / ".venv" / "bin" / "python"
DEPLOY_PY = SCRIPT_DIR / "deploy.py"

SHADOWNET_RPC = "https://rpc.shadownet.teztnets.com"
FAUCET_URL = "https://faucet.shadownet.teztnets.com"
TZKT_HOST = "shadownet.tzkt.io"

# ─── small log helpers ───────────────────────────────────────────────
G, R, Y, C, RESET = "\033[0;32m", "\033[0;31m", "\033[0;33m", "\033[0;36m", "\033[0m"
def ok(msg):   print(f"{G}✓{RESET} {msg}")
def info(msg): print(f"  {msg}")
def warn(msg): print(f"{Y}!{RESET} {msg}")
def err(msg):  print(f"{R}✗{RESET} {msg}", file=sys.stderr)
def hr():      print("─" * 60)

# ─── imports that require the venv ───────────────────────────────────
try:
    from pytezos import pytezos, Key
    from mnemonic import Mnemonic
except ImportError as e:
    err(f"Missing dependency: {e.name}")
    err("Run ./scripts/setup.sh first to create the .venv with pytezos installed.")
    sys.exit(1)


# ─── key generation ──────────────────────────────────────────────────
def generate_wallet() -> tuple[str, str]:
    """Return (mnemonic_string, tz1_address)."""
    m = Mnemonic("english")
    # 256-bit entropy → 24-word BIP39 phrase (standard for Tezos wallets).
    entropy = secrets.token_bytes(32)
    mnemonic = m.to_mnemonic(entropy)
    key = Key.from_mnemonic(mnemonic.split())
    return mnemonic, key.public_key_hash()


# ─── chain helpers ───────────────────────────────────────────────────
def get_balance_mutez(address: str) -> int | None:
    """Query the shadownet RPC for `address`. Returns mutez, or None on any
    transient error (RPC blip, network glitch). Never raises."""
    try:
        client = pytezos.using(shell=SHADOWNET_RPC)
        bal = client.account(address).get("balance", "0")
        return int(bal)
    except Exception:
        return None


def wait_for_funds(address: str, min_tez: float = 1.0,
                   poll_seconds: int = 3, retry_after_s: int = 60) -> int:
    """Poll until the address has at least `min_tez`. Loops indefinitely with
    a periodic "still waiting — recheck?" prompt so the user doesn't get
    stuck if the faucet is slow."""
    min_mutez = int(min_tez * 1_000_000)
    start = time.time()
    last_status = 0

    while True:
        bal = get_balance_mutez(address)
        elapsed = int(time.time() - start)

        if bal is not None and bal >= min_mutez:
            print()  # newline after the carriage-return status line
            return bal

        # Status line, refreshed in place.
        tez = (bal or 0) / 1_000_000
        if time.time() - last_status > 2:
            print(f"  Polling {SHADOWNET_RPC} … {elapsed}s elapsed, balance: {tez:.3f} ꜩ    ",
                  end="\r", flush=True)
            last_status = time.time()

        if elapsed >= retry_after_s:
            print()  # break the in-place status line
            warn(f"Still waiting after {elapsed}s. The faucet can take a minute or two.")
            answer = input("  Keep polling? [Y/n] ").strip().lower()
            if answer in ("n", "no"):
                return -1
            start = time.time()  # reset the timer for the next status window
            last_status = 0

        time.sleep(poll_seconds)


# ─── .env writer ─────────────────────────────────────────────────────
TEMPLATE_MARKER = "word1 word2 word3"  # sentinel from .env.example

def looks_like_template(mnemonic_value: str) -> bool:
    return TEMPLATE_MARKER in mnemonic_value

def write_env(new_mnemonic: str) -> None:
    """Update or create .env with DEPLOY_MNEMONIC=<new mnemonic>."""
    if ENV_PATH.exists():
        text = ENV_PATH.read_text()
    elif ENV_EXAMPLE.exists():
        text = ENV_EXAMPLE.read_text()
    else:
        text = ""

    # Check for an existing real DEPLOY_MNEMONIC and warn before clobbering.
    existing = re.search(r'^DEPLOY_MNEMONIC\s*=\s*["\']?([^"\'\n]*)', text, re.MULTILINE)
    if existing and existing.group(1).strip() and not looks_like_template(existing.group(1)):
        print()
        warn(".env already contains a DEPLOY_MNEMONIC that doesn't look like the template.")
        warn("Overwriting it will lose access to whatever wallet that mnemonic controls.")
        answer = input("  Overwrite anyway? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            info("Leaving .env alone. Your new mnemonic was printed above — save it manually.")
            return

    pattern = re.compile(r'^DEPLOY_MNEMONIC\s*=.*$', re.MULTILINE)
    new_line = f'DEPLOY_MNEMONIC="{new_mnemonic}"'
    if pattern.search(text):
        text = pattern.sub(new_line, text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += new_line + "\n"

    ENV_PATH.write_text(text)
    ok(f"Saved mnemonic → {ENV_PATH.relative_to(PROJECT_ROOT)}")
    info("  (.env is in .gitignore — won't be committed)")


# ─── main ────────────────────────────────────────────────────────────
def main():
    print()
    hr()
    print("  Shadownet test wallet bootstrap")
    hr()
    print()

    ok("Generating fresh 24-word BIP39 mnemonic")
    mnemonic, address = generate_wallet()

    print()
    info(f"{C}Address:{RESET}  {address}")
    info("")
    info(f"{C}Mnemonic{RESET} (write this down somewhere safe):")
    info("")
    words = mnemonic.split()
    for i in range(0, len(words), 6):
        info("  " + "  ".join(f"{i+j+1:2d}.{w}" for j, w in enumerate(words[i:i+6])))
    info("")
    info("This is a test-only wallet. Treat it with the same care you'd give a real one")
    info("anyway — your mainnet workflow will follow the same steps.")
    print()

    # Faucet
    hr()
    print(f"  Step 2 — fund the address")
    hr()
    info("")
    info(f"  Open:  {C}{FAUCET_URL}{RESET}")
    info(f"  Paste: {address}")
    info("")
    info("Complete the captcha and submit. The faucet drops ~6,000 testnet ꜩ.")
    print()
    try:
        input("Press Enter once you've submitted the faucet request… ")
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    # Poll
    print()
    ok("Watching the chain for the deposit…")
    balance = wait_for_funds(address)
    if balance < 0:
        err("Polling cancelled. The wallet exists but isn't funded yet.")
        err("Fund it later from the faucet and re-run this script with the same mnemonic,")
        err("or manually paste the mnemonic into .env's DEPLOY_MNEMONIC line.")
        sys.exit(2)

    tez = balance / 1_000_000
    print()
    ok(f"Funds received: {tez:.3f} ꜩ on shadownet")
    info(f"  Verify on tzkt: https://{TZKT_HOST}/{address}")
    print()

    # Save mnemonic
    write_env(mnemonic)

    # Offer deploy
    print()
    hr()
    print("  Step 4 — deploy the oracle (optional)")
    hr()
    info("")
    info("The wallet is now wired into .env, so the deploy script can sign with it.")
    info("You can run the deploy now, or later via ./scripts/deploy.sh oracle.")
    info("")
    try:
        answer = input("Deploy the oracle now? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer in ("", "y", "yes"):
        print()
        ok("Handing off to deploy.py…")
        print()
        os.execv(str(VENV_PY), [str(VENV_PY), str(DEPLOY_PY), "oracle"])
    else:
        print()
        info("Skipped. When ready: ./scripts/deploy.sh oracle")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        err("Aborted.")
        sys.exit(130)
