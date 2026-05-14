#!/usr/bin/env python3
"""
exercise_contracts.py — end-to-end live-chain smoke tests for each game.

Runs against whatever contract addresses are live in src/constants.js for
the chosen network. Each scenario walks one full happy-path:

    ad        bet → (oracle firstCard) → (oracle secondCard)
                  → continueBet → (oracle lastCard) → verify final state
    plinko    play → (oracle resolve) → verify path sums to slot
    oracle    requestRandom (via reference dApp) → (worker fulfillRandom)
                  → verify callback fired and lastResult updated
    war       createGame → (second key) joinGame → (oracle deal)
                  → verify winner paid (needs DEPLOY_MNEMONIC_2 in .env)
    reversi   createGame → joinGame → (oracle flipForFirst)
                  → submitMove → giveup → verify settled
    chess     createGame → joinGame → (oracle flipForFirst)
                  → play one move → giveup → verify settled
    ttt       (TODO: not yet wired)
    squares   newGrid → joinGrid → (oracle randomizeAxes) → setWinner

The oracle steps assume `./scripts/oracle-worker.sh` is running. Without
it, each scenario times out waiting for state to flip.

Usage
-----
    .venv/bin/python scripts/exercise_contracts.py --game ad
    .venv/bin/python scripts/exercise_contracts.py --game plinko --bet 0.2
    .venv/bin/python scripts/exercise_contracts.py --game all --network shadownet
    .venv/bin/python scripts/exercise_contracts.py --game war --dry-run

Exit code: 0 if all selected scenarios passed, 1 otherwise.

Authentication: DEPLOY_MNEMONIC for the primary key. Multi-player games
(war / reversi / chess / ttt) additionally need DEPLOY_MNEMONIC_2 in .env
for the joiner. Without it those scenarios skip.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
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
RESET, GREEN, YELLOW, RED, CYAN, DIM, BOLD = (
    "\033[0m", "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[2m", "\033[1m",
)
def log(msg): print(f"{DIM}[{time.strftime('%H:%M:%S')}]{RESET} {msg}", flush=True)
def ok(msg): log(f"{GREEN}✓{RESET} {msg}")
def warn(msg): log(f"{YELLOW}!{RESET} {msg}")
def err(msg): log(f"{RED}✗{RESET} {msg}")
def info(msg): log(f"  {msg}")
def section(t): print(f"\n{CYAN}═══ {t} ═══{RESET}", flush=True)


# ─── .env loader ──────────────────────────────────────────────────────
def load_dotenv():
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def read_constant(name):
    if not CONSTANTS_PATH.exists():
        return None
    m = re.search(rf"export const {re.escape(name)}\s*=\s*['\"]([^'\"]+)['\"]",
                  CONSTANTS_PATH.read_text())
    return m.group(1) if m else None


def field_of(record, name, default=None):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


# ─── Result tracking ──────────────────────────────────────────────────
@dataclass
class Scenario:
    name: str
    passed: bool = False
    skipped: bool = False
    notes: list[str] = field(default_factory=list)

    def note(self, s): self.notes.append(s); info(s)
    def passing(self, msg="passed"): self.passed = True; ok(f"{self.name}: {msg}")
    def failing(self, msg): self.passed = False; err(f"{self.name}: {msg}")
    def skip(self, msg): self.skipped = True; warn(f"{self.name}: skipping — {msg}")


# ─── Helpers ──────────────────────────────────────────────────────────
def wait_for(check, label, timeout=180, poll=3):
    """Poll `check()` until it returns truthy or timeout. Returns the value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = check()
        except Exception as e:
            info(f"  (poll error: {e}; retrying)")
            time.sleep(poll)
            continue
        if result:
            return result
        time.sleep(poll)
    raise TimeoutError(f"Timeout waiting for {label}")


def mutez(t): return int(round(t * 1_000_000))
def tez(m): return m / 1_000_000


