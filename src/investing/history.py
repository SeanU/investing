from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date

from . import data


@dataclass
class SecurityHistory:
    ticker: data.Ticker
    prices: list[data.Price]
    dividends: list[data.Dividend]

    @property
    def end_date(self) -> date:
        return max(price.date for price in self.prices)


@dataclass
class MarketHistory:
    securities: dict[data.Ticker, SecurityHistory]
    _price_index: dict[data.Ticker, tuple[list[date], list[float]]] = field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def end_date(self) -> date:
        return max(history.end_date for history in self.securities.values())

    def _price_lookup(self, ticker: data.Ticker) -> tuple[list[date], list[float]]:
        cached = self._price_index.get(ticker)
        if cached is not None:
            return cached

        sorted_prices = sorted(self.securities[ticker].prices, key=lambda p: p.date)
        dates = [price.date for price in sorted_prices]
        values = [price.price for price in sorted_prices]
        lookup = (dates, values)
        self._price_index[ticker] = lookup
        return lookup

    def get_price(self, ticker: data.Ticker, as_of: date) -> float:
        dates, prices = self._price_lookup(ticker)
        idx = bisect_right(dates, as_of) - 1
        if idx < 0:
            raise IndexError("No price available at or before requested date")
        return prices[idx]

    def get_dividends_by_ticker(
        self, from_date_exclusive: date, to_date_inclusive: date
    ) -> dict[data.Ticker, list[data.Dividend]]:
        return {
            ticker: [
                dividend
                for dividend in security.dividends
                if from_date_exclusive < dividend.payment_date <= to_date_inclusive
            ]
            for ticker, security in self.securities.items()
        }

    def get_dividends_by_payment_date(
        self, from_date_exclusive: date, to_date_inclusive: date
    ) -> dict[date, dict[data.Ticker, list[data.Dividend]]]:
        payment_dates = sorted(
            {
                dividend.payment_date
                for security in self.securities.values()
                for dividend in security.dividends
                if from_date_exclusive < dividend.payment_date <= to_date_inclusive
            }
        )

        return {
            payment_date: {
                ticker: [
                    dividend
                    for dividend in security.dividends
                    if dividend.payment_date == payment_date
                ]
                for ticker, security in self.securities.items()
            }
            for payment_date in payment_dates
        }


def load_market_history(price_path: str, dividend_path: str) -> MarketHistory:
    prices = data.load_prices(price_path)
    dividends = data.load_dividends(dividend_path)

    assert len(prices) == len(dividends), "Prices and dividends must match"

    return MarketHistory(
        {
            ticker: SecurityHistory(ticker, prices[ticker], dividends[ticker])
            for ticker in prices
        }
    )
