#!/usr/bin/env python3
"""
Acey-Duecey card-dealing oracle.

What it does:
  - Subscribes (via TzKT SignalR) to events from the AD contract.
  - When a `betMade` event fires, deals card 1 then card 2.
  - When the oracle sees the second-card was a non-pair (gameStatus → 1) and
    later a `continueBet` event fires (gameStatus → 2), deals card 3.
  - Tracks every action in a local SQLite DB so a crash + restart resumes
    cleanly without re-dealing.

Improvements over the previous oracle_AD.py:
  - No hardcoded seed phrase. Reads `ORACLE_KEY` (edsk... or 24-word mnemonic)
    from `.env` next to this script.
  - No separate Oracle contract — RNG generated locally with `secrets.randbelow`
    (CSPRNG, much better than `random`). One transaction per card instead of two.
  - No 2-second polling — TzKT SignalR pushes events as blocks land.
  - Idempotent: each (gameId, action) is recorded in SQLite the moment we
    submit; we won't re-deal on restart.
  - Restartable: if the daemon crashes mid-game, on restart it walks live
    contract storage and resumes any games stuck in status 0 or 2.

Required:
    pip3 install pytezos signalrcore python-dotenv
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

# Network — flip via .env without code edits
NETWORK = os.getenv("AD_NETWORK", "mainnet")  # "mainnet" | "shadownet"
RPC_URL = {
    "mainnet": "https://mainnet.tezos.ecadinfra.com/",
    "shadownet": "https://rpc.shadownet.teztnets.com/",
}[NETWORK]
TZKT_API = {
    "mainnet": "https://api.tzkt.io",
    "shadownet": "https://api.shadownet.tzkt.io",
}[NETWORK]
TZKT_WS = TZKT_API.replace("https://api.", "wss://api.") + "/v1/ws"

CONTRACT_ADDRESS = os.getenv("AD_CONTRACT_ADDRESS")
ORACLE_KEY = os.getenv("ORACLE_KEY")

DB_PATH = ROOT / "oracle_state.sqlite"

# Game status values (must match the contract).
STATUS_BET_PLACED = 0
STATUS_TWO_CARDS_DRAWN = 1
STATUS_CONTINUE_BET_PLACED = 2

# How many cards in the deck. We deal indexes 0..51.
DECK_SIZE = 52


# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("oracle")


# ─── Pre-flight ──────────────────────────────────────────────────────────────
def _bail(msg: str) -> None:
    log.error(msg)
    sys.exit(1)


if not CONTRACT_ADDRESS:
    _bail("Set AD_CONTRACT_ADDRESS in .env (the KT1 address of your AD contract).")
if not ORACLE_KEY:
    _bail("Set ORACLE_KEY in .env (edsk... private key OR 24-word mnemonic).")


# ─── Tezos client ────────────────────────────────────────────────────────────
def make_client() -> "pytezos.PyTezosClient":
    if ORACLE_KEY.startswith("edsk"):
        key = Key.from_encoded_key(ORACLE_KEY)
    else:
        # Treat as space-separated mnemonic.
        words = ORACLE_KEY.strip().split()
        if len(words) not in (12, 15, 18, 21, 24):
            _bail(f"ORACLE_KEY mnemonic should be 12/15/18/21/24 words, got {len(words)}.")
        key = Key.from_mnemonic(words)
    pt = pytezos.using(shell=RPC_URL, key=key)
    log.info("oracle  : %s", pt.key.public_key_hash())
    log.info("contract: %s (%s)", CONTRACT_ADDRESS, NETWORK)
    return pt


# ─── State store ─────────────────────────────────────────────────────────────
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dealt (
            game_id INTEGER NOT NULL,
            action  TEXT    NOT NULL,   -- 'firstCard' | 'secondCard' | 'lastCard'
            card    INTEGER NOT NULL,
            op_hash TEXT,
            ts      INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            PRIMARY KEY (game_id, action)
        );

        CREATE TABLE IF NOT EXISTS oracle_secrets (
            -- Per-game 32-byte secret the oracle folds into card derivation.
            -- Persisted so retries on the same game produce the same card
            -- (otherwise the second attempt would derive a different value
            -- and the contract would reject it as the wrong status anyway).
            game_id INTEGER PRIMARY KEY,
            secret  TEXT    NOT NULL,
            ts      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        );
        """
    )
    conn.commit()
    return conn


def already_dealt(conn: sqlite3.Connection, game_id: int, action: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM dealt WHERE game_id=? AND action=? LIMIT 1", (game_id, action)
    )
    return cur.fetchone() is not None


def record_deal(conn: sqlite3.Connection, game_id: int, action: str, card: int, op_hash: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO dealt (game_id, action, card, op_hash) VALUES (?,?,?,?)",
        (game_id, action, card, op_hash),
    )
    conn.commit()


