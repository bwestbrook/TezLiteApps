#!/usr/bin/env python3
"""
emulate_squares.py — End-to-end Squares emulator driven by real ESPN scores.

Pulls a *finished* game from NBA, NFL, EPL, NHL, or MLB; spins up a fresh
Squares grid on the deployed contract; buys it out across two wallets;
randomizes axes; reports each scoring period from the real linescore;
prints the resulting winners and pending payouts.

Why this exists: the on-chain happy path needs (a) at least two distinct
buyers, (b) a sport's worth of period-by-period scores, (c) an admin who
can call setAxes / reportQuarter. Hand-rolling that for a smoke test is
painful — this script does the whole thing in one shot off the DEPLOY
mnemonic from .env, fabricating a deterministic secondary wallet for the
second buyer.

Usage (shadownet, defaults to NBA on the most recent slate with a final):
    .venv/bin/python scripts/emulate_squares.py
    .venv/bin/python scripts/emulate_squares.py --league EPL --date 20260301
    .venv/bin/python scripts/emulate_squares.py --league MLB --event-id 401581234
    .venv/bin/python scripts/emulate_squares.py --dry-run    # no signed ops

Funding model:
- Primary signer = DEPLOY_MNEMONIC in .env (the contract's admin).
- Secondary buyer = DEPLOY_MNEMONIC_2 if set; otherwise a deterministic
  mnemonic derived from DEPLOY_MNEMONIC + a fixed salt (so re-running
  reuses the same wallet rather than orphaning funds).
- If the secondary's balance is below the minimum needed for ~48 buys
  plus per-op fees, the primary tops it up before the buy-out.

The script writes a one-line-per-step timeline to stdout — match the
operation hashes against shadownet.tzkt.io to audit. Exits 0 on success;
non-zero on any RPC/contract error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
CONSTANTS_PATH = PROJECT_ROOT / "src" / "constants.js"

# Network endpoints — mirror scripts/deploy.py so the two stay aligned.
RPCS = {
    "shadownet": "https://rpc.shadownet.teztnets.com",
    "mainnet":   "https://mainnet.tezos.ecadinfra.com",
}
TZKT = {
    "shadownet": "https://api.shadownet.tzkt.io",
    "mainnet":   "https://api.tzkt.io",
}

# ─── ESPN per-league config ─────────────────────────────────────────────
# All five leagues route through site.api.espn.com; only the path differs.
# numPeriods + weights must match periodSpecForLeague() in squaresGame.vue
# so the contract accepts the createGame params we emit.
LEAGUES: dict[str, dict] = {
    "NBA": {
        "espn_path": "basketball/nba",
        "numPeriods": 4,
        # NBA/NFL/NCAAM: heavy weight on the final period.
        "weights":   {0: 15, 1: 15, 2: 15, 3: 55},
    },
    "NFL": {
        "espn_path": "football/nfl",
        "numPeriods": 4,
        "weights":   {0: 15, 1: 15, 2: 15, 3: 55},
    },
    "NHL": {
        "espn_path": "hockey/nhl",
        "numPeriods": 3,
        "weights":   {0: 20, 1: 30, 2: 50},
    },
    "EPL": {
        # ESPN buckets the English Premier League under soccer/eng.1.
        "espn_path": "soccer/eng.1",
        "numPeriods": 2,
        "weights":   {0: 30, 1: 70},
    },
    "MLB": {
        "espn_path": "baseball/mlb",
        "numPeriods": 9,
        "weights":   {0: 8, 1: 8, 2: 8, 3: 8, 4: 8, 5: 8, 6: 10, 7: 10, 8: 32},
    },
}

# Holder-fee + ticket-price for the emulated game. Picked tiny so the
# script costs <0.1 ꜩ to fully exercise on shadownet.
DEFAULT_TICKET_MUTEZ = 1
DEFAULT_HOLDER_FEE_MUTEZ = 1

# House cells — must mirror smart_contract_squares_v2.py. The buy-out
# loop skips these and never assigns squares to either of them.
HOUSE_CELLS = {44, 90}
SELLABLE_CELLS = 100 - len(HOUSE_CELLS)
PER_PLAYER_CAP = 50

# Salt used to derive the secondary wallet's mnemonic from the primary's.
# Keeping this constant gives reproducible secondaries across runs so the
# user doesn't accumulate orphaned faucet balances.
SECONDARY_SALT = "emulate_squares.py:secondary-buyer:v1"


# ─── small logging helpers ──────────────────────────────────────────────
G, R, Y, C, B, RESET = "\033[0;32m", "\033[0;31m", "\033[0;33m", "\033[0;36m", "\033[1m", "\033[0m"
def hr() -> None: print("─" * 64)
def info(msg: str) -> None: print(f"  {msg}")
def step(msg: str) -> None: print(f"{C}→{RESET} {msg}")
def ok(msg: str) -> None: print(f"{G}✓{RESET} {msg}")
def warn(msg: str) -> None: print(f"{Y}!{RESET} {msg}")
def fail(msg: str) -> None: print(f"{R}✗{RESET} {msg}", file=sys.stderr)


# ─── .env reader (no python-dotenv dependency) ──────────────────────────
def read_env(name: str) -> str | None:
    """Pull a single key out of .env. Lightweight, no deps."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return os.environ.get(name)
    m = re.search(rf'^{re.escape(name)}\s*=\s*"?([^"\n]+)"?', env_path.read_text(), re.M)
    if m:
        return m.group(1).strip()
    return os.environ.get(name)


