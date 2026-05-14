"""
reconcile_txl_owners.py

One-shot reconciliation of the TXL manager contract's idLookUp big_map against
the Kalamint FA2 ledger on mainnet.

Flow:
  1. Pull TXL ghostnet contract storage  -> stored owner per token_id
  2. For each token_id, query Kalamint big_map 857 on mainnet (value=1, active)
     -> current on-chain owner
  3. Diff stored vs current
  4. Write CSV + markdown report to ./reports/
  5. With --execute, sign + send batched updateOwner ops via the oracle key

This is the same logic as oracle_TXL.py's watch loop, but:
  - Runs once and exits (no infinite sleep)
  - Batches operations (one signed group, lower fee, atomic-ish)
  - Has a dry-run default so you can review before signing
  - Writes a report you can keep alongside the contract

Usage:
  python reconcile_txl_owners.py                # dry run, write report
  python reconcile_txl_owners.py --execute      # sign + send updateOwner ops
  python reconcile_txl_owners.py --execute --batch-size 30
  python reconcile_txl_owners.py --token-ids 60199,60200  # limit to a subset

Requires: pip install pytezos requests
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

CONTRACT_ADDRESS = "KT1HD71gj4ZdehpS4Ri8nasjpDTPDQ574Sxy"  # TXL manager (ghostnet)
KALAMINT_BIGMAP_ID = 857  # Kalamint FA2 ledger on mainnet
GHOSTNET_TZKT = "https://api.ghostnet.tzkt.io/v1"
MAINNET_TZKT = "https://api.tzkt.io/v1"

# Oracle seed phrase — same one used by oracle_TXL.py. The oracle is the only
# address allowed to call updateOwner on the contract. Move this to env var
# (TXL_ORACLE_MNEMONIC) for prod.
DEFAULT_ORACLE_MNEMONIC = (
    "viable spy camp win honey impact assist town parrot abandon similar you "
    "print avocado arrive camp maze pet secret park thing leg milk flush"
).split()

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


@dataclass
class OwnerRow:
    token_id: int
    stored_owner: str
    current_owner: str | None
    needs_update: bool
    note: str = ""


def fetch_stored_owners(session: requests.Session) -> dict[int, str]:
    """Return {token_id: stored_owner_address} from the TXL contract storage."""
    url = f"{GHOSTNET_TZKT}/contracts/{CONTRACT_ADDRESS}/storage"
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    storage = resp.json()
    id_lookup = storage.get("idLookUp") or {}
    return {int(k): v["owner"] for k, v in id_lookup.items()}


def fetch_current_owner(session: requests.Session, token_id: int) -> str | None:
    """Look up the current Kalamint owner for a single token_id."""
    url = (
        f"{MAINNET_TZKT}/bigmaps/{KALAMINT_BIGMAP_ID}/keys"
        f"?active=true&value.eq=1&select=key&key.nat.eq={token_id}"
    )
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not payload:
        return None
    # key is {"nat": "<token_id>", "address": "<owner>"}
    return payload[0].get("address") if isinstance(payload[0], dict) else None


def reconcile(
    session: requests.Session,
    only_token_ids: Iterable[int] | None = None,
) -> list[OwnerRow]:
    stored = fetch_stored_owners(session)
    print(f"  Stored idLookUp entries: {len(stored)}")

    if only_token_ids is not None:
        target_ids = sorted(set(only_token_ids) & set(stored.keys()))
    else:
        target_ids = sorted(stored.keys())

    rows: list[OwnerRow] = []
    for i, token_id in enumerate(target_ids, 1):
        try:
            current = fetch_current_owner(session, token_id)
        except requests.RequestException as exc:
            rows.append(
                OwnerRow(
                    token_id=token_id,
                    stored_owner=stored[token_id],
                    current_owner=None,
                    needs_update=False,
                    note=f"fetch error: {exc}",
                )
            )
            continue

        stored_owner = stored[token_id]
        needs = current is not None and current != stored_owner
        note = "" if current else "no active value=1 holder in big_map 857"
        rows.append(
            OwnerRow(
                token_id=token_id,
                stored_owner=stored_owner,
                current_owner=current,
                needs_update=needs,
                note=note,
            )
        )
        if i % 25 == 0 or i == len(target_ids):
            print(f"  ...{i}/{len(target_ids)} checked")
    return rows


def write_reports(rows: list[OwnerRow]) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    csv_path = REPORTS_DIR / f"txl-owners-{stamp}.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["token_id", "stored_owner", "current_owner", "needs_update", "note"])
        for r in rows:
            w.writerow([r.token_id, r.stored_owner, r.current_owner or "", r.needs_update, r.note])

    needs = [r for r in rows if r.needs_update]
    missing = [r for r in rows if r.current_owner is None]
    md_path = REPORTS_DIR / f"txl-owners-{stamp}.md"
    with md_path.open("w") as f:
        f.write(f"# TXL owner reconciliation — {stamp}\n\n")
        f.write(f"- Contract: `{CONTRACT_ADDRESS}` (ghostnet)\n")
        f.write(f"- Source ledger: Kalamint mainnet big_map `{KALAMINT_BIGMAP_ID}`\n")
        f.write(f"- Total tokens tracked: **{len(rows)}**\n")
        f.write(f"- Owners that need updateOwner: **{len(needs)}**\n")
        f.write(f"- Tokens with no active holder in big_map 857: **{len(missing)}**\n\n")
        if needs:
            f.write("## Updates needed\n\n")
            f.write("| token_id | stored | current |\n")
            f.write("|---|---|---|\n")
            for r in needs:
                f.write(f"| {r.token_id} | `{r.stored_owner}` | `{r.current_owner}` |\n")
            f.write("\n")
        if missing:
            f.write("## Tokens with no active holder\n\n")
            for r in missing:
                f.write(f"- {r.token_id} — {r.note}\n")
            f.write("\n")
    return csv_path, md_path


def execute_updates(rows: list[OwnerRow], batch_size: int = 25) -> None:
    """Sign + send updateOwner ops for every row where needs_update is True."""
    try:
        from pytezos import Key, pytezos
    except ImportError:
        sys.exit("pytezos is not installed; run `pip install pytezos`")

    mnemonic = os.environ.get("TXL_ORACLE_MNEMONIC", " ".join(DEFAULT_ORACLE_MNEMONIC)).split()
    key = Key.from_mnemonic(mnemonic)
    client = pytezos.using(shell="https://ghostnet.smartpy.io", key=key)
    contract = client.contract(CONTRACT_ADDRESS)

    pending = [r for r in rows if r.needs_update and r.current_owner]
    if not pending:
        print("Nothing to update.")
        return

    print(f"Signing + sending updateOwner for {len(pending)} tokens "
          f"in batches of {batch_size}...")
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        ops = [
            contract.updateOwner(address=r.current_owner, txlId=r.token_id)
            for r in chunk
        ]
        bulk = client.bulk(*ops)
        try:
            opg = bulk.autofill().sign().inject(min_confirmations=1)
            print(f"  batch {start // batch_size + 1}: injected "
                  f"{opg['hash'] if isinstance(opg, dict) else opg}")
        except Exception as exc:
            print(f"  batch {start // batch_size + 1} failed: {exc}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true",
                   help="Actually sign + send updateOwner ops (default: dry run)")
    p.add_argument("--batch-size", type=int, default=25,
                   help="updateOwner calls per signed group")
    p.add_argument("--token-ids", type=str, default=None,
                   help="Comma-separated subset of TXL IDs to check")
    args = p.parse_args()

    only = None
    if args.token_ids:
        only = [int(x) for x in args.token_ids.split(",") if x.strip()]

    print(f"TXL contract:  {CONTRACT_ADDRESS} (ghostnet)")
    print(f"Kalamint bm:   {KALAMINT_BIGMAP_ID} (mainnet)")
    print(f"Mode:          {'EXECUTE' if args.execute else 'dry run'}")
    print()

    session = requests.Session()
    print("Step 1/3: reading TXL storage...")
    rows = reconcile(session, only_token_ids=only)
    needs = sum(1 for r in rows if r.needs_update)
    missing = sum(1 for r in rows if r.current_owner is None)
    print()
    print(f"Step 2/3: diff complete. "
          f"{needs} updates needed, {missing} missing, "
          f"{len(rows) - needs - missing} already current.")

    print("Step 3/3: writing report...")
    csv_path, md_path = write_reports(rows)
    print(f"  CSV:  {csv_path}")
    print(f"  MD:   {md_path}")

    if args.execute:
        print()
        execute_updates(rows, batch_size=args.batch_size)
    else:
        print("\nDry run complete. Re-run with --execute to inject the updateOwner ops.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