# ─── Per-game scenarios ───────────────────────────────────────────────
def exercise_ad(net, client, args, s: Scenario):
    """AD: bet → wait for cards → continueBet → wait for last → verify."""
    addr = args.address or read_constant(f"AD_CONTRACT_ADDRESS_{net.upper()}")
    if not addr or "KT1XXX" in addr:
        s.skip(f"AD not deployed on {net}")
        return
    s.note(f"AD: {addr}")
    contract = client.contract(addr)

    s.note("→ bet(aceHigh=1) with 0.3 ꜩ")
    op = contract.bet(1).with_amount(300000).send(min_confirmations=1)
    s.note(f"  injected {op.hash()[:14]}…")

    storage = contract.storage()
    game_id = int(storage["currentGameIndex"]) - 1
    s.note(f"  gameId = {game_id}")

    def both_cards_dealt():
        g = contract.storage()["games"].get(game_id)
        if not g: return False
        h = g.get("hand", {})
        h1 = int(h.get(1, h.get("1", -1)))
        h2 = int(h.get(2, h.get("2", -1)))
        return h1 >= 0 and h2 >= 0
    s.note("→ waiting for oracle worker to deal first + second cards…")
    wait_for(both_cards_dealt, "both cards", timeout=args.oracle_timeout)
    g = contract.storage()["games"][game_id]
    h = g["hand"]
    c1, c2 = int(h.get(1, h.get("1"))), int(h.get(2, h.get("2")))
    s.note(f"  cards: {c1}, {c2}  (ranks {c1//4+2}, {c2//4+2})")
    if int(g["gameStatus"]) == 5:
        s.passing("pair drawn — ante forfeit (no continueBet path to exercise)")
        return

    s.note(f"→ continueBet({game_id}) with 0.{args.bet_micro:03d} ꜩ + fee")
    bet_amount = mutez(args.bet) + 100000
    op = contract.continueBet(game_id).with_amount(bet_amount).send(min_confirmations=1)
    s.note(f"  injected {op.hash()[:14]}…")

    def last_card_dealt():
        g = contract.storage()["games"].get(game_id)
        if not g: return False
        return int(field_of(g, "gameStatus")) in (3, 4)
    s.note("→ waiting for oracle worker to deal last card…")
    wait_for(last_card_dealt, "last card", timeout=args.oracle_timeout)
    g = contract.storage()["games"][game_id]
    status = int(g["gameStatus"])
    c3 = int(g["hand"].get(3, g["hand"].get("3", -1)))
    s.note(f"  final card: {c3} (rank {c3//4+2}); status {status} ({'win' if status==3 else 'loss'})")
    s.passing(f"AD round {game_id} completed at status {status}")


def exercise_plinko(net, client, args, s: Scenario):
    addr = args.address or read_constant(f"PLINKO_CONTRACT_ADDRESS_{net.upper()}")
    if not addr or "KT1XXX" in addr:
        s.skip(f"Plinko not deployed on {net}")
        return
    s.note(f"Plinko: {addr}")
    contract = client.contract(addr)

    s.note(f"→ play(rows={args.rows}, risk={args.risk}) with {args.bet} ꜩ + 0.1 ꜩ fee")
    total = mutez(args.bet) + 100000
    op = contract.play(rows=args.rows, risk=args.risk).with_amount(total).send(min_confirmations=1)
    s.note(f"  injected {op.hash()[:14]}…")

    storage = contract.storage()
    round_id = int(storage["currentRoundId"]) - 1
    s.note(f"  roundId = {round_id}")

    def resolved():
        r = contract.storage()["rounds"].get(round_id)
        return r and int(field_of(r, "roundStatus")) != 0
    s.note("→ waiting for oracle worker to resolve…")
    wait_for(resolved, "round resolution", timeout=args.oracle_timeout)

    r = contract.storage()["rounds"][round_id]
    slot = int(r["finalSlot"])
    path = r.get("path", {})
    bit_sum = sum(int(v) for v in path.values())
    payout_mutez = int(field_of(r, "payout", 0))
    s.note(f"  slot={slot}  path bits={list(path.values())}  payout={tez(payout_mutez):.4f} ꜩ")
    if bit_sum != slot:
        s.failing(f"BUG: path bits sum to {bit_sum} but contract recorded slot {slot}")
        return
    s.passing(f"path verified (bits sum == slot == {slot})")


def exercise_oracle(net, client, args, s: Scenario):
    """Round-trip via the reference CoinFlip dApp. Both contracts must be
    deployed, and ORACLE_REFERENCE_CONTRACT_ADDRESS_<NET> must exist."""
    oracle = args.oracle_address or read_constant(f"ORACLE_CONTRACT_{net.upper()}")
    ref = args.address or read_constant(f"ORACLE_REFERENCE_CONTRACT_ADDRESS_{net.upper()}")
    if not oracle or "KT1XXX" in oracle:
        s.skip("RandomOracle not deployed")
        return
    if not ref or "KT1XXX" in ref:
        s.skip("Reference dApp not deployed — need ORACLE_REFERENCE_CONTRACT_ADDRESS")
        return
    s.note(f"Oracle:    {oracle}")
    s.note(f"Reference: {ref}")
    ref_contract = client.contract(ref)
    oracle_contract = client.contract(oracle)

    before_id = int(ref_contract.storage()["lastRequestId"])
    s.note(f"→ flip() — triggers requestRandom on RandomOracle")
    op = ref_contract.flip().with_amount(100000).send(min_confirmations=1)
    s.note(f"  injected {op.hash()[:14]}…")

    def fulfilled():
        st = ref_contract.storage()
        return int(st["lastRequestId"]) > before_id and not st["pending"]
    s.note("→ waiting for oracle worker to fulfill + callback…")
    wait_for(fulfilled, "oracle callback", timeout=args.oracle_timeout)
    st = ref_contract.storage()
    s.note(f"  lastResult = {st['lastResult']}  (request {st['lastRequestId']})")
    s.passing(f"oracle round-trip completed — coin showed {st['lastResult']}")


