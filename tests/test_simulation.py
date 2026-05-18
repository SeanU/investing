from datetime import date
import io

import pytest

from investing import data as d
from investing import history as h
from investing import portfolio as p
from investing.history import load_market_history
from investing.portfolio import AssetAllocation, HoldingTarget
from investing.simulation import (
    AnnualRebalance,
    BuyAndHold,
    MultiStrategySimulationResult,
    Strategy,
    first_available_price,
    print_simulation_preamble,
    simulate,
    simulate_many,
    start_date_sampling_bounds,
)


def _expected_end_date(start_date: date, years: int) -> date:
    """Mirror simulation._add_years leap-day handling for test expectations."""
    try:
        return start_date.replace(year=start_date.year + years)
    except ValueError:
        return start_date.replace(month=2, day=28, year=start_date.year + years)


def test__smoke_test():
    history = load_market_history("data/5-way-prices.xlsx", "data/5-way-dividends.xlsx")
    strategy = AnnualRebalance(
        AssetAllocation(
            [HoldingTarget(ticker, 1) for ticker in history.securities.keys()]
        ),
        0.05,
    )
    simulate(history, date(2022, 1, 1), 100_000, strategy)


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

    simulation = simulate(history, date(2022, 1, 1), 100_000, strategy)
    starting_portfolio = simulation.portfolios[0]
    start_date = date(2022, 1, 1)

    assert len(starting_portfolio.holdings) == 5
    assert starting_portfolio.total_value(start_date, history) == pytest.approx(
        100_000.0
    )

    values_by_ticker = starting_portfolio.value_by_ticker(start_date, history)
    for ticker in history.securities.keys():
        assert values_by_ticker[ticker] == pytest.approx(20_000.0)


class _NeverTradeStrategy(Strategy):
    def next_rebalance(self, current_date: date) -> date:
        return date.max

    def rebalance(
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
    )

    assert len(simulation.portfolios) == 2
    assert simulation.portfolios[0].holdings[0].quantity == pytest.approx(10.0)
    assert simulation.portfolios[-1].as_of_date == date(2026, 2, 1)
    assert simulation.trades == []
    assert simulation.dividends == []


def test_dividend_reinvestment_happens_before_rebalance():
    class _AlwaysRebalanceWithAToB(Strategy):
        def next_rebalance(self, current_date: date) -> date:
            first_rebalance = date(2026, 2, 1)
            if current_date < first_rebalance:
                return first_rebalance
            return date.max

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

        def rebalance(
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
    )

    trade_events = [
        (trade.kind, trade.ticker, trade.trade_date, trade.price, trade.quantity)
        for trade in simulation.trades
    ]
    assert len(trade_events) == len(set(trade_events))


def test_simulate_end_date_limits_how_long_simulation_runs():
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
        end_date=date(2026, 2, 1),
    )

    assert len(simulation.portfolios) == 2
    assert simulation.portfolios[-1].as_of_date == date(2026, 2, 1)
    assert len(simulation.trades) == 1
    assert simulation.trades[0].trade_date == date(2026, 2, 1)
    assert len(simulation.dividends) == 1
    assert simulation.dividends[0].payment_date == date(2026, 2, 1)


def test_simulate_many_returns_results_per_run_and_aggregate_metrics():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2027, 1, 1), 11.0),
                    d.Price(date(2028, 1, 1), 12.0),
                ],
                [],
            )
        }
    )
    strategy = BuyAndHold(AssetAllocation([HoldingTarget("A", 1)]))

    result = simulate_many(
        strategy=strategy,
        history=market_history,
        years=1,
        start_funds=100.0,
        num_simulations=5,
        seed=7,
    )

    assert len(result.simulations) == 5
    assert len(result.run_metrics) == 5
    assert result.metrics.terminal_wealth_p10 is not None
    assert result.metrics.terminal_wealth_p50 is not None
    assert result.metrics.terminal_wealth_p90 is not None
    for simulation, run_metric in zip(result.simulations, result.run_metrics):
        expected = simulate(
            history=market_history,
            start_date=simulation.portfolios[0].as_of_date,
            start_funds=100.0,
            strategy=strategy,
            end_date=simulation.portfolios[-1].as_of_date,
        )
        assert run_metric.terminal_wealth == pytest.approx(
            expected.portfolios[-1].total_value(
                expected.portfolios[-1].as_of_date, market_history
            )
        )


