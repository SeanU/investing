from datetime import date

import fastexcel as fe

from investing import data as d


def test_load_prices_ignores_overview_sheet_and_loads_ticker_sheets():
    """Given: workbook with `Overview` and multiple ticker sheets.

    Example input:
      - `data/5-way-prices.xlsx`

    Expected output:
      - Returned keys do not include `Overview`
      - Returned keys include expected ticker symbols
      - Each ticker has a non-empty list of Price objects
    """
    prices_by_ticker = d.load_prices("data/5-way-prices.xlsx")
    workbook_sheets = fe.read_excel("data/5-way-prices.xlsx").sheet_names
    expected_tickers = {sheet for sheet in workbook_sheets if sheet != "Overview"}

    assert "Overview" not in prices_by_ticker
    assert set(prices_by_ticker.keys()) == expected_tickers
    assert all(len(prices) > 0 for prices in prices_by_ticker.values())


def test_load_ticker_prices_maps_rows_to_price_dataclass():
    """Given: a single ticker sheet with Date and Price columns.

    Example input:
      - path: `data/5-way-prices.xlsx`
      - ticker: one known ticker sheet

    Expected output:
      - First element is `Price(date=<date>, price=<float>)`
      - List is in workbook row order
    """
    ticker = "VTSAX"
    prices = d.load_ticker_prices("data/5-way-prices.xlsx", ticker)

    assert len(prices) > 1
    assert isinstance(prices[0], d.Price)
    assert isinstance(prices[0].date, date)
    assert isinstance(prices[0].price, float)
    assert prices[0].date >= prices[1].date


def test_load_ticker_dividends_defaults_payment_date_when_missing():
    """Given: dividend row with missing payment date.

    Example input:
      - path to dividends workbook containing at least one null Payment Date row
      - ticker sheet with Ex-Dividend Date present

    Expected output:
      - Payment date defaults to ex_date + 3 days for that row
      - Output row is mapped to Dividend dataclass fields correctly
    """
    dividends_by_ticker = d.load_dividends("data/5-way-dividends.xlsx")
    all_dividends = [div for ticker_dividends in dividends_by_ticker.values() for div in ticker_dividends]

    fallback_rows = [
        div for div in all_dividends if div.payment_date == div.ex_date + d.timedelta(days=3)
    ]

    assert len(fallback_rows) > 0
    example = fallback_rows[0]
    assert isinstance(example, d.Dividend)
    assert example.payment_date == example.ex_date + d.timedelta(days=3)
