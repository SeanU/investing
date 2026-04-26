import csv
from pathlib import Path

import pytest

from investing.instruments_cli import fill_missing_names


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "name"])
        writer.writeheader()
        writer.writerows(rows)


def test_fill_missing_names_only_updates_blank_rows(tmp_path: Path):
    p = tmp_path / "all_instruments.csv"
    _write_csv(
        p,
        [
            {"ticker": "VTSAX", "name": ""},
            {"ticker": "VTIAX", "name": "Existing Name"},
            {"ticker": "UNKNOWN", "name": ""},
        ],
    )

    looked_up = {"VTSAX": "Vanguard Total Stock Mkt Idx Adm"}

    def fake_lookup(ticker: str) -> str | None:
        return looked_up.get(ticker)

    updated, unresolved = fill_missing_names(p, lookup=fake_lookup)

    assert updated == 1
    assert unresolved == ["UNKNOWN"]

    with p.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    assert rows[0]["name"] == "Vanguard Total Stock Mkt Idx Adm"
    assert rows[1]["name"] == "Existing Name"
    assert rows[2]["name"] == ""


def test_fill_missing_names_requires_expected_columns(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("symbol,display_name\nAAA,Example\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ticker"):
        fill_missing_names(p)
