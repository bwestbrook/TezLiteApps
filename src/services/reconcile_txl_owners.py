"""
reconcile_txl_owners.py — TXL v2 oracle worker (one-shot reconciler).

Reads the Kalamint FA2 ledger (mainnet big_map 857) for every TXL token,
diffs it against the TXL manager contract's idLookUp big_map on the
chosen network, and submits `batchUpdateOwner` ops to bring on-chain
ownership current.

v2 changes vs the legacy ghostnet script:
  - Network is an arg (shadownet or mainnet) — TXL contract address
    looked up per network from src/constants.js, not hardcoded.
  - Reads the oracle key from .env (TXL_ORACLE_MNEMONIC). The old
    hardcoded seed in oracle_TXL.py is publicly committed and must
    not be used.
  - Talks to the v2 contract's `batchUpdateOwner(updates: list[...])`
    entrypoint — up to 50 updates per signed op, vs one-update-per-op
    in the legacy script. ~6 ops to seed all 271 tokens.
  - Tokens currently owned by the objkt marketplace KT1 are routed to
    the contract's burnSentinel address (which IS the objkt KT1) —
    they accrue nothing and don't count toward activeSupply. This is
    the policy decided in v2 design (Q2 = burn-sentinel exclusion).

Flow:
  1. Pull current TXL storage (idLookUp big_map keys + values) via tzkt.
  2. For each Kalamint TXL token, query mainnet big_map 857 → current owner.
  3. Build a diff: stored owner ≠ current owner.
  4. Write CSV + markdown report to ./reports/.
  5. With --execute, batch the diff into `batchUpdateOwner` ops.

Usage:
  # Dry run, default network is whatever TXL_CONTRACT_ADDRESS resolves to
  python src/services/reconcile_txl_owners.py --network shadownet
  python src/services/reconcile_txl_owners.py --network mainnet --execute

Requires: pip install pytezos requests
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

# Canonical Kalamint big_map ID for the TXL FA2 ledger. Hardcoded
# because it's invariant — the same big_map serves every network the
# UI talks to (the FA2 collection itself lives on mainnet).
KALAMINT_BIGMAP_ID = 857

# objkt.com marketplace KT1 — must match OBJKT_MARKETPLACE in
# src/services/smart_contract_txl.py and txlOwners.js. Tokens held
# here are treated as burn-sentinel by the contract.
OBJKT_MARKETPLACE = "KT1FvqJwEDWb1Gwc55Jd1jjTHRVWbYKUUpyq"

# Per-batch update cap — must stay <= the contract's MAX_BATCH.
# Bigger batches mean fewer ops but risk hitting the per-op gas cap;
# 50 leaves headroom for the storage writes per update.
DEFAULT_BATCH_SIZE = 50

# Network → RPC + tzkt endpoints. Kalamint FA2 ledger only exists on
# mainnet, so the Kalamint queries always go there regardless of which
# network the TXL contract is on.
NETWORK_RPCS = {
    "shadownet": "https://rpc.shadownet.teztnets.com",
    "mainnet":   "https://mainnet.tezos.ecadinfra.com",
}
TZKT_API = {
    "shadownet": "https://api.shadownet.tzkt.io/v1",
    "mainnet":   "https://api.tzkt.io/v1",
}
MAINNET_TZKT = TZKT_API["mainnet"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.js"
ENV_PATH = PROJECT_ROOT / ".env"
REPORTS_DIR = PROJECT_ROOT / "reports"


@dataclass
class OwnerRow:
    token_id: int
    stored_owner: str | None
    current_owner: str | None
    target_owner: str | None   # what we'd submit to updateOwner (burn-sentinel-mapped)
    needs_update: bool
    note: str = ""


def load_dotenv() -> None:
    """Copy of deploy.py's loader — keeps this script standalone so
    operators can run it without pulling the rest of the deploy stack
    into scope."""
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip("'").strip('"'),
        )


def read_constant_from_js(name: str) -> str | None:
    """Pull `export const NAME = '...'` out of constants.js. Cheaper
    and dependency-free vs spinning up a JS interpreter."""
    text = CONSTANTS_PATH.read_text()
    m = re.search(
        rf"export const {re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]",
        text,
    )
    return m.group(1) if m else None


def get_txl_address(network: str) -> str:
    """Find the per-network TXL contract address baked into
    constants.js. deploy.py patches these on origination — so this
    script always points at whatever's live."""
    name = f"TXL_CONTRACT_ADDRESS_{network.upper()}"
    addr = read_constant_from_js(name)
    if not addr:
        sys.exit(f"Couldn't find `{name}` in {CONSTANTS_PATH.relative_to(PROJECT_ROOT)}.")
    return addr