# ─── ESPN ───────────────────────────────────────────────────────────────
@dataclass
class Period:
    q: int       # 0-indexed period
    home: int
    away: int


@dataclass
class FinishedGame:
    league: str
    event_id: str
    short_name: str   # 'CLE @ DET'
    home_abbr: str
    away_abbr: str
    home_total: int
    away_total: int
    periods: list[Period]  # exactly LEAGUES[league]['numPeriods'] entries


def _http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "TezLiteApps-emulate-squares/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def _competitor_periods(competitor: dict) -> list[int]:
    """ESPN linescores per period — handle both scoreboard ({'value': 29})
    and summary ({'displayValue': '29'}) shapes."""
    out: list[int] = []
    for ls in (competitor.get("linescores") or []):
        raw = ls.get("value")
        if raw is None:
            raw = ls.get("displayValue", 0)
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            out.append(0)
    return out


def _parse_event(league: str, event: dict) -> FinishedGame | None:
    """Convert one ESPN event into a FinishedGame, or None if it isn't
    completed / doesn't have enough period data for the league."""
    comps = event.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    competitors = comp.get("competitors") or []
    if len(competitors) < 2:
        return None

    status = (event.get("status") or {}).get("type") or {}
    if not status.get("completed"):
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    home_ls = _competitor_periods(home)
    away_ls = _competitor_periods(away)
    n = LEAGUES[league]["numPeriods"]
    # Need at least `numPeriods` entries on each side. ESPN sometimes
    # reports OT/extra-innings as additional entries — those are folded
    # into the final regulation period below (no contract-side OT
    # support; the squares pool pays on the configured period count).
    if len(home_ls) < n or len(away_ls) < n:
        return None

    periods: list[Period] = []
    for q in range(n):
        h = home_ls[q]
        a = away_ls[q]
        if q == n - 1:
            # Roll any trailing OT/extra periods into the final period
            # so the "final" weight collects them — best-effort, mostly
            # affects NBA games that went to OT.
            h += sum(home_ls[n:])
            a += sum(away_ls[n:])
        periods.append(Period(q=q, home=h, away=a))

    home_team = (home.get("team") or {})
    away_team = (away.get("team") or {})
    return FinishedGame(
        league=league,
        event_id=str(event.get("id", "")),
        short_name=event.get("shortName") or event.get("name") or "?",
        home_abbr=home_team.get("abbreviation", "?"),
        away_abbr=away_team.get("abbreviation", "?"),
        home_total=int(home.get("score", 0) or 0),
        away_total=int(away.get("score", 0) or 0),
        periods=periods,
    )


