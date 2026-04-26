# Market data: Google Sheets CLI (`investing-sheets`)

This project can **create** two Google Sheets (dividends and prices) from a JSON config, populate them with [Dividend Data](https://www.dividenddata.com/) spreadsheet formulas, and **export** them to Excel (`.xlsx`) under `data/`. The layout matches what [`src/investing/data.py`](../src/investing/data.py) expects: an `Overview` sheet plus one worksheet per ticker.

You need:

- A **Google account** and a **Google Cloud** project with OAuth credentials (steps below).
- A **Dividend Data** account and the **Dividend Data** add-on for Google Sheets (same as a manual workflow).
- Python dependencies installed via **`uv sync`** in this repo (includes `google-api-python-client` and `google-auth-oauthlib`).

## 1. Google Cloud setup

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select or create a project.
2. Go to **APIs and Services** → **Library**. Enable:
   - **Google Sheets API**
   - **Google Drive API**
3. Go to **APIs and Services** → **OAuth consent screen**. Configure it (Internal or External, as appropriate for your org). When adding scopes, include access that corresponds to:
   - spreadsheets (read/write)
   - Drive **per-file** access (`drive.file` is what the CLI requests)
4. Go to **APIs and Services** → **Credentials** → **Create credentials** → **OAuth client ID** → application type **Desktop app**. Download the JSON file.

This JSON is your **OAuth client secret** file. Do not commit it.

## 2. Store credentials and token locally

The CLI looks for client secrets in this order:

1. Path passed as **`--credentials`**
2. Environment variable **`GOOGLE_OAUTH_CREDENTIALS`** (full path to the JSON file)
3. **`credentials.json`** in the **current working directory**

On the **first** run, the CLI opens a browser so you can sign in and approve access. It then saves a **refreshable user token** to:

- Path passed as **`--token`**, or
- **`.google-sheets-token.json`** in the current working directory

The repo [`.gitignore`](../.gitignore) ignores `credentials.json` and `.google-sheets-token.json` so they are not committed by default.

## 3. JSON configuration file

The config drives tickers, display names, and the start date for **price** history. **Dividend** history uses full `"history"` in the formula; **price** history ends on **today** in the spreadsheet (`TODAY()`), not a fixed end date in JSON.

### Required shape

| Key | Description |
|-----|-------------|
| `tickers` | Object: keys are **ticker symbols** (also used as **sheet tab names**). Values are **human-readable names** shown on the `Overview` sheet. Order follows JSON key order. Characters not allowed in tab names (e.g. `\ / ? * [ ] :`) must not appear in keys. |
| `price_history` | Object with a single field `from`: string **`YYYY-MM-DD`**, embedded in `DIVIDENDDATA_QUOTE` history formulas. |

After a successful **`create`**, the tool appends:

| Key | Description |
|-----|-------------|
| `google_sheets` | Object with `dividends` and `prices`. Each has `spreadsheet_id` and `url` (edit link). Used by **`export`**. |

### Example (before `create`)

See [`config/market_data.example.json`](../config/market_data.example.json).

### Example (after `create`)

```json
{
  "tickers": { "...": "..." },
  "price_history": { "from": "2010-01-01" },
  "google_sheets": {
    "dividends": {
      "spreadsheet_id": "…",
      "url": "https://docs.google.com/spreadsheets/d/…/edit"
    },
    "prices": {
      "spreadsheet_id": "…",
      "url": "https://docs.google.com/spreadsheets/d/…/edit"
    }
  }
}
```

### Spreadsheet **file** titles in Google Drive

If your config file is `config/market_data.json`, the **stem** is `market_data`. The tool creates:

- **`market_data dividends`**
- **`market_data prices`**

Inside each file, the default **Sheet1** is renamed to **`Overview`**, and each ticker gets its own tab.

## 4. Install and run the CLI

From the repository root (with [`uv`](https://github.com/astral-sh/uv) available):

```bash
uv sync
```

### Create spreadsheets

```bash
uv run investing-sheets create path/to/your_config.json
```

Optional:

```bash
uv run investing-sheets --credentials C:\path\to\client_secret.json --token C:\path\to\token.json create path\to\your_config.json
```

**Behavior:**

- If `google_sheets` already has **both** `dividends.spreadsheet_id` and `prices.spreadsheet_id` set, the command **exits without calling Google** (avoids duplicate workbooks). Remove the `google_sheets` block from the JSON to run `create` again.
- If only **one** id is set, the command exits with an error (partial state). Fix or remove `google_sheets` before retrying.

### Refresh formulas (manual)

Open each workbook in Google Sheets, sign in to **Dividend Data** if prompted, and use the add-on’s **Refresh** so `DIVIDENDDATA_*` formulas materialize. Export uses **last saved** cell values; stale sheets produce stale Excel files.

See the [Dividend Data Spreadsheet Docs](https://github.com/divdatdev/Dividend-Data-Spreadsheet-Docs) for formula behavior.

### Export to Excel

```bash
uv run investing-sheets export path/to/your_config.json
```

Writes:

- `data/{stem}-dividends.xlsx`
- `data/{stem}-prices.xlsx`

where `{stem}` is the config filename without extension. Override the output directory:

```bash
uv run investing-sheets export path/to/your_config.json --data-dir path/to/output_dir
```

`export` requires a populated `google_sheets` section (run **`create`** first).

## 5. End-to-end checklist

1. Enable APIs and create **Desktop** OAuth client; place secrets where the CLI can find them (`credentials.json` or `GOOGLE_OAUTH_CREDENTIALS`).
2. Copy [`config/market_data.example.json`](../config/market_data.example.json) to your own path and edit `tickers` and `price_history.from`.
3. Run **`investing-sheets create`** with that config path; confirm `google_sheets` was written into the file.
4. Open both URLs from the config (or from Google Drive); install/use Dividend Data; **Refresh** both workbooks.
5. Run **`investing-sheets export`**; load the xlsx files with [`load_dividends` / `load_prices`](../src/investing/data.py) as usual.

## 6. Formula compatibility with `data.py`

The CLI writes:

- **Dividends:** `=DIVIDENDDATA_DIVIDENDS("TICKER", "history", TRUE)`
- **Prices:** `=DIVIDENDDATA_QUOTE("TICKER", "history", "from-date", TEXT(TODAY(),"yyyy-mm-dd"), TRUE)`

[`load_ticker_dividends`](../src/investing/data.py) expects columns: `Ex-Dividend Date`, `Payment Date`, `Adjusted Dividend`, `Dividend`. [`load_ticker_prices`](../src/investing/data.py) expects: `Date`, `Price`. If Dividend Data changes header labels, adjust the loader or the sheet after export.

## 7. Troubleshooting

| Issue | What to try |
|-------|-------------|
| `OAuth client secrets not found` | Set `--credentials` or `GOOGLE_OAUTH_CREDENTIALS`, or put `credentials.json` in the directory from which you run the command. |
| `create` refuses to run | Remove `google_sheets` from the config if you intend to create **new** spreadsheets (old Drive files remain until you delete them manually). |
| `export` says IDs are missing | Run `create` first so `google_sheets` is present. |
| Empty or old data in xlsx | Open each Google Sheet and run **Dividend Data Refresh**, then run `export` again. |
| Windows console and help | Avoid special Unicode in your own strings if you redirect help output; the built-in help uses ASCII-only text. |
