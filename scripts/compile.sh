#!/usr/bin/env bash
# compile.sh — Compile a SmartPy contract to Michelson locally, no IDE.
#
# Uses the smartpy-tezos PyPI package installed in a venv at
# $SMARTPY_VENV (default ~/smartpy-cli-venv). The package ships native
# macOS binaries (smartpy-{oasis,canopy}-macOS.exe) which we force via
# SMARTPY_OASIS / SMARTPY_CANOPY env vars — that bypasses the package's
# default routing which sends Darwin-x86_64 hosts through Docker (where
# the oasis binary crashes under emulation).
#
# First-time setup:
#   /usr/local/opt/python@3.12/bin/python3.12 -m venv ~/smartpy-cli-venv
#   ~/smartpy-cli-venv/bin/pip install smartpy-tezos
#
# Usage:
#   ./scripts/compile.sh plinko                      # compile + deploy to shadownet
#   ./scripts/compile.sh plinko --no-deploy          # just compile
#   ./scripts/compile.sh plinko --network mainnet    # extra args go to deploy.sh
#   ./scripts/compile.sh acey-duecey   (alias: ad)
#   ./scripts/compile.sh txl | ttt | squares | reversi | chess | oracle | war

set -euo pipefail
cd "$(dirname "$0")/.."

CONTRACT=""
NO_DEPLOY=0
DEPLOY_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-deploy) NO_DEPLOY=1; shift ;;
    -h|--help)
      echo "usage: $0 <contract> [--no-deploy] [extra deploy.sh args]"
      echo "  contracts: oracle, acey-duecey (or ad), txl, ttt, squares, reversi, chess, plinko, war"
      exit 0 ;;
    *)
      if [[ -z "$CONTRACT" ]]; then
        CONTRACT="$1"
      else
        DEPLOY_ARGS+=("$1")
      fi
      shift ;;
  esac
done

if [[ -z "$CONTRACT" ]]; then
  echo "usage: $0 <contract> [--no-deploy] [extra deploy.sh args]"
  echo "  contracts: oracle, acey-duecey (or ad), txl, ttt, squares, reversi, chess, plinko, war"
  exit 1
fi

# ─── colours ─────────────────────────────────────────────────────────
G="\033[0;32m"; R="\033[0;31m"; Y="\033[0;33m"; C="\033[0;36m"; B="\033[1m"; RESET="\033[0m"

# ─── contract → source map (mirrors compile-via-ide.sh) ──────────────
case "$CONTRACT" in
  oracle)         SRC="src/services/smart_contract_oracle.py" ;;
  acey-duecey|ad) SRC="src/services/smart_contractAD.py";   CONTRACT="acey-duecey" ;;
  txl)            SRC="src/services/smart_contract_txl.py" ;;
  ttt)            SRC="src/services/smart_contract_TTT.py" ;;
  squares)        SRC="src/services/smart_contract_squares_v2.py" ;;
  reversi)        SRC="src/services/smart_contractReversi.py" ;;
  chess)          SRC="src/services/smart_contractChess.py" ;;
  plinko)         SRC="src/services/smart_contractPlinko.py" ;;
  war)            SRC="src/services/smart_contractWar.py" ;;
  *)
    echo -e "${R}Unknown contract:${RESET} $CONTRACT"
    exit 1
    ;;
esac

if [[ ! -f "$SRC" ]]; then
  echo -e "${R}Source not found:${RESET} $SRC"
  exit 1
fi

# ─── locate the venv ─────────────────────────────────────────────────
VENV="${SMARTPY_VENV:-$HOME/smartpy-cli-venv}"
if [[ ! -x "$VENV/bin/python" ]]; then
  echo -e "${R}SmartPy venv not found at:${RESET} $VENV"
  echo
  echo "First-time setup:"
  echo "  /usr/local/opt/python@3.12/bin/python3.12 -m venv ~/smartpy-cli-venv"
  echo "  ~/smartpy-cli-venv/bin/pip install smartpy-tezos"
  echo
  echo "(Or set SMARTPY_VENV=<path> to point at an existing venv.)"
  exit 2
fi

PKG_DIR="$VENV/lib/python3.12/site-packages/smartpy"
if [[ ! -d "$PKG_DIR" ]]; then
  # Try other python versions in case the venv was made with a different one.
  PKG_DIR=$(find "$VENV/lib" -maxdepth 3 -type d -name smartpy 2>/dev/null | head -1 || true)