def fetch_by_event_id(league: str, event_id: str) -> FinishedGame | None:
    path = LEAGUES[league]["espn_path"]
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary"
        f"?{urllib.parse.urlencode({'event': event_id})}"
    )
    try:
        payload = _http_get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    if not competitions:
        return None
    status = competitions[0].get("status") or header.get("status") or {}
    return _parse_event(league, {
        "id": header.get("id") or event_id,
        "shortName": header.get("shortName") or header.get("name"),
        "status": status,
        "competitions": competitions,
    })


def fetch_by_date(league: str, date_yyyymmdd: str) -> FinishedGame | None:
    """Scoreboard for `date`; return the first event for this league with
    a completed status and enough linescore data."""
    path = LEAGUES[league]["espn_path"]
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
        f"?{urllib.parse.urlencode({'dates': date_yyyymmdd})}"
    )
    payload = _http_get(url)
    for ev in payload.get("events") or []:
        g = _parse_event(league, ev)
        if g:
            return g
    return None


def find_recent_finished_game(league: str, max_back_days: int = 14) -> FinishedGame | None:
    """Walk back day by day from today, return the first finished game we
    can find. ESPN serves yesterday's slate even hours into a new day,
    so the first iteration usually hits."""
    from datetime import date, timedelta
    today = date.today()
    for d in range(0, max_back_days + 1):
        day = today - timedelta(days=d)
        try:
            g = fetch_by_date(league, day.strftime("%Y%m%d"))
        except Exception as e:  # noqa: BLE001 — ESPN flake is recoverable
            warn(f"  ESPN scoreboard {day}: {e!s:.120}")
            continue
        if g:
            return g
    return None


# ─── Constants.js parsing — read the deployed KT1 for the network ──────
def read_squares_address(network: str) -> str:
    text = CONSTANTS_PATH.read_text()
    var = f"SQUARES_CONTRACT_ADDRESS_{network.upper()}"
    m = re.search(rf'export const {var}\s*=\s*[\'\"]([^\'\"]+)[\'\"]', text)
    if not m:
        raise SystemExit(f"Couldn't find {var} in constants.js")
    addr = m.group(1)
    if addr.startswith("KT1XXX"):
        raise SystemExit(f"{var} is a placeholder ({addr}); deploy the squares contract first.")
    return addr


# ─── Wallets ───────────────────────────────────────────────────────────
def derive_secondary_mnemonic(primary_mnemonic: str) -> str:
    """Deterministic 24-word mnemonic generated from the primary mnemonic
    plus a fixed salt. Uses a SHA-256 of the joined string as entropy.

    Not for production — this is purely for shadownet emulation, so the
    secondary's "key custody" is just whoever has access to .env."""
    from mnemonic import Mnemonic
    entropy = hashlib.sha256(
        (primary_mnemonic.strip() + "|" + SECONDARY_SALT).encode()
    ).digest()  # 32 bytes → 24 words
    return Mnemonic("english").to_mnemonic(entropy)


def make_clients(network: str):
    """Returns (primary_pyt, secondary_pyt, primary_addr, secondary_addr)."""
    from pytezos import pytezos, Key
    primary_mnem = read_env("DEPLOY_MNEMONIC")
    if not primary_mnem:
        raise SystemExit("DEPLOY_MNEMONIC is not set in .env")
    primary_key = Key.from_mnemonic(primary_mnem.split())

    secondary_mnem = read_env("DEPLOY_MNEMONIC_2") or derive_secondary_mnemonic(primary_mnem)
    secondary_key = Key.from_mnemonic(secondary_mnem.split())

    rpc = RPCS[network]
    primary_pyt = pytezos.using(shell=rpc, key=primary_key)
    secondary_pyt = pytezos.using(shell=rpc, key=secondary_key)
    return (
        primary_pyt, secondary_pyt,
        primary_key.public_key_hash(), secondary_key.public_key_hash(),
    )


