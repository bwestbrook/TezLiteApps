#!/usr/bin/env python3
"""
deploy.py — Originate TezLiteApps contracts on a chosen Tezos network.

Replaces the old src/services/deployContract.py stub. That stub had a
HARDCODED 24-word mnemonic — the account it controlled should be considered
compromised; rotate any funds out of it before using this script.

Usage:
    python scripts/deploy.py <contract-id> [--network <name>]
                             [--no-update-constants] [--skip-compile]
                             [--key <path>]

Examples:
    # Compile + originate the oracle on shadownet, then patch constants.js
    python scripts/deploy.py oracle

    # Same on mainnet
    python scripts/deploy.py oracle --network mainnet

    # Use a key file instead of an env var; don't touch constants.js
    python scripts/deploy.py acey-duecey --key ~/.tezos-client/keys/deploy.edsk \
                                         --no-update-constants

Authentication — provide ONE of:
    env  DEPLOY_MNEMONIC="word1 word2 ... word24"   (24-word BIP39 mnemonic)
    env  DEPLOY_SK="edsk..."                        (encoded secret key)
    flag --key /path/to/key.edsk                     (file containing the edsk)

Auto-loads a .env file at the repo root if present. .env is in .gitignore.

Prerequisites (one-time):
    pip install pytezos
    pipx install smartpy   # or follow https://smartpy.io/docs/cli for other install paths
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# ─── Project paths ─────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SOURCES_DIR = PROJECT_ROOT / "src" / "services"
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.js"
BUILD_DIR = SOURCES_DIR / "build"
# Canonical, committed Michelson lives here. deploy.py reads from this
# directory first; BUILD_DIR is a scratch fallback for in-progress
# SmartPy compiles. See contracts/README.md.
CONTRACTS_DIR = PROJECT_ROOT / "contracts"

# ─── Network endpoints ─────────────────────────────────────────────────────
# Tezos public RPCs. Shadownet is the current testnet (Ghostnet was
# decommissioned in 2026). Add networks here as new testnets appear.
NETWORK_RPCS = {
    "shadownet": "https://rpc.shadownet.teztnets.com",
    "mainnet":   "https://mainnet.tezos.ecadinfra.com",
}
# tzkt explorer subdomain per network (mainnet has no subdomain).
TZKT_HOSTS = {
    "shadownet": "shadownet.tzkt.io",
    "mainnet":   "tzkt.io",
}

# ─── Contract registry ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class ContractSpec:
    """Static metadata for one deployable contract."""
    id: str                  # CLI name, e.g. "oracle"
    source: Path             # path to the SmartPy .py source
    constants_var: str       # name of the constants.js variable to patch
    initial_balance_tez: float = 0.0   # tez to send along with origination

# Add new contracts here as they're written/audited. Keys are the CLI args
# the user passes to deploy.py.
CONTRACTS: dict[str, ContractSpec] = {
    "oracle": ContractSpec(
        id="oracle",
        source=SOURCES_DIR / "smart_contract_oracle.py",
        constants_var="ORACLE_CONTRACT",
    ),
    "acey-duecey": ContractSpec(
        id="acey-duecey",
        source=SOURCES_DIR / "smart_contractAD.py",
        constants_var="AD_CONTRACT_ADDRESS",
    ),
    "ttt": ContractSpec(
        id="ttt",
        source=SOURCES_DIR / "smart_contract_TTT.py",
        constants_var="TTT_CONTRACT_ADDRESS",
    ),
    "squares": ContractSpec(
        id="squares",
        source=SOURCES_DIR / "smart_contract_squares_v2.py",
        constants_var="SQUARES_CONTRACT_ADDRESS",
    ),
    "txl": ContractSpec(
        id="txl",
        source=SOURCES_DIR / "smart_contract_txl.py",
        constants_var="TXL_CONTRACT_ADDRESS",
    ),
    "plinko": ContractSpec(
        id="plinko",
        source=SOURCES_DIR / "smart_contractPlinko.py",
        constants_var="PLINKO_CONTRACT_ADDRESS",
    ),
    "war": ContractSpec(
        id="war",
        source=SOURCES_DIR / "smart_contractWar.py",
        constants_var="WAR_CONTRACT_ADDRESS",
    ),
    "reversi": ContractSpec(
        id="reversi",
        source=SOURCES_DIR / "smart_contractReversi.py",
        constants_var="REVERSI_CONTRACT_ADDRESS",
    ),
    "chess": ContractSpec(
        id="chess",
        source=SOURCES_DIR / "smart_contractChess.py",
        constants_var="CHESS_CONTRACT_ADDRESS",
    ),
    "oracle-reference": ContractSpec(
        id="oracle-reference",
        source=SOURCES_DIR / "smart_contract_oracle_reference.py",
        constants_var="ORACLE_REFERENCE_CONTRACT_ADDRESS",
    ),
}

# ─── .env loader ───────────────────────────────────────────────────────────
def load_dotenv():
    """Load KEY=VALUE pairs from a .env at project root, without overwriting
    pre-existing environment variables. .env is .gitignored."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


