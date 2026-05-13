#!/usr/bin/env python3
"""TezLiteApps — Blockchain timing harness.

Measures four kinds of latency against the live shadownet (or mainnet)
deployment, so you can answer "how long does X take" with real data.

Phases (toggle with --phase, default = all):
    orig         Origination latency. Re-deploys the chosen contract from
                 contracts/<id>/ and times build → sign → inject → confirm.
                 Costs gas. Skipped by default unless --include-orig.
    entrypoint   Round-trip per entrypoint: .send() → injected → confirmed.
                 Runs a small set of representative calls.
    oracle       End-to-end oracle latency: dt from bet → contract storage
                 reflects the oracle's resolve(...). Polls every poll-step.
    chain        Cross-contract op tracing. For each AD/Plinko bet, walks
                 the tzkt op tree to find the resulting TXL fee transfer
                 and reports inter-op latency (usually 0 — same block).

Output:
    perf_timings_<network>_<utc>.csv    detailed per-iteration rows
    Console summary table (mean / p50 / p95 per phase + entrypoint)

Examples:
    .venv/bin/python scripts/perf_timings.py
    .venv/bin/python scripts/perf_timings.py --phase entrypoint --iters 10
    .venv/bin/python scripts/perf_timings.py --phase oracle --iters 5
    .venv/bin/python scripts/perf_timings.py --include-orig --phase orig --contract plinko
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.js"

RPC = {
    "shadownet": "https://rpc.shadownet.teztnets.com",
    "mainnet":   "https://mainnet.tezos.ecadinfra.com",
}
TZKT_API = {
    "shadownet": "https://api.shadownet.tzkt.io/v1",
    "mainnet":   "https://api.tzkt.io/v1",
}

# ─── output helpers ──────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fmt_ms(s: float | None) -> str:
    return f"{s*1000:.0f}ms" if s is not None else "—"


# ─── constants.js parsing ────────────────────────────────────────────────
def lookup_address(var_name: str) -> str | None:
    """Read a CONTRACT_ADDRESS_* export out of src/constants.js."""
    text = CONSTANTS_PATH.read_text()
    m = re.search(rf"{var_name}\s*=\s*'([^']+)'", text)
    if not m:
        return None
    addr = m.group(1)
    if addr.startswith("KT1XXXX"):
        return None
    return addr


# ─── tzkt client (no auth, public) ───────────────────────────────────────
class TzKT:
    def __init__(self, network: str):
        self.base = TZKT_API[network]

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base}{path}"
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            url = f"{url}?{qs}"
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())

    def op_by_hash(self, op_hash: str) -> list[dict[str, Any]]:
        """Return every operation row tzkt knows for this hash. Multi-op
        originations or internal calls produce multiple rows."""
        return self._get(f"/operations/{op_hash}")

    def transactions_to(self, address: str, since_id: int | None = None,
                        limit: int = 100) -> list[dict[str, Any]]:
        params = {"target": address, "limit": limit, "sort.desc": "id"}
        if since_id:
            params["id.gt"] = since_id
        return self._get("/operations/transactions", params)


# ─── timing record schema ────────────────────────────────────────────────
@dataclass
class TimingRow:
    phase: str
    contract: str
    entrypoint: str
    iter: int
    t_send_ms: float | None = None        # wall time to inject (returns op hash)
    t_confirm_ms: float | None = None     # additional time to first confirm
    t_total_ms: float | None = None       # send + confirm
    block_height: int | None = None
    op_hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    error: str = ""


# ─── ORIG phase ──────────────────────────────────────────────────────────
def measure_origination(network: str, contract_id: str,
                        rows: list[TimingRow]) -> None:
    """Originate the chosen contract from committed artifacts. Times every
    sub-phase. Costs real testnet gas, so off by default."""
    from pytezos import pytezos  # noqa: F401 (lazy import)
    # Delegate the work to deploy.py — re-using the audited path means we
    # measure the same code the user actually runs.
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from deploy import (
        CONTRACTS, find_artifacts, load_dotenv, load_key, ensure_revealed,
        originate, extract_originated_address,
    )
    load_dotenv()
    spec = CONTRACTS[contract_id]
    canonical_dir = PROJECT_ROOT / "contracts" / contract_id
    if not canonical_dir.exists():
        rows.append(TimingRow(
            phase="orig", contract=contract_id, entrypoint="originate",
            iter=0, error=f"No artifacts at {canonical_dir}",
        ))
        return
    code_tz, storage_tz = find_artifacts(canonical_dir)
    client = pytezos_using(network, load_key(None))
    t0 = time.perf_counter()
    ensure_revealed(client)
    t_reveal = time.perf_counter() - t0
    t1 = time.perf_counter()
    address = originate(client, code_tz, storage_tz, spec)
    t_total = time.perf_counter() - t1
    rows.append(TimingRow(
        phase="orig",
        contract=contract_id,
        entrypoint="originate",
        iter=0,
        t_send_ms=None,
        t_confirm_ms=None,
        t_total_ms=t_total * 1000,
        extra={"reveal_ms": round(t_reveal * 1000), "new_address": address},
    ))


def pytezos_using(network: str, key):
    from pytezos import pytezos
    return pytezos.using(shell=RPC[network], key=key)


# ─── ENTRYPOINT phase ────────────────────────────────────────────────────
def measure_entrypoints(network: str, iters: int,
                        rows: list[TimingRow]) -> None:
    """Hit a representative entrypoint set on each live contract. We try
    cheap, idempotent calls only — no destructive state changes."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from deploy import load_dotenv, load_key, ensure_revealed
    load_dotenv()
    client = pytezos_using(network, load_key(None))
    ensure_revealed(client)

    # Each tuple: (contract_id, address, entrypoint, args_factory) — the
    # factory returns a kwargs dict and the amount in mutez.
    ad = lookup_address("AD_CONTRACT_ADDRESS_SHADOWNET" if network == "shadownet"
                        else "AD_CONTRACT_ADDRESS_MAINNET")
    plinko = lookup_address("PLINKO_CONTRACT_ADDRESS_SHADOWNET" if network == "shadownet"
                            else "PLINKO_CONTRACT_ADDRESS_MAINNET")
    targets = []
    if ad:
        targets.append(("acey-duecey", ad, "default",
                        lambda i: ({}, 1)))  # 1 µꜩ to default = no-op top-up
    if plinko:
        targets.append(("plinko", plinko, "default",
                        lambda i: ({}, 1)))

    if not targets:
        log("No live contract addresses found. Deploy first, then re-run.")
        return

    for cid, addr, entry, factory in targets:
        for i in range(iters):
            kwargs, amount = factory(i)
            t_row = TimingRow(
                phase="entrypoint", contract=cid, entrypoint=entry, iter=i,
            )
            try:
                contract = client.contract(addr)
                method = getattr(contract, entry)
                call = method(**kwargs) if kwargs else method()
                t0 = time.perf_counter()
                op = call.with_amount(amount).send(min_confirmations=0)
                t_row.t_send_ms = (time.perf_counter() - t0) * 1000
                t_row.op_hash = op.hash()
                # Wait for one confirmation, time separately
                t1 = time.perf_counter()
                op.wait_for_confirmation(num_blocks=1)
                t_row.t_confirm_ms = (time.perf_counter() - t1) * 1000
                t_row.t_total_ms = t_row.t_send_ms + t_row.t_confirm_ms
            except Exception as e:
                t_row.error = str(e)[:200]
            rows.append(t_row)
            log(f"  [entrypoint {cid}.{entry} #{i}] "
                f"send={fmt_ms(t_row.t_send_ms and t_row.t_send_ms/1000)}, "
                f"confirm={fmt_ms(t_row.t_confirm_ms and t_row.t_confirm_ms/1000)}")