def test_simulate_many_applies_plan_target_return_to_metrics():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2027, 1, 1), 11.0),
                    d.Price(date(2028, 1, 1), 9.0),
                    d.Price(date(2028, 12, 31), 12.0),
                ],
                [],
            )
        }
    )
    strategy = BuyAndHold(AssetAllocation([HoldingTarget("A", 1)]))

    result = simulate_many(
        strategy=strategy,
        history=market_history,
        years=1,
        start_funds=100.0,
        num_simulations=6,
        plan_target_return=0.04,
        seed=7,
    )

    assert result.metrics.sortino_ratio is not None
    assert result.metrics.success_probability is not None
    for run_metric in result.run_metrics:
        assert run_metric.sortino_ratio is not None


def test_first_available_price_returns_earliest_quote_even_when_unsorted():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 2, 1), 11.0),
                    d.Price(date(2026, 1, 1), 10.0),
                ],
                [],
            )
        }
    )
    on_date, price = first_available_price(market_history, "A")
    assert on_date == date(2026, 1, 1)
    assert price == 10.0


def test_start_date_sampling_bounds_align_with_simulate_many_window():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2027, 1, 1), 11.0),
                    d.Price(date(2028, 12, 31), 12.0),
                ],
                [],
            ),
            "B": h.SecurityHistory(
                "B",
                [
                    d.Price(date(2026, 3, 1), 20.0),
                    d.Price(date(2027, 3, 1), 21.0),
                    d.Price(date(2028, 12, 31), 22.0),
                ],
                [],
            ),
        }
    )
    strategy = BuyAndHold(
        AssetAllocation([HoldingTarget("A", 1), HoldingTarget("B", 1)])
    )
    lo, hi = start_date_sampling_bounds(market_history, [strategy], years=1)
    assert lo == date(2026, 3, 1)
    assert hi == date(2027, 12, 31)


def test_print_simulation_preamble_includes_prices_and_sampling_range():
    market_history = h.MarketHistory(
        {
            "Z": h.SecurityHistory(
                "Z",
                [
                    d.Price(date(2026, 1, 5), 1.25),
                    d.Price(date(2028, 12, 31), 2.0),
                ],
                [],
            ),
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2028, 12, 31), 11.0),
                ],
                [],
            ),
        }
    )
    strategy = BuyAndHold(
        AssetAllocation([HoldingTarget("A", 1), HoldingTarget("Z", 1)])
    )
    buf = io.StringIO()
    print_simulation_preamble(market_history, [strategy], years=1, file=buf)
    text = buf.getvalue()
    assert "Securities (earliest available price):" in text
    assert "  A: 2026-01-01 @ 10" in text
    assert "  Z: 2026-01-05 @ 1.25" in text
    assert "Start dates are sampled uniformly" in text
    assert "2026-01-05 through 2027-12-31" in text


def test_simulate_many_respects_start_window_and_horizon():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2027, 1, 1), 11.0),
                    d.Price(date(2028, 12, 31), 12.0),
                ],
                [],
            ),
            "B": h.SecurityHistory(
                "B",
                [
                    d.Price(date(2026, 3, 1), 20.0),
                    d.Price(date(2027, 3, 1), 21.0),
                    d.Price(date(2028, 12, 31), 22.0),
                ],
                [],
            ),
        }
    )
    strategy = BuyAndHold(
        AssetAllocation([HoldingTarget("A", 1), HoldingTarget("B", 1)])
    )

    result = simulate_many(
        strategy=strategy,
        history=market_history,
        years=1,
        start_funds=100.0,
        num_simulations=20,
        seed=3,
    )

    earliest_start = date(2026, 3, 1)
    latest_start = date(2027, 12, 31)
    for simulation in result.simulations:
        start_date = simulation.portfolios[0].as_of_date
        end_date = simulation.portfolios[-1].as_of_date
        assert earliest_start <= start_date <= latest_start
        assert end_date == _expected_end_date(start_date, 1)


def test_simulate_many_raises_for_invalid_inputs_or_window():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 6, 1), 11.0),
                ],
                [],
            )
        }
    )
    strategy = BuyAndHold(AssetAllocation([HoldingTarget("A", 1)]))

    with pytest.raises(ValueError, match="years must be greater than 0"):
        simulate_many(
            strategy=strategy,
            history=market_history,
            years=0,
            start_funds=100.0,
            num_simulations=1,
        )

    with pytest.raises(ValueError, match="num_simulations must be greater than 0"):
        simulate_many(
            strategy=strategy,
            history=market_history,
            years=1,
            start_funds=100.0,
            num_simulations=0,
        )

    with pytest.raises(ValueError, match="no valid start-date window"):
        simulate_many(
            strategy=strategy,
            history=market_history,
            years=1,
            start_funds=100.0,
            num_simulations=1,
        )


