from dataclasses import dataclass
from datetime import date

from .data import Ticker
from .history import MarketHistory


@dataclass
class Holding:
    ticker: Ticker
    purchase_date: date
    price: float
    quantity: float

    @property
    def value(self) -> float:
        return self.price * self.quantity

    def sell(self, quantity: float) -> Holding:
        assert self.quantity >= quantity
        return Holding(
            self.ticker, self.purchase_date, self.price, self.quantity - quantity
        )


@dataclass
class Portfolio:
    as_of_date: date
    holdings: list[Holding]

    def total_value(self) -> float:
        """Get value for whole portlfolio."""

        return sum(holding.value for holding in self.holdings)

    def holdings_by_ticker(self) -> dict[Ticker, list[Holding]]:
        tickers = {holding.ticker for holding in self.holdings}

        return {
            ticker: [holding for holding in self.holdings if holding.ticker == ticker]
            for ticker in tickers
        }

    def value_by_ticker(self) -> dict[Ticker, float]:
        """Get total position value by ticker."""

        return {
            ticker: sum(holding.value for holding in holdings)
            for ticker, holdings in self.holdings_by_ticker().items()
        }

    def trade(
        self,
        *,
        sell_ticker: Ticker,
        buy_ticker: Ticker,
        amount: float,
        trade_date: date,
        prices: MarketHistory,
    ) -> Portfolio:
        sell_price = prices.get_price(sell_ticker, trade_date)
        sell_quantity = amount / sell_price

        buy_price = prices.get_price(buy_ticker, trade_date)
        buy_quantity = amount / buy_price

        # generate new holdings for security to sell
        current_holdings = [
            holding for holding in self.holdings if holding.ticker == sell_ticker
        ]
        current_holdings.sort(key=lambda h: h.purchase_date)
        remaining_holdings = []

        for holding in current_holdings:
            if holding.quantity <= sell_quantity:
                sell_quantity -= holding.quantity
            elif sell_quantity != 0:
                remaining_holdings.append(holding.sell(sell_quantity))
                sell_quantity = 0
            else:
                remaining_holdings.append(holding)

        # generate new holding for security to buy
        new_holding = Holding(buy_ticker, trade_date, buy_price, buy_quantity)

        # compose and return new portfolio
        return Portfolio(
            date.today(),
            [holding for holding in self.holdings if holding.ticker != sell_ticker]
            + remaining_holdings
            + [new_holding],
        )