def balance_tez(client) -> float:
    try:
        bal = client.account(client.key.public_key_hash()).get("balance", "0")
        return int(bal) / 1_000_000
    except Exception:
        return 0.0


def ensure_funded(primary, secondary, secondary_addr: str, min_tez: float, dry_run: bool):
    """Top up the secondary wallet from primary if its balance is under
    min_tez. Idempotent — silently no-ops when already funded."""
    bal = balance_tez(secondary)
    if bal >= min_tez:
        info(f"secondary balance: {bal:.4f} ꜩ (≥ {min_tez:.2f}) — no top-up needed")
    else:
        need = Decimal(str(min_tez - bal + 0.05))  # +0.05 ꜩ slack for fees
        step(f"funding secondary: {primary.key.public_key_hash()[:12]}… → {secondary_addr[:12]}… ({need} ꜩ)")
        if dry_run:
            warn("  --dry-run set, skipping transfer")
            return
        op = primary.transaction(destination=secondary_addr, amount=need).send(min_confirmations=1)
        ok(f"  funded: {op.hash()[:14]}…  ({balance_tez(secondary):.4f} ꜩ now)")

    # Pytezos's contract.method().send() doesn't auto-prepend a Reveal
    # operation reliably on this RPC, so an unrevealed wallet that gets
    # funded above will fail its first buy with 'unrevealed_key'. Force
    # the reveal explicitly here — it's a no-op if already revealed.
    if dry_run:
        return
    try:
        op = secondary.reveal().autofill().sign().inject(min_confirmations=1)
        op_hash = getattr(op, "hash", None) or op.get("hash") if isinstance(op, dict) else None
        ok(f"  reveal: {(op_hash or '(no hash)')[:14]}…")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "already_revealed" in msg or "previously_revealed_key" in msg:
            info("  reveal: already on chain")
        else:
            warn(f"  reveal failed (continuing): {msg[:120]}")


# ─── Contract orchestration ─────────────────────────────────────────────
def open_contract(client, addr: str):
    return client.contract(addr)


def storage_via_tzkt(network: str, addr: str, gid: int) -> dict:
    """Read one game row out of the games big_map via tzkt. Pytezos's own
    storage() returns the bigmap id, not its contents, so we go around it."""
    url = f"{TZKT[network]}/v1/contracts/{addr}/bigmaps/games/keys/{gid}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.load(r)["value"]


def create_game(primary, contract, game: FinishedGame,
                ticket_mutez: int, fee_mutez: int, dry_run: bool) -> int:
    """createGame from the primary (admin) wallet. Returns the new gameId."""
    spec = LEAGUES[game.league]
    name = f"ESPN:{game.event_id} - {game.short_name}"
    step(f"createGame name={name!r}  numPeriods={spec['numPeriods']}  weights={spec['weights']}")
    if dry_run:
        warn("  --dry-run set, skipping send")
        return -1
    op = contract.createGame(
        name=name,
        ticketPrice=ticket_mutez,
        holderFee=fee_mutez,
        numPeriods=spec["numPeriods"],
        quarterWeights=spec["weights"],
    ).send(min_confirmations=1)
    gid = int(contract.storage()["currentGameId"]) - 1
    ok(f"  gameId={gid}  ({op.hash()[:14]}…)")
    return gid


