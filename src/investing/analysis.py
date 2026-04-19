from datetime import date
import polars as pl

from investing.portfolio import Portfolio


def value_history(portfolios: list[Portfolio]) -> pl.DataFrame:
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
            "price": holding.current_price,
        }
        for portfolio in filtered
        for holding in portfolio.holdings
    ]

    df = pl.DataFrame(holdings)
    return df.group_by("date", "ticker", "price").agg(pl.sum("quantity"))
