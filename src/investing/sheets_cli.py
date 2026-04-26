"""CLI: create Google Sheets from JSON config and export to data/*.xlsx."""

from __future__ import annotations

import argparse
from pathlib import Path

from investing.sheets_api import get_credentials, run_create, run_export
from investing.sheets_config import ensure_create_allowed, load_config


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Sync market data workbooks via Google Sheets + Dividend Data add-on. "
            "After create, open each workbook and run Dividend Data Refresh before export."
        )
    )
    p.add_argument(
        "--credentials",
        metavar="PATH",
        help="OAuth client secrets JSON (Desktop). Default: GOOGLE_OAUTH_CREDENTIALS or ./credentials.json",
    )
    p.add_argument(
        "--token",
        metavar="PATH",
        help="Path to store OAuth token (default: .google-sheets-token.json in cwd)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("create", help="Create two spreadsheets and write google_sheets into config")
    c.add_argument("config", type=Path, help="Path to market data JSON config")

    e = sub.add_parser("export", help="Export spreadsheets from config to Excel under data/")
    e.add_argument("config", type=Path, help="Path to market data JSON config")
    e.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Output directory for xlsx (default: ./data)",
    )
    return p


def main() -> None:
    args = _parser().parse_args()
    creds = get_credentials(credentials_path=args.credentials, token_path=args.token)

    if args.command == "create":
        cfg = load_config(args.config)
        ensure_create_allowed(cfg)
        run_create(cfg, creds)
    elif args.command == "export":
        cfg = load_config(args.config)
        run_export(cfg, creds, data_dir=args.data_dir.resolve())
    else:  # pragma: no cover
        raise SystemExit(2)
