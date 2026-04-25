from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Callable

from investing.data import Ticker
from investing.history import MarketHistory
from investing.portfolio import AssetAllocation, Holding, Portfolio, PortfolioTransition, Trade


@dataclass
class SimulationResult:
    portfolios: list[Portfolio]
    trades: list[Trade] 


class Strategy(ABC):
    starting_allocation: AssetAllocation

    def __init__(self, starting_allocation: AssetAllocation):
        self.starting_allocation = starting_allocation

    @abstractmethod
    def next_rebalance(self, current_date: date) -> date:
        raise NotImplementedError()

    @abstractmethod
    def reblance(
        self, portfolio: Portfolio, history: MarketHistory, current_date: date
    ) -> PortfolioTransition:
        raise NotImplementedError()

    @abstractmethod
    def reinvest_dividends(
        self,
        portfolio: Portfolio,
        history: MarketHistory,
        current_date: date,
        payouts: dict[Ticker, float],
    ) -> PortfolioTransition:
        raise NotImplementedError()


class BuyAndHold(Strategy):
    def __init__(self, target_allocation: AssetAllocation):
        super().__init__(target_allocation)

    def next_rebalance(self, current_date: date) -> date:
        return date.max

    def reblance(
        self, portfolio: Portfolio, history: MarketHistory, current_date: date
    ) -> PortfolioTransition:
        return PortfolioTransition(portfolio)

    def reinvest_dividends(
        self,
        portfolio: Portfolio,
        history: MarketHistory,
        current_date: date,
        payouts: dict[Ticker, float],
    ) -> PortfolioTransition:
        transition = PortfolioTransition(portfolio)
        for ticker, amount in payouts.items():
            if amount > 0:
                transition = transition.update(
                    transition.portfolio.buy(ticker, amount, current_date, history)
                )

        return transition


class AnnualRebalance(Strategy):
    def __init__(self, target_allocation: AssetAllocation, max_deviation: float):
        super().__init__(target_allocation)
        self.allocation = target_allocation
        self.max_deviation = max_deviation

    def next_rebalance(self, current_date: date) -> date:
        return date(current_date.year + 1, current_date.month, current_date.day)

    def _redistribute_overallocation(
        self,
        ticker: Ticker,
        portfolio: Portfolio,
        value_proportions: dict[Ticker, float],
        overallocation: float,
        history: MarketHistory,
        current_date: date,
    ) -> PortfolioTransition:
        sell_amount = portfolio.total_value(current_date, history) * overallocation

        undervalued_holdings = {
            ticker: self.allocation.proportions[ticker] - proportion
            for ticker, proportion in value_proportions.items()
            if proportion < self.allocation.proportions[ticker]
        }
        total_undervaluation = sum(undervalued_holdings.values())

        transition = portfolio.sell(ticker, sell_amount, current_date, history)
        for buy_ticker, proportion in undervalued_holdings.items():
            undervalue_prorating = proportion / total_undervaluation
            buy_amount = undervalue_prorating * sell_amount
            transition = transition.update(
                transition.portfolio.buy(
                    buy_ticker, buy_amount, current_date, history
                )
            )

        value_before = portfolio.total_value(current_date, history)
        value_after = transition.portfolio.total_value(current_date, history)
        assert value_before == value_after

        return transition

    def _redistribute_underallocation(
        self,
        ticker: Ticker,
        portfolio: Portfolio,
        value_proportions: dict[Ticker, float],
        underallocation: float,
        history: MarketHistory,
        current_date: date,
    ) -> PortfolioTransition:
        buy_amount = portfolio.total_value(current_date, history) * underallocation

        overvalued_holdings = {
            ticker: proportion - self.allocation.proportions[ticker]
            for ticker, proportion in value_proportions.items()
            if proportion > self.allocation.proportions[ticker]
        }
        total_overvaluation = sum(overvalued_holdings.values())

        transition = PortfolioTransition(portfolio)
        for sell_ticker, proportion in overvalued_holdings.items():
            overvalue_prorating = proportion / total_overvaluation
            sell_amount = overvalue_prorating * buy_amount
            transition = transition.update(
                transition.portfolio.sell(
                    sell_ticker, sell_amount, current_date, history
                )
            )
        transition = transition.update(
            transition.portfolio.buy(ticker, buy_amount, current_date, history)
        )

        value_before = portfolio.total_value(current_date, history)
        value_after = transition.portfolio.total_value(current_date, history)
        assert value_before == value_after

        return transition

    def _distribute_overallocations(
        self, portfolio: Portfolio, history: MarketHistory, current_date: date
    ) -> PortfolioTransition:
        value_proportions = {
            ticker: value / portfolio.total_value(current_date, history)
            for ticker, value in portfolio.value_by_ticker(current_date, history).items()
        }
        for ticker, proportion in value_proportions.items():
            overallocation = proportion - self.allocation.proportions[ticker]
            if overallocation > self.max_deviation:
                redistributed = self._redistribute_overallocation(
                    ticker,
                    portfolio,
                    value_proportions,
                    overallocation,
                    history,
                    current_date,
                )
                downstream = self._distribute_overallocations(
                    redistributed.portfolio, history, current_date
                )
                return redistributed.update(downstream)

        return PortfolioTransition(portfolio)

    def _distribute_underallocations(
        self, portfolio: Portfolio, history: MarketHistory, current_date: date
    ) -> PortfolioTransition:
        value_proportions = {
            ticker: value / portfolio.total_value(current_date, history)
            for ticker, value in portfolio.value_by_ticker(current_date, history).items()
        }
        for ticker, proportion in value_proportions.items():
            underallocation = self.allocation.proportions[ticker] - proportion
            if underallocation > self.max_deviation:
                redistributed = self._redistribute_underallocation(
                    ticker,
                    portfolio,
                    value_proportions,
                    underallocation,
                    history,
                    current_date,
                )
                downstream = self._distribute_underallocations(
                    redistributed.portfolio, history, current_date
                )
                return redistributed.update(downstream)

        return PortfolioTransition(portfolio)

    def reblance(
        self, portfolio: Portfolio, history: MarketHistory, current_date: date
    ) -> PortfolioTransition:
        over_transition = self._distribute_overallocations(
            portfolio, history, current_date
        )
        under_transition = self._distribute_underallocations(
            over_transition.portfolio, history, current_date
        )
        return over_transition.update(under_transition)

    def reinvest_dividends(
        self,
        portfolio: Portfolio,
        history: MarketHistory,
        current_date: date,
        payouts: dict[Ticker, float],
    ) -> PortfolioTransition:
        transition = PortfolioTransition(portfolio)
        for ticker, amount in payouts.items():
            if amount > 0:
                transition = transition.update(
                    transition.portfolio.buy(ticker, amount, current_date, history)
                )

        return transition