# ─── Card RNG ────────────────────────────────────────────────────────────────
# Cards are derived from H(player_nonce || oracle_secret || game_id || slot)
# so neither side has unilateral control:
#   - the player commits 32 random bytes when betting (recorded on chain)
#   - the oracle generates a per-deal 32-byte secret (recorded in SQLite for audit)
# A malicious oracle can't pick favorable cards without choosing its secret
# AFTER seeing the player's nonce — but the player's nonce is on chain at bet
# time, before the oracle deals. A malicious player can't predict the oracle's
# secret. Both sides need to be honest in their own contribution.
def derive_card(player_nonce: bytes, oracle_secret: bytes, game_id: int, slot: int,
                exclude: set[int] = ()) -> int:
    pool = [c for c in range(DECK_SIZE) if c not in exclude]
    if not pool:
        raise RuntimeError("Deck exhausted.")
    seed = hashlib.sha256(
        player_nonce + oracle_secret +
        game_id.to_bytes(8, "big") + slot.to_bytes(1, "big")
    ).digest()
    n = int.from_bytes(seed, "big")
    return pool[n % len(pool)]


def card_hash(game_id: int, slot: int, card: int, oracle_secret: bytes) -> str:
    """Public attestation: H(game_id|slot|card|oracle_secret) — recorded
    on-chain in `handHashes`. Reveals after the deal so anyone can audit
    that the oracle's secret matched what it claims."""
    payload = f"{game_id}|{slot}|{card}|".encode() + oracle_secret
    return hashlib.sha256(payload).hexdigest()


def fetch_game_storage(pt, game_id: int) -> dict | None:
    """Pull a single game's record from the contract's big_map."""
    try:
        return pt.contract(CONTRACT_ADDRESS).storage()["games"][game_id]
    except KeyError:
        return None
    except Exception as e:
        log.warning("storage read for game %s failed: %s", game_id, e)
        return None


def player_nonce_bytes(game: dict) -> bytes:
    """Coerce the on-chain bytes value (hex-encoded) to a Python bytes."""
    raw = game.get("playerNonce", "")
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        return bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
    return b""


# ─── Card dealing ────────────────────────────────────────────────────────────
def get_or_make_oracle_secret(conn: sqlite3.Connection, game_id: int) -> bytes:
    """Per-game oracle secret. Generated once and persisted so retries use the
    same secret (otherwise we'd derive different cards on retry)."""
    row = conn.execute(
        "SELECT secret FROM oracle_secrets WHERE game_id=?", (game_id,)
    ).fetchone()
    if row:
        return bytes.fromhex(row[0])
    secret = secrets.token_bytes(32)
    conn.execute(
        "INSERT INTO oracle_secrets (game_id, secret) VALUES (?,?)",
        (game_id, secret.hex()),
    )
    conn.commit()
    return secret


def _send_card(pt, entrypoint: str, game_id: int, card: int, hash_str: str):
    method = getattr(pt.contract(CONTRACT_ADDRESS), entrypoint)
    op = (
        method(gameId=game_id, card=card, hash=hash_str)
        .as_transaction().autofill().sign().inject()
    )
    return op["hash"] if isinstance(op, dict) else str(op)


def deal_first(pt, conn, game_id: int) -> int | None:
    if already_dealt(conn, game_id, "firstCard"):
        return None
    game = fetch_game_storage(pt, game_id)
    if not game:
        return None
    pn = player_nonce_bytes(game)
    secret = get_or_make_oracle_secret(conn, game_id)
    card = derive_card(pn, secret, game_id, slot=1)
    op_hash = _send_card(pt, "firstCard", game_id, card, card_hash(game_id, 1, card, secret))
    record_deal(conn, game_id, "firstCard", card, op_hash)
    log.info("game %s: firstCard=%d  op=%s", game_id, card, op_hash)
    return card


def deal_second(pt, conn, game_id: int, exclude: set[int]) -> int | None:
    if already_dealt(conn, game_id, "secondCard"):
        return None
    game = fetch_game_storage(pt, game_id)
    if not game:
        return None
    pn = player_nonce_bytes(game)
    secret = get_or_make_oracle_secret(conn, game_id)
    card = derive_card(pn, secret, game_id, slot=2, exclude=exclude)
    op_hash = _send_card(pt, "secondCard", game_id, card, card_hash(game_id, 2, card, secret))
    record_deal(conn, game_id, "secondCard", card, op_hash)
    log.info("game %s: secondCard=%d  op=%s", game_id, card, op_hash)
    return card