def buy_out(primary, secondary, contract_primary, contract_secondary,
            gid: int, ticket_mutez: int, fee_mutez: int, dry_run: bool):
    """Buy every sellable square across the two wallets.

    Primary takes the first PER_PLAYER_CAP eligible cells (the contract's
    per-player-per-game limit), secondary fills the rest. Indices 44 and
    90 (house cells) are skipped entirely."""
    sellable = [i for i in range(100) if i not in HOUSE_CELLS]
    assert len(sellable) == SELLABLE_CELLS
    primary_idxs = sellable[:PER_PLAYER_CAP]
    secondary_idxs = sellable[PER_PLAYER_CAP:]
    per_op_mutez = ticket_mutez + fee_mutez
    amount = Decimal(per_op_mutez) / Decimal(1_000_000)

    step(f"primary buys {len(primary_idxs)} squares (idx 0..{primary_idxs[-1]})")
    step(f"secondary buys {len(secondary_idxs)} squares (idx {secondary_idxs[0]}..{secondary_idxs[-1]})")
    if dry_run:
        warn("  --dry-run set, skipping buys")
        return

    def batch_buy(client, contract, who: str, idxs: list[int]):
        # Tezos requires an account to reveal its public key on-chain
        # before signed ops can run. pytezos auto-appends a Reveal to a
        # *single* operation, but its bulk() builder doesn't — so a
        # freshly funded wallet hits 'contract.unrevealed_key' on its
        # first batch. Always send the first square as a single op to
        # piggyback the reveal, then bulk the remainder.
        if not idxs:
            return
        head = idxs[0]
        op = contract.buySquare(gameId=gid, squareIdx=head).with_amount(amount).send(
            min_confirmations=1
        )
        info(f"  {who} reveal+buy idx {head:>2}: {op.hash()[:14]}…")

        rest = idxs[1:]
        # Chunk into 20-op batches so we don't trip Tezos's hard.gas_limit.
        # 100 mutez × 20 ops is still <0.005 ꜩ per batch. Between batches
        # we sleep a beat — pytezos caches the wallet's nonce/counter on
        # the client, and a fresh bulk built right after a single op can
        # otherwise reuse the just-spent counter and trip a mempool
        # conflict ("conflicting operation, total fee of at least …").
        for chunk_start in range(0, len(rest), 20):
            chunk = rest[chunk_start:chunk_start + 20]
            for attempt in range(3):
                try:
                    bulk = client.bulk(*[
                        contract.buySquare(gameId=gid, squareIdx=i).with_amount(amount)
                        for i in chunk
                    ])
                    op = bulk.send(min_confirmations=1)
                    info(f"  {who} batch [{chunk[0]:>2}..{chunk[-1]:>2}]: {op.hash()[:14]}…")
                    break
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    if "conflicting operation" in msg or "counter_in_the_past" in msg or "counter_in_the_future" in msg:
                        wait = 6 * (attempt + 1)
                        warn(f"  {who} batch retry in {wait}s ({msg[:80]}…)")
                        time.sleep(wait)
                        continue
                    raise
            else:
                fail(f"  {who} batch [{chunk[0]:>2}..{chunk[-1]:>2}] gave up after 3 retries")
                raise SystemExit(2)

    batch_buy(primary, contract_primary, "primary  ", primary_idxs)
    batch_buy(secondary, contract_secondary, "secondary", secondary_idxs)


def set_axes(primary, contract, gid: int, seed: int, dry_run: bool):
    """Two random permutations of 0..9 for the home + away digit axes.
    Deterministic when `seed` is passed so re-runs reproduce."""
    rng = random.Random(seed)
    axis_home = list(range(10)); rng.shuffle(axis_home)
    axis_away = list(range(10)); rng.shuffle(axis_away)
    home_map = {i: axis_home[i] for i in range(10)}
    away_map = {i: axis_away[i] for i in range(10)}
    step(f"setAxes home={axis_home} away={axis_away}")
    if dry_run:
        warn("  --dry-run set, skipping send")
        return home_map, away_map
    op = contract.setAxes(gameId=gid, axisHome=home_map, axisAway=away_map).send(min_confirmations=1)
    ok(f"  {op.hash()[:14]}…")
    return home_map, away_map