def fetch_stored_owners(session: requests.Session, network: str, contract: str) -> dict[int, str]:
    """Walk the contract's idLookUp big_map via tzkt. v2 is lazy-
    populated so this may return an empty dict — that's the expected
    state right after origination, before the first oracle run."""
    base = TZKT_API[network]
    # First get the big_map ID for `idLookUp`.
    storage_url = f"{base}/contracts/{contract}/storage"
    resp = session.get(storage_url, timeout=30)
    resp.raise_for_status()
    storage = resp.json()
    ptr = storage.get("idLookUp")
    if ptr in (None, "", 0):
        return {}
    # idLookUp is rendered as either the big_map ID (int) or an inlined
    # object depending on tzkt version + storage size; handle both.
    if isinstance(ptr, dict):
        return {int(k): v["owner"] for k, v in ptr.items()}

    # Big-map walk via paginated keys endpoint.
    out: dict[int, str] = {}
    offset = 0
    while True:
        keys_url = (
            f"{base}/bigmaps/{ptr}/keys"
            f"?active=true&limit=1000&offset={offset}"
            "&select=key,value"
        )
        page = session.get(keys_url, timeout=30).json()
        if not page:
            break
        for entry in page:
            tid = int(entry["key"])
            owner = entry["value"]["owner"]
            out[tid] = owner
        offset += len(page)
        if len(page) < 1000:
            break
    return out


def fetch_current_kalamint_owners(
    session: requests.Session, token_ids: Iterable[int]
) -> dict[int, str]:
    """Bulk-fetch current owners for a list of TXL token IDs from the
    Kalamint big_map on mainnet. tzkt supports key.nat.in= for batched
    queries — ~10 token-IDs-per-URL-query keeps URLs reasonable."""
    ids = sorted(set(token_ids))
    out: dict[int, str] = {}
    chunk = 50
    for i in range(0, len(ids), chunk):
        slice_ = ids[i : i + chunk]
        joined = ",".join(str(t) for t in slice_)
        url = (
            f"{MAINNET_TZKT}/bigmaps/{KALAMINT_BIGMAP_ID}/keys"
            f"?active=true&value.eq=1&select=key"
            f"&limit=10000&key.nat.in={joined}"
        )
        rows = session.get(url, timeout=30).json()
        for row in rows or []:
            # Key shape: {"nat": "<token_id>", "address": "<owner>"}
            out[int(row["nat"])] = row["address"]
    return out


def diff(
    stored: dict[int, str],
    current: dict[int, str],
    burn_sentinel: str,
) -> list[OwnerRow]:
    """Build per-token rows. target_owner is what we'd call
    updateOwner with — for objkt-owned tokens that's the burn
    sentinel, otherwise the Kalamint current owner verbatim."""
    rows: list[OwnerRow] = []
    all_ids = sorted(set(stored.keys()) | set(current.keys()))
    for tid in all_ids:
        s = stored.get(tid)
        c = current.get(tid)
        target = c
        note = ""
        if c == OBJKT_MARKETPLACE:
            target = burn_sentinel
            note = "→ burn-sentinel (objkt marketplace)"
        if c is None:
            note = "no active value=1 holder in Kalamint big_map 857"
        needs = target is not None and target != s
        rows.append(
            OwnerRow(
                token_id=tid,
                stored_owner=s,
                current_owner=c,
                target_owner=target,
                needs_update=needs,
                note=note,
            )
        )
    return rows


def write_reports(rows: list[OwnerRow], contract: str, network: str) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    csv_path = REPORTS_DIR / f"txl-owners-{stamp}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "token_id", "stored_owner", "current_owner",
            "target_owner", "needs_update", "note",
        ])
        for r in rows:
            w.writerow([
                r.token_id, r.stored_owner or "", r.current_owner or "",
                r.target_owner or "", r.needs_update, r.note,
            ])

    needs = [r for r in rows if r.needs_update]
    missing = [r for r in rows if r.current_owner is None]
    objkt = [r for r in rows if r.current_owner == OBJKT_MARKETPLACE]
    md_path = REPORTS_DIR / f"txl-owners-{stamp}.md"
    with md_path.open("w") as f:
        f.write(f"# TXL v2 owner reconciliation — {stamp}\n\n")
        f.write(f"- Network: `{network}`\n")
        f.write(f"- TXL contract: `{contract}`\n")
        f.write(f"- Source ledger: Kalamint mainnet big_map `{KALAMINT_BIGMAP_ID}`\n")
        f.write(f"- Tokens checked: **{len(rows)}**\n")
        f.write(f"- Updates needed: **{len(needs)}**\n")
        f.write(f"- objkt-marketplace tokens (→ burn sentinel): **{len(objkt)}**\n")
        f.write(f"- Tokens with no active Kalamint holder: **{len(missing)}**\n\n")
        if needs:
            f.write("## Updates needed\n\n")
            f.write("| token_id | stored | current | target |\n")
            f.write("|---|---|---|---|\n")
            for r in needs:
                f.write(
                    f"| {r.token_id} | `{r.stored_owner or '∅'}` | "
                    f"`{r.current_owner or '∅'}` | `{r.target_owner or '∅'}` |\n"
                )
            f.write("\n")
        if missing:
            f.write("## Tokens with no active holder\n\n")
            for r in missing:
                f.write(f"- {r.token_id} — {r.note}\n")
            f.write("\n")
    return csv_path, md_path


