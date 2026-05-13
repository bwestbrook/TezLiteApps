#!/usr/bin/env bash
# test-oracle.sh — Run scripts/test_oracle.py inside the project venv.
#
# Usage:
#   ./scripts/test-oracle.sh                       # default flow
#   ./scripts/test-oracle.sh --skip-make-request   # read + default() only
#   ./scripts/test-oracle.sh --address KT1...      # different contract
set -euo pipefail
cd "$(dirname "$0")/.."

err() { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }

if [[ ! -x .venv/bin/python ]]; then
  err "Error: .venv missing. Run ./scripts/setup.sh first."
  exit 1
fi
if [[ ! -f .env ]]; then
  err "Error: .env missing. Run ./scripts/new-test-wallet.sh, or copy from .env.example."
  exit 1
fi

exec .venv/bin/python scripts/test_oracle.py "$@"