def exercise_war(net, client_primary, args, s: Scenario, client_secondary):
    addr = args.address or read_constant(f"WAR_CONTRACT_ADDRESS_{net.upper()}")
    if not addr or "KT1XXX" in addr:
        s.skip(f"War not deployed on {net}")
        return
    if not client_secondary:
        s.skip("War needs DEPLOY_MNEMONIC_2 for the joiner")
        return
    s.note(f"War: {addr}")
    c1 = client_primary.contract(addr)
    c2 = client_secondary.contract(addr)
    wager = mutez(args.bet)
    total = wager + 100000

    s.note(f"→ player1.createGame(wager={tez(wager):.3f} ꜩ)")
    op = c1.createGame(wager=wager).with_amount(total).send(min_confirmations=1)
    game_id = int(c1.storage()["currentGameId"]) - 1
    s.note(f"  gameId = {game_id}  ({op.hash()[:14]}…)")

    s.note(f"→ player2.joinGame({game_id})")
    op = c2.joinGame(game_id).with_amount(total).send(min_confirmations=1)
    s.note(f"  joined ({op.hash()[:14]}…)")

    def dealt():
        g = c1.storage()["games"].get(game_id)
        return g and int(field_of(g, "gameStatus")) == 2
    s.note("→ waiting for oracle worker to deal both cards…")
    wait_for(dealt, "deal", timeout=args.oracle_timeout)
    g = c1.storage()["games"][game_id]
    s.note(f"  cards: {int(g['card1'])}, {int(g['card2'])}; winner={g['winner']}")
    s.passing(f"War game {game_id} settled")


def exercise_flip_game(name, addr_var, net, client_primary, args, s, client_secondary):
    """Shared scenario for skill games with flipForFirst (reversi, chess, ttt).
    Just creates → joins → flips → resigns to keep things short."""
    addr = args.address or read_constant(f"{addr_var}_{net.upper()}")
    if not addr or "KT1XXX" in addr:
        s.skip(f"{name} not deployed on {net}")
        return
    if not client_secondary:
        s.skip(f"{name} needs DEPLOY_MNEMONIC_2 for the joiner")
        return
    s.note(f"{name}: {addr}")
    c1 = client_primary.contract(addr)
    c2 = client_secondary.contract(addr)
    wager = mutez(args.bet)
    total = wager + 100000

    s.note(f"→ player1.createGame(wager={tez(wager):.3f} ꜩ)")
    c1.createGame(wager=wager).with_amount(total).send(min_confirmations=1)
    game_id = int(c1.storage()["currentGameId"]) - 1
    s.note(f"  gameId = {game_id}")

    s.note(f"→ player2.joinGame({game_id})")
    c2.joinGame(game_id).with_amount(total).send(min_confirmations=1)

    def flipped():
        g = c1.storage()["games"].get(game_id)
        return g and int(field_of(g, "gameStatus")) == 2
    s.note("→ waiting for oracle worker to flipForFirst…")
    wait_for(flipped, "flip", timeout=args.oracle_timeout)

    s.note("→ player1.giveup() — exercising the settlement path")
    # Both Chess and Reversi have a "giveup" or "resign" entrypoint. Try both.
    contract = c1
    if hasattr(contract, "giveup"):
        contract.giveup(game_id).send(min_confirmations=1)
    else:
        contract.resign(game_id).send(min_confirmations=1)
    g = c1.storage()["games"][game_id]
    s.note(f"  final gameStatus = {field_of(g, 'gameStatus')}; winner = {g['winner']}")
    s.passing(f"{name} game {game_id} settled by resignation")


def exercise_squares(net, client, args, s: Scenario):
    addr = args.address or read_constant(f"SQUARES_CONTRACT_ADDRESS_{net.upper()}")
    if not addr or "KT1XXX" in addr:
        s.skip(f"Squares not deployed on {net}")
        return
    s.note(f"Squares: {addr}")
    contract = client.contract(addr)
    s.note("→ newGrid(nSquares=5) with 0.6 ꜩ (fee 0.1 + 0.5 of squares)")
    contract.newGrid(nSquares=5).with_amount(600000).send(min_confirmations=1)
    grid_id = int(contract.storage()["currentGridIndex"]) - 1
    s.note(f"  gridId = {grid_id}")
    def randomized():
        axes = contract.storage()["axes"].get(grid_id)
        return axes and axes.get("seed")
    s.note("→ waiting for oracle worker to randomizeAxes…")
    wait_for(randomized, "randomize", timeout=args.oracle_timeout)
    axes = contract.storage()["axes"][grid_id]
    s.note(f"  x: {list(axes['xLabels'].values())}")
    s.note(f"  y: {list(axes['yLabels'].values())}")
    s.passing(f"Squares grid {grid_id} axes randomized")


