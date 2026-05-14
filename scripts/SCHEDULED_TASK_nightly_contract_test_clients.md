# Scheduled Task: nightly-contract-test-clients

This file describes a recurring task that should run nightly at **3:00 AM local time**
to write Python test clients against the deployed TezLiteApps Tezos contracts.

## Why this exists as a markdown file

It was drafted from inside a scheduled-task session, which is not allowed to create
new scheduled tasks. To register the schedule, open a fresh (non-scheduled) Claude
chat and paste a message like:

> Schedule a recurring task with cron `0 3 * * *`, taskId `nightly-contract-test-clients`,
> notifyOnCompletion=true, and the prompt from
> `/Users/benjaminwestbrook/Repositories/TezLiteApps/scripts/SCHEDULED_TASK_nightly_contract_test_clients.md`
> (the section labeled "Prompt" below).

Claude in that fresh session will use the `create_scheduled_task` tool with these
parameters.

## Schedule

- **cronExpression:** `0 3 * * *`  (every day at 3:00 AM local time)
- **taskId:** `nightly-contract-test-clients`
- **notifyOnCompletion:** `true`

## Description (one-line)

Nightly: write as many Python test clients as possible for the deployed
TezLiteApps Tezos contracts.

## Prompt

Write as many Python test clients as possible for the deployed TezLiteApps Tezos
contracts. Work autonomously — the user is asleep and will not answer questions.
Run until you have exhausted the contract list, the test ideas, or your token
budget. Whichever comes first.

### Context

Repository: `/Users/benjaminwestbrook/Repositories/TezLiteApps` (a Vue + SmartPy
gambling games dApp on Tezos).

Smart contracts (SmartPy source) live in `src/services/`:
- `smart_contractChess.py` — H2H chess with wager + house cut (per-game lobby, modern @sp.module)
- `smart_contract_TTT.py` — TezTacToe 4×4×4 connect-4 with wager + house cut
- `smart_contractReversi.py` — Reversi/Othello H2H with wager
- `smart_contractAD.py` — Acey Duecey card gambling
- `smart_contractPlinko.py` — Single-player Plinko with seed-based multipliers
- `smart_contractWar.py` — High-card war H2H
- `smart_contract_squares.py` — Squares grid game
- `smart_contract_oracle.py` — Oracle that signs/feeds randomness
- `smart_contract_txl.py` — TXL holder reward distributor (the "house" beneficiary)

Deployed contract addresses are in `src/constants.js` — search for constants
matching `*_CONTRACT_ADDRESS_GHOSTNET`, `*_CONTRACT_ADDRESS_SHADOWNET`, and
`*_CONTRACT_ADDRESS_MAINNET`. **Always prefer ghostnet/shadownet addresses** for
testing. Skip any address that still equals the placeholder pattern `KT1XXX…`.

Existing test/oracle scripts you can study for style and dependencies:
`scripts/test_oracle.py`, `scripts/oracle_worker.py`,
`scripts/oracle_acey_duecey.py`, `scripts/deploy.py`, `scripts/new_test_wallet.py`.
The repo uses **pytezos** as the Python Tezos client (look for
`from pytezos import pytezos` or similar imports).

Wallet / network config lives in `.env` (check `.env.example` for the variable
list — typically `ADMIN_SK`, `ORACLE_SK`, `TEZOS_RPC_URL`, `NETWORK`).
**Read-only** clients don't need any private key. **Write** clients need
test-wallet keys; do NOT use mainnet keys, and do NOT spend real ꜩ.

### Objective

Create a new directory `scripts/test_clients/` and populate it with one or more
Python test client files per contract. Each test client must:

1. Be self-contained and runnable as `python3 scripts/test_clients/<name>.py`
   from the repo root.
2. Print human-readable output showing what it did and what it found.
3. Default to ghostnet/shadownet via the `NETWORK` env var (with sensible
   fallback).
4. Be **read-only by default**. If a client also has write capability (e.g.
   createGame), gate it behind `--write` or `WRITE_OK=1` env var so the nightly
   run never auto-spends.
5. Exit non-zero on assertion failure so the file can be wired into CI later.

For each contract that has a non-placeholder deployed address, aim to ship at
least these client classes. Order them by impact:

**Tier 1 (highest priority, do these first for every deployed contract):**
- `<contract>_storage_probe.py` — Fetch storage via TzKT or pytezos; assert
  top-level shape (admin/oracle/txlContract addresses present, fee/wager bounds
  in reasonable ranges, currentGameId/currentGameIndex >= 0). Print a one-line
  summary of the contract state.