def report_periods(primary, contract, gid: int, game: FinishedGame, dry_run: bool):
    """Walk the periods in order, call reportQuarter for each. The
    contract is deliberately permissive about ordering, so we go 0..N-1
    for predictable output."""
    for p in game.periods:
        step(f"reportQuarter q={p.q} {game.home_abbr}={p.home} {game.away_abbr}={p.away} "
             f"(digits home={p.home % 10} away={p.away % 10})")
        if dry_run:
            warn("  --dry-run set, skipping send")
            continue
        op = contract.reportQuarter(
            gameId=gid, quarter=p.q, homeScore=p.home, awayScore=p.away,
        ).send(min_confirmations=1)
        ok(f"  {op.hash()[:14]}…")


def summarize(network: str, contract_addr: str, gid: int, game: FinishedGame,
              home_map: dict[int, int], away_map: dict[int, int],
              primary_addr: str, secondary_addr: str):
    """Read the on-chain game + pending claims and pretty-print who won."""
    g = storage_via_tzkt(network, contract_addr, gid)
    spec = LEAGUES[game.league]
    squares = g["squares"]

    print()
    hr()
    print(f"  {B}Result · {game.league} · {game.short_name} (ESPN:{game.event_id}){RESET}")
    hr()
    info(f"phase={g['phase']}  pot remaining={int(g['pot'])} mutez  quartersDone={g['quartersDone']}")
    print()
    for p in game.periods:
        home_digit = p.home % 10
        away_digit = p.away % 10
        # Reverse the permutation: which row label maps to home_digit?
        win_row = next(k for k, v in home_map.items() if v == home_digit)
        win_col = next(k for k, v in away_map.items() if v == away_digit)
        win_idx = win_row * 10 + win_col
        owner = squares.get(str(win_idx)) or squares.get(win_idx)
        weight = spec["weights"][p.q]
        if owner is None:
            label = "(unowned — paid to TXL)"
        elif owner == primary_addr:
            label = f"PRIMARY  ({owner[:12]}…)"
        elif owner == secondary_addr:
            label = f"SECONDARY ({owner[:12]}…)"
        else:
            label = f"other ({owner[:12]}…)"
        print(f"  Q{p.q+1}  {game.home_abbr} {p.home:>3} / {game.away_abbr} {p.away:<3}"
              f"  digit({home_digit},{away_digit}) → cell {win_idx:>2}"
              f"  weight {weight:>2}%  →  {label}")
    print()

    # Pending payouts per buyer.
    for who, addr in [("primary", primary_addr), ("secondary", secondary_addr)]:
        try:
            url = f"{TZKT[network]}/v1/contracts/{contract_addr}/bigmaps/pending/keys/{addr}"
            with urllib.request.urlopen(url, timeout=15) as r:
                row = json.load(r)
            credit = int(row["value"])
            tz = credit / 1_000_000
            print(f"  pending[{who}] = {credit} mutez ({tz:.6f} ꜩ)")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  pending[{who}] = 0")
            else:
                raise


