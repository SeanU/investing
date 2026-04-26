# investing

Utilities for portfolio data workflows, including Google Sheets export and ticker metadata maintenance.

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
uv run investing-sheets create config/market_data.example.json
uv run investing-sheets export config/market_data.example.json
```

Note: `config/market_data.example.json` is an example template; copy it to your own config file before real use.

Populate blank instrument names in CSV:

```bash
uv run investing-instruments populate-missing-names
```