# ─── SmartPy compilation ───────────────────────────────────────────────────
import shlex  # noqa: E402  (placed here so the import-block stays grouped)


def find_smartpy_command() -> list[str] | None:
    """Return a list-form command that invokes the SmartPy compiler, e.g.
    ['.smartpy-cli/SmartPy.sh'] or ['.venv/bin/python', '-m', 'smartpy'].

    Modern SmartPy installs via `pip install smartpy` and is invoked as
    `python -m smartpy`. Older installs use a `SmartPy.sh` shell script.
    We try in priority order so the most common case (pip + module) wins."""

    # 1) Explicit override — $SMARTPY_CLI can be a path or a full command.
    env_override = os.environ.get("SMARTPY_CLI", "").strip()
    if env_override:
        return shlex.split(env_override)

    # 2) Project-local binary installs (scripts/setup.sh bash-installer path).
    home = Path.home()
    binaries = [
        # Project-local
        PROJECT_ROOT / ".smartpy-cli" / "SmartPy.sh",
        PROJECT_ROOT / ".smartpy-cli" / "smartpy",
        PROJECT_ROOT / ".smartpy-cli" / "bin" / "SmartPy.sh",
        PROJECT_ROOT / ".smartpy-cli" / "bin" / "smartpy",
        PROJECT_ROOT / ".venv" / "bin" / "smartpy",
        PROJECT_ROOT / ".venv" / "bin" / "SmartPy.sh",
        # Canonical bash-installer location ($HOME/smartpy-cli/)
        home / "smartpy-cli" / "SmartPy.sh",
        home / "smartpy-cli" / "smartpy",
        # macOS standalone .app bundles (SmartPy.app / SmartPyCLI.app)
        Path("/Applications/SmartPy.app/Contents/MacOS/SmartPy"),
        Path("/Applications/SmartPyCLI.app/Contents/MacOS/SmartPy.sh"),
        home / "Applications" / "SmartPy.app" / "Contents" / "MacOS" / "SmartPy",
        home / "Applications" / "SmartPyCLI.app" / "Contents" / "MacOS" / "SmartPy.sh",
        # Homebrew (just in case)
        Path("/opt/homebrew/bin/SmartPy.sh"),
        Path("/usr/local/bin/SmartPy.sh"),
        Path("/usr/local/bin/smartpy"),
        # Linux ~/.local convention
        home / ".local" / "bin" / "SmartPy.sh",
        home / ".local" / "bin" / "smartpy",
    ]
    for c in binaries:
        try:
            if c.is_file() and os.access(c, os.X_OK):
                return [str(c)]
        except OSError:
            continue

    # 3) Module-based invocation (`python -m smartpy`). This is the path
    #    that the PyPI smartpy package supports today, even though it
    #    doesn't always install a console script.
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.is_file():
        try:
            check = subprocess.run(
                [str(venv_python), "-c", "import smartpy"],
                capture_output=True,
                timeout=15,
            )
            if check.returncode == 0:
                return [str(venv_python), "-m", "smartpy"]
        except (subprocess.TimeoutExpired, OSError):
            pass

    # 4) Whatever's on $PATH.
    for name in ("smartpy", "SmartPy.sh"):
        p = shutil.which(name)
        if p:
            return [p]

    return None


