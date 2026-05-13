# contracts/

Compiled, deployable Michelson for each on-chain contract used by
TezLiteApps. **These files are the source of truth at deploy time.**
`scripts/deploy.py` reads them directly — no SmartPy install required.

## Layout

```
contracts/
├── README.md       (this file)
└── <contract-id>/
    ├── code.tz     contract Michelson — what runs on-chain
    └── storage.tz  initial storage value passed at origination
```

Currently committed:

| Contract id    | Source (SmartPy)                              | Status     |
| -------------- | --------------------------------------------- | ---------- |
| `oracle`       | `src/services/smart_contract_oracle.py`        | ✓ compiled |
| `acey-duecey`  | `src/services/smart_contractAD.py`             | TODO       |
| `ttt`          | `src/services/smart_contract_TTT.py`           | TODO       |
| `squares`      | `src/services/smart_contract_squares.py`       | TODO       |

To add a new one:

1. Write / edit the SmartPy source in `src/services/`.
2. Compile in the SmartPy online IDE (https://smartpy.io/ide).
3. Save the Michelson code as `contracts/<id>/code.tz`.
4. Save the initial storage as `contracts/<id>/storage.tz`.
5. Register the contract in `scripts/deploy.py`'s `CONTRACTS` dict.

Then `./scripts/deploy.sh <id>` works forever without re-compiling.

## Why this layout

Michelson is the canonical artifact. SmartPy is just a convenience for
*writing* it. Once a contract is compiled and audited, the `.tz` files
should be versioned the same way any deployable artifact would be:

- Diffable in git, so PR review can spot accidental changes.
- Reproducible — the bytes here are exactly what hits the chain.
- No tooling dependency at deploy time — `pytezos` is the only Python
  package you need.

The previous `src/services/build/<id>/` directory is gitignored and
exists only as scratch space for in-progress SmartPy compiles. The
deploy script falls back to it when `contracts/<id>/` doesn't have a
checked-in version, so you can iterate on a new contract before
committing the canonical Michelson.
