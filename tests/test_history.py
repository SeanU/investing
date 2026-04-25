from datetime import date

from investing import data as d
from investing import history as h


def test_market_history_end_date_is_max_across_securities():
    """Given: securities with different last available price dates.

    Example input:
      - A prices through 2026-01-03
      - B prices through 2026-01-05

    Expected output:
      - market_history.end_date == 2026-01-05
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 1, 3), 11.0),
                ],
                [],
            ),
            "B": h.SecurityHistory(
                "B",
                [
                    d.Price(date(2026, 1, 2), 20.0),
                    d.Price(date(2026, 1, 5), 21.0),
                ],
                [],
            ),
        }
    )

    assert market_history.end_date == date(2026, 1, 5)


def test_get_price_returns_latest_price_on_or_before_as_of_date():
    """Given: sparse price history and an as_of date between observations.

    Example input:
      - A prices: 2026-01-01 -> 10.0, 2026-01-03 -> 12.0
      - as_of: 2026-01-02

    Expected output:
      - get_price("A", 2026-01-02) == 10.0
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 1, 3), 12.0),
                ],
                [],
            )
        }
    )

    assert market_history.get_price("A", date(2026, 1, 2)) == 10.0


def test_load_market_history_combines_price_and_dividend_data_by_ticker():
    """Given: matching ticker sets from prices and dividends workbooks.

    Example input:
      - `data/5-way-prices.xlsx`
      - `data/5-way-dividends.xlsx`

    Expected output:
      - Returned MarketHistory contains same ticker keys as source sheets
      - Each SecurityHistory has non-empty prices and dividends lists
    """
    market_history = h.load_market_history("data/5-way-prices.xlsx", "data/5-way-dividends.xlsx")
    prices = d.load_prices("data/5-way-prices.xlsx")
    dividends = d.load_dividends("data/5-way-dividends.xlsx")

    assert set(market_history.securities.keys()) == set(prices.keys()) == set(dividends.keys())
    for ticker, security in market_history.securities.items():
        assert security.ticker == ticker
        assert len(security.prices) > 0
        assert len(security.dividends) > 0