def compile_contract(spec: ContractSpec) -> tuple[Path, Path]:
    """Compile a SmartPy source to Michelson code + initial storage.

    Returns (code_tz_path, storage_tz_path). Raises SystemExit on failure
    with a helpful message.
    """
    smartpy_cmd = find_smartpy_command()
    if not smartpy_cmd:
        die(
            f"SmartPy compiler not found locally.\n\n"
            f"Easiest path — compile + deploy in one shot via the local\n"
            f"wrapper. It uses smartpy-tezos from ~/smartpy-cli-venv and\n"
            f"runs in ~3s (no browser, no clipboard dance):\n\n"
            f"    ./scripts/compile.sh {spec.id}\n\n"
            f"First-time setup (if the venv doesn't exist yet):\n"
            f"    /usr/local/opt/python@3.12/bin/python3.12 -m venv ~/smartpy-cli-venv\n"
            f"    ~/smartpy-cli-venv/bin/pip install smartpy-tezos\n\n"
            f"Browser-IDE fallback (works on any machine, slower):\n"
            f"    ./scripts/compile-via-ide.sh {spec.id}\n\n"
            f"If you already have SmartPy.sh installed elsewhere, set\n"
            f"SMARTPY_CLI=/path/to/SmartPy.sh in .env."
        )

    out_dir = BUILD_DIR / spec.id
    # Clean previous output so we never grab stale artifacts.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    log(f"Compiling {spec.source.relative_to(PROJECT_ROOT)} → {out_dir.relative_to(PROJECT_ROOT)}/")
    log(f"  using: {' '.join(smartpy_cmd)}")
    result = subprocess.run(
        smartpy_cmd + ["compile", str(spec.source), str(out_dir)],
        cwd=str(SOURCES_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        die(f"smartpy compile failed (exit {result.returncode})")

    code_tz, storage_tz = find_artifacts(out_dir)
    log(f"  code:    {code_tz.relative_to(PROJECT_ROOT)}")
    log(f"  storage: {storage_tz.relative_to(PROJECT_ROOT)}")
    return code_tz, storage_tz


def find_artifacts(out_dir: Path) -> tuple[Path, Path]:
    """Locate the contract code + initial storage artifacts. Code is always
    Michelson text (.tz). Storage can be either:

      • Michelson text:  storage.tz   /   *_storage.tz
      • Raw Micheline:   storage.json

    JSON wins when both exist — it sidesteps PyTezos's Michelson value
    parser entirely, which matters for large structures (the TXL storage
    has 271 entries).

    Code naming we recognize:
      • code.tz                      (canonical, committed)
      • step_<N>_cont_<M>_<Name>.tz  (SmartPy IDE auto-export)
      • contract.tz                  (legacy manual-save)

    Picks the latest pair under whatever conventions match.
    """
    all_tz = sorted(out_dir.rglob("*.tz"))
    all_json = sorted(out_dir.rglob("storage.json"))
    if not all_tz and not all_json:
        die(
            f"No artifacts found under {out_dir}.\n"
            f"  If you compiled via the IDE: save the Michelson code to\n"
            f"      {out_dir / 'code.tz'}\n"
            f"  and the initial storage to either:\n"
            f"      {out_dir / 'storage.tz'}    (Michelson text)\n"
            f"  or  {out_dir / 'storage.json'}  (raw Micheline JSON)"
        )

    # Separate .tz files into code vs storage. SmartPy's compiler emits
    # a flock of `step_NNN_..._params.tz` files (sample call data for
    # each test-scenario step) alongside the actual `*_contract.tz` —
    # we explicitly prefer the contract artifact, then fall back to the
    # generic "everything else" pool only if no `*_contract.tz` exists
    # (e.g. canonical hand-written `code.tz`).
    storage_tz_files = [
        p for p in all_tz
        if p.name.endswith("_storage.tz") or p.name == "storage.tz"
    ]
    contract_files = [p for p in all_tz if p.name.endswith("_contract.tz")]
    if contract_files:
        code_files = contract_files
    else:
        code_files = [
            p for p in all_tz
            if p not in storage_tz_files
            and "_metadata" not in p.name
            and "_params" not in p.name
        ]

    if not code_files:
        die(
            f"Found storage but no contract code .tz under {out_dir}.\n"
            f"  Save the Michelson contract code to:\n"
            f"      {out_dir / 'code.tz'}"
        )

    # Storage selection: JSON wins over .tz when both exist (more robust
    # for large initial storages than going through the Michelson parser).
    if all_json:
        return code_files[-1], all_json[-1]
    if storage_tz_files:
        return code_files[-1], storage_tz_files[-1]

    die(
        f"Found contract code but no initial storage under {out_dir}.\n"
        f"  Save either:\n"
        f"      {out_dir / 'storage.tz'}    (Michelson `(Pair … )` block)\n"
        f"  or  {out_dir / 'storage.json'}  (raw Micheline JSON)"
    )


# ─── Key loading ───────────────────────────────────────────────────────────
def load_key(key_arg: str | None):
    """Return a pytezos Key built from --key, DEPLOY_MNEMONIC, or DEPLOY_SK."""
    from pytezos import Key

    passphrase = os.environ.get("DEPLOY_PASSWORD", "")

    if key_arg:
        key_path = Path(key_arg).expanduser()
        if not key_path.exists():
            die(f"--key file not found: {key_path}")
        edsk = key_path.read_text().strip()
        return Key.from_encoded_key(edsk, passphrase=passphrase)

    mnemonic = os.environ.get("DEPLOY_MNEMONIC", "").strip()
    if mnemonic:
        return Key.from_mnemonic(mnemonic.split(), passphrase=passphrase)

    sk = os.environ.get("DEPLOY_SK", "").strip()
    if sk:
        return Key.from_encoded_key(sk, passphrase=passphrase)

    die(
        "No deploy key configured. Provide one of:\n"
        "  --key /path/to/key.edsk\n"
        "  export DEPLOY_MNEMONIC=\"word1 word2 ... word24\"\n"
        "  export DEPLOY_SK=edsk...\n"
        "Or put DEPLOY_MNEMONIC=... in a .env file at the repo root."
    )


# ─── Origination ───────────────────────────────────────────────────────────
def strip_micheline_meta(node):
    """Recursively drop underscore-prefixed keys (e.g. `_comment`) from a
    Micheline JSON value. Tezos's RPC validator only accepts the canonical
    keys (`prim`, `args`, `annots`, `int`, `string`, `bytes`), so any
    documentation we embed must be removed before submission."""
    if isinstance(node, dict):
        return {
            k: strip_micheline_meta(v)
            for k, v in node.items()
            if not k.startswith("_")
        }
    if isinstance(node, list):
        return [strip_micheline_meta(x) for x in node]
    return node


def parse_storage(code_micheline, storage_tz: Path):
    """Convert the initial-storage `.tz` file into Micheline JSON.

    PyTezos's `michelson_to_micheline` parses scripts (parameter+storage+code)
    and types fine, but it doesn't accept bare data values like
    `(Pair "tz1…" …)`. To parse a typed value we have to:
      1. Pull the storage TYPE node out of the script Micheline.
      2. Build a MichelsonType class from that type.
      3. Use that class's `from_michelson(text)` to parse the value.

    Also accepts a sibling `.json` file (raw Micheline JSON) as an escape
    hatch — drop one in alongside `code.tz` if the Michelson parser is
    being difficult.
    """
    import json
    # Escape hatch: a sibling .json file (raw Micheline) wins if present.
    # `storage_tz` might already BE the .json path (find_artifacts will hand
    # us either), so with_suffix(".json") returns the same path in that case.
    json_path = storage_tz if storage_tz.suffix == ".json" else storage_tz.with_suffix(".json")
    if json_path.is_file():
        raw = json.loads(json_path.read_text())
        # Strip any documentation-only fields. Tezos's Micheline parser is
        # strict — only prim/args/int/string/bytes/annots are valid keys.
        # `_comment` (and any other underscore-prefixed key) is for humans.
        return strip_micheline_meta(raw)

    # Locate the `storage <type>` directive within the script.
    if isinstance(code_micheline, list):
        sections = code_micheline
    else:
        sections = [code_micheline]
    storage_section = next(
        (s for s in sections if isinstance(s, dict) and s.get("prim") == "storage"),
        None,
    )
    if storage_section is None or not storage_section.get("args"):
        die(
            f"Couldn't find a `storage <type>` directive in the contract "
            f"code. Make sure code.tz contains all three of "
            f"parameter / storage / code sections."
        )
    storage_type_node = storage_section["args"][0]

    # Build a typed parser and feed it the storage text.
    from pytezos.michelson.types.base import MichelsonType
    storage_text = storage_tz.read_text().strip()

    StorageT = MichelsonType.match(storage_type_node)
    try:
        value = StorageT.from_michelson(storage_text)
    except Exception as e1:
        # Some PyTezos versions are pickier about parens around the
        # outermost expression. Retry with them stripped.
        if storage_text.startswith("(") and storage_text.endswith(")"):
            inner = storage_text[1:-1].strip()
            try:
                value = StorageT.from_michelson(inner)
            except Exception as e2:
                die(
                    f"Couldn't parse storage.tz as the contract's storage "
                    f"type.\n"
                    f"  First error:  {e1}\n"
                    f"  After paren-strip: {e2}\n\n"
                    f"Workaround — convert storage.tz to Micheline JSON and "
                    f"save it next to storage.tz as `storage.json`. The deploy "
                    f"script reads JSON in preference to .tz."
                )
        else:
            die(
                f"Couldn't parse storage.tz as the contract's storage type:\n"
                f"  {e1}\n\n"
                f"Workaround — save the Micheline JSON form as `storage.json` "
                f"in the same folder."
            )
    return value.to_micheline_value()


def ensure_revealed(client) -> None:
    """First op from any new Tezos account requires a `reveal` to put the
    public key on-chain. Subsequent ops don't. We probe the account's
    manager_key via RPC; if absent we submit a reveal. If the reveal itself
    fails with 'previously_revealed' (race / re-run), we treat that as
    success and move on."""
    addr = client.key.public_key_hash()
    revealed = False
    try:
        manager_key = client.shell.head.context.contracts[addr].manager_key()
        revealed = manager_key is not None
    except Exception:
        # RPC might 404 or otherwise complain — fall through and try reveal.
        pass

    if revealed:
        return

    log("First op from this account — revealing public key on-chain…")
    try:
        client.reveal().autofill().sign().inject(_async=False, min_confirmations=1)
        log("  ✓ Public key revealed")
    except Exception as e:
        msg = str(e)
        # Different pytezos / protocol versions phrase this slightly
        # differently — tolerate the common variants.
        already = any(s in msg for s in (
            "previously_revealed",
            "key.already_revealed",
            "AlreadyRevealedError",
        ))
        if already:
            log("  (already revealed — continuing)")
            return
        raise


def originate(spec: ContractSpec, code_tz: Path, storage_tz: Path, network: str, key) -> str:
    """Originate the contract on `network` and return the new KT1... address."""
    from pytezos import pytezos
    from pytezos.michelson.parse import michelson_to_micheline

    rpc = NETWORK_RPCS[network]
    log(f"Connecting to {network} at {rpc}")
    client = pytezos.using(shell=rpc, key=key)

    # Prefer the sibling .json (raw Micheline array) when available —
    # SmartPy oasis emits both contract.tz (text) and contract.json
    # (Micheline). The JSON skips a finicky text-parse step (the .tz
    # output uses a `parameter ...; storage ...; code { … }` style
    # without an outer `{ … }` wrapper, which trips pytezos's PLY
    # parser even after wrapping). Canonical artifacts under contracts/
    # ship only .tz, so fall through to the text parser there.
    import json
    code_json_path = code_tz.with_suffix(".json")
    if code_json_path.exists():
        code_micheline = json.loads(code_json_path.read_text())
    else:
        code_micheline = michelson_to_micheline(code_tz.read_text())
    storage_micheline = parse_storage(code_micheline, storage_tz)

    deployer = key.public_key_hash()
    balance = client.account(deployer).get("balance", "0")
    balance_tez = int(balance) / 1_000_000
    log(f"Deployer: {deployer}")
    log(f"Balance:  {balance_tez:.4f} ꜩ")
    if balance_tez < 1:
        log("WARNING: low balance. Shadownet faucet: https://faucet.shadownet.teztnets.com")

    # First op from a freshly-funded account requires a reveal so the
    # network knows the public key behind the signature. Idempotent.
    ensure_revealed(client)

    log(f"Originating {spec.id}…")
    op = client.origination(script={"code": code_micheline, "storage": storage_micheline})
    if spec.initial_balance_tez > 0:
        op = op.with_amount(int(spec.initial_balance_tez * 1_000_000))
    op = op.autofill().sign().inject(_async=False, min_confirmations=1)

    address = extract_originated_address(op)
    if not address:
        die(f"Could not parse originated contract address from operation result.\n{op}")
    return address


def extract_originated_address(op_result) -> str | None:
    """Walk the injection result to find the new KT1... address.
    PyTezos can return either the operation dict itself or a list of blocks."""
    candidates = []
    if isinstance(op_result, list):
        for entry in op_result:
            candidates.extend(entry.get("contents", []))
    elif isinstance(op_result, dict):
        candidates.extend(op_result.get("contents", []))
    for c in candidates:
        if c.get("kind") != "origination":
            continue
        meta = c.get("metadata", {}).get("operation_result", {})
        for addr in meta.get("originated_contracts", []):
            return addr
    return None


# ─── constants.js patching ─────────────────────────────────────────────────
def update_constants(spec: ContractSpec, address: str, network: str):
    """Replace the per-network constant in src/constants.js with the new
    address. Each contract has two parallel exports — e.g.
        export const AD_CONTRACT_ADDRESS_SHADOWNET = '...'
        export const AD_CONTRACT_ADDRESS_MAINNET   = '...'
    The active `AD_CONTRACT_ADDRESS` resolves to whichever the user has
    toggled to in the UI."""
    text = CONSTANTS_PATH.read_text()
    var_suffixed = f"{spec.constants_var}_{network.upper()}"
    pattern = re.compile(
        rf"(export const {re.escape(var_suffixed)}\s*=\s*)['\"][^'\"]*['\"]"
    )
    new_text, n = pattern.subn(rf"\1'{address}'", text)
    if n == 0:
        log(
            f"WARNING: couldn't find `{var_suffixed}` in constants.js — patch skipped.\n"
            f"  (Add the per-network constants for {spec.constants_var}, "
            f"see the existing entries near the top.)"
        )
        return
    CONSTANTS_PATH.write_text(new_text)
    log(f"Updated {var_suffixed} in src/constants.js → {address}")


# ─── Small UX helpers ──────────────────────────────────────────────────────
def log(msg: str):
    print(f"  {msg}")

def die(msg: str, code: int = 1):
    sys.stderr.write("\n" + msg.rstrip() + "\n\n")
    sys.exit(code)


# ─── Main ──────────────────────────────────────────────────────────────────
def main():
    load_dotenv()

    p = argparse.ArgumentParser(
        description="Originate TezLiteApps contracts on a Tezos network.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Networks:\n"
            "  shadownet  (default — current Tezos testnet)\n"
            "  mainnet\n\n"
            "Contracts:\n  " + "\n  ".join(sorted(CONTRACTS.keys()))
        ),
    )
    p.add_argument("contract", choices=sorted(CONTRACTS.keys()),
                   help="Which contract to deploy")
    p.add_argument("--network", choices=sorted(NETWORK_RPCS.keys()),
                   default="shadownet", help="Target Tezos network (default: shadownet)")
    p.add_argument("--key", help="Path to an .edsk key file (alternative to env vars)")
    p.add_argument("--no-update-constants", action="store_true",
                   help="Skip patching src/constants.js after a successful origination")
    p.add_argument("--skip-compile", action="store_true",
                   help="Use existing build artifacts in src/services/build/")
    args = p.parse_args()

    spec = CONTRACTS[args.contract]
    if not spec.source.exists():
        die(f"Source not found: {spec.source}")

    log("=" * 60)
    log(f"Deploying {spec.id} → {args.network}")
    log("=" * 60)

    # Resolve where the Michelson lives. Priority:
    #   1. contracts/<id>/      — canonical, committed
    #   2. src/services/build/<id>/  — scratch from SmartPy compiles
    # Pass --skip-compile to use whichever exists without recompiling.
    canonical_dir = CONTRACTS_DIR / spec.id
    scratch_dir = BUILD_DIR / spec.id

    if args.skip_compile:
        if canonical_dir.exists():
            out_dir = canonical_dir
        elif scratch_dir.exists():
            out_dir = scratch_dir
        else:
            die(
                f"No artifacts found. Looked in:\n"
                f"  {canonical_dir.relative_to(PROJECT_ROOT)}/\n"
                f"  {scratch_dir.relative_to(PROJECT_ROOT)}/\n"
                f"Either compile fresh (drop --skip-compile) or place\n"
                f"code.tz + storage.tz under one of those paths."
            )
        code_tz, storage_tz = find_artifacts(out_dir)
        log(f"Using artifacts in {out_dir.relative_to(PROJECT_ROOT)}/")
    elif canonical_dir.exists() and any(canonical_dir.rglob("*.tz")):
        # If a canonical build is committed, prefer it over a fresh compile.
        # Saves time and avoids needing SmartPy installed. Users who want to
        # recompile can either delete contracts/<id>/ or compile manually.
        code_tz, storage_tz = find_artifacts(canonical_dir)
        log(f"Using committed artifacts in {canonical_dir.relative_to(PROJECT_ROOT)}/")
        log("  (delete that directory to force a fresh SmartPy compile)")
    else:
        code_tz, storage_tz = compile_contract(spec)

    # Sign + send
    key = load_key(args.key)
    address = originate(spec, code_tz, storage_tz, args.network, key)

    log("")
    log(f"✓ {spec.id} originated at {address}")
    log(f"  https://{TZKT_HOSTS[args.network]}/{address}")
    log("")

    if not args.no_update_constants:
        update_constants(spec, address, args.network)

    log("Done.")


if __name__ == "__main__":
    main()
