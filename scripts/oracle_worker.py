#!/usr/bin/env python3
"""
oracle_worker.py — off-chain oracle for the Acey-Duecey contract.

What it does
------------
Polls AD's on-chain storage every few seconds. For each game it finds:

  status == 0  AND  hand[1] == -1                 → call firstCard
  status == 0  AND  hand[1] >= 0 AND hand[2] == -1 → call secondCard
  status == 2  (player has placed continueBet)    → call lastCard

Each call picks a uniform-random deck index 0..51 and tags it with a hex
hash so the operation is traceable. The worker only acts on its OWN
games (i.e. ones it's authorised to advance) — it reads AD.storage.oracle
once at startup and bails if our key doesn't match.

Why this exists
---------------
The AD contract trusts a single tz1 address (stored in `oracle`) to
deliver cards. The dApp UI exposes manual "Deal first card" buttons for
that role, but during real play you don't want a human in the loop. This
worker is the production-style equivalent: a daemon that sees a new game
and advances it within a few seconds, no clicks required.

Design notes
------------
- *Stateless across runs.* All decisions come from re-reading on-chain
  storage. Restart anytime — the worker will pick up wherever the chain
  left off. No local DB, no journal.
- *Single-threaded.* Tezos rejects a second operation from the same
  address while one is still in the mempool, so we use sequential
  `.send(min_confirmations=1)` calls. With shadownet's ~15-second block
  time that means at most ~4 actions per minute per worker. Plenty.
- *Reads AD address from constants.js* so it always matches whatever the
  dApp is pointing at (you don't have to update two places after a
  redeploy).
- *Pure functions where possible.* `next_action_for_game()` decides what
  to do from a game record; tests can call it directly without RPC.

Usage
-----
    ./scripts/oracle-worker.sh              # default — runs forever
    ./scripts/oracle-worker.sh --once       # process one poll cycle then exit
    ./scripts/oracle-worker.sh --poll 3     # 3-second poll interval
    ./scripts/oracle-worker.sh --dry-run    # log what it WOULD do, no signing

    # Override the AD address from the command line (otherwise we read
    # AD_CONTRACT_ADDRESS_SHADOWNET / _MAINNET from src/constants.js):
    ./scripts/oracle-worker.sh --address KT1...

Authentication: same as deploy.py — DEPLOY_MNEMONIC in .env. (The wallet
that mnemonic derives must be the one set as storage.oracle for AD,
otherwise every call will fail with `notOracleADFirst2C` etc.)
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

# ─── Project paths ────────────────────────────────────────────────────
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


# ─── Pure decision function — easy to test ───────────────────────────
@dataclass
class NextAction:
    entrypoint: str          # 'firstCard' | 'secondCard' | 'lastCard'
    game_id: int             # contract's monotonic gameId
    card: int                # random deck index 0..51
    hash: str                # tag string for traceability

def next_action_for_game(game_id: int, game: dict) -> NextAction | None:
    """Inspect one game record and decide whether the oracle should act.

    Returns a NextAction to submit, or None if the game doesn't need
    oracle help right now (already advanced, or finished).

    `game` is the dict tzkt/pytezos returns for storage.games[gid].
    Card slots live under `hand` as a map keyed by 1/2/3. tzkt returns
    int values as strings, so coerce."""
    def slot(key: int) -> int:
        h = game.get("hand", {}) or {}
        raw = h.get(key, h.get(str(key), -1))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return -1

    status = int(game.get("gameStatus", 0))
    h1 = slot(1)
    h2 = slot(2)

    if status == 0 and h1 == -1:
        return _build_action("firstCard", game_id)
    if status == 0 and h1 >= 0 and h2 == -1:
        return _build_action("secondCard", game_id)
    if status == 2:
        return _build_action("lastCard", game_id)

    # status 1 (awaiting player's continueBet) — not our problem.
    # status 3 / 4 / 5 — finished. Ignore.
    return None


def _build_action(entrypoint: str, game_id: int) -> NextAction:
    """Pick a random card + a unique tag for traceability."""
    card = secrets.randbelow(52)
    hash_tag = f"{entrypoint}-{secrets.token_hex(6)}"
    return NextAction(entrypoint=entrypoint, game_id=int(game_id), card=card, hash=hash_tag)


# ─── Main loop ────────────────────────────────────────────────────────
class Worker:
    def __init__(self, args):
        from pytezos import pytezos, Key
        from pytezos.crypto.key import Key as _UnusedKey   # silence unused-warnings
        del _UnusedKey

        self.args = args
        self.network = args.network
        self.rpc = NETWORK_RPCS[self.network]
        self.tzkt = TZKT_HOSTS[self.network]

        # Address: explicit override > constants.js per-network entry
        addr_var = f"AD_CONTRACT_ADDRESS_{self.network.upper()}"
        self.contract_address = args.address or read_constant(addr_var)
        if not self.contract_address or "KT1XXX" in self.contract_address:
            die(f"No usable AD contract address. Looked up {addr_var} in "
                f"constants.js (got: {self.contract_address!r}). "
                f"Pass --address KT1... explicitly if needed.")

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

        self.contract = self.client.contract(self.contract_address)
        self.stopping = False

    def announce(self):
        section("Oracle worker — Acey-Duecey")
        info(f"Network:  {self.network}")
        info(f"RPC:      {self.rpc}")
        info(f"Contract: {self.contract_address}")
        info(f"Explorer: https://{self.tzkt}/{self.contract_address}")
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
        """Sanity check: storage.oracle must match our key. If not, every
        deal would fail. Bail loudly so the user knows to update the
        oracle address (via the contract's updateOracle entrypoint or a
        redeploy)."""
        try:
            storage = self.contract.storage()
        except Exception as e:
            err(f"Couldn't read contract storage: {e}")
            return False

        on_chain_oracle = storage.get("oracle", "") if isinstance(storage, dict) else getattr(storage, "oracle", "")
        if self.args.dry_run:
            info(f"storage.oracle = {on_chain_oracle}")
            return True

        my_addr = self.key.public_key_hash()
        if (on_chain_oracle or "").lower() != my_addr.lower():
            err(f"Authorisation mismatch.")
            err(f"  storage.oracle = {on_chain_oracle}")
            err(f"  my key         = {my_addr}")
            err(f"  Either update AD.storage.oracle to my address, or run this")
            err(f"  worker with the key that matches the current oracle address.")
            return False

        ok(f"Authorised as the AD oracle ({my_addr})")
        return True

    def one_pass(self) -> int:
        """Single poll cycle. Returns number of actions submitted."""
        try:
            storage = self.contract.storage()
        except Exception as e:
            err(f"Storage poll failed: {e}")
            return 0

        games = storage.get("games", {}) if isinstance(storage, dict) else getattr(storage, "games", {})

        # Walk every game and act on the first one that needs help. We
        # do at most one action per pass to keep ops serial and let the
        # next poll see the chain-of-effects from this one.
        for raw_id, game in games.items():
            try:
                gid = int(raw_id)
            except (TypeError, ValueError):
                continue
            action = next_action_for_game(gid, game)
            if not action:
                continue
            return self._submit_action(action)

        return 0

    def _submit_action(self, action: NextAction) -> int:
        label = f"game {action.game_id:>3} → {action.entrypoint}(card={action.card})"

        if self.args.dry_run:
            warn(f"DRY-RUN: would submit {label}  tag={action.hash}")
            return 0

        info(f"Submitting {label}  tag={action.hash}")
        try:
            # PyTezos exposes each entrypoint as an attribute on the
            # contract proxy — there's no `.methodsObject[name]` accessor
            # like Taquito. We have the entrypoint name as a string, so
            # grab it via getattr.
            entrypoint_fn = getattr(self.contract, action.entrypoint)
            op = entrypoint_fn(
                card=action.card,
                gameId=action.game_id,
                hash=action.hash,
            ).send(min_confirmations=1)
            # PyTezos returns an OperationGroup whose injected hash is on
            # `.hash`; some versions surface it as `opg_hash`.
            op_hash = (
                getattr(op, "hash", None)
                or getattr(op, "opg_hash", None)
                or "(unknown)"
            )
            ok(f"  confirmed — {op_hash}")
            info(f"  https://{self.tzkt}/{op_hash}")
            return 1
        except Exception as e:
            msg = str(e)
            if any(s in msg.lower() for s in ("bad game", "notoracle", "previously")):
                warn(f"  contract rejected: {msg[:140]}")
                warn(f"  (race with another oracle, or game advanced between "
                     f"poll and submit — will re-check next cycle)")
            else:
                err(f"  submit failed: {msg[:200]}")
            return 0

    def loop(self):
        if not self.check_authorised():
            sys.exit(2)

        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        cycles = 0
        actions_total = 0
        while not self.stopping:
            cycles += 1
            n = self.one_pass()
            actions_total += n
            if n == 0:
                # Tighter polling when idle so users don't wait forever
                # for the first action after they place a bet.
                pass
            if self.args.once:
                ok(f"--once: {actions_total} action(s) in 1 cycle. Exiting.")
                return
            # Wait, but split into short slices so SIGINT lands fast.
            for _ in range(self.args.poll * 4):
                if self.stopping: break
                time.sleep(0.25)
        ok(f"Stopped after {cycles} cycle(s), {actions_total} action(s) submitted.")

    def _on_signal(self, signum, _frame):
        warn(f"Caught signal {signum} — finishing current cycle and exiting.")
        self.stopping = True


# ─── helpers ──────────────────────────────────────────────────────────
def die(msg: str, code: int = 1):
    err(msg)
    sys.exit(code)


# ─── Entry ────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(
        description="Off-chain oracle daemon for the Acey-Duecey contract.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage")[1] if "Usage" in __doc__ else "",
    )
    p.add_argument("--network", choices=list(NETWORK_RPCS), default="shadownet")
    p.add_argument("--address", help="Override the AD contract address "
                                     "(default: AD_CONTRACT_ADDRESS_<NETWORK> in constants.js)")
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
