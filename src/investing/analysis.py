from datetime import date
import polars as pl

from investing.history import MarketHistory
from investing.portfolio import Portfolio


def position_history(portfolios: list[Portfolio], history: MarketHistory) -> pl.DataFrame:
    # Take only last portfolio version for each date
    # This is to account for multiple portfolio versions
    # on rebalancing days.
    filtered = []
    last_date = date.min
    for portfolio in portfolios:
        if portfolio.as_of_date == last_date:
            filtered[-1] = portfolio
        else:
            filtered.append(portfolio)
            last_date = portfolio.as_of_date

    holdings = [
        {
            "date": portfolio.as_of_date,
            "ticker": holding.ticker,
            "quantity": holding.quantity,
            "price": history.get_price(holding.ticker, portfolio.as_of_date),
        }
        for portfolio in filtered
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


def value_history(portfolios: list[Portfolio], history: MarketHistory) -> pl.DataFrame:
    positions = position_history(portfolios, history)
    return pl.concat(
        [
            positions.select("date", "ticker", "valuation"),
            positions.group_by("date")
            .agg(pl.sum("valuation"))
            .with_columns(pl.lit("_TOTAL").alias("ticker"))
            .select("date", "ticker", "valuation"),
        ]
    ).sort(["date", "ticker"])
