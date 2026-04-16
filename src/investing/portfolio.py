from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from .data import Ticker
from .history import MarketHistory


@dataclass
class Holding:
    ticker: Ticker
    purchase_date: date
    purchase_price: float
    quantity: float

    @property
    def basis(self) -> float:
        return self.purchase_price * self.quantity


@dataclass
class Trade:
    kind: Literal["buy", "sell"]
    ticker: Ticker
    holding: Holding | None
    trade_date: date
    price: float
    quantity: float


def sell(
    holding: Holding, price: float, quantity: float, trade_date: date
) -> tuple[Holding | None, Trade]:
    assert holding.quantity >= quantity
    new_holding: Holding | None = None
    if holding.quantity > quantity:
        new_holding = Holding(
            holding.ticker,
            holding.purchase_date,
            holding.purchase_price,
            holding.quantity - quantity,
        )

    return (
        new_holding,
        Trade("sell", holding.ticker, holding, trade_date, price, quantity),
    )


def buy(
    ticker: Ticker, price: float, quantity: float, trade_date: date
) -> tuple[Holding, Trade]:

    return (
        Holding(ticker, trade_date, price, quantity),
        Trade("buy", ticker, None, trade_date, price, quantity),
    )


@dataclass
class Portfolio:
    as_of_date: date
    holdings: list[Holding]
    trades: list[Trade] = field(default_factory=list)

    def total_value(self) -> float:
        """Get value for whole portlfolio."""

        return sum(holding.basis for holding in self.holdings)

    def holdings_by_ticker(self) -> dict[Ticker, list[Holding]]:
        tickers = {holding.ticker for holding in self.holdings}

        return {
            ticker: [holding for holding in self.holdings if holding.ticker == ticker]
            for ticker in tickers
        }

    def value_by_ticker(self) -> dict[Ticker, float]:
        """Get total position value by ticker."""

        return {
            ticker: sum(holding.basis for holding in holdings)
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
        remaining_holdings = [
            holding for holding in self.holdings if holding.ticker != sell_ticker
        ]
        new_trades = []

        for holding in current_holdings:
            if sell_quantity == 0:
                remaining_holdings.append(holding)
            else:
                remainder, trade = sell(
                    holding,
                    sell_price,
                    min(sell_quantity, holding.quantity),
                    trade_date,
                )
                sell_quantity -= trade.quantity
                new_trades.append(trade)
                if remainder:
                    remaining_holdings.append(remainder)

        # generate new holding for security to buy
        new_holding, trade = buy(buy_ticker, buy_price, buy_quantity, trade_date)
        remaining_holdings.append(new_holding)
        new_trades.append(trade)

        # compose and return new portfolio
        return Portfolio(date.today(), remaining_holdings, self.trades + new_trades)