def test_simulate_many_supports_multiple_strategies_with_shared_dates():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2027, 1, 1), 11.0),
                    d.Price(date(2028, 1, 1), 12.0),
                    d.Price(date(2028, 12, 31), 13.0),
                ],
                [],
            )
        }
    )
    strategies = [
        BuyAndHold(AssetAllocation([HoldingTarget("A", 1)])),
        AnnualRebalance(AssetAllocation([HoldingTarget("A", 1)]), 0.05),
    ]

    result = simulate_many(
        strategy=strategies,
        history=market_history,
        years=1,
        start_funds=100.0,
        num_simulations=8,
        seed=11,
    )

    assert isinstance(result, MultiStrategySimulationResult)
    assert set(result.by_strategy) == {"BuyAndHold", "AnnualRebalance"}
    buy_and_hold_dates = [
        (sim.portfolios[0].as_of_date, sim.portfolios[-1].as_of_date)
        for sim in result.by_strategy["BuyAndHold"].simulations
    ]
    annual_rebalance_dates = [
        (sim.portfolios[0].as_of_date, sim.portfolios[-1].as_of_date)
        for sim in result.by_strategy["AnnualRebalance"].simulations
    ]
    assert buy_and_hold_dates == annual_rebalance_dates
    assert len(result.by_strategy["BuyAndHold"].run_metrics) == 8
    assert len(result.by_strategy["AnnualRebalance"].run_metrics) == 8


def test_simulate_many_multiple_strategies_use_common_window():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2027, 1, 1), 11.0),
                    d.Price(date(2028, 12, 31), 12.0),
                ],
                [],
            ),
            "B": h.SecurityHistory(
                "B",
                [
                    d.Price(date(2026, 6, 1), 20.0),
                    d.Price(date(2027, 6, 1), 21.0),
                    d.Price(date(2028, 12, 31), 22.0),
                ],
                [],
            ),
        }
    )
    strategies = [
        BuyAndHold(AssetAllocation([HoldingTarget("A", 1)])),
        BuyAndHold(AssetAllocation([HoldingTarget("B", 1)])),
    ]

    result = simulate_many(
        strategy=strategies,
        history=market_history,
        years=1,
        start_funds=100.0,
        num_simulations=12,
        seed=5,
    )

    assert isinstance(result, MultiStrategySimulationResult)
    earliest_start = date(2026, 6, 1)
    latest_start = date(2027, 12, 31)
    for strategy_result in result.by_strategy.values():
        for simulation in strategy_result.simulations:
            start_date = simulation.portfolios[0].as_of_date
            end_date = simulation.portfolios[-1].as_of_date
            assert earliest_start <= start_date <= latest_start
            assert end_date == _expected_end_date(start_date, 1)


def test_simulate_many_multiple_strategies_reproducible_with_seed():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2027, 1, 1), 11.0),
                    d.Price(date(2028, 12, 31), 12.0),
                ],
                [],
            )
        }
    )
    strategies = [
        BuyAndHold(AssetAllocation([HoldingTarget("A", 1)])),
        AnnualRebalance(AssetAllocation([HoldingTarget("A", 1)]), 0.05),
    ]

    first = simulate_many(
        strategy=strategies,
        history=market_history,
        years=1,
        start_funds=100.0,
        num_simulations=10,
        seed=99,
    )
    second = simulate_many(
        strategy=strategies,
        history=market_history,
        years=1,
        start_funds=100.0,
        num_simulations=10,
        seed=99,
    )

    assert isinstance(first, MultiStrategySimulationResult)
    assert isinstance(second, MultiStrategySimulationResult)
    assert list(first.by_strategy) == list(second.by_strategy)
    for label in first.by_strategy:
        first_dates = [
            sim.portfolios[0].as_of_date for sim in first.by_strategy[label].simulations
        ]
        second_dates = [
            sim.portfolios[0].as_of_date
            for sim in second.by_strategy[label].simulations
        ]
        assert first_dates == second_dates


def test_simulate_many_raises_for_empty_strategy_collection():
    market_history = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2027, 1, 1), 11.0),
                ],
                [],
            )
        }
    )

    with pytest.raises(ValueError, match="at least one strategy is required"):
        simulate_many(
            strategy=[],
            history=market_history,
            years=1,
            start_funds=100.0,
            num_simulations=1,
        )
