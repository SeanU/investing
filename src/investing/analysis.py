from datetime import date, timedelta
from typing import Literal
import polars as pl

from investing.history import MarketHistory
from investing.portfolio import Portfolio


def _next_month(current_date: date) -> date:
    next_year = current_date.year
    next_month = current_date.month + 1

    if next_month > 12:
        next_year += 1
        next_month = 1

    return date(next_year, next_month, current_date.day)


def _reporting_dates(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: Literal["daily", "weekly", "monthly"],
) -> list[date]:
    if not portfolios:
        return []

    start_date = min(portfolio.as_of_date for portfolio in portfolios)
    cadence_dates: list[date] = []

    current_date = start_date
    while current_date <= history.end_date:
        cadence_dates.append(current_date)
        if reporting_frequency == "daily":
            current_date += timedelta(days=1)
        elif reporting_frequency == "weekly":
            current_date += timedelta(days=7)
        elif reporting_frequency == "monthly":
            current_date = _next_month(current_date)
        else:
            raise ValueError(
                "reporting_frequency must be one of: daily, weekly, monthly"
            )

    trade_dates = [portfolio.as_of_date for portfolio in portfolios]
    return sorted(set(cadence_dates + trade_dates))


def _reporting_portfolios(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: Literal["daily", "weekly", "monthly"],
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

        expanded.append(
            Portfolio(report_date, current_snapshot.holdings, current_snapshot.trades)
        )

    return expanded


def position_history(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: Literal["daily", "weekly", "monthly"],
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


def value_history(
    portfolios: list[Portfolio],
    history: MarketHistory,
    reporting_frequency: Literal["daily", "weekly", "monthly"],
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
