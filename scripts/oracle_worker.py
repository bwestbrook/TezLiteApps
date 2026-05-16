#!/usr/bin/env python3
"""
oracle_worker.py — off-chain oracle daemon for TezLiteApps games (v3).

Supports multiple games behind one process. Pick which to run with
`--game`:

    --game randomness   the v3 commit-reveal randomness flow (AD, Plinko,
                        TTT all consume this — no per-game handlers needed)
    --game war          legacy War handler (still oracle-keyed)
    --game reversi      legacy Reversi handler (still oracle-keyed)
    --game chess        legacy Chess handler (still oracle-keyed)
    --game squares      Super-Bowl squares axes + quarter reporting
    --game all          everything above (default)

v3 randomness — what 'randomness' actually does
------------------------------------------------
The handler runs two coordinated loops against the on-chain RandomOracle:

  1. OracleCommitter — every ~N blocks, generates a fresh 32-byte preimage,
     hashes it, and calls `postCommit(hash)`. Persists the preimage to a
     journal at ~/.tezliteapps/commits.json so a restart doesn't lose any
     pending preimages. Maintains COMMITS_TO_KEEP_AHEAD unrevealed commits
     ready for new requests to bind to.

  2. RandomnessHandler — polls the oracle's request log:
       - any pending request whose bound commit is SEALED and we have the
         preimage in our journal → call revealCommit(commitId, preimage)
       - any pending request whose bound commit is REVEALED → call
         fulfillRandom(requestId) (permissionless — anyone can; we do it
         as the bridge so callers don't have to)

The v2 per-game handlers (AD / Plinko / TTT) that called firstCard /
secondCard / lastCard / resolve / flipForFirst directly are RETIRED in
v3 — those games now call `RandomOracle.requestRandom` from inside their
own entrypoints, and the response lands via their `onRandomFulfilled`
callbacks driven by the RandomnessHandler above.

Why this exists
---------------
v2 trusted a single tz1 address (`storage.oracle` on each game contract)
to pick the random values. v3 removes that trust via commit-reveal +
user-contributed entropy — see docs/V3_COMMIT_REVEAL.md. The daemon's
role shifts: it no longer gets to *choose* values, only to schedule
commits and bridge the reveal+fulfill steps. The values fall out of
on-chain hashing once a commit is revealed.

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
import hashlib
import json
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


def _opg_hash(op: Any) -> str:
    """Extract the op hash from whatever pytezos returns from .send().
    pytezos 3.17 returns an OperationGroup whose `.hash` is a METHOD
    (not an attribute) — naive `getattr(op, "hash", None) or …` returns
    the bound method (truthy), so we end up logging "<bound method
    OperationGroup.hash …>" instead of the hash. Call the method if
    it's callable; fall back to dict-style for older pytezos."""
    h = getattr(op, "hash", None)
    if callable(h):
        try:
            return h()
        except Exception:
            pass
    if isinstance(op, dict) and "hash" in op:
        return op["hash"]
    if isinstance(h, str):
        return h
    return "(unknown)"


# ═══════════════════════════════════════════════════════════════════════
# v3 commit-reveal — preimage journal (persisted across restarts)
# ═══════════════════════════════════════════════════════════════════════

# Where the OracleCommitter keeps generated preimages so a worker
# restart doesn't lose them (in which case bound requests would never be
# fulfillable). Per-network so multiple deployments don't collide.
JOURNAL_DIR = Path.home() / ".tezliteapps"

def journal_path(network: str) -> Path:
    return JOURNAL_DIR / f"commits-{network}.json"

def load_journal(network: str) -> dict[str, dict]:
    p = journal_path(network)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as e:
        warn(f"journal at {p} unreadable ({e}); starting empty (existing "
             f"on-chain commits without a local preimage will be unfulfillable)")
        return {}

def save_journal(network: str, journal: dict[str, dict]) -> None:
    p = journal_path(network)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(journal, indent=2, sort_keys=True))
    tmp.replace(p)  # atomic on POSIX

# How many unrevealed commits we try to maintain on-chain at all times,
# so new randomRequest ops can always find a fresh commitId to bind to.
# Raise if request rate is high; lower to reduce per-block postCommit gas.
COMMITS_TO_KEEP_AHEAD = 3

# Empty-bytes encoding the contract uses for an unrevealed commit.
EMPTY_BYTES_MARKERS = ("", "0x", b"", "00", None)


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


