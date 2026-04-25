from dataclasses import dataclass
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

    @property
    def end_date(self) -> date:
        return max(history.end_date for history in self.securities.values())

    def get_price(self, ticker: data.Ticker, as_of: date) -> float:
        prices = self.securities[ticker].prices
        prices = [price for price in prices if price.date <= as_of]
        prices.sort(key=lambda p: p.date)
        return prices[-1].price

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
