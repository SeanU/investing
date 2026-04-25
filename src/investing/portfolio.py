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


@dataclass
class HoldingTarget:
    ticker: Ticker
    weight: int


@dataclass
class AssetAllocation:
    targets: list[HoldingTarget]

    @property
    def proportions(self) -> dict[Ticker, float]:
        total_weight = sum(target.weight for target in self.targets)

        return {target.ticker: target.weight / total_weight for target in self.targets}


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

    def total_value(self, as_of_date: date, prices: MarketHistory) -> float:
        """Get value for whole portfolio."""

        return sum(
            holding.quantity * prices.get_price(holding.ticker, as_of_date)
            for holding in self.holdings
        )

    def holdings_by_ticker(self) -> dict[Ticker, list[Holding]]:
        tickers = {holding.ticker for holding in self.holdings}

        return {
            ticker: [holding for holding in self.holdings if holding.ticker == ticker]
            for ticker in tickers
        }

    def value_by_ticker(
        self, as_of_date: date, prices: MarketHistory
    ) -> dict[Ticker, float]:
        """Get total position value by ticker."""

        return {
            ticker: sum(
                holding.quantity * prices.get_price(holding.ticker, as_of_date)
                for holding in holdings
            )
            for ticker, holdings in self.holdings_by_ticker().items()
        }

    def sell(
        self,
        ticker: Ticker,
        amount: float,
        trade_date: date,
        prices: MarketHistory,
    ) -> Portfolio:
        sell_price = prices.get_price(ticker, trade_date)
        sell_quantity = amount / sell_price
        current_holdings = [
            holding for holding in self.holdings if holding.ticker == ticker
        ]
        current_holdings.sort(key=lambda h: h.purchase_date)
        remaining_holdings = [
            holding for holding in self.holdings if holding.ticker != ticker
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

        return Portfolio(trade_date, remaining_holdings, self.trades + new_trades)

    def buy(
        self,
        ticker: Ticker,
        amount: float,
        trade_date: date,
        prices: MarketHistory,
    ) -> Portfolio:
        buy_price = prices.get_price(ticker, trade_date)
        buy_quantity = amount / buy_price
        new_holding, new_trade = buy(ticker, buy_price, buy_quantity, trade_date)
        return Portfolio(
            trade_date, self.holdings + [new_holding], self.trades + [new_trade]
        )

    def trade(
        self,
        *,
        sell_ticker: Ticker,
        buy_ticker: Ticker,
        amount: float,
        trade_date: date,
        prices: MarketHistory,
    ) -> Portfolio:
        return self.sell(sell_ticker, amount, trade_date, prices).buy(
            buy_ticker, amount, trade_date, prices
        )