def _make_starting_portfolio(
    history: MarketHistory,
    allocation: AssetAllocation,
    start_date: date,
    start_funds: float,
) -> Portfolio:
    def _make_holding(ticker: Ticker, proportion: float) -> Holding:
        value = start_funds * proportion
        price = history.get_price(ticker, start_date)
        return Holding(ticker, start_date, price, value / price)

    return Portfolio(
        start_date,
        [
            _make_holding(ticker, proportion)
            for ticker, proportion in allocation.proportions.items()
        ],
    )


def monthly_time_step(current_date: date) -> date:
    next_year = current_date.year
    next_month = current_date.month + 1

    if next_month > 12:
        next_year += 1
        next_month = 1

    return date(next_year, next_month, current_date.day)


def simulate(
    history: MarketHistory,
    start_date: date,
    start_funds: float,
    strategy: Strategy,
    time_step: Callable[[date], date],
) -> SimulationResult:
    starting_portfolio = _make_starting_portfolio(
        history, strategy.starting_allocation, start_date, start_funds
    )
    portfolio_log = [starting_portfolio]
    trade_log: list[Trade] = []

    current_date = start_date
    next_rebalance = strategy.next_rebalance(start_date)
    while current_date < history.end_date:
        previous_date = current_date
        current_date = time_step(current_date)
        previous_portfolio = portfolio_log[-1]
        new_portfolio = previous_portfolio
        dividends_by_payment_date = history.get_dividends_by_payment_date(
            previous_date, current_date
        )
        for payment_date in sorted(dividends_by_payment_date):
            dividends = dividends_by_payment_date[payment_date]
            payouts = new_portfolio.dividend_payouts(dividends)
            transition = strategy.reinvest_dividends(
                new_portfolio, history, payment_date, payouts
            )
            new_portfolio = transition.portfolio
            trade_log.extend(transition.trades)

        if current_date >= next_rebalance:
            transition = strategy.reblance(new_portfolio, history, current_date)
            new_portfolio = transition.portfolio
            trade_log.extend(transition.trades)
            next_rebalance = strategy.next_rebalance(next_rebalance)

        if new_portfolio != previous_portfolio:
            portfolio_log.append(new_portfolio)

    return SimulationResult(portfolio_log, trade_log)
