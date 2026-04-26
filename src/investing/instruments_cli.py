"""CLI utilities for maintaining config/all_instruments.csv."""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable


def lookup_name_from_yahoo_search(ticker: str) -> str | None:
    """Return a public human-readable name for a ticker, if found."""
    url = (
        "https://query2.finance.yahoo.com/v1/finance/search?"
        + urllib.parse.urlencode({"q": ticker, "quotesCount": 10, "newsCount": 0})
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    ticker_upper = ticker.upper()
    quotes = payload.get("quotes") or []
    for quote in quotes:
        symbol = str(quote.get("symbol") or "").upper()
        if symbol != ticker_upper:
            continue
        name = quote.get("longname") or quote.get("shortname")
        if name:
            return str(name).strip()
    return None


def fill_missing_names(
    csv_path: Path, lookup: Callable[[str], str | None] = lookup_name_from_yahoo_search
) -> tuple[int, list[str]]:
    """
    Fill empty name cells in-place for rows with a ticker.

    Returns:
        (updated_count, unresolved_tickers)
    """
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError(f"{csv_path} is missing a header row.")
        if "ticker" not in fieldnames or "name" not in fieldnames:
            raise ValueError(f"{csv_path} must include 'ticker' and 'name' columns.")
        rows = list(reader)

    updated_count = 0
    unresolved: list[str] = []
    for row in rows:
        ticker = (row.get("ticker") or "").strip()
        name = (row.get("name") or "").strip()
        if not ticker or name:
            continue

        looked_up = lookup(ticker)
        if looked_up:
            row["name"] = looked_up
            updated_count += 1
        else:
            unresolved.append(ticker)

    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", delete=False, dir=csv_path.parent
    ) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = Path(tmp.name)

    tmp_path.replace(csv_path)
    return updated_count, unresolved


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Maintain all_instruments.csv by filling only missing human-readable names "
            "from a public quote search source."
        )
    )
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser(
        "populate-missing-names",
        help="Fill blank name cells for tickers in a CSV file",
    )
    c.add_argument(
        "--csv",
        type=Path,
        default=Path("config/all_instruments.csv"),
        help="CSV path with ticker,name columns (default: config/all_instruments.csv)",
    )
    return p


def main() -> None:
    args = _parser().parse_args()
    if args.command != "populate-missing-names":  # pragma: no cover
        raise SystemExit(2)

    csv_path: Path = args.csv.resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    updated_count, unresolved = fill_missing_names(csv_path)
    print(f"Updated {updated_count} row(s) in {csv_path}")
    if unresolved:
        print("Could not resolve:", ", ".join(unresolved))