# NOTE: v2 ADHandler / PlinkoHandler are RETIRED in v3 — those games now
# call RandomOracle.requestRandom from inside bet()/play() and receive
# results via their own onRandomFulfilled callbacks. The RandomnessHandler
# below covers them transparently. TTT lost its direct flipForFirst
# handler for the same reason.


class WarHandler(GameHandler):
    """Best-of-3 speed war. Each game with gameStatus == 1 (joined,
    awaiting deal) gets a single call to deal(gameId, cards1, cards2,
    seed) where cards1/cards2 are 3-entry maps (round_idx → deck_idx)."""
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
            # Six distinct deck indices: three for each player, one per
            # round. Sampled without replacement so no card appears twice
            # across the whole match (mirrors a single physical deck).
            deck = list(range(52))
            secrets.SystemRandom().shuffle(deck)
            six = deck[:6]
            cards1 = {0: six[0], 1: six[1], 2: six[2]}
            cards2 = {0: six[3], 1: six[4], 2: six[5]}
            seed = f"war-{gid}-{secrets.token_hex(6)}"
            label = (
                f"game {gid:>3} → deal(p1={list(cards1.values())} "
                f"p2={list(cards2.values())})"
            )
            def submit(contract: Any, gid=gid, c1=cards1, c2=cards2, seed=seed) -> str:
                op = contract.deal(
                    gameId=gid, cards1=c1, cards2=c2, seed=seed,
                ).send(min_confirmations=1)
                return _opg_hash(op)
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
                return _opg_hash(op)
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


# NOTE: v2 TTTHandler is RETIRED in v3 — TTT's flipForFirst entrypoint
# was removed; joinGame() now triggers RandomOracle.requestRandom and
# the bit lands via TTT.onRandomFulfilled. RandomnessHandler covers it.


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
                    return _opg_hash(op)
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
                return _opg_hash(op)
            return HandlerAction(label=label, submit=submit)
        return None

    def storage_oracle(self) -> str:
        """v2 stores the trusted authority as `admin` (both setAxes and
        reportQuarter are admin-only), not `oracle`. Override the auth
        check so the daemon verifies its key matches the contract's
        admin instead."""
        return _field(self.contract.storage(), "admin", "") or ""


def _is_unrevealed(preimage_raw: Any) -> bool:
    """Detect the 'commit not yet revealed' state across the various
    encodings tzkt / pytezos may return for sp.bytes."""
    if preimage_raw is None:
        return True
    if isinstance(preimage_raw, str):
        return preimage_raw in EMPTY_BYTES_MARKERS or preimage_raw == "0x" or len(preimage_raw) == 0
    if isinstance(preimage_raw, (bytes, bytearray)):
        return len(preimage_raw) == 0
    return False


class OracleCommitter(GameHandler):
    """Posts fresh sha256(preimage) commits to the RandomOracle on a
    rolling schedule so requestRandom callers always find a fresh
    bindable commitId. Persists preimages to ~/.tezliteapps/commits-<net>.json
    so a restart doesn't lose any pending preimages — a request bound
    to a commit whose preimage is gone is unfulfillable forever.

    The handler is paired with RandomnessHandler (below): committer
    keeps fresh commits on chain; randomness handler reveals + fulfills.
    """
    name = "oracle-committer"

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"ORACLE_CONTRACT_{network.upper()}"

    def __init__(self, network: str, address: str, client: Any):
        super().__init__(network, address, client)
        self.journal = load_journal(network)

    def find_actions(self) -> list[HandlerAction]:
        storage = self.contract.storage()
        commit_log = _field(storage, "commitLog", {}) or {}
        current_commit_id = int(_field(storage, "currentCommitId", 0))

        # Count commits that are posted but still sealed (no preimage yet).
        unrevealed = 0
        for cid_str, entry in commit_log.items():
            preimage = _field(entry, "revealedPreimage", "")
            if _is_unrevealed(preimage):
                unrevealed += 1

        if unrevealed >= COMMITS_TO_KEEP_AHEAD:
            return []

        # Generate a fresh preimage + hash. We pre-stage it in the
        # journal under the expected commitId BEFORE the op submits so
        # an op-then-crash doesn't strand a posted commit without a
        # local preimage. After the op confirms, we re-anchor the
        # journal key to the actual on-chain commitId in case there
        # were races (multiple committers, manual postCommit, etc.).
        preimage = secrets.token_bytes(32)
        hash_bytes = hashlib.sha256(preimage).digest()
        expected_cid = current_commit_id
        self.journal[str(expected_cid)] = {
            "preimage_hex": preimage.hex(),
            "hash_hex": hash_bytes.hex(),
            "posted_at_level": None,    # filled in after the op confirms
            "status": "pre-staged",
        }
        save_journal(self.network, self.journal)

        label = (f"postCommit hash=0x{hash_bytes.hex()[:10]}…  "
                 f"(expected cid {expected_cid}, {unrevealed} unrevealed)")
        def submit(contract: Any, hash_bytes=hash_bytes, preimage_hex=preimage.hex(), expected_cid=expected_cid) -> str:
            # SmartPy flattens single-field record params to bare types,
            # so pytezos's introspected signature is `postCommit(bytes)`
            # not `postCommit(hash=bytes)`. Passing as kwarg trips the
            # `or`-tree dispatcher with "Unexpected arguments: {'hash': ...}".
            op = contract.postCommit(hash_bytes).send(min_confirmations=1)
            # Re-read storage to find the actual commitId assigned.
            try:
                after = self.contract.storage()
                actual_cid = int(_field(after, "currentCommitId", expected_cid + 1)) - 1
            except Exception:
                actual_cid = expected_cid
            if actual_cid != expected_cid:
                # Race: another op bumped currentCommitId between our read and submit.
                # Move the journal entry to the correct cid so reveal can find it.
                self.journal.pop(str(expected_cid), None)
            self.journal[str(actual_cid)] = {
                "preimage_hex": preimage_hex,
                "hash_hex": hash_bytes.hex(),
                "posted_at_level": int(_field(after, "currentCommitId", 0)),  # informational
                "status": "posted",
            }
            save_journal(self.network, self.journal)
            return _opg_hash(op)
        return [HandlerAction(label=label, submit=submit)]


