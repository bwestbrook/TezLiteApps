#!/usr/bin/env bash
# find-smartpy.sh — Hunt for an installed SmartPy CLI on this machine and
# print the path. Useful when SmartPy's IDE installed a standalone bundle
# somewhere non-obvious.
#
# After running, paste the printed path into .env as:
#     SMARTPY_CLI=/path/that/was/found

set -euo pipefail

echo "Searching for SmartPy CLI…"
echo

# Check the most common paths first.
KNOWN_PATHS=(
  "$HOME/smartpy-cli/SmartPy.sh"
  "$HOME/smartpy-cli/smartpy"
  "$HOME/Applications/SmartPy.app/Contents/MacOS/SmartPy"
  "/Applications/SmartPy.app/Contents/MacOS/SmartPy"
  "/Applications/SmartPyCLI.app/Contents/MacOS/SmartPy.sh"
  "/usr/local/bin/SmartPy.sh"
  "/usr/local/bin/smartpy"
  "/opt/homebrew/bin/SmartPy.sh"
)

FOUND=""
for p in "${KNOWN_PATHS[@]}"; do
  if [[ -x "$p" ]]; then
    echo "  ✓ $p"
    [[ -z "$FOUND" ]] && FOUND="$p"
  fi
done

# Try `which` for anything on PATH.
for name in SmartPy.sh smartpy SmartPy; do
  if w="$(command -v "$name" 2>/dev/null)"; then
    if [[ -x "$w" ]]; then
      echo "  ✓ $w (on PATH as '$name')"
      [[ -z "$FOUND" ]] && FOUND="$w"
    fi
  fi
done

# Last-ditch: scan a few likely directories. Limit depth so we don't crawl
# the entire home folder.
echo
echo "Scanning common install dirs (depth 4)…"
SCAN_ROOTS=(
  "$HOME/smartpy-cli"
  "$HOME/Applications"
  "/Applications"
  "$HOME/.local"
)
for root in "${SCAN_ROOTS[@]}"; do
  [[ -d "$root" ]] || continue
  while IFS= read -r line; do
    if [[ -x "$line" ]]; then
      echo "  ? $line"
      [[ -z "$FOUND" ]] && FOUND="$line"
    fi
  done < <(find "$root" -maxdepth 4 -type f \
                       \( -name 'SmartPy.sh' -o -name 'smartpy' -o -name 'SmartPy' \) \
                       2>/dev/null)
done

echo
if [[ -n "$FOUND" ]]; then
  echo "Best guess: $FOUND"
  echo
  echo "Wire it into .env:"
  echo "  SMARTPY_CLI=\"$FOUND\""
  echo
  echo "Then deploy with:"
  echo "  ./scripts/deploy.sh oracle"
else
  echo "Nothing found. Two options:"
  echo
  echo "  • If the IDE installed a .app bundle, look in Applications and"
  echo "    point SMARTPY_CLI at the executable inside Contents/MacOS/."
  echo
  echo "  • Use the online IDE workflow instead — no install needed:"
  echo "      ./scripts/compile-via-ide.sh oracle"
fi
