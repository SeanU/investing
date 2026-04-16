from dataclasses import dataclass
from datetime import date

from . import data


@dataclass
class SecurityHistory:
    ticker: data.Ticker
    prices: list[data.Price]
    dividends: list[data.Dividend]


@dataclass
class MarketHistory:
    securities: dict[data.Ticker, SecurityHistory]

    def get_price(self, ticker: data.Ticker, as_of: date) -> float:
        prices = self.securities[ticker].prices
        prices = [price for price in prices if price.date <= as_of]
        prices.sort(key=lambda p: p.date)
        return prices[-1].price


def load_market_history(price_path: str, dividend_path: str) -> MarketHistory:
    prices = data.load_prices(price_path)
    dividends = data.load_dividends(dividend_path)

    assert len(prices) == len(dividends), "Prices and dividends must match"

    return MarketHistory(
        [
            SecurityHistory(ticker, prices[ticker], dividends[ticker])
            for ticker in prices
        ]
    )