# ─── ORACLE phase ────────────────────────────────────────────────────────
def measure_oracle_cadence(network: str, iters: int, poll_step: float,
                           rows: list[TimingRow]) -> None:
    """Place an AD bet, poll storage every poll_step seconds, record dt
    until status[gameId] flips from 0 → 1. Assumes the oracle worker is
    running (./scripts/oracle-worker.sh). If not, this will hang."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from deploy import load_dotenv, load_key, ensure_revealed
    load_dotenv()
    client = pytezos_using(network, load_key(None))
    ensure_revealed(client)

    ad = lookup_address("AD_CONTRACT_ADDRESS_SHADOWNET" if network == "shadownet"
                        else "AD_CONTRACT_ADDRESS_MAINNET")
    if not ad:
        log("Skipping oracle phase: no AD contract address.")
        return

    for i in range(iters):
        t_row = TimingRow(
            phase="oracle", contract="acey-duecey", entrypoint="bet→firstCard",
            iter=i,
        )
        try:
            contract = client.contract(ad)
            t0 = time.perf_counter()
            op = contract.bet(1).with_amount(300000).send(min_confirmations=1)
            t_row.t_send_ms = (time.perf_counter() - t0) * 1000
            t_row.op_hash = op.hash()
            # Read storage to find our new gameId
            storage_after = contract.storage()
            current_idx = int(storage_after["currentGameIndex"])
            game_id = current_idx - 1
            t_row.extra["gameId"] = game_id
            # Poll until status != 0
            t1 = time.perf_counter()
            timeout = 120.0
            status = 0
            while time.perf_counter() - t1 < timeout:
                time.sleep(poll_step)
                games = contract.storage()["games"]
                g = games.get(game_id)
                if not g:
                    continue
                status = int(g.get("gameStatus", 0))
                if status != 0:
                    break
            t_row.t_confirm_ms = (time.perf_counter() - t1) * 1000
            t_row.t_total_ms = t_row.t_send_ms + t_row.t_confirm_ms
            t_row.extra["resolved_status"] = status
        except Exception as e:
            t_row.error = str(e)[:200]
        rows.append(t_row)
        log(f"  [oracle bet #{i}] "
            f"bet={fmt_ms(t_row.t_send_ms and t_row.t_send_ms/1000)}, "
            f"oracle_lag={fmt_ms(t_row.t_confirm_ms and t_row.t_confirm_ms/1000)}")


# ─── CHAIN phase ─────────────────────────────────────────────────────────
def measure_chain_propagation(network: str, iters: int,
                              rows: list[TimingRow]) -> None:
    """For each AD `bet` and Plinko `play`, find the resulting TXL fee
    transaction in the same block and report inter-op latency. tzkt
    exposes operation siblings via parent-child links."""
    ad = lookup_address("AD_CONTRACT_ADDRESS_SHADOWNET" if network == "shadownet"
                        else "AD_CONTRACT_ADDRESS_MAINNET")
    plinko = lookup_address("PLINKO_CONTRACT_ADDRESS_SHADOWNET" if network == "shadownet"
                            else "PLINKO_CONTRACT_ADDRESS_MAINNET")
    txl = lookup_address("TXL_CONTRACT_ADDRESS_SHADOWNET" if network == "shadownet"
                         else "TXL_CONTRACT_ADDRESS_MAINNET")
    tzkt = TzKT(network)

    def trace(source_contract: str, target: str):
        if not source_contract or not txl:
            return
        # Last N transactions targeting source_contract.
        txs = tzkt.transactions_to(source_contract, limit=iters * 2)
        used = 0
        for tx in txs:
            if used >= iters:
                break
            op_hash = tx.get("hash")
            if not op_hash:
                continue
            ops = tzkt.op_by_hash(op_hash)
            # Find sibling targeting TXL.
            fee_op = next((o for o in ops if o.get("target", {}).get("address") == txl), None)
            t_row = TimingRow(
                phase="chain",
                contract=target,
                entrypoint=tx.get("parameter", {}).get("entrypoint", "?")
                              if isinstance(tx.get("parameter"), dict) else "?",
                iter=used,
                op_hash=op_hash,
                block_height=tx.get("level"),
            )
            if fee_op:
                # Inter-op latency on Tezos is structurally 0 (same block),
                # so we report block-level packing: 0 if same block, else
                # block delta * ~30s.
                same_block = fee_op.get("level") == tx.get("level")
                t_row.extra = {
                    "txl_fee_amount": fee_op.get("amount"),
                    "same_block": same_block,
                    "block_delta": (fee_op.get("level") - tx.get("level"))
                                   if not same_block else 0,
                }
                t_row.t_total_ms = 0 if same_block else 30000
            else:
                t_row.extra = {"note": "no TXL sibling op (entrypoint may not transfer fee)"}
            rows.append(t_row)
            used += 1

    if ad:
        trace(ad, "acey-duecey → txl")
    if plinko:
        trace(plinko, "plinko → txl")


# ─── summary printing ────────────────────────────────────────────────────
def percentile(values: list[float], q: float) -> float:
    if not values: return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * q
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def summarize(rows: list[TimingRow]) -> None:
    if not rows:
        log("No rows recorded.")
        return
    # Group by (phase, contract, entrypoint)
    groups: dict[tuple[str, str, str], list[float]] = {}
    for r in rows:
        if r.t_total_ms is None:
            continue
        groups.setdefault((r.phase, r.contract, r.entrypoint), []).append(r.t_total_ms)
    cols = ["phase", "contract", "entrypoint", "n", "mean (ms)",
            "p50 (ms)", "p95 (ms)", "min", "max"]
    widths = [12, 22, 18, 4, 12, 12, 12, 10, 10]
    log("")
    log("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    log("  ".join("-" * w for w in widths))
    for (phase, contract, entry), vals in sorted(groups.items()):
        row = [
            phase, contract, entry,
            str(len(vals)),
            f"{statistics.mean(vals):.0f}",
            f"{percentile(vals, 0.5):.0f}",
            f"{percentile(vals, 0.95):.0f}",
            f"{min(vals):.0f}",
            f"{max(vals):.0f}",
        ]
        log("  ".join(c.ljust(w) for c, w in zip(row, widths)))
    log("")
    errs = [r for r in rows if r.error]
    if errs:
        log(f"Errors encountered: {len(errs)}")
        for r in errs[:5]:
            log(f"  • {r.phase}/{r.contract}/{r.entrypoint} #{r.iter}: {r.error[:120]}")


def write_csv(rows: list[TimingRow], out: Path) -> None:
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "phase", "contract", "entrypoint", "iter",
            "t_send_ms", "t_confirm_ms", "t_total_ms",
            "block_height", "op_hash", "extra", "error",
        ])
        for r in rows:
            w.writerow([
                r.phase, r.contract, r.entrypoint, r.iter,
                r.t_send_ms, r.t_confirm_ms, r.t_total_ms,
                r.block_height, r.op_hash,
                json.dumps(r.extra) if r.extra else "",
                r.error,
            ])
    log(f"Wrote {len(rows)} rows → {out.relative_to(PROJECT_ROOT)}")


# ─── main ────────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--network", default="shadownet", choices=["shadownet", "mainnet"])
    p.add_argument("--phase", action="append",
                   choices=["orig", "entrypoint", "oracle", "chain"],
                   help="Repeat to enable multiple phases. Default: all except orig.")
    p.add_argument("--iters", type=int, default=5,
                   help="Iterations per phase/contract pair (default: 5).")
    p.add_argument("--poll-step", type=float, default=1.0,
                   help="Seconds between oracle-phase storage polls.")
    p.add_argument("--include-orig", action="store_true",
                   help="Allow the destructive orig phase (re-originates).")
    p.add_argument("--contract", default="plinko",
                   help="Contract to re-originate during --phase orig.")
    p.add_argument("--out", type=Path, default=None,
                   help="CSV output path. Default: perf_timings_<net>_<utc>.csv")
    args = p.parse_args()

    phases = args.phase or ["entrypoint", "oracle", "chain"]
    if "orig" in phases and not args.include_orig:
        log("Refusing to run --phase orig without --include-orig "
            "(it costs real gas).")
        phases = [p for p in phases if p != "orig"]
        if not phases:
            return 1

    log(f"Network:    {args.network}")
    log(f"Phases:     {', '.join(phases)}")
    log(f"Iterations: {args.iters}")

    rows: list[TimingRow] = []
    if "orig" in phases:
        log("\n─── ORIGINATION ───")
        measure_origination(args.network, args.contract, rows)
    if "entrypoint" in phases:
        log("\n─── ENTRYPOINT ROUND-TRIP ───")
        measure_entrypoints(args.network, args.iters, rows)
    if "oracle" in phases:
        log("\n─── ORACLE CADENCE ───")
        measure_oracle_cadence(args.network, args.iters, args.poll_step, rows)
    if "chain" in phases:
        log("\n─── CROSS-CONTRACT CHAIN ───")
        measure_chain_propagation(args.network, args.iters, rows)

    log("\n─── SUMMARY ───")
    summarize(rows)

    out = args.out or (PROJECT_ROOT / f"perf_timings_{args.network}_"
                       f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv")
    write_csv(rows, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
