"""Google OAuth, Sheets create, and Drive export.

Google Cloud setup:
1. Google Cloud project: APIs and Services - enable **Google Sheets API** and **Google Drive API**.
2. OAuth consent screen (External or Internal): add scopes for spreadsheets and drive.file.
3. Credentials: Create OAuth client ID (Desktop app) and download JSON as your client secrets file.

Point ``--credentials`` at that file (or set ``GOOGLE_OAUTH_CREDENTIALS``). First run opens a browser;
the token is stored at ``--token`` (default: ``.google-sheets-token.json`` in the current directory).

Export returns **last materialized** values; open each spreadsheet and use Dividend Data Refresh
before export if you need up-to-date figures.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from investing.sheets_config import (
    MarketDataConfig,
    ensure_export_ready,
    merge_google_sheets_into_raw,
    save_config_atomic,
)

# drive.file: files created by this app; sufficient for create + export of those files.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]


def _credentials_path(cli_value: str | None) -> Path:
    env = os.environ.get("GOOGLE_OAUTH_CREDENTIALS")
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    if env:
        return Path(env).expanduser().resolve()
    return Path("credentials.json").resolve()


def _token_path(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    return Path(".google-sheets-token.json").resolve()


def get_credentials(*, credentials_path: str | None, token_path: str | None) -> Credentials:
    cpath = _credentials_path(credentials_path)
    tpath = _token_path(token_path)
    creds: Credentials | None = None
    if tpath.is_file():
        creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not cpath.is_file():
                raise FileNotFoundError(
                    f"OAuth client secrets not found at {cpath}. "
                    "Download a Desktop OAuth JSON from Google Cloud Console or set "
                    "GOOGLE_OAUTH_CREDENTIALS."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(cpath), SCOPES)
            creds = flow.run_local_server(port=0)
        tpath.parent.mkdir(parents=True, exist_ok=True)
        tpath.write_text(creds.to_json(), encoding="utf-8")
    return creds


def _sheets_service(creds: Credentials):
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _drive_service(creds: Credentials):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _dividend_formula(ticker: str) -> str:
    return f'=DIVIDENDDATA_DIVIDENDS("{ticker}", "history", TRUE)'


def _quote_formula(ticker: str, from_date: str) -> str:
    return (
        f'=DIVIDENDDATA_QUOTE("{ticker}", "history", "{from_date}", '
        f'TEXT(TODAY(),"yyyy-mm-dd"), TRUE)'
    )


def create_pair(cfg: MarketDataConfig, creds: Credentials) -> tuple[str, str]:
    """Create dividends + prices spreadsheets; return (dividends_id, prices_id)."""
    sheets = _sheets_service(creds)
    stem = cfg.stem
    tickers = list(cfg.tickers.items())
    price_from = cfg.price_from

    div_id = _create_one_workbook(
        sheets,
        title=f"{stem} dividends",
        tickers=tickers,
        formula_fn=_dividend_formula,
    )
    price_id = _create_one_workbook(
        sheets,
        title=f"{stem} prices",
        tickers=tickers,
        formula_fn=lambda t: _quote_formula(t, price_from),
    )
    return div_id, price_id


def _create_one_workbook(
    sheets: Any,
    *,
    title: str,
    tickers: list[tuple[str, str]],
    formula_fn: Any,
) -> str:
    body = {"properties": {"title": title}}
    try:
        created = sheets.spreadsheets().create(body=body).execute()
    except HttpError as e:
        raise RuntimeError(f"spreadsheets.create failed: {e}") from e

    spreadsheet_id = created["spreadsheetId"]
    first_sheet_id = created["sheets"][0]["properties"]["sheetId"]

    requests: list[dict[str, Any]] = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": first_sheet_id, "title": "Overview"},
                "fields": "title",
            }
        }
    ]
    for ticker, _name in tickers:
        requests.append({"addSheet": {"properties": {"title": ticker}}})

    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id, body={"requests": requests}
    ).execute()

    overview_rows: list[list[Any]] = [["Ticker", "Name"]]
    for ticker, name in tickers:
        overview_rows.append([ticker, name])

    n = len(overview_rows)
    data: list[dict[str, Any]] = [
        {
            "range": _sheet_a1("Overview", f"A1:B{n}"),
            "majorDimension": "ROWS",
            "values": overview_rows,
        }
    ]
    for ticker, _ in tickers:
        data.append(
            {
                "range": _sheet_a1(ticker, "A1"),
                "majorDimension": "ROWS",
                "values": [[formula_fn(ticker)]],
            }
        )

    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()

    return spreadsheet_id


def _sheet_a1(title: str, a1: str) -> str:
    """A1 range with quoted sheet title for values API."""
    safe = title.replace("'", "''")
    return f"'{safe}'!{a1}"


def export_xlsx(
    creds: Credentials,
    *,
    dividends_id: str,
    prices_id: str,
    stem: str,
    data_dir: Path,
) -> tuple[Path, Path]:
    """Export both spreadsheets to data_dir; return written paths."""
    drive = _drive_service(creds)
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    data_dir.mkdir(parents=True, exist_ok=True)
    div_path = data_dir / f"{stem}-dividends.xlsx"
    price_path = data_dir / f"{stem}-prices.xlsx"

    for sid, path in ((dividends_id, div_path), (prices_id, price_path)):
        try:
            buf: bytes = drive.files().export(fileId=sid, mimeType=mime).execute()
        except HttpError as e:
            raise RuntimeError(f"Drive export failed for {path.name}: {e}") from e
        path.write_bytes(buf)
    return div_path, price_path


def run_create(cfg: MarketDataConfig, creds: Credentials) -> None:
    div_id, price_id = create_pair(cfg, creds)
    updated = merge_google_sheets_into_raw(cfg.raw, dividends_id=div_id, prices_id=price_id)
    save_config_atomic(cfg.path, updated)
    print("Created spreadsheets:")
    print(f"  dividends: {div_id}")
    print(f"  prices:    {price_id}")
    print(f"Config updated: {cfg.path}")


def run_export(cfg: MarketDataConfig, creds: Credentials, data_dir: Path) -> None:
    ensure_export_ready(cfg)
    d_id, p_id = cfg.dividends_id(), cfg.prices_id()
    div_path, price_path = export_xlsx(
        creds, dividends_id=d_id, prices_id=p_id, stem=cfg.stem, data_dir=data_dir
    )
    print("Exported:")
    print(f"  {div_path}")
    print(f"  {price_path}")
    print(
        "\nIf values look stale, open the Google Sheets and use Dividend Data Refresh, then re-run export."
    )
