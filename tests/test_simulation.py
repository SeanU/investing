from datetime import date

import pytest

from investing import data as d
from investing import history as h
from investing import portfolio as p
from investing.history import load_market_history
from investing.portfolio import AssetAllocation, HoldingTarget
from investing.simulation import (
    AnnualRebalance,
    BuyAndHold,
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

    simulation = simulate(history, date(2022, 1, 1), 100_000, strategy, monthly_time_step)
    starting_portfolio = simulation.portfolios[0]
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

    transition = strategy.reblance(portfolio, market_history, date(2026, 1, 1))
    rebalanced = transition.portfolio
    rebalanced_values = rebalanced.value_by_ticker(date(2026, 1, 1), market_history)

    assert rebalanced.total_value(date(2026, 1, 1), market_history) == pytest.approx(
        portfolio.total_value(date(2026, 1, 1), market_history)
    )
    assert rebalanced_values["A"] == pytest.approx(50.0)
    assert rebalanced_values["B"] == pytest.approx(50.0)


class _NeverTradeStrategy(Strategy):
    def next_rebalance(self, current_date: date) -> date:
        return current_date

    def reblance(
        self, portfolio: p.Portfolio, history: h.MarketHistory, current_date: date
    ) -> p.PortfolioTransition:
        return p.PortfolioTransition(portfolio)

    def reinvest_dividends(
        self,
        portfolio: p.Portfolio,
        history: h.MarketHistory,
        current_date: date,
        payouts: dict[d.Ticker, float],
    ) -> p.PortfolioTransition:
        return p.PortfolioTransition(portfolio)


def test_simulate_keeps_start_and_end_snapshots_when_no_trades_are_made():
    """Given: strategy that never trades.

    Expected output:
      - simulate returns starting and ending portfolio snapshots
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

    simulation = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        monthly_time_step,
    )

    assert len(simulation.portfolios) == 2
    assert simulation.portfolios[0].as_of_date == date(2026, 1, 1)
    assert simulation.portfolios[-1].as_of_date == date(2026, 3, 1)
    assert simulation.trades == []
    assert simulation.dividends == []


def test_simulate_does_not_duplicate_final_snapshot_when_end_date_already_logged():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                ],
                [
                    d.Dividend(
                        amount=1.0,
                        adjusted_amount=1.0,
                        ex_date=date(2026, 1, 15),
                        payment_date=date(2026, 2, 1),
                    )
                ],
            )
        }
    )
    strategy = BuyAndHold(AssetAllocation([HoldingTarget("A", 1)]))
    simulation = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        monthly_time_step,
    )

    assert len(simulation.portfolios) == 2
    assert simulation.portfolios[-1].as_of_date == date(2026, 2, 1)


def test_simulate_applies_dividends_on_payment_date():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                ],
                [
                    d.Dividend(
                        amount=1.0,
                        adjusted_amount=1.0,
                        ex_date=date(2026, 1, 15),
                        payment_date=date(2026, 2, 1),
                    )
                ],
            )
        }
    )
    strategy = BuyAndHold(AssetAllocation([HoldingTarget("A", 1)]))
    simulation = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        monthly_time_step,
    )

    assert len(simulation.portfolios) == 2
    assert simulation.portfolios[-1].as_of_date == date(2026, 2, 1)
    total_quantity = sum(
        holding.quantity
        for holding in simulation.portfolios[-1].holdings
        if holding.ticker == "A"
    )
    assert total_quantity == pytest.approx(11.0)
    assert simulation.trades[-1].kind == "buy"
    assert simulation.trades[-1].ticker == "A"
    assert simulation.trades[-1].quantity == pytest.approx(1.0)
    assert len(simulation.dividends) == 1
    dividend_payment = simulation.dividends[0]
    assert dividend_payment.payment_date == date(2026, 2, 1)
    assert dividend_payment.ticker == "A"
    assert dividend_payment.shares_held == pytest.approx(10.0)
    assert dividend_payment.amount_per_share == pytest.approx(1.0)
    assert dividend_payment.total_payment == pytest.approx(10.0)


def test_simulate_does_not_apply_dividends_before_payment_date():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                ],
                [
                    d.Dividend(
                        amount=1.0,
                        adjusted_amount=1.0,
                        ex_date=date(2026, 1, 10),
                        payment_date=date(2026, 3, 1),
                    )
                ],
            )
        }
    )
    strategy = _NeverTradeStrategy(AssetAllocation([HoldingTarget("A", 1)]))
    simulation = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        monthly_time_step,
    )

    assert len(simulation.portfolios) == 2
    assert simulation.portfolios[0].holdings[0].quantity == pytest.approx(10.0)
    assert simulation.portfolios[-1].as_of_date == date(2026, 2, 1)
    assert simulation.trades == []
    assert simulation.dividends == []


def test_dividend_reinvestment_happens_before_rebalance():
    class _AlwaysRebalanceWithAToB(Strategy):
        def next_rebalance(self, current_date: date) -> date:
            return current_date

        def reinvest_dividends(
            self,
            portfolio: p.Portfolio,
            history: h.MarketHistory,
            current_date: date,
            payouts: dict[d.Ticker, float],
        ) -> p.PortfolioTransition:
            reinvested = portfolio
            trades: list[p.Trade] = []
            for ticker, amount in payouts.items():
                if amount > 0:
                    transition = reinvested.buy(ticker, amount, current_date, history)
                    reinvested = transition.portfolio
                    trades.extend(transition.trades)
            return p.PortfolioTransition(reinvested, trades)

        def reblance(
            self, portfolio: p.Portfolio, history: h.MarketHistory, current_date: date
        ) -> p.PortfolioTransition:
            value_by_ticker = portfolio.value_by_ticker(current_date, history)
            if value_by_ticker["A"] > value_by_ticker["B"]:
                return portfolio.trade(
                    sell_ticker="A",
                    buy_ticker="B",
                    amount=5.0,
                    trade_date=current_date,
                    prices=history,
                )
            return p.PortfolioTransition(portfolio)

    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                ],
                [
                    d.Dividend(
                        amount=0.5,
                        adjusted_amount=0.5,
                        ex_date=date(2026, 1, 15),
                        payment_date=date(2026, 2, 1),
                    )
                ],
            ),
            "B": h.SecurityHistory(
                "B",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                ],
                [],
            ),
        }
    )
    strategy = _AlwaysRebalanceWithAToB(
        AssetAllocation([HoldingTarget("A", 1), HoldingTarget("B", 1)])
    )
    simulation = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        monthly_time_step,
    )

    assert len(simulation.portfolios) == 2
    final_portfolio = simulation.portfolios[-1]
    assert final_portfolio.as_of_date == date(2026, 2, 1)
    assert simulation.trades[0].kind == "buy"
    assert simulation.trades[0].ticker == "A"
    assert simulation.trades[0].quantity == pytest.approx(0.25)
    assert simulation.trades[1].kind == "sell"
    assert simulation.trades[1].ticker == "A"
    assert simulation.trades[2].kind == "buy"
    assert simulation.trades[2].ticker == "B"


def test_simulate_processes_each_payment_date_without_lumping():
    def quarterly_time_step(_: date) -> date:
        return date(2026, 4, 1)

    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                    d.Price(date(2026, 3, 1), 10.0),
                    d.Price(date(2026, 4, 1), 20.0),
                ],
                [
                    d.Dividend(
                        amount=1.0,
                        adjusted_amount=1.0,
                        ex_date=date(2026, 1, 15),
                        payment_date=date(2026, 2, 1),
                    ),
                    d.Dividend(
                        amount=1.0,
                        adjusted_amount=1.0,
                        ex_date=date(2026, 2, 15),
                        payment_date=date(2026, 3, 1),
                    ),
                ],
            )
        }
    )
    strategy = BuyAndHold(AssetAllocation([HoldingTarget("A", 1)]))
    simulation = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        quarterly_time_step,
    )

    assert len(simulation.portfolios) == 3
    final_portfolio = simulation.portfolios[-1]
    assert final_portfolio.as_of_date == date(2026, 4, 1)
    assert len(simulation.trades) == 2
    assert simulation.trades[0].trade_date == date(2026, 2, 1)
    assert simulation.trades[1].trade_date == date(2026, 3, 1)
    assert simulation.trades[0].quantity == pytest.approx(1.0)
    assert simulation.trades[1].quantity == pytest.approx(1.1)
    assert len(simulation.dividends) == 2
    assert simulation.dividends[0].payment_date == date(2026, 2, 1)
    assert simulation.dividends[0].ticker == "A"
    assert simulation.dividends[0].shares_held == pytest.approx(10.0)
    assert simulation.dividends[0].amount_per_share == pytest.approx(1.0)
    assert simulation.dividends[0].total_payment == pytest.approx(10.0)
    assert simulation.dividends[1].payment_date == date(2026, 3, 1)
    assert simulation.dividends[1].ticker == "A"
    assert simulation.dividends[1].shares_held == pytest.approx(11.0)
    assert simulation.dividends[1].amount_per_share == pytest.approx(1.0)
    assert simulation.dividends[1].total_payment == pytest.approx(11.0)


def test_simulate_trade_log_contains_unique_events_without_snapshot_duplicates():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                ],
                [
                    d.Dividend(
                        amount=1.0,
                        adjusted_amount=1.0,
                        ex_date=date(2026, 1, 15),
                        payment_date=date(2026, 2, 1),
                    )
                ],
            )
        }
    )
    strategy = BuyAndHold(AssetAllocation([HoldingTarget("A", 1)]))
    simulation = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        monthly_time_step,
    )

    trade_events = [
        (trade.kind, trade.ticker, trade.trade_date, trade.price, trade.quantity)
        for trade in simulation.trades
    ]
    assert len(trade_events) == len(set(trade_events))


def test_simulate_end_date_limits_how_long_simulation_runs():
    def quarterly_time_step(_: date) -> date:
        return date(2026, 4, 1)

    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                    d.Price(date(2026, 3, 1), 10.0),
                    d.Price(date(2026, 4, 1), 20.0),
                ],
                [
                    d.Dividend(
                        amount=1.0,
                        adjusted_amount=1.0,
                        ex_date=date(2026, 1, 15),
                        payment_date=date(2026, 2, 1),
                    ),
                    d.Dividend(
                        amount=1.0,
                        adjusted_amount=1.0,
                        ex_date=date(2026, 2, 15),
                        payment_date=date(2026, 3, 1),
                    ),
                ],
            )
        }
    )
    strategy = BuyAndHold(AssetAllocation([HoldingTarget("A", 1)]))
    simulation = simulate(
        market_history,
        date(2026, 1, 1),
        100.0,
        strategy,
        quarterly_time_step,
        end_date=date(2026, 2, 1),
    )

    assert len(simulation.portfolios) == 2
    assert simulation.portfolios[-1].as_of_date == date(2026, 2, 1)
    assert len(simulation.trades) == 1
    assert simulation.trades[0].trade_date == date(2026, 2, 1)
    assert len(simulation.dividends) == 1
    assert simulation.dividends[0].payment_date == date(2026, 2, 1)