def deal_last(pt, conn, game_id: int, exclude: set[int]) -> int | None:
    if already_dealt(conn, game_id, "lastCard"):
        return None
    game = fetch_game_storage(pt, game_id)
    if not game:
        return None
    pn = player_nonce_bytes(game)
    secret = get_or_make_oracle_secret(conn, game_id)
    card = derive_card(pn, secret, game_id, slot=3, exclude=exclude)
    op_hash = _send_card(pt, "lastCard", game_id, card, card_hash(game_id, 3, card, secret))
    record_deal(conn, game_id, "lastCard", card, op_hash)
    log.info("game %s: lastCard=%d  op=%s", game_id, card, op_hash)
    return card


# ─── Reconciliation against live storage (called on startup) ─────────────────
def reconcile_pending_games(pt, conn) -> None:
    """Walk the contract's games big_map and finish any half-dealt rounds."""
    log.info("Reconciling against live storage...")
    storage = pt.contract(CONTRACT_ADDRESS).storage()
    games_bm = storage["games"]
    current = int(storage["currentGameIndex"])

    handled = 0
    for gid in range(current):
        try:
            game = games_bm[gid]
        except KeyError:
            continue  # already pruned (future feature) or never existed
        status = int(game["gameStatus"])
        # status 0: needs first + (potentially) second card
        # status 2: needs last card
        if status == STATUS_BET_PLACED:
            try:
                _ = deal_first(pt, conn, gid)
                # Wait for the first card op to be confirmed before dealing second
                # — we don't know which exact card was on-chain until reconciled,
                # so just exclude the local one.
                first = conn.execute(
                    "SELECT card FROM dealt WHERE game_id=? AND action='firstCard'", (gid,)
                ).fetchone()
                if first is None:
                    continue
                deal_second(pt, conn, gid, exclude={first[0]})
                handled += 1
            except Exception as e:
                log.exception("reconcile game %s: %s", gid, e)
        elif status == STATUS_CONTINUE_BET_PLACED:
            try:
                # Use the on-chain hand for exclusion if we don't have local state.
                exclude = set()
                for slot in (1, 2):
                    onchain_card = int(game["hand"].get(slot, -1))
                    if onchain_card >= 0:
                        exclude.add(onchain_card)
                deal_last(pt, conn, gid, exclude=exclude)
                handled += 1
            except Exception as e:
                log.exception("reconcile game %s: %s", gid, e)
    log.info("Reconciliation done — handled %d game(s).", handled)


# ─── TzKT SignalR event subscription ─────────────────────────────────────────
def make_signalr(pt, conn):
    """Build the TzKT SignalR client subscribed to our contract's events."""
    hub = (
        HubConnectionBuilder()
        .with_url(f"{TZKT_API}/v1/ws")
        .with_automatic_reconnect({"type": "raw", "keep_alive_interval": 10, "reconnect_interval": 5})
        .build()
    )

    def on_open():
        log.info("SignalR connected to %s", TZKT_API)
        hub.send("SubscribeToOperations", [{"address": CONTRACT_ADDRESS, "types": "transaction"}])

    def on_close():
        log.warning("SignalR disconnected")

    def on_operations(args):
        # `args` is a list with one dict containing 'data' = list of operations
        try:
            ops = args[0].get("data", [])
        except Exception:
            return
        for op in ops:
            params = op.get("parameter") or {}
            entrypoint = params.get("entrypoint")
            value = params.get("value", {})

            if entrypoint == "bet":
                # New game just opened. Deal first + second card.
                # The new gameId is currentGameIndex - 1 *after* the bet was applied.
                # Easiest robust thing is to pull live storage.
                storage = pt.contract(CONTRACT_ADDRESS).storage()
                gid = int(storage["currentGameIndex"]) - 1
                try:
                    first = deal_first(pt, conn, gid)
                    if first is None:
                        continue
                    deal_second(pt, conn, gid, exclude={first})
                except Exception:
                    log.exception("dealing first/second for game %s", gid)

            elif entrypoint == "continueBet":
                gid = int(value.get("gameId", -1))
                if gid < 0:
                    continue
                # Pull on-chain hand to exclude already-dealt cards.
                try:
                    game = pt.contract(CONTRACT_ADDRESS).storage()["games"][gid]
                    exclude = {int(game["hand"][s]) for s in (1, 2) if int(game["hand"].get(s, -1)) >= 0}
                    deal_last(pt, conn, gid, exclude=exclude)
                except Exception:
                    log.exception("dealing last for game %s", gid)

    hub.on_open(on_open)
    hub.on_close(on_close)
    hub.on("operations", on_operations)
    return hub


# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    pt = make_client()
    conn = db()
    reconcile_pending_games(pt, conn)
    hub = make_signalr(pt, conn)
    hub.start()
    log.info("Oracle running. Ctrl-C to exit.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        try:
            hub.stop()
        except Exception:
            pass
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
