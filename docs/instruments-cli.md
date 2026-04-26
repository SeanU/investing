# Instruments CSV CLI (`investing-instruments`)

This utility maintains `config/all_instruments.csv` and fills missing human-readable names for tickers using a public source.

## What it does

- Reads a CSV with columns: `ticker,name`
- Finds rows where:
  - `ticker` is present, and
  - `name` is blank
- Looks up names from Yahoo Finance public search
- Writes updates back to the same CSV
- Leaves existing (non-blank) names unchanged

## Command

From the repository root:

```bash
uv run investing-instruments populate-missing-names
```

Use a custom CSV path:

```bash
uv run investing-instruments populate-missing-names --csv path/to/all_instruments.csv
```

Default CSV path:

- `config/all_instruments.csv`

## Expected CSV format

The file must include a header row with both columns:

- `ticker`
- `name`

Example:

```csv
ticker,name
VTSAX,Vanguard Total Stock Market Index Fund Admiral Shares
VTIAX,
VXUS,
```

After running, blank names may be filled if the lookup succeeds.

## Output and error behavior

- Prints number of updated rows
- Prints unresolved tickers (if any)
- Exits with an error if:
  - CSV file does not exist
  - Required columns are missing

## Notes

- This command only fills missing names; it does not add or remove rows.
- Name lookups depend on external service responses and may occasionally miss a ticker.
