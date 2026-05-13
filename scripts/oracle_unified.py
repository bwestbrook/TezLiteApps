#!/usr/bin/env python3
"""
Unified RNG oracle daemon.

Watches the on-chain RNG oracle contract for `requested` events. For each
new request:

  1. Generates `count` cryptographically-secure random integers in [0, max).
     If noReplace=True, draws without replacement.
  2. Mixes the request's `playerNonce` (when non-empty) into a sha256-derived
     seed so the result is committable / auditable later.
  3. Submits `fulfillRandomness(tag, values, attestation)`.

Records every fulfillment in a local SQLite log so we can prove that
`H(playerNonce || oracleSecret || ... ) == values[i]` after the fact, and
so that restarts don't double-fulfill.

Required env (in .env at repo root):
  AD_NETWORK             "mainnet" | "shadownet"  (default: mainnet)
  RNG_ORACLE_ADDRESS     KT1 of the deployed RNG oracle
  ORACLE_KEY             edsk... or 24-word mnemonic

Run:
  pip3 install pytezos signalrcore python-dotenv
  python3 scripts/oracle_unified.py
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    from pytezos import pytezos
    from pytezos.crypto.key import Key
    from signalrcore.hub_connection_builder import HubConnectionBuilder
except ImportError as e:
    sys.exit(
        f"Missing dependency: {e.name}\n"
        "Install with:  pip3 install pytezos signalrcore python-dotenv"
    )


# ─── Config ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

NETWORK = os.getenv("AD_NETWORK", "mainnet")
RPC_URL = {
    "mainnet": "https://mainnet.tezos.ecadinfra.com/",
    "shadownet": "https://rpc.shadownet.teztnets.com/",
}[NETWORK]
TZKT_API = {
    "mainnet": "https://api.tzkt.io",
    "shadownet": "https://api.shadownet.tzkt.io",
}[NETWORK]

RNG_ORACLE_ADDRESS = os.getenv("RNG_ORACLE_ADDRESS")
ORACLE_KEY = os.getenv("ORACLE_KEY")
DB_PATH = ROOT / "oracle_unified.sqlite"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("rng-oracle")


def _bail(msg: str) -> None:
    log.error(msg)
    sys.exit(1)


if not RNG_ORACLE_ADDRESS:
    _bail("Set RNG_ORACLE_ADDRESS in .env (KT1 of the unified RNG oracle).")
if not ORACLE_KEY:
    _bail("Set ORACLE_KEY in .env (edsk... private key or 24-word mnemonic).")


# ─── Tezos client ────────────────────────────────────────────────────────────
def make_client():
    if ORACLE_KEY.startswith("edsk"):
        key = Key.from_encoded_key(ORACLE_KEY)
    else:
        words = ORACLE_KEY.strip().split()
        if len(words) not in (12, 15, 18, 21, 24):
            _bail(f"ORACLE_KEY mnemonic length unexpected: {len(words)}")
        key = Key.from_mnemonic(words)
    pt = pytezos.using(shell=RPC_URL, key=key)
    log.info("oracle: %s", pt.key.public_key_hash())
    log.info("rng-oracle contract: %s (%s)", RNG_ORACLE_ADDRESS, NETWORK)
    return pt


# ─── State store ─────────────────────────────────────────────────────────────
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS fulfilled (
            tag        TEXT PRIMARY KEY,
            values_csv TEXT NOT NULL,
            attestation TEXT NOT NULL,
            secret     TEXT NOT NULL,
            op_hash    TEXT,
            ts         INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
    """)
    conn.commit()
    return conn


def already_fulfilled(conn, tag):
    return conn.execute("SELECT 1 FROM fulfilled WHERE tag=? LIMIT 1", (tag,)).fetchone() is not None


def record_fulfillment(conn, tag, values, attestation, secret, op_hash):
    conn.execute(
        "INSERT OR REPLACE INTO fulfilled (tag, values_csv, attestation, secret, op_hash) VALUES (?,?,?,?,?)",
        (tag, ",".join(map(str, values)), attestation, secret.hex(), op_hash),
    )
    conn.commit()