# ─── CLI ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--league", choices=list(LEAGUES.keys()), default="NBA")
    ap.add_argument("--event-id", help="ESPN event id (skip the scoreboard lookup)")
    ap.add_argument("--date", help="YYYYMMDD to search a slate for a finished game")
    ap.add_argument("--network", choices=list(RPCS.keys()), default="shadownet")
    ap.add_argument("--ticket-price-mutez", type=int, default=DEFAULT_TICKET_MUTEZ)
    ap.add_argument("--holder-fee-mutez", type=int, default=DEFAULT_HOLDER_FEE_MUTEZ)
    ap.add_argument("--axes-seed", type=int, default=42,
                    help="Deterministic seed for setAxes permutations (default 42)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print every action but never sign / send")
    args = ap.parse_args()

    if args.network == "mainnet" and not args.dry_run:
        warn("Running on MAINNET. Press Ctrl-C in 3s to abort.")
        try: time.sleep(3)
        except KeyboardInterrupt: sys.exit(130)

    # ─── 1. ESPN ────────────────────────────────────────────────────
    hr(); print(f"  {B}Emulating Squares — {args.league}{RESET}"); hr()

    step("fetching game from ESPN…")
    if args.event_id:
        g = fetch_by_event_id(args.league, args.event_id)
    elif args.date:
        g = fetch_by_date(args.league, args.date)
    else:
        g = find_recent_finished_game(args.league)
    if not g:
        fail(f"No finished {args.league} game found. Pass --event-id or --date.")
        sys.exit(1)

    ok(f"{g.short_name}  ESPN:{g.event_id}  final {g.home_total}-{g.away_total}")
    for p in g.periods:
        info(f"Q{p.q+1}: {g.home_abbr} {p.home}  /  {g.away_abbr} {p.away}")

    # ─── 2. wallets + funding ───────────────────────────────────────
    print(); step("setting up wallets…")
    primary, secondary, primary_addr, secondary_addr = make_clients(args.network)
    info(f"primary   = {primary_addr}  ({balance_tez(primary):.3f} ꜩ)")
    info(f"secondary = {secondary_addr}  ({balance_tez(secondary):.3f} ꜩ)")

    # Per-op cost ≈ ticket+fee + ~1000 mutez of gas. Reserve enough
    # for the secondary's share + slack.
    per_op_mutez = args.ticket_price_mutez + args.holder_fee_mutez
    secondary_need_tez = max(0.2, (per_op_mutez * (SELLABLE_CELLS - PER_PLAYER_CAP)) / 1_000_000 + 0.10)
    ensure_funded(primary, secondary, secondary_addr, secondary_need_tez, args.dry_run)

    # ─── 3. contract orchestration ──────────────────────────────────
    contract_addr = read_squares_address(args.network)
    info(f"squares   = {contract_addr}")
    c_primary = open_contract(primary, contract_addr)
    c_secondary = open_contract(secondary, contract_addr)
    print()

    step("createGame")
    gid = create_game(primary, c_primary, g, args.ticket_price_mutez,
                      args.holder_fee_mutez, args.dry_run)

    print()
    step("buy out the board")
    buy_out(primary, secondary, c_primary, c_secondary, gid,
            args.ticket_price_mutez, args.holder_fee_mutez, args.dry_run)

    # In dry-run mode skip the rest — without a real gid setAxes etc.
    # would just try to push placeholders against the chain.
    if args.dry_run:
        warn("--dry-run: skipping setAxes / reportQuarter / summary.")
        return

    # Auto-lock should have fired at sold == 98. Confirm before setAxes.
    print()
    step("verifying auto-lock fired")
    on_chain = storage_via_tzkt(args.network, contract_addr, gid)
    if int(on_chain["sold"]) != SELLABLE_CELLS:
        fail(f"unexpected sold count: {on_chain['sold']} (wanted {SELLABLE_CELLS})")
        sys.exit(2)
    if int(on_chain["phase"]) != 1:
        fail(f"auto-lock didn't fire — phase={on_chain['phase']} after sell-out (expected 1=LOCKED)")
        sys.exit(2)
    ok(f"sold={on_chain['sold']}  phase={on_chain['phase']} (LOCKED)")

    print()
    step("setAxes (admin)")
    home_map, away_map = set_axes(primary, c_primary, gid, args.axes_seed, args.dry_run)

    print()
    step("reportQuarter for every period (admin)")
    report_periods(primary, c_primary, gid, g, args.dry_run)

    # ─── 4. summary ─────────────────────────────────────────────────
    summarize(args.network, contract_addr, gid, g, home_map, away_map,
              primary_addr, secondary_addr)
    print()
    ok("Done. Inspect on tzkt:")
    info(f"  https://{args.network}.tzkt.io/{contract_addr}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        fail("aborted")
        sys.exit(130)
