from datetime import date

import pytest

from investing import data as d
from investing import history as h
from investing import portfolio as p
from investing.history import load_market_history
from investing.portfolio import AssetAllocation, HoldingTarget
from investing.simulation import (
    AnnualRebalance,
    Strategy,
    monthly_time_step,
    simulate,
)


def test__smoke_test():
    history = load_market_history("data/5-way-prices.xlsx", "data/5-way-dividends.xlsx")
    strategy = AnnualRebalance(
        AssetAllocation(
            [HoldingTarget(ticker, 1) for ticker in history.securities.keys()]
        ),
        0.05,
    )
    simulate(history, date(2022, 1, 1), 100_000, strategy, monthly_time_step)


def test_monthly_time_step_rolls_december_to_january_same_day():
    """Given: a date in December.

    Example input:
      - current_date = 2026-12-15

    Expected output:
      - next_date = 2027-01-15
    """
    assert monthly_time_step(date(2026, 12, 15)) == date(2027, 1, 15)


def test_simulate_builds_starting_portfolio_from_target_allocation():
    """Given: equal-weight allocation and fixed start funds.

    Example input:
      - start_date = 2022-01-01
      - start_funds = 100_000
      - target allocation: 5 tickers, equal weights
      - strategy: AnnualRebalance(max_deviation=0.05)

    Expected output:
      - First portfolio in the log has one holding per ticker
      - Sum of holding values equals 100_000 at start date
      - Each holding starts close to 20_000 in value
    """
    history = load_market_history("data/5-way-prices.xlsx", "data/5-way-dividends.xlsx")
    strategy = AnnualRebalance(
        AssetAllocation(
            [HoldingTarget(ticker, 1) for ticker in history.securities.keys()]
        ),
        0.05,
    )

    portfolios = simulate(history, date(2022, 1, 1), 100_000, strategy, monthly_time_step)
    starting_portfolio = portfolios[0]
    start_date = date(2022, 1, 1)

    assert len(starting_portfolio.holdings) == 5
    assert starting_portfolio.total_value(start_date, history) == pytest.approx(100_000.0)

    values_by_ticker = starting_portfolio.value_by_ticker(start_date, history)
    for ticker in history.securities.keys():
        assert values_by_ticker[ticker] == pytest.approx(20_000.0)


def test_annual_rebalance_keeps_total_value_constant_during_reallocation():
    """Given: a date where allocation drift exceeds max_deviation and rebalance occurs.

    Example input:
      - portfolio with clear over/under allocation
      - current_date where rebalance is triggered

    Expected output:
      - Rebalanced portfolio has same total_value as pre-rebalance portfolio
      - Holdings composition changes toward target weights
    """
    strategy = AnnualRebalance(
        AssetAllocation([HoldingTarget("A", 1), HoldingTarget("B", 1)]),
        0.05,
    )
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory("A", [d.Price(date(2026, 1, 1), 10.0)], []),
            "B": h.SecurityHistory("B", [d.Price(date(2026, 1, 1), 10.0)], []),
        }
    )
    portfolio = p.Portfolio(
        date(2026, 1, 1),
        [
            p.Holding("A", date(2026, 1, 1), 10.0, 7.0),
            p.Holding("B", date(2026, 1, 1), 10.0, 3.0),
        ],
    )

    rebalanced = strategy.reblance(portfolio, market_history, date(2026, 1, 1))
    rebalanced_values = rebalanced.value_by_ticker(date(2026, 1, 1), market_history)

    assert rebalanced.total_value(date(2026, 1, 1), market_history) == pytest.approx(
        portfolio.total_value(date(2026, 1, 1), market_history)
    )
    assert rebalanced_values["A"] == pytest.approx(50.0)
    assert rebalanced_values["B"] == pytest.approx(50.0)


class _NeverTradeStrategy(Strategy):
    def next_rebalance(self, current_date: date) -> date:
        return current_date

    def reblance(self, portfolio: p.Portfolio, history: h.MarketHistory, current_date: date):
        return portfolio


def test_simulate_keeps_single_snapshot_when_no_trades_are_made():
    """Given: strategy that never trades.

    Expected output:
      - simulate returns only the starting portfolio snapshot
      - no per-time-step portfolio clones are added
    """
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 11.0),
                    d.Price(date(2026, 3, 1), 12.0),
                ],
                [],
            )
        }
    )
    strategy = _NeverTradeStrategy(AssetAllocation([HoldingTarget("A", 1)]))

    portfolios = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        monthly_time_step,
    )

    assert len(portfolios) == 1
    assert portfolios[0].as_of_date == date(2026, 1, 1)
