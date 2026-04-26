import json
from pathlib import Path

import pytest

from investing.sheets_api import _dividend_formula, _quote_formula
from investing.sheets_config import (
    ensure_create_allowed,
    ensure_export_ready,
    load_config,
    merge_google_sheets_into_raw,
    save_config_atomic,
    spreadsheet_edit_url,
)


def test_spreadsheet_edit_url():
    assert (
        spreadsheet_edit_url("abc123")
        == "https://docs.google.com/spreadsheets/d/abc123/edit"
    )


def test_load_minimal_config(tmp_path: Path):
    p = tmp_path / "m.json"
    p.write_text(
        json.dumps(
            {
                "tickers": {"AAA": "Fund A"},
                "price_history": {"from": "2020-01-01"},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.stem == "m"
    assert cfg.tickers == {"AAA": "Fund A"}
    assert cfg.price_from == "2020-01-01"


def test_load_rejects_invalid_tab_char(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps(
            {
                "tickers": {"BAD/NAME": "x"},
                "price_history": {"from": "2020-01-01"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tab names"):
        load_config(p)


def test_ensure_create_allowed_aborts_when_both_ids(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "tickers": {"A": "a"},
                "price_history": {"from": "2020-01-01"},
                "google_sheets": {
                    "dividends": {"spreadsheet_id": "d1", "url": "u"},
                    "prices": {"spreadsheet_id": "p1", "url": "u"},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    with pytest.raises(SystemExit, match="already has google_sheets"):
        ensure_create_allowed(cfg)


def test_ensure_create_allowed_aborts_partial(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "tickers": {"A": "a"},
                "price_history": {"from": "2020-01-01"},
                "google_sheets": {
                    "dividends": {"spreadsheet_id": "d1", "url": "u"},
                    "prices": {"spreadsheet_id": "", "url": ""},
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    with pytest.raises(SystemExit, match="partial google_sheets"):
        ensure_create_allowed(cfg)


def test_ensure_export_ready(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text(
        json.dumps(
            {
                "tickers": {"A": "a"},
                "price_history": {"from": "2020-01-01"},
            }
        ),
        encoding="utf-8",
    )
    cfg = load_config(p)
    with pytest.raises(SystemExit, match="missing google_sheets"):
        ensure_export_ready(cfg)


def test_merge_google_sheets_roundtrip(tmp_path: Path):
    raw = {"tickers": {"X": "y"}, "price_history": {"from": "2010-01-01"}}
    merged = merge_google_sheets_into_raw(raw, dividends_id="d", prices_id="p")
    assert merged["google_sheets"]["dividends"]["spreadsheet_id"] == "d"
    assert "docs.google.com" in merged["google_sheets"]["prices"]["url"]

    out = tmp_path / "out.json"
    save_config_atomic(out, merged)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["tickers"] == {"X": "y"}
    assert data["google_sheets"]["prices"]["spreadsheet_id"] == "p"


def test_dividend_formula_matches_data_loader_expectations():
    """History table must include headers for data.load_ticker_dividends columns."""
    f = _dividend_formula("VTSAX")
    assert "DIVIDENDDATA_DIVIDENDS" in f
    assert '"history"' in f or "history" in f
    assert "TRUE" in f


def test_quote_formula_uses_today_and_from_date():
    f = _quote_formula("VTSAX", "2010-01-01")
    assert "DIVIDENDDATA_QUOTE" in f
    assert "2010-01-01" in f
    assert "TEXT(TODAY()" in f
    assert "TRUE" in f