def execute_updates(
    rows: list[OwnerRow], network: str, contract_addr: str, batch_size: int
) -> None:
    """Sign + send batchUpdateOwner ops for every row needing an update.
    Reads TXL_ORACLE_MNEMONIC from env (preferred) or DEPLOY_MNEMONIC
    as a fallback for the bootstrap reconcile when the oracle key
    hasn't been provisioned yet."""
    try:
        from pytezos import Key, pytezos
    except ImportError:
        sys.exit("pytezos is not installed; run `pip install pytezos`")

    # Prefer per-network mnemonic (TXL_ORACLE_MNEMONIC_SHADOWNET /
    # _MAINNET) so a shadownet operator can't accidentally use the
    # mainnet key (or vice versa). Fall back to the unsuffixed
    # variable for older .env files and single-network setups.
    per_network = os.environ.get(
        f"TXL_ORACLE_MNEMONIC_{network.upper()}", ""
    ).strip()
    mnemonic = per_network or os.environ.get("TXL_ORACLE_MNEMONIC", "").strip()
    if not mnemonic:
        sys.exit(
            f"No oracle mnemonic configured for {network}. Add either "
            f"TXL_ORACLE_MNEMONIC_{network.upper()} or TXL_ORACLE_MNEMONIC "
            f"to .env. The v1 seed in oracle_TXL.py is publicly "
            f"committed and must not be reused. See "
            f"docs/TXL_MAINNET_RUNBOOK.md."
        )
    key = Key.from_mnemonic(mnemonic.split())
    rpc = NETWORK_RPCS[network]
    client = pytezos.using(shell=rpc, key=key)
    contract = client.contract(contract_addr)

    pending = [r for r in rows if r.needs_update and r.target_owner]
    if not pending:
        print("Nothing to update.")
        return

    print(
        f"Signing + sending batchUpdateOwner from {key.public_key_hash()} "
        f"for {len(pending)} tokens in batches of {batch_size}…"
    )
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        updates = [
            {"txlId": r.token_id, "newOwner": r.target_owner}
            for r in chunk
        ]
        try:
            # pytezos introspects this entrypoint as a BARE list — SmartPy
            # flattens single-field records on parameters, so the
            # parameter shape is `list[record(...)]` not
            # `record(updates=list[...])`. Passing as a kwarg trips
            # pytezos's `or`-tree dispatcher with "expected list, got
            # dict". Pass positionally + use .send() (handles autofill
            # + sign + inject in one).
            opg = contract.batchUpdateOwner(updates).send(min_confirmations=1)
            op_hash = opg.hash() if hasattr(opg, "hash") else (
                opg["hash"] if isinstance(opg, dict) else opg
            )
            print(f"  batch {start // batch_size + 1}: {op_hash}")
        except Exception as exc:
            print(f"  batch {start // batch_size + 1} failed: {exc}")
            # Don't bail — the operator can re-run with --execute and
            # the diff will re-converge on what's left.
            time.sleep(1)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--network", choices=sorted(NETWORK_RPCS.keys()), default="shadownet",
        help="Which network's TXL contract to reconcile (default: shadownet)",
    )
    p.add_argument(
        "--execute", action="store_true",
        help="Actually sign + send batchUpdateOwner ops (default: dry run)",
    )
    p.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Updates per signed batchUpdateOwner op (default {DEFAULT_BATCH_SIZE})",
    )
    p.add_argument(
        "--token-ids", type=str, default=None,
        help="Comma-separated subset of TXL IDs to reconcile (default: all)",
    )
    args = p.parse_args()

    load_dotenv()
    network = args.network
    contract_addr = get_txl_address(network)

    print(f"TXL contract: {contract_addr} ({network})")
    print(f"Kalamint big_map: {KALAMINT_BIGMAP_ID} (mainnet)")
    print(f"Mode: {'EXECUTE' if args.execute else 'dry run'}")
    print()

    session = requests.Session()
    stored = fetch_stored_owners(session, network, contract_addr)
    print(f"  Stored idLookUp entries: {len(stored)}")

    # Token universe = txlOwners.js TXL_TOKEN_IDS. We mirror it here to
    # avoid a Node round-trip; it's the same canonical list.
    target_ids = _txl_token_ids()
    if args.token_ids:
        only = {int(x) for x in args.token_ids.split(",") if x.strip()}
        target_ids = [t for t in target_ids if t in only]

    print(f"  Querying Kalamint for {len(target_ids)} token(s)…")
    current = fetch_current_kalamint_owners(session, target_ids)
    print(f"  Active Kalamint holders: {len(current)}")

    rows = diff(stored, current, burn_sentinel=OBJKT_MARKETPLACE)
    csv_path, md_path = write_reports(rows, contract_addr, network)
    needs = sum(1 for r in rows if r.needs_update)
    print()
    print(f"  Diff: {needs} updates needed.")
    print(f"  CSV: {csv_path}")
    print(f"  MD:  {md_path}")

    if args.execute:
        print()
        execute_updates(rows, network, contract_addr, args.batch_size)
    else:
        print("\nDry run complete. Re-run with --execute to inject ops.")
    return 0


