#!/usr/bin/env python3
"""
oracle_worker.py — off-chain oracle daemon for TezLiteApps games.

Supports multiple games behind one process. Pick which to run with
`--game`:

    --game acey-duecey   only AD (deals cards)
    --game plinko        only Plinko (resolves drops)
    --game all           both (default)

For Acey-Duecey
---------------
Polls AD's on-chain storage every few seconds. For each game it finds:

  status == 0  AND  hand[1] == -1                 → call firstCard
  status == 0  AND  hand[1] >= 0 AND hand[2] == -1 → call secondCard
  status == 2  (player has placed continueBet)    → call lastCard

Each call picks a uniform-random deck index 0..51 and tags it with a hex
hash so the operation is traceable.

For Plinko
----------
Polls Plinko's on-chain storage. For each round it finds:

  roundStatus == 0 (pending)  → call resolve(roundId, slot, seed)

The slot is drawn from a true binomial distribution (sum of N independent
50/50 coin flips for an N-row board), so the on-chain landing matches
real Plinko physics — center slots are exponentially more likely than
edges, mirroring Pascal's triangle. The UI's `animateBall()` then draws
a plausible left/right path to land on that slot. The seed is a hex
token committed on chain so the result is auditable.

Why this exists
---------------
Both contracts trust a single tz1 address (`storage.oracle`) to advance
state. The dApp UI exposes manual buttons for that role during dev, but
in production you want a daemon doing it in seconds, not a human. The
worker reads the oracle key once at startup and bails if our key
doesn't match the on-chain `oracle` for any selected game.

Design notes
------------
- *Stateless across runs.* All decisions come from re-reading on-chain
  storage. Restart anytime — the worker picks up wherever the chain
  left off. No local DB, no journal.
- *Single-threaded.* Tezos rejects a second op from the same address
  while one is in the mempool, so we use sequential
  `.send(min_confirmations=1)`. With shadownet's ~15s block time that
  means at most ~4 actions per minute per worker. Plenty.
- *One action per game per cycle.* Keeps ops serial per contract and
  lets the next poll see the chain-of-effects from this one.
- *Reads contract addresses from constants.js* so the worker always
  matches whatever the dApp is pointing at (no two-places-to-update).

Usage
-----
    ./scripts/oracle-worker.sh                      # runs both games forever
    ./scripts/oracle-worker.sh --game plinko        # only Plinko
    ./scripts/oracle-worker.sh --game acey-duecey   # only AD
    ./scripts/oracle-worker.sh --once               # one poll cycle then exit
    ./scripts/oracle-worker.sh --poll 3             # 3-second poll interval
    ./scripts/oracle-worker.sh --dry-run            # log decisions, don't sign

    # Override the contract address (only valid with a single --game):
    ./scripts/oracle-worker.sh --game plinko --address KT1...

Authentication: same as deploy.py — DEPLOY_MNEMONIC in .env. The wallet
that mnemonic derives must be the one set as storage.oracle for every
selected game, otherwise every call will fail.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# ─── Project paths ────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
# Make sibling scripts importable (sports_api lives next to this file).
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
ENV_PATH = PROJECT_ROOT / ".env"
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.js"

NETWORK_RPCS = {
    "shadownet": "https://rpc.shadownet.teztnets.com",
    "mainnet":   "https://mainnet.tezos.ecadinfra.com",
}
TZKT_HOSTS = {
    "shadownet": "shadownet.tzkt.io",
    "mainnet":   "tzkt.io",
}

# ─── tiny ANSI logger ────────────────────────────────────────────────
RESET, GREEN, YELLOW, RED, CYAN, DIM = (
    "\033[0m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[2m",
)
def log(msg):   print(f"{DIM}[{time.strftime('%H:%M:%S')}]{RESET} {msg}", flush=True)
def ok(msg):    log(f"{GREEN}✓{RESET} {msg}")
def warn(msg):  log(f"{YELLOW}!{RESET} {msg}")
def err(msg):   log(f"{RED}✗{RESET} {msg}")
def info(msg):  log(f"  {msg}")
def section(t): print(); print(f"{CYAN}─── {t} ───{RESET}", flush=True)


# ─── .env loader ──────────────────────────────────────────────────────
def load_dotenv() -> None:
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


# ─── constants.js reader ──────────────────────────────────────────────
def read_constant(name: str) -> str | None:
    """Return the string literal for `export const <name> = '...'` or None."""
    if not CONSTANTS_PATH.exists():
        return None
    m = re.search(
        rf"export const {re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]",
        CONSTANTS_PATH.read_text(),
    )
    return m.group(1) if m else None


# ─── Storage helpers ──────────────────────────────────────────────────
def _field(record: Any, name: str, default: Any) -> Any:
    """tzkt/pytezos sometimes returns records as dicts, sometimes as
    objects with attributes. Read either way."""
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


# ═══════════════════════════════════════════════════════════════════════
# AD — Acey-Duecey decision logic (pure, easy to unit-test)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ADAction:
    entrypoint: str          # 'firstCard' | 'secondCard' | 'lastCard'
    game_id: int             # contract's monotonic gameId
    card: int                # random deck index 0..51
    hash: str                # tag string for traceability

def next_action_for_game(game_id: int, game: dict) -> ADAction | None:
    """Inspect one AD game record and decide whether the oracle should
    act. Returns an ADAction to submit, or None if the game doesn't
    need help right now (already advanced, or finished).

    `game` is the dict tzkt/pytezos returns for storage.games[gid].
    Card slots live under `hand` as a map keyed by 1/2/3. tzkt returns
    int values as strings, so coerce."""
    def slot(key: int) -> int:
        h = _field(game, "hand", {}) or {}
        raw = h.get(key, h.get(str(key), -1)) if isinstance(h, dict) else -1
        try:
            return int(raw)
        except (TypeError, ValueError):
            return -1

    status = int(_field(game, "gameStatus", 0))
    h1 = slot(1)
    h2 = slot(2)

    if status == 0 and h1 == -1:
        return _build_ad_action("firstCard", game_id)
    if status == 0 and h1 >= 0 and h2 == -1:
        return _build_ad_action("secondCard", game_id)
    if status == 2:
        return _build_ad_action("lastCard", game_id)

    # status 1 (awaiting player's continueBet) — not our problem.
    # status 3 / 4 / 5 — finished. Ignore.
    return None


def _build_ad_action(entrypoint: str, game_id: int) -> ADAction:
    """Pick a random card + a unique tag for traceability."""
    card = secrets.randbelow(52)
    hash_tag = f"{entrypoint}-{secrets.token_hex(6)}"
    return ADAction(entrypoint=entrypoint, game_id=int(game_id), card=card, hash=hash_tag)


# ═══════════════════════════════════════════════════════════════════════
# Plinko — drop resolution logic (pure)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class PlinkoAction:
    round_id: int
    rows: int
    x_bits: dict[int, int]   # per-layer 0/1 deflections on the X axis
    z_bits: dict[int, int]   # per-layer 0/1 deflections on the Z axis
    final_x: int             # = sum(x_bits.values())   ∈ [0, rows]
    final_z: int             # = sum(z_bits.values())   ∈ [0, rows]
    ring: int                # Chebyshev distance from centre = the contract's payout key
    seed: str                # auditable hex tag committed on chain

def next_action_for_round(round_id: int, rnd: Any) -> PlinkoAction | None:
    """Inspect one Plinko round and decide whether to resolve it.
    Returns a PlinkoAction, or None if the round is already settled or
    the row count is bogus.

    3D Plinko: the ball makes TWO independent 50/50 deflections per
    layer — one on X, one on Z — so we draw `rows` coin flips for each
    axis. The contract derives finalX = sum(xBits), finalZ = sum(zBits),
    both Binomial(rows, 1/2), then the Chebyshev `ring` distance from
    centre that drives the (radially-symmetric) multiplier lookup. The
    UI replays both bit streams as the ball's 3D path, so the on-chain
    randomness directly drives the animation."""
    status = int(_field(rnd, "roundStatus", 0))
    if status != 0:
        return None
    rows = int(_field(rnd, "rows", 0))
    if rows not in (8, 12, 16):
        # Shouldn't happen — the contract rejects other values at play()
        # time — but if we somehow see one, skip rather than guess.
        return None
    x_bits = {i: secrets.randbelow(2) for i in range(rows)}
    z_bits = {i: secrets.randbelow(2) for i in range(rows)}
    final_x = sum(x_bits.values())
    final_z = sum(z_bits.values())
    half = rows // 2
    ring = max(abs(final_x - half), abs(final_z - half))
    seed = f"plinko-{round_id}-{secrets.token_hex(8)}"
    return PlinkoAction(
        round_id=int(round_id), rows=rows,
        x_bits=x_bits, z_bits=z_bits,
        final_x=final_x, final_z=final_z, ring=ring, seed=seed,
    )


# ═══════════════════════════════════════════════════════════════════════
# Game handler — one per supported contract
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class HandlerAction:
    """One submittable action, with a human-readable label and a
    closure that performs the actual pytezos call. The closure is
    deferred so dry-run can log without signing."""
    label: str
    submit: Callable[[Any], str]   # takes pytezos contract proxy → op hash


class GameHandler:
    """Base class. Override `find_actions` and `address_constant_for`."""

    name: str = ""

    def __init__(self, network: str, address: str, client: Any):
        self.network = network
        self.address = address
        self.client = client
        self.contract = client.contract(address)

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        raise NotImplementedError

    def storage_oracle(self) -> str:
        """Return the on-chain `oracle` field for auth check."""
        return _field(self.contract.storage(), "oracle", "") or ""

    def find_actions(self) -> list[HandlerAction]:
        """Walk storage and return AT MOST one action this cycle. (We
        keep it serial per contract so each new poll can see the prior
        op's effects.)"""
        raise NotImplementedError


class ADHandler(GameHandler):
    name = "acey-duecey"

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"AD_CONTRACT_ADDRESS_{network.upper()}"

    def find_actions(self) -> list[HandlerAction]:
        storage = self.contract.storage()
        games = _field(storage, "games", {}) or {}
        for raw_id, game in games.items():
            try:
                gid = int(raw_id)
            except (TypeError, ValueError):
                continue
            action = next_action_for_game(gid, game)
            if action:
                return [self._wrap(action)]
        return []

    def _wrap(self, action: ADAction) -> HandlerAction:
        label = f"game {action.game_id:>3} → {action.entrypoint}(card={action.card})  tag={action.hash}"
        def submit(contract: Any) -> str:
            # PyTezos exposes each entrypoint as an attribute on the
            # contract proxy — no `.methodsObject[name]` accessor like
            # Taquito. We have the name as a string, so getattr.
            entrypoint_fn = getattr(contract, action.entrypoint)
            op = entrypoint_fn(
                card=action.card,
                gameId=action.game_id,
                hash=action.hash,
            ).send(min_confirmations=1)
            return getattr(op, "hash", None) or getattr(op, "opg_hash", None) or "(unknown)"
        return HandlerAction(label=label, submit=submit)


class PlinkoHandler(GameHandler):
    name = "plinko"

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"PLINKO_CONTRACT_ADDRESS_{network.upper()}"

    def find_actions(self) -> list[HandlerAction]:
        storage = self.contract.storage()
        rounds = _field(storage, "rounds", {}) or {}
        for raw_id, rnd in rounds.items():
            try:
                rid = int(raw_id)
            except (TypeError, ValueError):
                continue
            action = next_action_for_round(rid, rnd)
            if action:
                return [self._wrap(action)]
        return []

    def _wrap(self, action: PlinkoAction) -> HandlerAction:
        x_preview = "".join(str(action.x_bits[i]) for i in range(action.rows))
        z_preview = "".join(str(action.z_bits[i]) for i in range(action.rows))
        label = (f"round {action.round_id:>3} → resolve("
                 f"x={x_preview} z={z_preview} → "
                 f"({action.final_x},{action.final_z}) ring={action.ring})")
        def submit(contract: Any) -> str:
            op = contract.resolve(
                roundId=action.round_id,
                xBits=action.x_bits,
                zBits=action.z_bits,
                seed=action.seed,
            ).send(min_confirmations=1)
            return getattr(op, "hash", None) or getattr(op, "opg_hash", None) or "(unknown)"
        return HandlerAction(label=label, submit=submit)


class WarHandler(GameHandler):
    """Two-card showdown. Each game with gameStatus == 1 (joined, awaiting
    deal) gets a single call to deal(gameId, card1, card2, seed)."""
    name = "war"

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"WAR_CONTRACT_ADDRESS_{network.upper()}"

    def find_actions(self) -> list[HandlerAction]:
        storage = self.contract.storage()
        games = _field(storage, "games", {}) or {}
        for raw_id, g in games.items():
            try:
                gid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if int(_field(g, "gameStatus", 0)) != 1:
                continue
            c1 = secrets.randbelow(52)
            c2 = secrets.randbelow(52)
            seed = f"war-{gid}-{secrets.token_hex(6)}"
            label = f"game {gid:>3} → deal(c1={c1}, c2={c2})"
            def submit(contract: Any, gid=gid, c1=c1, c2=c2, seed=seed) -> str:
                op = contract.deal(
                    gameId=gid, card1=c1, card2=c2, seed=seed,
                ).send(min_confirmations=1)
                return getattr(op, "hash", None) or getattr(op, "opg_hash", None) or "(unknown)"
            return [HandlerAction(label=label, submit=submit)]
        return []


class _CoinFlipHandler(GameHandler):
    """Shared base for skill games that need a single coin flip at start
    to fairly assign first move. Subclasses just set `name` + address var."""

    def find_actions(self) -> list[HandlerAction]:
        storage = self.contract.storage()
        games = _field(storage, "games", {}) or {}
        for raw_id, g in games.items():
            try:
                gid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if int(_field(g, "gameStatus", 0)) != 1:
                continue
            bit = secrets.randbelow(2)
            seed = f"{self.name}-flip-{gid}-{secrets.token_hex(6)}"
            label = f"game {gid:>3} → flipForFirst(bit={bit})"
            def submit(contract: Any, gid=gid, bit=bit, seed=seed) -> str:
                op = contract.flipForFirst(
                    gameId=gid, bit=bit, seed=seed,
                ).send(min_confirmations=1)
                return getattr(op, "hash", None) or getattr(op, "opg_hash", None) or "(unknown)"
            return [HandlerAction(label=label, submit=submit)]
        return []


class ReversiHandler(_CoinFlipHandler):
    name = "reversi"
    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"REVERSI_CONTRACT_ADDRESS_{network.upper()}"


class ChessHandler(_CoinFlipHandler):
    name = "chess"
    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"CHESS_CONTRACT_ADDRESS_{network.upper()}"


class TTTHandler(GameHandler):
    """TezTacToe first-move flip.

    Unlike reversi/chess, TTT keeps per-game state nested under a
    `metaData` map (string→int), and the flip happens *after* both
    players pair — the game is already `gameStatus == 2` (active) but
    `firstMoveDecided == 0`. flipForFirst(gameId, bit, seed) sets
    playerTurn from the bit and marks firstMoveDecided, unblocking
    makeMove. Idempotent on-chain, so a double-submit just reverts.
    """
    name = "ttt"

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"TTT_CONTRACT_ADDRESS_{network.upper()}"

    def find_actions(self) -> list[HandlerAction]:
        storage = self.contract.storage()
        games = _field(storage, "games", {}) or {}
        for raw_id, g in games.items():
            try:
                gid = int(raw_id)
            except (TypeError, ValueError):
                continue
            meta = _field(g, "metaData", {}) or {}
            try:
                status = int(meta.get("gameStatus", 0))
                decided = int(meta.get("firstMoveDecided", 0))
            except (TypeError, ValueError, AttributeError):
                continue
            # Flip once both players have paired (status 2) and the flip
            # hasn't run yet.
            if status != 2 or decided != 0:
                continue
            bit = secrets.randbelow(2)
            seed = f"ttt-flip-{gid}-{secrets.token_hex(6)}"
            label = f"game {gid:>3} → flipForFirst(bit={bit}) → P{bit + 1} moves first"
            def submit(contract: Any, gid=gid, bit=bit, seed=seed) -> str:
                op = contract.flipForFirst(
                    gameId=gid, bit=bit, seed=seed,
                ).send(min_confirmations=1)
                return getattr(op, "hash", None) or getattr(op, "opg_hash", None) or "(unknown)"
            return [HandlerAction(label=label, submit=submit)]
        return []


class SquaresHandler(GameHandler):
    """Super-Bowl squares (v2): once a game reaches PHASE_LOCKED (sales
    closed, either by sell-out or admin closeSales), the daemon picks two
    independent Fisher-Yates permutations of [0..9] and calls
    setAxes(gameId, axisHome, axisAway) to commit them on-chain.

    setAxes is admin-only in v2. Run this daemon with a key that is the
    squares contract's admin — same operational model as the other game
    handlers in this file. (The v2 contract also exposes a requestAxes →
    on-chain RandomOracle round-trip for fully-verifiable randomness; the
    daemon flow here is the simpler operator-trust path that the contract
    explicitly supports: "admin or a relayer bot" in setAxes' docstring.)

    Phases (must mirror smart_contract_squares_v2.py):
      0 = SELLING, 1 = LOCKED, 2 = AXES_SET, 3 = COMPLETE

    Two action paths, both admin-only:
      • PHASE_LOCKED (no axes yet)  → setAxes(gameId, axisHome, axisAway)
      • PHASE_AXES_SET + ESPN tag   → reportQuarter(gameId, q, home, away)
        when the live game has a quarter ESPN considers final but the
        chain still has quarterReported[q] == False. The grid's
        `createGame.name` carries the tag (e.g. "ESPN:401871337  ·  Cavs
        vs Pistons G6"), parsed by scripts/sports_api.parse_espn_id.
    """
    name = "squares"
    PHASE_LOCKED = 1
    PHASE_AXES_SET = 2
    # Squares pays out 4 quarters total. ESPN reports OT as period 5+,
    # which we ignore here — overtime points roll into Q4's settlement
    # decision off-platform if the operator wants to handle that.
    MAX_QUARTERS = 4

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"SQUARES_CONTRACT_ADDRESS_{network.upper()}"

    @staticmethod
    def _shuffled_0_9() -> dict[int, int]:
        """Fisher-Yates shuffle on [0..9]. Returns {position: digit}, the
        shape v2's axisHome / axisAway maps expect (TMap(TInt, TInt))."""
        order = list(range(10))
        for i in range(len(order) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            order[i], order[j] = order[j], order[i]
        return {i: v for i, v in enumerate(order)}

    def find_actions(self) -> list[HandlerAction]:
        storage = self.contract.storage()
        games = _field(storage, "games", {}) or {}
        for raw_id, game in games.items():
            try:
                gid = int(raw_id)
            except (TypeError, ValueError):
                continue
            phase = int(_field(game, "phase", 0))

            # ─── 1. Axes step (existing) ────────────────────────────
            assigned = bool(_field(game, "axesAssigned", False))
            if phase == self.PHASE_LOCKED and not assigned:
                axis_home = self._shuffled_0_9()
                axis_away = self._shuffled_0_9()
                label = (f"game {gid:>3} → setAxes("
                         f"home={list(axis_home.values())}, "
                         f"away={list(axis_away.values())})")
                def submit(contract: Any, gid=gid, ah=axis_home, aa=axis_away) -> str:
                    op = contract.setAxes(
                        gameId=gid, axisHome=ah, axisAway=aa,
                    ).send(min_confirmations=1)
                    return getattr(op, "hash", None) or getattr(op, "opg_hash", None) or "(unknown)"
                return [HandlerAction(label=label, submit=submit)]

            # ─── 2. Sports score step ───────────────────────────────
            if phase == self.PHASE_AXES_SET:
                action = self._sports_action(gid, game)
                if action:
                    return [action]
        return []

    def _sports_action(self, gid: int, game: Any) -> HandlerAction | None:
        """Look at the grid's name for an `ESPN:<event_id>` tag, fetch the
        live game from ESPN, and (if a quarter is final but the contract
        still has `quarterReported[q] == False`) return a reportQuarter
        action. Returns None if no tag, no event, no finished quarter
        left, or if the HTTP fetch failed (we'll just retry next poll).
        """
        # Lazy import so squares-less worker runs don't pull ESPN code.
        try:
            from sports_api import parse_espn_id, fetch_game
        except ImportError:
            return None

        name = _field(game, "name", "") or ""
        event_id = parse_espn_id(name)
        if not event_id:
            return None

        try:
            espn = fetch_game(event_id)
        except Exception as e:  # noqa: BLE001 — broad: ESPN reliability is best-effort
            warn(f"squares: ESPN fetch for event {event_id} failed: {e!s:.140}")
            return None
        if not espn:
            return None

        # On-chain `quarterReported` is a TMap(TInt, TBool) keyed 0..3.
        # tzkt sometimes returns ints, sometimes strings, sometimes the
        # booleans wrapped — defensively coerce both sides.
        reported = _field(game, "quarterReported", {}) or {}
        def is_done(q: int) -> bool:
            raw = reported.get(q, reported.get(str(q), False)) if isinstance(reported, dict) else False
            return bool(raw) and str(raw).lower() != "false"

        # ESPN's quarter_finals() returns one entry per finished period
        # (including OT). We only care about Q1..Q4 — index 0..3 — so
        # the contract's `quarter < 4` precondition holds.
        for q_info in espn.quarter_finals():
            q = int(q_info["q"])
            if q >= self.MAX_QUARTERS:
                continue
            if is_done(q):
                continue
            home_pts = int(q_info["home"])
            away_pts = int(q_info["away"])
            label = (f"game {gid:>3} → reportQuarter(q={q}, "
                     f"{espn.home.abbr}={home_pts}, "
                     f"{espn.away.abbr}={away_pts}) · ESPN:{event_id}")
            def submit(contract: Any, gid=gid, q=q, h=home_pts, a=away_pts) -> str:
                op = contract.reportQuarter(
                    gameId=gid, quarter=q, homeScore=h, awayScore=a,
                ).send(min_confirmations=1)
                return getattr(op, "hash", None) or getattr(op, "opg_hash", None) or "(unknown)"
            return HandlerAction(label=label, submit=submit)
        return None

    def storage_oracle(self) -> str:
        """v2 stores the trusted authority as `admin` (both setAxes and
        reportQuarter are admin-only), not `oracle`. Override the auth
        check so the daemon verifies its key matches the contract's
        admin instead."""
        return _field(self.contract.storage(), "admin", "") or ""


class RandomnessHandler(GameHandler):
    """RandomOracle (v2) — generic randomness service for 3rd-party dApps.

    Watches the deployed RandomOracle contract for requests with
    requestStatus == 0 and calls fulfillRandom(requestId, values, seed)
    with cryptographically-random nats in [0, maxValue].

    This is the same daemon code that powers AD / Plinko / War / Reversi /
    Chess / TTT / Squares, just pointed at a different contract. Any dApp
    on Tezos can request randomness from RandomOracle — see
    src/services/smart_contract_oracle_reference.py for an integration
    example and docs/ORACLE_INTEGRATION.md for the full walkthrough."""
    name = "randomness"

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"ORACLE_CONTRACT_{network.upper()}"

    def find_actions(self) -> list[HandlerAction]:
        storage = self.contract.storage()
        requests = _field(storage, "requests", {}) or {}
        for raw_id, req in requests.items():
            try:
                rid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if int(_field(req, "requestStatus", 0)) != 0:
                continue
            n = int(_field(req, "nRandoms", 1))
            max_value = int(_field(req, "maxValue", 1))
            # secrets.randbelow(max_value + 1) gives an inclusive draw.
            values = [secrets.randbelow(max_value + 1) for _ in range(n)]
            seed = f"oracle-{rid}-{secrets.token_hex(8)}"
            label = (f"req {rid:>3} → fulfillRandom(n={n}, max={max_value}, "
                     f"values={values})")
            def submit(contract: Any, rid=rid, values=values, seed=seed) -> str:
                op = contract.fulfillRandom(
                    requestId=rid,
                    randomValues=values,
                    seed=seed,
                ).send(min_confirmations=1)
                return getattr(op, "hash", None) or getattr(op, "opg_hash", None) or "(unknown)"
            return [HandlerAction(label=label, submit=submit)]
        return []


HANDLERS: dict[str, type[GameHandler]] = {
    "acey-duecey": ADHandler,
    "plinko": PlinkoHandler,
    "war": WarHandler,
    "reversi": ReversiHandler,
    "chess": ChessHandler,
    "ttt": TTTHandler,
    "squares": SquaresHandler,
    "randomness": RandomnessHandler,
}


# ═══════════════════════════════════════════════════════════════════════
# Worker — owns the RPC client + poll loop, dispatches to handlers
# ═══════════════════════════════════════════════════════════════════════

class Worker:
    def __init__(self, args: argparse.Namespace):
        from pytezos import pytezos, Key

        self.args = args
        self.network = args.network
        self.rpc = NETWORK_RPCS[self.network]
        self.tzkt = TZKT_HOSTS[self.network]

        mnemonic = os.environ.get("DEPLOY_MNEMONIC", "").strip()
        if not mnemonic and not args.dry_run:
            die("DEPLOY_MNEMONIC missing from .env. "
                "Run scripts/new-test-wallet.sh to generate one, or "
                "re-run with --dry-run to see what the worker would do.")

        if args.dry_run:
            self.key = None
            self.client = pytezos.using(shell=self.rpc)
        else:
            self.key = Key.from_mnemonic(mnemonic.split())
            self.client = pytezos.using(shell=self.rpc, key=self.key)

        # Build the list of active handlers.
        chosen = list(HANDLERS) if args.game == "all" else [args.game]
        if args.address and len(chosen) != 1:
            die("--address can only be used together with a single --game "
                "(it would be ambiguous with --game all).")

        self.handlers: list[GameHandler] = []
        for game in chosen:
            cls = HANDLERS[game]
            addr_var = cls.address_constant_for(self.network)
            addr = args.address if args.address else read_constant(addr_var)
            if not addr or "KT1XXX" in addr:
                warn(f"{game}: no usable contract address (looked up {addr_var} in "
                     f"constants.js, got {addr!r}). Skipping.")
                continue
            self.handlers.append(cls(self.network, addr, self.client))

        if not self.handlers:
            die("No active handlers — every selected game had a missing or "
                "placeholder address. Nothing to do.")

        self.stopping = False

    def announce(self) -> None:
        section("Oracle worker")
        info(f"Network:  {self.network}")
        info(f"RPC:      {self.rpc}")
        for h in self.handlers:
            info(f"  • {h.name:11} {h.address}")
            info(f"    https://{self.tzkt}/{h.address}")
        info(f"Poll:     every {self.args.poll}s   (--once to do one cycle and exit)")
        info(f"Mode:     {'DRY-RUN — no operations will be signed' if self.args.dry_run else 'live'}")
        info("")
        if self.key:
            addr = self.key.public_key_hash()
            info(f"Worker key:    {addr}")
            try:
                bal = int(self.client.account().get("balance", "0")) / 1_000_000
                info(f"Worker balance: {bal:.4f} ꜩ")
            except Exception as e:
                warn(f"Couldn't read balance: {e}")
            info("")

    def check_authorised(self) -> bool:
        """Each selected handler's `storage.oracle` must match our key,
        otherwise every call would fail. Bail loudly so the user knows
        to update the oracle address (via the contract's updateOracle
        entrypoint or a redeploy)."""
        if self.args.dry_run:
            for h in self.handlers:
                try:
                    info(f"{h.name}: storage.oracle = {h.storage_oracle()}")
                except Exception as e:
                    warn(f"{h.name}: couldn't read storage.oracle: {e}")
            return True

        my_addr = self.key.public_key_hash()
        kept: list[GameHandler] = []
        for h in self.handlers:
            try:
                on_chain = (h.storage_oracle() or "").lower()
            except Exception as e:
                err(f"{h.name}: couldn't read contract storage — skipping ({e})")
                continue
            if on_chain != my_addr.lower():
                warn(f"{h.name}: not authorised "
                     f"(storage.oracle = {on_chain}, my key = {my_addr}). Skipping.")
                continue
            ok(f"{h.name}: authorised as oracle ({my_addr})")
            kept.append(h)
        self.handlers = kept
        if not kept:
            err("No authorised handlers. Update one of the contracts' "
                f"storage.oracle to my key ({my_addr}), or run with a key "
                f"that matches.")
            return False
        return True

    def one_pass(self) -> int:
        """Single poll cycle across every handler. Returns total ops
        submitted. At most one action per handler per cycle."""
        submitted = 0
        for h in self.handlers:
            try:
                actions = h.find_actions()
            except Exception as e:
                err(f"{h.name}: storage poll failed: {e}")
                continue
            for action in actions:
                submitted += self._submit(h, action)
        return submitted

    def _submit(self, handler: GameHandler, action: HandlerAction) -> int:
        prefix = f"[{handler.name}]"
        if self.args.dry_run:
            warn(f"DRY-RUN {prefix} would submit  {action.label}")
            return 0

        info(f"{prefix} submitting  {action.label}")
        try:
            op_hash = action.submit(handler.contract)
            ok(f"  confirmed — {op_hash}")
            info(f"  https://{self.tzkt}/{op_hash}")
            return 1
        except Exception as e:
            msg = str(e)
            lower = msg.lower()
            soft_fail_markers = (
                "bad game", "notoracle", "not oracle", "previously",
                "already resolved", "slot out of range",
            )
            if any(s in lower for s in soft_fail_markers):
                warn(f"  contract rejected: {msg[:140]}")
                warn(f"  (race with another oracle, or state advanced between "
                     f"poll and submit — will re-check next cycle)")
            else:
                err(f"  submit failed: {msg[:200]}")
            return 0

    def loop(self) -> None:
        if not self.check_authorised():
            sys.exit(2)

        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        cycles = 0
        actions_total = 0
        while not self.stopping:
            cycles += 1
            actions_total += self.one_pass()
            if self.args.once:
                ok(f"--once: {actions_total} action(s) in 1 cycle. Exiting.")
                return
            # Sleep in short slices so SIGINT lands fast.
            for _ in range(self.args.poll * 4):
                if self.stopping: break
                time.sleep(0.25)
        ok(f"Stopped after {cycles} cycle(s), {actions_total} action(s) submitted.")

    def _on_signal(self, signum: int, _frame: Any) -> None:
        warn(f"Caught signal {signum} — finishing current cycle and exiting.")
        self.stopping = True


# ─── helpers ──────────────────────────────────────────────────────────
def die(msg: str, code: int = 1) -> None:
    err(msg)
    sys.exit(code)


# ─── Entry ────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(
        description="Off-chain oracle daemon for TezLiteApps games (AD + Plinko).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage")[1] if "Usage" in __doc__ else "",
    )
    p.add_argument("--game", choices=[*HANDLERS, "all"], default="all",
                   help="Which game(s) to serve (default: all)")
    p.add_argument("--network", choices=list(NETWORK_RPCS), default="shadownet")
    p.add_argument("--address", help="Override the contract address (only "
                                     "valid with a single --game). Default: "
                                     "<GAME>_CONTRACT_ADDRESS_<NETWORK> from "
                                     "constants.js")
    p.add_argument("--poll", type=int, default=5,
                   help="Seconds between polls when idle (default: 5)")
    p.add_argument("--once", action="store_true",
                   help="Run a single poll cycle, then exit")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't sign anything — log what we would do")
    args = p.parse_args()

    load_dotenv()
    worker = Worker(args)
    worker.announce()
    try:
        worker.loop()
    except KeyboardInterrupt:
        print()
        err("Interrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
