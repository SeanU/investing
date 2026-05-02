# investing

Utilities for portfolio data workflows, including Google Sheets export, ticker metadata maintenance, and Monte Carlo–style portfolio simulations.

## Documentation

- [`docs/google-sheets-cli.md`](./docs/google-sheets-cli.md): Create and export market-data workbooks with `investing-sheets`.
- [`docs/instruments-cli.md`](./docs/instruments-cli.md): Fill missing names in `config/all_instruments.csv` with `investing-instruments`.

## Quick start

Install dependencies:

```bash
uv sync
```

Create Google Sheets and export `.xlsx` files:

```bash
uv run investing-sheets create market_data.example
uv run investing-sheets export market_data.example
```

Each command loads `config/portfolios/<NAME>.json`. The repo includes `market_data.example` as a template; copy that file to a new stem under `config/portfolios/` before real use.

Populate blank instrument names in CSV:

```bash
uv run investing-instruments populate-missing-names
```

## Simulation

Run many randomized simulations (shared random start dates across strategies) from a JSON config:

```bash
uv run investing-simulate config/simulations/simulation.example.json
```

The config names a **market data basename** (for example `market_data.example`). The CLI loads `data/<basename>-prices.xlsx` and `data/<basename>-dividends.xlsx` from the current working directory. It also sets `num_simulations`, `years` (horizon), `starting_value`, a required `seed`, and a `strategies` list. Each strategy has a `name`, an `allocation` of ticker → positive integer weights, and `rebalancing`: either `{ "type": "buy_and_hold" }` or `{ "type": "annual", "max_deviation": <number> }` (threshold only applies to annual rebalancing).

Results are written under `output/<config_stem>/`: Parquet tables for runs, portfolios, holdings, trades, dividends, per-run and aggregate metrics, plus a copy of the input config as `config.json`. If that output directory already exists, the command exits with an error and does not run or overwrite anything.
