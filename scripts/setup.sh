#!/usr/bin/env bash
# setup.sh — One-time setup for deploying TezLiteApps contracts.
#
# Creates a project-local Python virtualenv at .venv/ and installs pytezos
# and smartpy into it. Skips pipx entirely — that was the source of the
# `pipx: command not found` error.
#
# Re-running this script is safe (idempotent). It reuses an existing .venv
# and only installs missing packages.

set -euo pipefail
cd "$(dirname "$0")/.."

# ─── tiny logger helpers ──────────────────────────────────────────────
ok()   { printf '\033[0;32m%s\033[0m\n' "$1"; }
warn() { printf '\033[0;33m%s\033[0m\n' "$1"; }
err()  { printf '\033[0;31m%s\033[0m\n' "$1" >&2; }

# ─── find Python 3.10+ ────────────────────────────────────────────────
find_python() {
  for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
      local version major minor
      version="$($cmd -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
      [[ -z "$version" ]] && continue
      major="${version%.*}"
      minor="${version#*.}"
      if (( major == 3 && minor >= 10 )); then
        echo "$cmd"
        return 0
      fi
    fi
  done
  return 1
}

PY="$(find_python)" || {
  err "Python 3.10+ not found."
  err "  macOS:  brew install python@3.12"
  err "  Linux:  sudo apt install python3.12 python3.12-venv  (or your distro's equivalent)"
  err "  Or: https://www.python.org/downloads/"
  exit 1
}
PY_VERSION="$($PY --version)"
ok "Using $PY_VERSION ($(command -v "$PY"))"

# ─── create / reuse the venv ─────────────────────────────────────────
VENV_DIR=".venv"
if [[ -d "$VENV_DIR" ]]; then
  ok ".venv exists — reusing"
else
  ok "Creating virtual environment in $VENV_DIR/"
  "$PY" -m venv "$VENV_DIR"
fi

# Use the venv's binaries directly — avoids issues with `source` in some
# non-bash shells, and works the same way on macOS and Linux.
VENV_PY="$VENV_DIR/bin/python"
VENV_PIP="$VENV_PY -m pip"

ok "Upgrading pip in venv"
$VENV_PIP install --quiet --upgrade pip

# ─── install Python deps ─────────────────────────────────────────────
# pytezos: signing + RPC. smartpy: compile .py contracts → Michelson.
ok "Installing pytezos (this is the slow one)"
$VENV_PIP install --quiet pytezos

# ─── SmartPy install (best-effort) ───────────────────────────────────
# IMPORTANT: the PyPI package literally named `smartpy` is an unrelated
# state-machine library — NOT SmartPy.io's Tezos compiler. We do NOT pip
# install it. The real Tezos SmartPy compiler is only distributed via the
# bash installer at smartpy.io/cli or the online IDE at smartpy.io/ide.
#
# If you previously ran an older setup.sh and got the wrong `smartpy`
# package installed in the venv, uninstall it so it doesn't shadow imports.
if "$VENV_PY" -c "import smartpy; import sys; sys.exit(0 if hasattr(smartpy, 'StateMachine') or not hasattr(smartpy, 'add_test') else 1)" 2>/dev/null; then
  warn "Removing the unrelated PyPI 'smartpy' package from the venv (it's not SmartPy.io)"
  $VENV_PIP uninstall --quiet --yes smartpy >/dev/null 2>&1 || true
fi

# Try the official bash installer — best-effort. If it fails (smartpy.io
# slow, weird arch, no curl, whatever), we don't error out: the user can
# still compile via the online IDE.
SMARTPY_HOME="$PWD/.smartpy-cli"
SMARTPY_READY=""

find_smartpy() {
  for candidate in \
    "$SMARTPY_HOME/SmartPy.sh" \
    "$SMARTPY_HOME/smartpy" \
    "$SMARTPY_HOME/bin/SmartPy.sh" \
    "$SMARTPY_HOME/bin/smartpy"; do
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

SMARTPY_BIN="$(find_smartpy)" || SMARTPY_BIN=""
if [[ -n "$SMARTPY_BIN" ]]; then
  SMARTPY_READY="$SMARTPY_BIN"
  ok "  SmartPy CLI present: ${SMARTPY_BIN#"$PWD/"}"
else
  ok "Trying SmartPy bash installer (optional — IDE fallback works either way)"
  mkdir -p "$SMARTPY_HOME"
  if command -v curl >/dev/null 2>&1 && \
     curl -fsSL https://smartpy.io/cli/install.sh 2>/dev/null \
       | bash -s -- "$SMARTPY_HOME" >/dev/null 2>&1; then
    SMARTPY_BIN="$(find_smartpy)" || SMARTPY_BIN=""
    if [[ -n "$SMARTPY_BIN" ]]; then
      SMARTPY_READY="$SMARTPY_BIN"
      ok "  Installed: ${SMARTPY_BIN#"$PWD/"}"
    fi
  fi
  if [[ -z "$SMARTPY_READY" ]]; then
    warn "  Bash installer didn't produce a CLI. That's fine — use the IDE flow below."
    rmdir "$SMARTPY_HOME" 2>/dev/null || true
  fi
fi

# ─── verify ──────────────────────────────────────────────────────────
ok "Verifying installations"
"$VENV_PY" -c "import pytezos; print(f'  pytezos {pytezos.__version__}')"

# ─── .env scaffold ───────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    warn "No .env file found. Copying from .env.example."
    cp .env.example .env
    warn "Edit .env and paste your 24-word mnemonic before running deploy.sh."
  else
    warn "No .env or .env.example present. You'll need to provide a key via --key."
  fi
else
  ok ".env present"
fi

# ─── done ────────────────────────────────────────────────────────────
echo
ok "✓ Setup complete."
echo
if [[ -n "$SMARTPY_READY" ]]; then
cat <<'EOF'
Next steps:
  1. Bootstrap a shadownet wallet:
       ./scripts/new-test-wallet.sh
  2. Deploy the oracle (compiles locally + originates + patches constants.js):
       ./scripts/deploy.sh oracle
EOF
else
cat <<'EOF'
Next steps (SmartPy isn't installed locally — using the IDE workflow):
  1. Bootstrap a shadownet wallet:
       ./scripts/new-test-wallet.sh
  2. Compile the oracle via the SmartPy online IDE — the script opens
     your browser, copies the source to the clipboard, and waits for you
     to drop the resulting .tz files into src/services/build/oracle/:
       ./scripts/compile-via-ide.sh oracle
  3. That script will offer to deploy automatically. Or run it yourself:
       ./scripts/deploy.sh oracle --skip-compile
EOF
fi
