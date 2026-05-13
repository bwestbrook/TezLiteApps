#!/usr/bin/env bash
# deploy.sh — Thin wrapper around scripts/deploy.py that activates the
# project-local .venv first. Use this instead of calling Python directly
# so you don't have to remember to source the venv.
#
# Usage:
#   ./scripts/deploy.sh <contract-id> [--network shadownet|mainnet] [other flags]
#
# Examples:
#   ./scripts/deploy.sh oracle
#   ./scripts/deploy.sh oracle --network mainnet
#   ./scripts/deploy.sh acey-duecey --no-update-constants

set -euo pipefail
cd "$(dirname "$0")/.."

err() { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }

if [[ ! -d .venv ]]; then
  err "Error: .venv/ not found."
  err "Run ./scripts/setup.sh first."
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  err "Error: .venv looks broken — no python binary at .venv/bin/python."
  err "Delete .venv and re-run ./scripts/setup.sh."
  exit 1
fi

if [[ ! -f .env && $# -eq 0 ]]; then
  err "Hint: no .env file. Copy from .env.example and paste your mnemonic,"
  err "      or pass --key /path/to/key.edsk on the command line."
fi

# Don't try to `source` — just use the venv's binaries directly. Works in
# any POSIX-ish shell (bash, zsh, dash) regardless of activate-script quirks.
exec .venv/bin/python scripts/deploy.py "$@"
