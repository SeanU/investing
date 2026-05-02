from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date

from . import data


# Payment date -> tickers that pay on that date -> dividend rows (same ticker may
# appear once per payment date with a merged list).
_DividendByDate = dict[date, dict[data.Ticker, list[data.Dividend]]]


@dataclass
class SecurityHistory:
    ticker: data.Ticker
    prices: list[data.Price]
    dividends: list[data.Dividend]

    @property
    def end_date(self) -> date:
        return max(price.date for price in self.prices)


@dataclass(slots=True)
class DividendCalendar:
    """Index of all dividends by payment date for O(log n + k) range queries.

    Built once from a market's securities; :meth:`dividends_by_payment_date`
    slices sorted payment dates with bisect instead of rescanning every
    security's dividend list.
    """

    _sorted_payment_dates: list[date]
    _by_payment_date: _DividendByDate

    @classmethod
    def from_securities(
        cls, securities: dict[data.Ticker, SecurityHistory]
    ) -> DividendCalendar:
        by_date: _DividendByDate = {}
        for ticker, security in securities.items():
            for dividend in security.dividends:
                payment = dividend.payment_date
                by_date.setdefault(payment, {}).setdefault(ticker, []).append(dividend)
        sorted_dates = sorted(by_date.keys())
        return cls(sorted_dates, by_date)

    def dividends_by_payment_date(
        self, from_date_exclusive: date, to_date_inclusive: date
    ) -> dict[date, dict[data.Ticker, list[data.Dividend]]]:
        if not self._sorted_payment_dates:
            return {}
        lo = bisect_right(self._sorted_payment_dates, from_date_exclusive)
        hi = bisect_right(self._sorted_payment_dates, to_date_inclusive)
        dates = self._sorted_payment_dates
        by_date = self._by_payment_date
        return {dates[i]: by_date[dates[i]] for i in range(lo, hi)}


@dataclass
class MarketHistory:
    securities: dict[data.Ticker, SecurityHistory]
    _price_index: dict[data.Ticker, tuple[list[date], list[float]]] = field(
        default_factory=dict, init=False, repr=False
    )
    _dividend_calendar: DividendCalendar | None = field(
        default=None, init=False, repr=False
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

    def _ensure_dividend_calendar(self) -> DividendCalendar:
        """Return the dividend index, building and caching it if needed."""
        if self._dividend_calendar is None:
            self._dividend_calendar = DividendCalendar.from_securities(self.securities)
        return self._dividend_calendar

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
        return self._ensure_dividend_calendar().dividends_by_payment_date(
            from_date_exclusive, to_date_inclusive
        )


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
