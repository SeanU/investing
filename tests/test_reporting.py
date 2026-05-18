from datetime import date

import polars as pl

from investing import data as d
from investing import history as h
from investing import portfolio as p
from investing import reporting as r


def test_next_month_clamps_day_for_shorter_month():
    assert r._next_month(date(2026, 1, 31)) == date(2026, 2, 28)
    assert r._next_month(date(2024, 1, 31)) == date(2024, 2, 29)
    assert r._next_month(date(2026, 3, 30)) == date(2026, 4, 30)


def test_position_history_monthly_does_not_crash_for_start_day_31():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 31), 10.0),
                    d.Price(date(2026, 2, 28), 11.0),
                    d.Price(date(2026, 3, 31), 12.0),
                ],
                [],
            )
        }
    )
    portfolios = [
        p.Portfolio(
            date(2026, 1, 31),
            [p.Holding("A", date(2026, 1, 31), 10.0, 1.0)],
        )
    ]

    positions = r.position_history(portfolios, market_history, "monthly")
    reported_dates = sorted(set(positions["date"].to_list()))

    assert date(2026, 1, 31) in reported_dates
    assert date(2026, 2, 28) in reported_dates


def test_position_history_forward_fills_holdings_between_trade_dates():
    """Given: sparse trade-date portfolio snapshots and explicit reporting dates.

    Example input:
      - Portfolio snapshots on 2026-01-03 and 2026-01-05
      - Reporting dates include 2026-01-04 (no trade)

    Expected output:
      - 2026-01-04 valuation uses holdings from 2026-01-03 snapshot
      - Quantity stays constant while price is marked-to-market
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 3), 10.0),
                    d.Price(date(2026, 1, 4), 12.0),
                    d.Price(date(2026, 1, 5), 12.0),
                ],
                [],
            )
        }
    )
    portfolios = [
        p.Portfolio(date(2026, 1, 3), [p.Holding("A", date(2026, 1, 1), 9.0, 2.0)]),
        p.Portfolio(date(2026, 1, 5), [p.Holding("A", date(2026, 1, 1), 9.0, 3.0)]),
    ]
    positions = r.position_history(portfolios, market_history, "daily")
    jan4_a = positions.filter(
        (pl.col("date") == date(2026, 1, 4)) & (pl.col("ticker") == "A")
    )

    assert jan4_a.height == 1
    assert jan4_a["quantity"][0] == 2.0
    assert jan4_a["valuation"][0] == 24.0


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

    positions = r.position_history(portfolios, market_history, "daily")
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

    values = r.value_history(portfolios, market_history, "daily")
    total_rows = values.filter(pl.col("ticker") == "_TOTAL").sort("date")

    assert total_rows.height == 2
    assert total_rows["valuation"][0] == 80.0
    assert total_rows["valuation"][1] == 87.0
    assert values.sort(["date", "ticker"]).rows() == values.rows()


def test_position_history_includes_trade_dates_between_monthly_steps():
    """Given: monthly reporting cadence with a mid-month trade snapshot.

    Expected output:
      - position history includes cadence dates plus in-between trade dates
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 1, 15), 12.0),
                    d.Price(date(2026, 2, 1), 11.0),
                ],
                [],
            )
        }
    )
    portfolios = [
        p.Portfolio(date(2026, 1, 1), [p.Holding("A", date(2026, 1, 1), 10.0, 1.0)]),
        p.Portfolio(date(2026, 1, 15), [p.Holding("A", date(2026, 1, 1), 10.0, 2.0)]),
    ]

    positions = r.position_history(portfolios, market_history, "monthly")
    reported_dates = sorted(set(positions["date"].to_list()))

    assert reported_dates == [date(2026, 1, 1), date(2026, 1, 15), date(2026, 2, 1)]


def test_position_history_daily_skips_non_trading_days():
    """Daily cadence should only emit dates present in the market's trading calendar.

    Given prices on Jan 2, 5, 6 (a weekend gap), daily reporting should not
    invent rows for Jan 3 or Jan 4 even though they are calendar days in range.
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 2), 10.0),
                    d.Price(date(2026, 1, 5), 11.0),
                    d.Price(date(2026, 1, 6), 12.0),
                ],
                [],
            )
        }
    )
    portfolios = [
        p.Portfolio(date(2026, 1, 2), [p.Holding("A", date(2026, 1, 2), 10.0, 1.0)]),
    ]

    positions = r.position_history(portfolios, market_history, "daily")
    reported_dates = sorted(set(positions["date"].to_list()))

    assert reported_dates == [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)]


def test_validate_reporting_frequency_accepts_choices():
    assert r.validate_reporting_frequency("daily") == "daily"
    assert r.validate_reporting_frequency("weekly") == "weekly"
    assert r.validate_reporting_frequency("monthly") == "monthly"


def test_validate_reporting_frequency_rejects_unknown():
    import pytest

    with pytest.raises(ValueError, match="daily, weekly, monthly"):
        r.validate_reporting_frequency("quarterly")  # type: ignore[arg-type]


def test_total_value_series_aligns_with_value_history_total():
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
    dates, totals = r.total_value_series(portfolios, market_history, "daily")
    vh = r.value_history(portfolios, market_history, "daily")
    for as_of, t in zip(dates, totals, strict=True):
        tot_row = vh.filter(
            (pl.col("date") == as_of) & (pl.col("ticker") == "_TOTAL")
        )["valuation"][0]
        assert t == tot_row
