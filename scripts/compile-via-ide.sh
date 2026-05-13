#!/usr/bin/env bash
# compile-via-ide.sh — Walk you through compiling a contract via the
# SmartPy online IDE, then chain into the deploy script.
#
# Use this when local SmartPy install isn't working (which is most of the
# time — SmartPy.io's compiler isn't on PyPI, and the bash installer is
# flaky). The IDE compile is the SmartPy team's officially-supported path
# that works in any browser.
#
# Usage:
#   ./scripts/compile-via-ide.sh oracle
#   ./scripts/compile-via-ide.sh txl
#   ./scripts/compile-via-ide.sh acey-duecey      (alias: 'ad')
#   ./scripts/compile-via-ide.sh ttt | squares | reversi | chess | plinko

set -euo pipefail
cd "$(dirname "$0")/.."

CONTRACT="${1:-oracle}"

# ─── colours ─────────────────────────────────────────────────────────
G="\033[0;32m"; R="\033[0;31m"; Y="\033[0;33m"; C="\033[0;36m"; B="\033[1m"; RESET="\033[0m"

# ─── contract → source map ───────────────────────────────────────────
case "$CONTRACT" in
  oracle)      SRC="src/services/smart_contract_oracle.py" ;;
  acey-duecey|ad) SRC="src/services/smart_contractAD.py"; CONTRACT="acey-duecey" ;;
  txl)         SRC="src/services/smart_contract_txl.py" ;;
  ttt)         SRC="src/services/smart_contract_TTT.py" ;;
  squares)     SRC="src/services/smart_contract_squares.py" ;;
  reversi)     SRC="src/services/smart_contractReversi.py" ;;
  chess)       SRC="src/services/smart_contractChess.py" ;;
  plinko)      SRC="src/services/smart_contractPlinko.py" ;;
  war)         SRC="src/services/smart_contractWar.py" ;;
  *)
    echo -e "${R}Unknown contract:${RESET} $CONTRACT"
    echo "Known: oracle, acey-duecey (or ad), txl, ttt, squares, reversi, chess, plinko, war"
    exit 1
    ;;
esac

if [[ ! -f "$SRC" ]]; then
  echo -e "${R}Source not found:${RESET} $SRC"
  exit 1
fi

OUT="src/services/build/$CONTRACT"
mkdir -p "$OUT"

# ─── intro ───────────────────────────────────────────────────────────
clear || true
echo
echo -e "${B}  Compile ${C}$CONTRACT${RESET}${B} via the SmartPy online IDE${RESET}"
echo "  ────────────────────────────────────────────────"
echo
echo "  SmartPy.io's compiler isn't reliably installable locally, but their"
echo "  online IDE works in any browser. You'll compile there once and the"
echo "  deploy script will pick up the .tz output."
echo

# ─── open browser + copy source to clipboard if we can ─────────────
URL="https://smartpy.io/ide"

opened="no"
if command -v open >/dev/null 2>&1; then
  open "$URL" >/dev/null 2>&1 && opened="yes"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$URL" >/dev/null 2>&1 && opened="yes"
elif command -v start >/dev/null 2>&1; then
  start "$URL" >/dev/null 2>&1 && opened="yes"
fi

clipped="no"
if command -v pbcopy >/dev/null 2>&1; then
  pbcopy < "$SRC" && clipped="yes"
elif command -v wl-copy >/dev/null 2>&1; then
  wl-copy < "$SRC" && clipped="yes"
elif command -v xclip >/dev/null 2>&1; then
  xclip -selection clipboard < "$SRC" && clipped="yes"
fi

# ─── steps ───────────────────────────────────────────────────────────
echo -e "${B}  1.${RESET} Open the IDE:"
if [[ "$opened" == "yes" ]]; then
  echo -e "     ${G}✓${RESET} Already opened in your browser → ${C}$URL${RESET}"
else
  echo -e "     ${C}$URL${RESET}"
fi
echo
echo -e "${B}  2.${RESET} Paste in the contract source:"
if [[ "$clipped" == "yes" ]]; then
  echo -e "     ${G}✓${RESET} Source for ${C}$SRC${RESET} is on your clipboard. Cmd-V into the editor."
else
  echo -e "     Copy and paste the contents of ${C}$SRC${RESET}"
  echo -e "     (cat ${C}$SRC${RESET} | pbcopy   on macOS will copy it to your clipboard)"
fi
echo
echo -e "${B}  3.${RESET} Click ${C}Run${RESET} (top right). You should see"
echo -e "     ${G}\"Contract compiled successfully.\"${RESET} in the output panel."
echo
echo -e "${B}  4.${RESET} In the right panel, find the ${C}Step 0: Contract ...${RESET} section."
echo -e "     Click its ${C}Compilation${RESET} sub-tab. There are two paths:"
echo
echo -e "     ${B}A — Download as ZIP (if you can find the button):${RESET}"
echo -e "       At the bottom of the Compilation panel there's a small"
echo -e "       Download icon (cloud-with-arrow). It saves a .zip you unzip"
echo -e "       into:  ${C}$(pwd)/$OUT/${RESET}"
echo
echo -e "     ${B}B — Manual copy (always works):${RESET}"
echo -e "       1. Copy the entire Michelson code block (starts with"
echo -e "          ${C}parameter ...${RESET}) and save to:"
echo -e "             ${C}$OUT/contract.tz${RESET}"
echo -e "       2. Copy the initial storage block (the ${C}(Pair ...)${RESET})"
echo -e "          and save to:"
echo -e "             ${C}$OUT/storage.tz${RESET}"
echo
echo -e "${B}  5.${RESET} Whichever path — the deploy script accepts both naming"
echo -e "     conventions. Just make sure both files are in ${C}$OUT/${RESET}."
echo

# ─── wait for user ──────────────────────────────────────────────────
read -r -p "Press Enter when those .tz files are in $OUT/ ... " _ || true
echo

# ─── verify ──────────────────────────────────────────────────────────
shopt -s nullglob
CODE_FILES=("$OUT"/*.tz)
shopt -u nullglob

if (( ${#CODE_FILES[@]} == 0 )); then
  echo -e "${R}✗${RESET} No .tz files found in $OUT/."
  echo "  Make sure you unzipped into that exact directory, then re-run this script."
  exit 2
fi

# Check we have both a code and storage file.
has_code="no"; has_storage="no"
for f in "${CODE_FILES[@]}"; do
  if [[ "$f" == *_storage.tz ]]; then
    has_storage="yes"
  elif [[ "$f" != *_metadata.tz ]]; then
    has_code="yes"
  fi
done

if [[ "$has_code" != "yes" ]]; then
  echo -e "${R}✗${RESET} No contract code .tz found (only _storage.tz). Re-export from the IDE."
  exit 3
fi
if [[ "$has_storage" != "yes" ]]; then
  echo -e "${R}✗${RESET} No _storage.tz found. Make sure you exported the storage init from the IDE."
  exit 3
fi

echo -e "${G}✓${RESET} Found compiled artifacts in $OUT/:"
for f in "${CODE_FILES[@]}"; do
  echo -e "    ${f#"$(pwd)/"}"
done
echo

# ─── chain into deploy ──────────────────────────────────────────────
read -r -p "Deploy $CONTRACT to shadownet now? [Y/n] " ANS || true
ANS="${ANS:-Y}"
if [[ "$ANS" =~ ^[Yy]([Ee][Ss])?$ ]]; then
  echo
  exec ./scripts/deploy.sh "$CONTRACT" --skip-compile
fi

echo
echo "Skipped. When you're ready:"
echo "  ./scripts/deploy.sh $CONTRACT --skip-compile"
