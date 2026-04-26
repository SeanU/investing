from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import TypeAlias

import polars as pl
import fastexcel as fe

IGNORE_SHEETS = ["Overview"]

Ticker: TypeAlias = str


def _cell_to_date(value: datetime | date | None) -> date | None:
    """Excel cells may be parsed as date or datetime depending on file/engine."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


@dataclass
class Dividend:
    amount: float
    adjusted_amount: float
    ex_date: date
    payment_date: date


@dataclass
class Price:
    date: date
    price: float


def load_ticker_dividends(path: str, ticker: Ticker) -> list[Dividend]:
    df = pl.read_excel(
        path,
        sheet_name=ticker,
        has_header=True,
        columns=["Ex-Dividend Date", "Payment Date", "Adjusted Dividend", "Dividend"],
    )
    dividends: list[Dividend] = []
    for row in df.iter_rows(named=True):
        ex = _cell_to_date(row["Ex-Dividend Date"])
        if ex is None:
            continue
        pay = _cell_to_date(row["Payment Date"])
        dividends.append(
            Dividend(
                row["Dividend"],
                row["Adjusted Dividend"],
                ex,
                pay if pay is not None else ex + timedelta(days=3),
            )
        )
    return dividends


def load_dividends(path: str) -> dict[Ticker, list[Dividend]]:
    return {
        sheet_name: load_ticker_dividends(path, sheet_name)
        for sheet_name in fe.read_excel(path).sheet_names
        if sheet_name not in IGNORE_SHEETS
    }


def load_ticker_prices(path: str, ticker: Ticker) -> list[Price]:
    df = pl.read_excel(
        path,
        sheet_name=ticker,
        has_header=True,
        columns=["Date", "Price"],
    )
    prices: list[Price] = []
    for row in df.iter_rows(named=True):
        d = _cell_to_date(row["Date"])
        if d is None:
            continue
        prices.append(Price(d, row["Price"]))
    return prices


def load_prices(path: str) -> dict[Ticker, list[Price]]:
    return {
        sheet_name: load_ticker_prices(path, sheet_name)
        for sheet_name in fe.read_excel(path).sheet_names
        if sheet_name not in IGNORE_SHEETS
    }