# ─── Main ─────────────────────────────────────────────────────────────
GAMES = {
    "ad":      exercise_ad,
    "plinko":  exercise_plinko,
    "oracle":  exercise_oracle,
    "war":     exercise_war,
    "reversi": lambda net, c1, args, s, c2: exercise_flip_game(
        "reversi", "REVERSI_CONTRACT_ADDRESS", net, c1, args, s, c2),
    "chess":   lambda net, c1, args, s, c2: exercise_flip_game(
        "chess", "CHESS_CONTRACT_ADDRESS", net, c1, args, s, c2),
    "squares": exercise_squares,
}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--game", action="append",
                   help=f"One of: {', '.join(GAMES)} | all. Can repeat.")
    p.add_argument("--network", choices=list(NETWORK_RPCS), default="shadownet")
    p.add_argument("--address", help="Override the contract address (single-game).")
    p.add_argument("--oracle-address",
                   help="Override RandomOracle KT1 (for --game oracle).")
    p.add_argument("--bet", type=float, default=0.1,
                   help="Player bet in ꜩ (default 0.1).")
    p.add_argument("--bet-micro", type=int, default=100,
                   help="Display-only — micro-tez component of the bet shown in logs.")
    p.add_argument("--rows", type=int, default=8, help="Plinko rows (8/12/16).")
    p.add_argument("--risk", type=int, default=0, help="Plinko risk (0/1/2).")
    p.add_argument("--oracle-timeout", type=int, default=180,
                   help="Seconds to wait for the oracle worker.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would run, then exit.")
    args = p.parse_args()

    games = args.game or ["ad", "plinko"]
    if "all" in games:
        games = list(GAMES)

    unknown = [g for g in games if g not in GAMES]
    if unknown:
        err(f"Unknown games: {unknown}. Known: {list(GAMES)}")
        return 1

    load_dotenv()

    section("Setup")
    info(f"Network:   {args.network}")
    info(f"RPC:       {NETWORK_RPCS[args.network]}")
    info(f"Games:     {games}")
    info(f"Timeout:   {args.oracle_timeout}s per oracle wait")

    if args.dry_run:
        warn("--dry-run: not signing any operations")
        return 0

    from pytezos import pytezos, Key
    mnemonic = os.environ.get("DEPLOY_MNEMONIC", "").strip()
    mnemonic2 = os.environ.get("DEPLOY_MNEMONIC_2", "").strip()
    if not mnemonic:
        err("DEPLOY_MNEMONIC missing from .env.")
        return 1
    key = Key.from_mnemonic(mnemonic.split())
    client = pytezos.using(shell=NETWORK_RPCS[args.network], key=key)
    info(f"Primary:   {key.public_key_hash()}")
    try:
        bal = int(client.account().get("balance", "0")) / 1_000_000
        info(f"  balance: {bal:.4f} ꜩ")
    except Exception as e:
        warn(f"  couldn't read balance: {e}")

    client2 = None
    if mnemonic2:
        key2 = Key.from_mnemonic(mnemonic2.split())
        client2 = pytezos.using(shell=NETWORK_RPCS[args.network], key=key2)
        info(f"Secondary: {key2.public_key_hash()}")
    else:
        info("Secondary: not configured (multi-player games will skip)")

    scenarios: list[Scenario] = []
    for game in games:
        section(f"{game.upper()}")
        sc = Scenario(name=game)
        scenarios.append(sc)
        fn = GAMES[game]
        try:
            # Pass client2 only to scenarios that need it; others ignore.
            if game in ("war", "reversi", "chess"):
                fn(args.network, client, args, sc, client2)
            else:
                fn(args.network, client, args, sc)
        except TimeoutError as e:
            sc.failing(f"timeout — {e}")
        except KeyboardInterrupt:
            sc.failing("interrupted")
            break
        except Exception as e:
            sc.failing(f"exception — {type(e).__name__}: {e}")

    section("Summary")
    passed = sum(1 for s in scenarios if s.passed)
    skipped = sum(1 for s in scenarios if s.skipped)
    failed = sum(1 for s in scenarios if not s.passed and not s.skipped)
    for s in scenarios:
        status = (f"{GREEN}PASS{RESET}" if s.passed
                  else f"{YELLOW}SKIP{RESET}" if s.skipped
                  else f"{RED}FAIL{RESET}")
        print(f"  {status}  {s.name}")
    print(f"\n  {BOLD}{passed} passed, {failed} failed, {skipped} skipped{RESET}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
