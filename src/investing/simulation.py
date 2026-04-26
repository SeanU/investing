from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from random import Random

from investing.data import Ticker
from investing.history import MarketHistory
from investing.metrics import SimulationMetrics, compute_simulation_metrics
from investing.portfolio import AssetAllocation, Holding, Portfolio, PortfolioTransition, Trade


@dataclass
class DividendPayment:
    payment_date: date
    ticker: Ticker
    shares_held: float
    amount_per_share: float
    total_payment: float


@dataclass
class SimulationResult:
    portfolios: list[Portfolio]
    trades: list[Trade]
    dividends: list[DividendPayment]


@dataclass
class MultiSimulationResult:
    simulations: list[SimulationResult]
    run_metrics: list[SimulationMetrics]
    metrics: SimulationMetrics


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


def simulate(
    history: MarketHistory,
    start_date: date,
    start_funds: float,
    strategy: Strategy,
    end_date: date | None = None,
) -> SimulationResult:
    def _apply_dividends(
        portfolio: Portfolio, from_date: date, to_date: date
    ) -> PortfolioTransition:
        transition = PortfolioTransition(portfolio)
        dividends_by_payment_date = history.get_dividends_by_payment_date(
            from_date, to_date
        )
        for payment_date in sorted(dividends_by_payment_date):
            dividends = dividends_by_payment_date[payment_date]
            payouts = transition.portfolio.dividend_payouts(dividends)
            holdings_by_ticker = transition.portfolio.holdings_by_ticker()
            for ticker, ticker_dividends in dividends.items():
                total_dividend_payment = payouts.get(ticker, 0.0)
                if total_dividend_payment <= 0:
                    continue
                shares_held = sum(
                    holding.quantity for holding in holdings_by_ticker.get(ticker, [])
                )
                amount_per_share = sum(
                    dividend.adjusted_amount for dividend in ticker_dividends
                )
                dividend_log.append(
                    DividendPayment(
                        payment_date=payment_date,
                        ticker=ticker,
                        shares_held=shares_held,
                        amount_per_share=amount_per_share,
                        total_payment=total_dividend_payment,
                    )
                )
            reinvestment = strategy.reinvest_dividends(
                transition.portfolio, history, payment_date, payouts
            )
            transition = transition.update(reinvestment)

        return transition

    def _ensure_final_snapshot(portfolios: list[Portfolio], as_of_date: date) -> None:
        latest_portfolio = portfolios[-1]
        if latest_portfolio.as_of_date == as_of_date:
            return
        dividend_transition = _apply_dividends(
            latest_portfolio, latest_portfolio.as_of_date, as_of_date
        )
        trade_log.extend(dividend_transition.trades)
        portfolios.append(Portfolio(as_of_date, dividend_transition.portfolio.holdings))

    starting_portfolio = _make_starting_portfolio(
        history, strategy.starting_allocation, start_date, start_funds
    )
    portfolio_log = [starting_portfolio]
    trade_log: list[Trade] = []
    dividend_log: list[DividendPayment] = []

    simulation_end_date = history.end_date
    if end_date is not None:
        simulation_end_date = min(simulation_end_date, end_date)

    current_date = start_date
    next_rebalance = strategy.next_rebalance(start_date)
    while current_date < simulation_end_date:
        previous_date = current_date
        current_date = min(next_rebalance, simulation_end_date)
        previous_portfolio = portfolio_log[-1]
        dividend_transition = _apply_dividends(
            previous_portfolio, previous_date, current_date
        )
        new_portfolio = dividend_transition.portfolio
        trade_log.extend(dividend_transition.trades)

        while current_date >= next_rebalance:
            transition = strategy.reblance(new_portfolio, history, current_date)
            new_portfolio = transition.portfolio
            trade_log.extend(transition.trades)
            upcoming_rebalance = strategy.next_rebalance(next_rebalance)
            if upcoming_rebalance <= next_rebalance:
                raise ValueError(
                    "strategy.next_rebalance must return a date after current_date"
                )
            next_rebalance = upcoming_rebalance

        if new_portfolio != previous_portfolio:
            portfolio_log.append(new_portfolio)

    _ensure_final_snapshot(portfolio_log, simulation_end_date)

    return SimulationResult(portfolio_log, trade_log, dividend_log)


def _add_years(when: date, years: int) -> date:
    """Add calendar years, clamping leap-day overflow to Feb 28."""
    try:
        return when.replace(year=when.year + years)
    except ValueError:
        return when.replace(month=2, day=28, year=when.year + years)


def _strategy_tickers(strategy: Strategy) -> set[Ticker]:
    return set(strategy.starting_allocation.proportions.keys())


def _first_price_date(history: MarketHistory, ticker: Ticker) -> date:
    prices = history.securities[ticker].prices
    return min(price.date for price in prices)


def _start_date_bounds(
    history: MarketHistory, strategy: Strategy, years: int
) -> tuple[date, date]:
    if years <= 0:
        raise ValueError("years must be greater than 0")

    tickers = _strategy_tickers(strategy)
    if not tickers:
        raise ValueError("strategy must include at least one ticker")

    earliest_start = max(_first_price_date(history, ticker) for ticker in tickers)
    latest_start = _add_years(history.end_date, -years)
    if earliest_start > latest_start:
        raise ValueError("no valid start-date window for requested simulation horizon")

    return earliest_start, latest_start


def _random_start_dates(
    history: MarketHistory,
    strategy: Strategy,
    years: int,
    num_simulations: int,
    rng: Random,
) -> list[date]:
    if num_simulations <= 0:
        raise ValueError("num_simulations must be greater than 0")

    earliest_start, latest_start = _start_date_bounds(history, strategy, years)
    candidate_days = (latest_start - earliest_start).days + 1
    return [
        earliest_start + timedelta(days=rng.randrange(candidate_days))
        for _ in range(num_simulations)
    ]


def simulate_many(
    strategy: Strategy,
    history: MarketHistory,
    years: int,
    start_funds: float,
    num_simulations: int,
    seed: int | None = None,
) -> MultiSimulationResult:
    """Run multiple randomized simulations for the given strategy."""
    rng = Random(seed)
    start_dates = _random_start_dates(
        history, strategy, years, num_simulations, rng=rng
    )
    simulations: list[SimulationResult] = []
    run_metrics: list[SimulationMetrics] = []

    for start_date in start_dates:
        end_date = _add_years(start_date, years)
        result = simulate(
            history=history,
            start_date=start_date,
            start_funds=start_funds,
            strategy=strategy,
            end_date=end_date,
        )
        simulations.append(result)
        run_metrics.append(
            compute_simulation_metrics(
                result.portfolios,
                history,
                start_funds=start_funds,
            )
        )

    aggregate_metrics = compute_simulation_metrics(
        [result.portfolios for result in simulations],
        history,
        start_funds=start_funds,
    )

    return MultiSimulationResult(
        simulations=simulations,
        run_metrics=run_metrics,
        metrics=aggregate_metrics,
    )