class RandomnessHandler(GameHandler):
    """RandomOracle v3 reveal + fulfill bridge.

    Two action paths per cycle (one per call; the loop picks the most
    urgent each pass):

      1. Reveal — any pending request whose bound commit is still SEALED
         AND whose preimage is in our journal → call
         revealCommit(commitId, preimage). After this, the same commit's
         requests become permissionlessly fulfillable.

      2. Fulfill — any pending request whose bound commit is REVEALED →
         call fulfillRandom(requestId). This is permissionless (anyone
         can call it), but we do it as the bridge to keep latency low
         and to invoke the callback contracts that drive AD / Plinko /
         TTT / and 3rd-party consumers.

    Determinism: this handler has NO say over the random values. They
    are derived inside fulfillRandom from on-chain inputs alone — the
    preimage we publish (forced to match the committed hash), the
    user-supplied nonce stored at request time, and the request's
    monotonic ID. Any third party can re-derive and verify.
    """
    name = "randomness"

    @classmethod
    def address_constant_for(cls, network: str) -> str:
        return f"ORACLE_CONTRACT_{network.upper()}"

    def __init__(self, network: str, address: str, client: Any):
        super().__init__(network, address, client)
        self.journal = load_journal(network)

    def find_actions(self) -> list[HandlerAction]:
        # Re-read the journal each pass — the OracleCommitter (potentially
        # in the same process) may have added entries since the last cycle.
        self.journal = load_journal(self.network)

        storage = self.contract.storage()
        requests = _field(storage, "requests", {}) or {}
        commit_log = _field(storage, "commitLog", {}) or {}

        # First pass: any fulfillable request? Prefer fulfillment over
        # reveal so the callback latency stays minimal once the preimage
        # is on chain.
        for raw_id, req in requests.items():
            try:
                rid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if int(_field(req, "requestStatus", 0)) != 0:
                continue
            cid_raw = _field(req, "commitId", 0)
            try:
                cid = int(cid_raw)
            except (TypeError, ValueError):
                continue
            commit = commit_log.get(cid) or commit_log.get(str(cid))
            if commit is None:
                continue
            preimage = _field(commit, "revealedPreimage", "")
            if not _is_unrevealed(preimage):
                label = f"req {rid:>3} → fulfillRandom (bound commit {cid} already revealed)"
                def submit(contract: Any, rid=rid) -> str:
                    # Single-field-record flatten — see postCommit note.
                    op = contract.fulfillRandom(rid).send(min_confirmations=1)
                    return _opg_hash(op)
                return [HandlerAction(label=label, submit=submit)]

        # Second pass: any pending request whose bound commit needs a
        # reveal AND we hold the preimage? Reveal it.
        for raw_id, req in requests.items():
            try:
                rid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if int(_field(req, "requestStatus", 0)) != 0:
                continue
            cid_raw = _field(req, "commitId", 0)
            try:
                cid = int(cid_raw)
            except (TypeError, ValueError):
                continue
            commit = commit_log.get(cid) or commit_log.get(str(cid))
            if commit is None:
                continue
            if not _is_unrevealed(_field(commit, "revealedPreimage", "")):
                continue
            journal_entry = self.journal.get(str(cid))
            if not journal_entry or "preimage_hex" not in journal_entry:
                # Sealed commit with bound requests but no local preimage.
                # This is a sign the worker is in a divergent state (a
                # different worker posted that commit, or our journal
                # was wiped). Log loudly so the operator notices.
                warn(f"req {rid}: commit {cid} sealed but no preimage in "
                     f"journal — request will hang until preimage is recovered")
                continue
            preimage_bytes = bytes.fromhex(journal_entry["preimage_hex"])
            label = f"revealCommit({cid})  (unblocks req {rid} + others bound to this commit)"
            def submit(contract: Any, cid=cid, preimage_bytes=preimage_bytes) -> str:
                # Two-field record — passing as a dict via kwargs would
                # also trip the `or`-tree introspection; positional dict
                # (or positional ordered tuple) navigates it correctly.
                op = contract.revealCommit(
                    {"commitId": cid, "preimage": preimage_bytes},
                ).send(min_confirmations=1)
                # Mark the journal entry as revealed for hygiene.
                je = self.journal.get(str(cid), {})
                je["status"] = "revealed"
                self.journal[str(cid)] = je
                save_journal(self.network, self.journal)
                return _opg_hash(op)
            return [HandlerAction(label=label, submit=submit)]

        return []

    def storage_oracle(self) -> str:
        """The randomness handler itself doesn't need the oracle role — it
        only calls revealCommit (oracle-only) and fulfillRandom
        (permissionless). The committer handles the oracle gating.
        Returning self.client's key bypasses the auth check below."""
        return _field(self.contract.storage(), "oracle", "") or ""


