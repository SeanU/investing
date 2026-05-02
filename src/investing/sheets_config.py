"""Load, validate, and save market-data JSON config for Google Sheets sync."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# Google Sheets worksheet titles cannot contain: \ / ? * [ ]
_INVALID_TAB_CHARS = re.compile(r"[\\/?*\[\]:]")

PORTFOLIOS_CONFIG_DIR = Path("config/portfolios")


def portfolio_config_path(config_root: str) -> Path:
    """Path to ``config/portfolios/<config_root>.json`` (relative to the process cwd).

    *config_root* is the basename without ``.json`` (e.g. ``market_data.example``).
    """
    name = config_root.strip()
    if not name:
        raise ValueError("Config name must be non-empty.")
    if name in (".", ".."):
        raise ValueError("Invalid config name.")
    if "/" in name or "\\" in name:
        raise ValueError("Config name must not contain path separators.")
    filename = f"{name}.json"
    if Path(filename).name != filename:
        raise ValueError("Invalid config name.")
    return PORTFOLIOS_CONFIG_DIR / filename


@dataclass(frozen=True)
class GoogleSheetsEntry:
    spreadsheet_id: str
    url: str


@dataclass(frozen=True)
class MarketDataConfig:
    """In-memory config; path is tracked for stem and saving."""

    path: Path
    raw: dict[str, Any]

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def tickers(self) -> dict[str, str]:
        t = self.raw.get("tickers")
        if not isinstance(t, dict):
            raise ValueError("config.tickers must be a JSON object (ticker to name).")
        out: dict[str, str] = {}
        for k, v in t.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("config.tickers keys and values must be strings.")
            if not k.strip() or not v.strip():
                raise ValueError("config.tickers: empty ticker or name not allowed.")
            if _INVALID_TAB_CHARS.search(k):
                raise ValueError(
                    f"config.tickers key {k!r} contains a character not allowed in sheet tab names."
                )
            out[k] = v
        return out

    @property
    def price_from(self) -> str:
        ph = self.raw.get("price_history")
        if not isinstance(ph, dict):
            raise ValueError("config.price_history must be an object.")
        from_raw = ph.get("from")
        if not isinstance(from_raw, str) or not from_raw.strip():
            raise ValueError(
                "config.price_history.from must be a non-empty date string (YYYY-MM-DD)."
            )
        try:
            date.fromisoformat(from_raw.strip())
        except ValueError as e:
            raise ValueError(
                f"config.price_history.from must be a valid YYYY-MM-DD date: {from_raw!r}"
            ) from e
        return from_raw.strip()

    def google_sheets_block(self) -> dict[str, Any] | None:
        gs = self.raw.get("google_sheets")
        if gs is None:
            return None
        if not isinstance(gs, dict):
            raise ValueError("config.google_sheets must be an object when present.")
        return gs

    def dividends_id(self) -> str:
        gs = self.google_sheets_block()
        if not gs:
            return ""
        d = gs.get("dividends")
        if not isinstance(d, dict):
            return ""
        sid = d.get("spreadsheet_id")
        return sid.strip() if isinstance(sid, str) else ""

    def prices_id(self) -> str:
        gs = self.google_sheets_block()
        if not gs:
            return ""
        p = gs.get("prices")
        if not isinstance(p, dict):
            return ""
        sid = p.get("spreadsheet_id")
        return sid.strip() if isinstance(sid, str) else ""


def load_config(path: str | Path) -> MarketDataConfig:
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Config not found: {p}")
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a JSON object.")
    cfg = MarketDataConfig(path=p, raw=raw)
    tickers = cfg.tickers
    if not tickers:
        raise ValueError("config.tickers must be non-empty.")
    _ = cfg.price_from
    return cfg


def ensure_create_allowed(cfg: MarketDataConfig) -> None:
    """Abort create if spreadsheets are already recorded (or partial state)."""
    d, p = cfg.dividends_id(), cfg.prices_id()
    if d and p:
        raise SystemExit(
            "Config already has google_sheets with both spreadsheet IDs. "
            "Remove the google_sheets block from the JSON to create new spreadsheets."
        )
    if d or p:
        raise SystemExit(
            "Config has partial google_sheets (only one spreadsheet_id). "
            "Fix or remove the google_sheets block before running create."
        )


def spreadsheet_edit_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"


def merge_google_sheets_into_raw(
    raw: dict[str, Any],
    *,
    dividends_id: str,
    prices_id: str,
) -> dict[str, Any]:
    out = dict(raw)
    out["google_sheets"] = {
        "dividends": {
            "spreadsheet_id": dividends_id,
            "url": spreadsheet_edit_url(dividends_id),
        },
        "prices": {
            "spreadsheet_id": prices_id,
            "url": spreadsheet_edit_url(prices_id),
        },
    }
    return out


def save_config_atomic(path: Path, data: Mapping[str, Any]) -> None:
    text = json.dumps(dict(data), indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def ensure_export_ready(cfg: MarketDataConfig) -> tuple[str, str]:
    d, p = cfg.dividends_id(), cfg.prices_id()
    if not d or not p:
        raise SystemExit(
            "Config is missing google_sheets spreadsheet IDs. Run "
            "`uv run investing-sheets create NAME` first (loads config/portfolios/NAME.json), "
            "then open each workbook and use Dividend Data Refresh before export."
        )
    return d, p
