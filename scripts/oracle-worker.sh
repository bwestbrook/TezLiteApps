#!/usr/bin/env bash
# oracle-worker.sh — run scripts/oracle_worker.py inside the project venv.
#
# Examples:
#   ./scripts/oracle-worker.sh                # forever, polling every 5s
#   ./scripts/oracle-worker.sh --once         # one pass, then exit
#   ./scripts/oracle-worker.sh --dry-run      # log decisions, don't sign
#   ./scripts/oracle-worker.sh --poll 3       # 3-second poll interval
#   ./scripts/oracle-worker.sh --network mainnet --address KT1...
#
# Ctrl-C exits cleanly after the current poll cycle.

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

exec .venv/bin/python scripts/oracle_worker.py "$@"
