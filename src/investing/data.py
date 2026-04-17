from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import TypeAlias

import polars as pl
import fastexcel as fe

IGNORE_SHEETS = ["Overview"]

Ticker: TypeAlias = str


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
    return [
        Dividend(
            row["Dividend"],
            row["Adjusted Dividend"],
            row["Ex-Dividend Date"].date(),
            row["Payment Date"].date()
            if row["Payment Date"]
            else row["Ex-Dividend Date"].date() + timedelta(days=3),
        )
        for row in df.iter_rows(named=True)
    ]


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
    return [
        Price(
            row["Date"].date(),
            row["Price"],
        )
        for row in df.iter_rows(named=True)
    ]


def load_prices(path: str) -> dict[Ticker, list[Price]]:
    return {
        sheet_name: load_ticker_prices(path, sheet_name)
        for sheet_name in fe.read_excel(path).sheet_names
        if sheet_name not in IGNORE_SHEETS
    }
