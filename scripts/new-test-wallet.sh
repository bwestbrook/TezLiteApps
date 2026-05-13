#!/usr/bin/env bash
# new-test-wallet.sh — Interactive walkthrough that generates a shadownet
# test wallet, waits for you to fund it from the faucet, saves the
# mnemonic into .env, and optionally chains into the oracle deploy.
#
# Usage:
#   ./scripts/new-test-wallet.sh

set -euo pipefail
cd "$(dirname "$0")/.."

err() { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }

if [[ ! -d .venv ]]; then
  err "Error: .venv/ not found."
  err "Run ./scripts/setup.sh first."
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  err "Error: .venv/bin/python missing — delete .venv and re-run ./scripts/setup.sh."
  exit 1
fi

exec .venv/bin/python scripts/new_test_wallet.py "$@"