fi
if [[ ! -d "$PKG_DIR" ]]; then
  echo -e "${R}smartpy-tezos not installed in venv:${RESET} $VENV"
  echo "Install it with:  $VENV/bin/pip install smartpy-tezos"
  exit 2
fi

# ─── pick the right binaries for this OS ─────────────────────────────
UNAME=$(uname -s)
case "$UNAME" in
  Darwin) OASIS="$PKG_DIR/smartpy-oasis-macOS.exe"; CANOPY="$PKG_DIR/smartpy-canopy-macOS.exe" ;;
  Linux)  OASIS="$PKG_DIR/smartpy-oasis-linux.exe"; CANOPY="$PKG_DIR/smartpy-canopy-linux.exe" ;;
  *)      echo -e "${R}Unsupported OS:${RESET} $UNAME"; exit 1 ;;
esac

if [[ ! -x "$OASIS" ]]; then
  echo -e "${R}Compiler binary missing:${RESET} $OASIS"
  echo "Try reinstalling: $VENV/bin/pip install --force-reinstall smartpy-tezos"
  exit 2
fi

# ─── compile ─────────────────────────────────────────────────────────
OUT="src/services/build/$CONTRACT"
rm -rf "$OUT"
mkdir -p "$OUT"

SRC_ABS="$(pwd)/$SRC"
echo -e "${B}Compiling${RESET} $SRC ${B}→${RESET} $OUT/"
echo -e "  using: ${C}${OASIS#$HOME/}${RESET}"

# SmartPy writes outputs into the cwd, into a subdir named after the
# test scenario (e.g. "plinko basic" → "plinko_basic/"). Run from $OUT
# so the artifacts land in the build dir, then flatten the subdir up.
(
  cd "$OUT"
  SMARTPY_OASIS="$OASIS" \
  SMARTPY_CANOPY="$CANOPY" \
  "$VENV/bin/python" "$SRC_ABS"
)

# Flatten: SmartPy nests artifacts one level deep, one subdir per
# @sp.add_test scenario (sanitised scenario name). Move files up so
# deploy.py finds them at $OUT/* (it accepts step_*.tz names).
#
# Convention: the canonical deploy storage comes from the
# alphabetically-FIRST scenario (e.g. "squares basic compile" → subdir
# squares_basic_compile/). We iterate subdirs in sorted order and skip
# any filename that's already been claimed by an earlier subdir — so the
# first scenario's `c = main.Squares(...)` produces the initial storage
# deploy.py originates. Without this guard, multi-scenario contracts
# (squares-v2 has 3) silently bake LAST-scenario artifacts because mv
# overwrites on conflict, swapping real KT1 constructor args for the
# sp.test_account placeholder tz1s from the test runtime scenarios.
shopt -s nullglob
SUBDIRS=("$OUT"/*/)
shopt -u nullglob
for d in "${SUBDIRS[@]}"; do
  shopt -s nullglob
  for f in "$d"/*; do
    fname=$(basename "$f")
    if [[ -e "$OUT/$fname" ]]; then continue; fi
    mv "$f" "$OUT/"
  done
  shopt -u nullglob
  rm -rf "$d"
done

# ─── done ─────────────────────────────────────────────────────────────
codes=("$OUT"/*_contract.tz)
storages=("$OUT"/*_storage.tz)
if (( ${#codes[@]} == 0 )); then
  echo -e "${R}✗ No *_contract.tz produced in $OUT/${RESET}"
  ls "$OUT" || true
  exit 3
fi

echo -e "${G}✓${RESET} Compiled."
echo "  code:    ${codes[0]#"$(pwd)/"}"
[[ ${#storages[@]} -gt 0 ]] && echo "  storage: ${storages[0]#"$(pwd)/"}"
echo

# ─── chain into deploy (unless --no-deploy) ──────────────────────────
if (( NO_DEPLOY )); then
  echo "--no-deploy set. To deploy later:"
  echo "  ./scripts/deploy.sh $CONTRACT --skip-compile"
  exit 0
fi

echo -e "${B}Deploying${RESET} ${CONTRACT}…"
# `set -u` plus `"${arr[@]}"` on an empty array trips "unbound variable"
# on older bash (macOS ships 3.2). The `${arr[@]+…}` alt-expansion is
# defined-empty-safe and yields nothing when DEPLOY_ARGS is empty.
exec ./scripts/deploy.sh "$CONTRACT" --skip-compile ${DEPLOY_ARGS[@]+"${DEPLOY_ARGS[@]}"}