HANDLERS: dict[str, type[GameHandler]] = {
    # v3: AD / Plinko / TTT are RETIRED here — they call RandomOracle
    # internally and the RandomnessHandler bridges reveal+fulfill on
    # their behalf. Running --game randomness covers all three (plus any
    # 3rd-party dApp using the v3 oracle).
    "oracle-committer": OracleCommitter,
    "randomness": RandomnessHandler,
    # v2 handlers still in place for games that haven't migrated yet.
    "war": WarHandler,
    "reversi": ReversiHandler,
    "chess": ChessHandler,
    "squares": SquaresHandler,
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

        # Worker key resolution order (most specific → least):
        #   1. --mnemonic-env <NAME>           CLI override
        #   2. ORACLE_MNEMONIC_<NETWORK>       per-network oracle key
        #   3. TXL_ORACLE_MNEMONIC_<NETWORK>   alias (the TXL deploy uses
        #                                      this name; on mainnet the
        #                                      same tz1 serves both the
        #                                      TXL oracle role AND the
        #                                      RandomOracle oracle role,
        #                                      so the env var is dual-use)
        #   4. DEPLOY_MNEMONIC                 legacy fallback
        net = self.network.upper()
        candidates = []
        if args.mnemonic_env:
            candidates.append(args.mnemonic_env)
        candidates += [
            f"ORACLE_MNEMONIC_{net}",
            f"TXL_ORACLE_MNEMONIC_{net}",
            "DEPLOY_MNEMONIC",
        ]
        mnemonic = ""
        chosen_var = None
        for var in candidates:
            val = os.environ.get(var, "").strip()
            if val:
                mnemonic = val
                chosen_var = var
                break

        if not mnemonic and not args.dry_run:
            die(
                f"No worker mnemonic found. Looked for (in order): "
                f"{', '.join(candidates)}. Add one to .env, or re-run "
                f"with --dry-run."
            )

        if args.dry_run:
            self.key = None
            self.client = pytezos.using(shell=self.rpc)
        else:
            self.key = Key.from_mnemonic(mnemonic.split())
            self.client = pytezos.using(shell=self.rpc, key=self.key)
            info(f"signer: {self.key.public_key_hash()} (from {chosen_var})")

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
    p.add_argument("--mnemonic-env", default=None,
                   help="Name of the .env variable holding the worker "
                        "mnemonic (overrides the default ORACLE_MNEMONIC_"
                        "<NETWORK> / TXL_ORACLE_MNEMONIC_<NETWORK> / "
                        "DEPLOY_MNEMONIC fallback chain)")
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