- `<contract>_invariants.py` — Walk the games map and assert per-game
  invariants (e.g. for chess: gameStatus ∈ {0,1,2,3,4}; if status >= 3 then
  winner != burn for non-draws; toMove ∈ {0,1,2}; houseCutBps <= 1000). For
  TTT: gameStatus ∈ {0..5}, playerTurn ∈ {1,2}, win lines reachable. For
  plinko: bucket payouts sum sanely.

**Tier 2 (do these next):**
- `<contract>_history_replay.py` — Pull recent operations from TzKT
  (`/v1/operations/transactions?target=<addr>`) and reconstruct game outcomes.
  Cross-check that emitted events (`gameCreated`, `gameJoined`, `moveSubmitted`,
  `resigned`, `draw`, `catsGame`, etc.) line up with on-chain storage
  transitions.
- `<contract>_payout_audit.py` — For settled games, verify the math:
  `pot = 2*wager`, `houseCut = pot * houseCutBps / 10000`,
  `winner_paid = pot - houseCut` (or per-side = `(pot-houseCut)/2` for draws).
  Use TzKT `/v1/operations/transactions?initiator=<addr>` to look up the actual
  outgoing payouts and reconcile.

**Tier 3 (best-effort write-mode tests, only if --write is passed):**
- `<contract>_e2e_happy_path.py --write` — Create a game, join from a second
  test wallet, play through to settlement. Two test wallets should already
  exist in the repo (look for `scripts/new_test_wallet.py` output, or `.env`
  `TEST_WALLET_1_SK` / `TEST_WALLET_2_SK`). If no test wallets exist, skip
  with a clear message.
- `<contract>_edge_cases.py --write` — Try the assertion paths: wager too
  small, wager too big, wrong sender, wrong amount, double-join,
  settle-when-not-in-progress. Each call should revert; the client asserts the
  revert message matches the expected one.

### Execution plan

1. Read `src/constants.js` to enumerate deployed contracts. Build a list of
   (name, address, network).
2. For each contract with a real address (not placeholder), read the
   corresponding `src/services/smart_contract*.py` to learn the storage shape,
   entrypoint signatures, and revert messages. Don't guess — ground every
   assertion in what the contract actually says.
3. Read `scripts/test_oracle.py` and `scripts/oracle_worker.py` to copy the
   pytezos boilerplate (RPC config, signer wiring, network selection).
4. For each contract, write Tier 1 first. Then Tier 2. Then Tier 3.
5. After each file, run it once read-only against the live contract
   (`python3 scripts/test_clients/<name>.py`) and capture the output. If it
   fails because pytezos / a dependency is missing, note that in the file's
   docstring and move on — do **not** attempt to install packages on the
   user's machine without their consent.
6. Maintain `scripts/test_clients/README.md` listing every client, what it
   tests, and how to run it. Update incrementally so a partial run still
   leaves a useful index.
7. Maintain `scripts/test_clients/RUN_LOG.md` — append a timestamped entry
   for each run summarizing files added, files modified, and any failed
   assertions found in the live storage. This is the hand-off artifact for
   the user.

### Constraints

- **Do not modify** any file outside `scripts/test_clients/` and its README/log.
  The contracts and Vue components are off-limits for this task.
- **Do not deploy** anything. Do not call any write entrypoint without
  `--write`. Do not transact on mainnet under any circumstance.
- **Do not install** packages globally. If pytezos is missing, write the
  clients anyway (they'll be runnable once the user pip-installs locally) and
  note the dependency in the README.
- **Do not invent** addresses, key names, or storage fields. Read them from
  the actual files.
- If you find a real bug in a deployed contract during read-only auditing
  (e.g. stranded mutez, broken invariants), record it in `RUN_LOG.md` under a
  `## Findings` section — do not try to fix the contract.
- Token budget: pace yourself. Prefer covering all contracts at Tier 1 over
  going deep on one contract at Tier 3.

### Success criteria

- At minimum, every deployed (non-placeholder) contract has a
  `_storage_probe.py` and an `_invariants.py` that runs cleanly read-only.
- `scripts/test_clients/README.md` lists every file with a one-line description.
- `scripts/test_clients/RUN_LOG.md` has a fresh dated entry summarizing what
  was added and any findings.
- Files saved into the user's repo at
  `/Users/benjaminwestbrook/Repositories/TezLiteApps/scripts/test_clients/`.

### Output

Finish with a concise report: how many clients were written, which contracts
are covered at which tier, and any live-storage findings worth the user's
attention in the morning. Provide `computer://` links to the README and
RUN_LOG so the user can open them directly.