def _txl_token_ids() -> list[int]:
    """Canonical Kalamint TXL token IDs. Kept in lockstep with
    src/services/txlOwners.js and src/services/smart_contract_txl.py.
    Embedded here so the script has no JS dependency."""
    return [
        60199, 60200, 60201, 60202, 60203, 60204, 60206, 60207, 60208, 60209,
        60210, 60211, 60212, 60213, 60215, 60216, 60218, 60219, 60220, 60221,
        60224, 60225, 60226, 60227, 60228, 60230, 60231, 60233, 60234, 60235,
        60236, 60237, 60238, 60239, 60240, 60241, 60242, 60243, 60244, 60245,
        60246, 60247, 60248, 60249, 60250, 60251, 60252, 60253, 60254, 60255,
        60256, 60257, 60258, 60259, 60260, 60338, 60339, 60340, 60344, 60346,
        60348, 60349, 60350, 60354, 60355, 60356, 60357, 60358, 60359, 60361,
        60362, 60363, 60366, 60367, 60368, 60369, 60370, 60371, 60372, 60373,
        60374, 60375, 60377, 60379, 60380, 60381, 60382, 60383, 60384, 60386,
        60387, 60388, 60389, 60391, 60392, 60393, 60394, 60395, 60396, 60397,
        60399, 60401, 60403, 60404, 60406, 60407, 60413, 60414, 60416, 60418,
        60429, 60432, 60433, 60434, 60436, 60437, 60438, 60439, 60440, 60441,
        60442, 60443, 60444, 60445, 60446, 60447, 60448, 60449, 60450, 60451,
        60452, 60453, 60454, 60455, 60456, 60457, 60458, 60459, 60460, 60461,
        60462, 60463, 60464, 60465, 60466, 60467, 60468, 60469, 60470, 60471,
        60472, 60473, 60474, 60475, 60476, 60477, 60478, 60479, 60480, 60481,
        60483, 60486, 60487, 60489, 60491, 60492, 60493, 60494, 60495, 60496,
        60497, 60498, 60499, 60500, 60501, 60502, 60534, 60535, 60536, 60537,
        60545, 60546, 60547, 60548, 60549, 60550, 60551, 60552, 60553, 60554,
        60560, 60561, 60562, 60563, 60564, 60565, 60566, 60567, 60571, 60572,
        60573, 60575, 60576, 60577, 60578, 60580, 60581, 60582, 60583, 60584,
        60585, 60586, 60587, 60589, 60590, 60593, 60595, 60596, 60597, 60599,
        60600, 60601, 60603, 60605, 60606, 60607, 60608, 60612, 60613, 60614,
        60615, 60616, 60617, 60618, 60619, 60620, 60621, 60622, 60623, 60624,
        60625, 60626, 60627, 60628, 60629, 60630, 60631, 60632, 60633, 60636,
        60637, 60638, 60639, 60640, 60641, 60642, 60643, 60644, 60645, 60646,
        60647, 60648, 60649, 60650, 60651, 60688, 60690, 60692, 60693, 60694,
        60696,
    ]


if __name__ == "__main__":
    sys.exit(main())
