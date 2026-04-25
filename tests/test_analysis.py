from datetime import date

import polars as pl

from investing import analysis as a
from investing import data as d
from investing import history as h
from investing import portfolio as p


def test_position_history_keeps_only_last_portfolio_version_per_date():
    """Given: multiple portfolio versions on same rebalancing date.

    Example input:
      - Two portfolio entries on 2026-01-03 (pre and post rebalance)
      - Distinct quantities for ticker A in each version

    Expected output:
      - position_history includes only the last 2026-01-03 version
      - Quantity/valuation for A matches the post-rebalance portfolio
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [d.Price(date(2026, 1, 3), 10.0), d.Price(date(2026, 1, 4), 10.0)],
                [],
            )
        }
    )
    portfolios = [
        p.Portfolio(date(2026, 1, 3), [p.Holding("A", date(2026, 1, 1), 9.0, 1.0)]),
        p.Portfolio(date(2026, 1, 3), [p.Holding("A", date(2026, 1, 1), 9.0, 2.0)]),
        p.Portfolio(date(2026, 1, 4), [p.Holding("A", date(2026, 1, 1), 9.0, 3.0)]),
    ]

    positions = a.position_history(portfolios, market_history)
    jan3_a = positions.filter(
        (pl.col("date") == date(2026, 1, 3)) & (pl.col("ticker") == "A")
    )

    assert jan3_a.height == 1
    assert jan3_a["quantity"][0] == 2.0
    assert jan3_a["valuation"][0] == 20.0


def test_position_history_aggregates_quantities_for_same_ticker_and_price():
    """Given: two lots of same ticker at same date and price.

    Example input:
      - Portfolio holdings: A(qty=1), A(qty=3), B(qty=2)
      - Prices implied by holdings for the same date

    Expected output:
      - Output has one row per (date, ticker, price)
      - A quantity aggregated to 4
      - A valuation equals price * 4
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory("A", [d.Price(date(2026, 1, 3), 10.0)], []),
            "B": h.SecurityHistory("B", [d.Price(date(2026, 1, 3), 20.0)], []),
        }
    )
    portfolios = [
        p.Portfolio(
            date(2026, 1, 3),
            [
                p.Holding("A", date(2026, 1, 1), 10.0, 1.0),
                p.Holding("A", date(2026, 1, 2), 10.0, 3.0),
                p.Holding("B", date(2026, 1, 1), 20.0, 2.0),
            ],
        )
    ]

    positions = a.position_history(portfolios, market_history)
    a_row = positions.filter(
        (pl.col("date") == date(2026, 1, 3))
        & (pl.col("ticker") == "A")
        & (pl.col("price") == 10.0)
    )

    assert a_row.height == 1
    assert a_row["quantity"][0] == 4.0
    assert a_row["valuation"][0] == 40.0


def test_value_history_adds_total_row_for_each_date():
    """Given: position history containing multiple tickers on each date.

    Example input:
      - Two dates with per-ticker valuations

    Expected output:
      - value_history includes `_TOTAL` row for each date
      - `_TOTAL` valuation equals sum of ticker valuations on that date
      - Output sorted by (date, ticker)
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [d.Price(date(2026, 1, 3), 10.0), d.Price(date(2026, 1, 4), 11.0)],
                [],
            ),
            "B": h.SecurityHistory(
                "B",
                [d.Price(date(2026, 1, 3), 20.0), d.Price(date(2026, 1, 4), 19.0)],
                [],
            ),
        }
    )
    portfolios = [
        p.Portfolio(
            date(2026, 1, 3),
            [
                p.Holding("A", date(2026, 1, 1), 9.0, 2.0),
                p.Holding("B", date(2026, 1, 1), 19.0, 3.0),
            ],
        ),
        p.Portfolio(
            date(2026, 1, 4),
            [
                p.Holding("A", date(2026, 1, 1), 9.0, 1.0),
                p.Holding("B", date(2026, 1, 1), 19.0, 4.0),
            ],
        ),
    ]

    values = a.value_history(portfolios, market_history)
    total_rows = values.filter(pl.col("ticker") == "_TOTAL").sort("date")

    assert total_rows.height == 2
    assert total_rows["valuation"][0] == 80.0
    assert total_rows["valuation"][1] == 87.0
    assert values.sort(["date", "ticker"]).rows() == values.rows()