# ─── RNG ─────────────────────────────────────────────────────────────────────
def derive_values(player_nonce: bytes, oracle_secret: bytes, tag: str,
                  max_val: int, count: int, no_replace: bool) -> list[int]:
    """Deterministic-given-(nonce, secret, tag) but unpredictable to either side
    on its own. The off-chain oracle records `oracle_secret` in SQLite so it
    can later prove `values == H(nonce || secret || tag || i) % max`."""
    out = []
    drawn = set()
    i = 0
    safety = 0
    while len(out) < count:
        seed = hashlib.sha256(
            player_nonce + oracle_secret + tag.encode() +
            i.to_bytes(8, "big")
        ).digest()
        n = int.from_bytes(seed, "big") % max_val
        if no_replace:
            if n not in drawn:
                drawn.add(n)
                out.append(n)
            i += 1
        else:
            out.append(n)
            i += 1
        safety += 1
        if safety > count * 1000:
            raise RuntimeError("RNG safety guard hit — bad params?")
    return out


def attestation_for(player_nonce: bytes, oracle_secret: bytes, tag: str) -> str:
    """Public hash recorded on chain. Verifier knows: tag, values (post-fulfill),
    player_nonce (already on chain). They DON'T see oracle_secret until the
    operator publishes the per-tag secret out of band."""
    return hashlib.sha256(
        player_nonce + oracle_secret + tag.encode()
    ).hexdigest()


# ─── Fulfillment ─────────────────────────────────────────────────────────────
def fulfill_request(pt, conn, request):
    tag = request["tag"]
    if already_fulfilled(conn, tag):
        return
    max_val = int(request["max"])
    count = int(request["count"])
    no_replace = bool(request["noReplace"])
    nonce_hex = request.get("playerNonce", "")
    pn = bytes.fromhex(nonce_hex[2:] if nonce_hex.startswith("0x") else nonce_hex) if nonce_hex else b""

    secret = secrets.token_bytes(32)
    values = derive_values(pn, secret, tag, max_val, count, no_replace)
    att = attestation_for(pn, secret, tag)

    # Build the SmartPy big_map argument: {0: v0, 1: v1, ...}
    values_map = {i: v for i, v in enumerate(values)}

    op = (pt.contract(RNG_ORACLE_ADDRESS)
          .fulfillRandomness(tag=tag, values=values_map, attestation=att)
          .as_transaction().autofill().sign().inject())
    op_hash = op["hash"] if isinstance(op, dict) else str(op)
    record_fulfillment(conn, tag, values, att, secret, op_hash)
    log.info("fulfilled tag=%s values=%s op=%s", tag, values, op_hash)


# ─── Reconciliation ──────────────────────────────────────────────────────────
def reconcile(pt, conn):
    """Walk live storage and fulfill any request that's still pending."""
    log.info("reconciling against live storage...")
    storage = pt.contract(RNG_ORACLE_ADDRESS).storage()
    requests = storage.get("requests", {}) or {}
    n = 0
    for tag, req in requests.items():
        if req.get("fulfilled"):
            continue
        if already_fulfilled(conn, tag):
            continue
        try:
            fulfill_request(pt, conn, {"tag": tag, **req})
            n += 1
        except Exception:
            log.exception("reconcile fulfill %s failed", tag)
    log.info("reconcile done — %d fulfilled.", n)


# ─── SignalR ─────────────────────────────────────────────────────────────────
def make_signalr(pt, conn):
    hub = (
        HubConnectionBuilder()
        .with_url(f"{TZKT_API}/v1/ws")
        .with_automatic_reconnect({"type": "raw", "keep_alive_interval": 10, "reconnect_interval": 5})
        .build()
    )

    def on_open():
        log.info("SignalR connected to %s", TZKT_API)
        hub.send("SubscribeToOperations", [{"address": RNG_ORACLE_ADDRESS, "types": "transaction"}])

    def on_close():
        log.warning("SignalR disconnected")

    def on_operations(args):
        try:
            ops = args[0].get("data", [])
        except Exception:
            return
        for op in ops:
            params = op.get("parameter") or {}
            if params.get("entrypoint") != "requestRandomness":
                continue
            value = params.get("value", {}) or {}
            tag = value.get("tag")
            if not tag:
                continue
            # Pull the canonical record from storage so we agree on every field.
            try:
                req = pt.contract(RNG_ORACLE_ADDRESS).storage()["requests"][tag]
            except Exception:
                log.exception("storage read for tag %s failed", tag)
                continue
            try:
                fulfill_request(pt, conn, {"tag": tag, **req})
            except Exception:
                log.exception("fulfill failed for tag %s", tag)

    hub.on_open(on_open)
    hub.on_close(on_close)
    hub.on("operations", on_operations)
    return hub


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    pt = make_client()
    conn = db()
    reconcile(pt, conn)
    hub = make_signalr(pt, conn)
    hub.start()
    log.info("Unified RNG oracle running. Ctrl-C to exit.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("shutting down.")
    finally:
        try:
            hub.stop()
        except Exception:
            pass
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
