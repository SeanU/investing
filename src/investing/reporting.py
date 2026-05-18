import calendar
from datetime import date, timedelta
from typing import Literal, cast

import polars as pl

from investing.history import MarketHistory
from investing.portfolio import Portfolio

ReportingFrequency = Literal["daily", "weekly", "monthly"]

REPORTING_FREQUENCY_CHOICES: frozenset[str] = frozenset({"daily", "weekly", "monthly"})

REPORTING_FREQUENCY_ERROR = (
    "reporting_frequency must be one of: daily, weekly, monthly"
)


def validate_reporting_frequency(value: str) -> ReportingFrequency:
    if value in REPORTING_FREQUENCY_CHOICES:
        return cast(ReportingFrequency, value)
    raise ValueError(REPORTING_FREQUENCY_ERROR)


def _next_month(current_date: date) -> date:
    next_year = current_date.year
    next_month = current_date.month + 1

    if next_month > 12:
        next_year += 1
        next_month = 1

    last_day_of_next_month = calendar.monthrange(next_year, next_month)[1]
    next_day = min(current_date.day, last_day_of_next_month)
    return date(next_year, next_month, next_day)


def _reporting_dates(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: ReportingFrequency,
) -> list[date]:
    if not portfolios:
        return []

    start_date = min(portfolio.as_of_date for portfolio in portfolios)

    if reporting_frequency == "daily":
        cadence_dates: list[date] = history.trading_days(start_date, history.end_date)
    else:
        steppers = {
            "weekly": lambda d: d + timedelta(days=7),
            "monthly": _next_month,
        }
        if reporting_frequency not in steppers:
            raise ValueError(REPORTING_FREQUENCY_ERROR)
        next_date = steppers[reporting_frequency]

        cadence_dates = []
        current_date = start_date
        while current_date <= history.end_date:
            cadence_dates.append(current_date)
            current_date = next_date(current_date)

    trade_dates = [portfolio.as_of_date for portfolio in portfolios]
    return sorted(set(cadence_dates + trade_dates))


def _reporting_portfolios(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: ReportingFrequency,
) -> list[Portfolio]:
    if not portfolios:
        return []

    reporting_dates = _reporting_dates(portfolios, history, reporting_frequency)

    snapshots_by_date = {
        portfolio.as_of_date: portfolio
        for portfolio in sorted(portfolios, key=lambda p: p.as_of_date)
    }
    snapshots = sorted(snapshots_by_date.values(), key=lambda p: p.as_of_date)

    expanded: list[Portfolio] = []
    snapshot_idx = 0
    current_snapshot: Portfolio | None = None
    for report_date in sorted(reporting_dates):
        while (
            snapshot_idx < len(snapshots)
            and snapshots[snapshot_idx].as_of_date <= report_date
        ):
            current_snapshot = snapshots[snapshot_idx]
            snapshot_idx += 1

        if current_snapshot is None:
            continue

        expanded.append(Portfolio(report_date, current_snapshot.holdings))

    return expanded


def position_history(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: ReportingFrequency,
) -> pl.DataFrame:
    expanded = _reporting_portfolios(portfolios, history, reporting_frequency)
    if not expanded:
        return pl.DataFrame(
            schema={
                "date": pl.Date,
                "ticker": pl.Utf8,
                "price": pl.Float64,
                "quantity": pl.Float64,
                "valuation": pl.Float64,
            }
        )

    holdings = [
        {
            "date": portfolio.as_of_date,
            "ticker": holding.ticker,
            "quantity": holding.quantity,
            "price": history.get_price(holding.ticker, portfolio.as_of_date),
        }
        for portfolio in expanded
        for holding in portfolio.holdings
    ]

    df = pl.DataFrame(holdings)
    return (
        df.group_by("date", "ticker", "price")
        .agg(pl.sum("quantity"))
        .with_columns(
            (pl.col("price") * pl.col("quantity")).round(2).alias("valuation")
        )
    )


def total_value_series(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: ReportingFrequency,
) -> tuple[list[date], list[float]]:
    """Dates and total portfolio value at each reporting point.

    Valuations match :func:`position_history` (per-line ``round`` then sum per
    date).
    """
    positions = position_history(portfolios, history, reporting_frequency)
    if positions.is_empty():
        return [], []
    by_date = positions.group_by("date").agg(
        pl.sum("valuation").alias("total")
    ).sort("date")
    return by_date["date"].to_list(), by_date["total"].to_list()


def value_history(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: ReportingFrequency,
) -> pl.DataFrame:
    positions = position_history(portfolios, history, reporting_frequency)
    if positions.is_empty():
        return pl.DataFrame(
            schema={"date": pl.Date, "ticker": pl.Utf8, "valuation": pl.Float64}
        )

    return pl.concat(
        [
            positions.select("date", "ticker", "valuation"),
            positions.group_by("date")
            .agg(pl.sum("valuation"))
            .with_columns(pl.lit("_TOTAL").alias("ticker"))
            .select("date", "ticker", "valuation"),
        ]
    ).sort(["date", "ticker"])
