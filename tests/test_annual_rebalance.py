from datetime import date

import pytest

from investing import data as d
from investing import history as h
from investing import portfolio as p
from investing.portfolio import AssetAllocation, HoldingTarget
from investing.simulation import AnnualRebalance


class TestAnnualRebalance:
    """Focused unit tests for :class:`AnnualRebalance` scheduling and rebalance logic."""

    def test_next_rebalance_advances_one_calendar_year(self):
        """``next_rebalance`` returns the same calendar month and day one year later."""
        strategy = AnnualRebalance(
            AssetAllocation([HoldingTarget("A", 1), HoldingTarget("B", 1)]),
            max_deviation=0.05,
        )
        assert strategy.next_rebalance(date(2024, 6, 15)) == date(2025, 6, 15)

    def test_next_rebalance_leap_day_non_leap_year(self):
        """Feb 29 + 1 year uses the last valid day in February when needed."""
        strategy = AnnualRebalance(
            AssetAllocation([HoldingTarget("A", 1), HoldingTarget("B", 1)]),
            max_deviation=0.05,
        )
        assert strategy.next_rebalance(date(2016, 2, 29)) == date(2017, 2, 28)
        assert strategy.next_rebalance(date(2024, 2, 29)) == date(2025, 2, 28)

    def test_rebalance_preserves_total_value(self):
        """Rebalance moves holdings toward targets without changing NAV."""
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

        transition = strategy.rebalance(portfolio, market_history, date(2026, 1, 1))
        rebalanced = transition.portfolio
        rebalanced_values = rebalanced.value_by_ticker(date(2026, 1, 1), market_history)

        assert rebalanced.total_value(
            date(2026, 1, 1), market_history
        ) == pytest.approx(portfolio.total_value(date(2026, 1, 1), market_history))
        assert rebalanced_values["A"] == pytest.approx(50.0)
        assert rebalanced_values["B"] == pytest.approx(50.0)

    def test_rebalance_leaves_portfolio_unchanged_when_drifts_are_within_band(self):
        """It shouldn't rebalance if drifts are too small."""
        strategy = AnnualRebalance(
            AssetAllocation([HoldingTarget("A", 1), HoldingTarget("B", 1)]),
            max_deviation=0.05,
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
                p.Holding("A", date(2026, 1, 1), 10.0, 5.2),
                p.Holding("B", date(2026, 1, 1), 10.0, 4.8),
            ],
        )

        transition = strategy.rebalance(portfolio, market_history, date(2026, 1, 1))

        assert transition.trades == []
        assert transition.portfolio.total_value(
            date(2026, 1, 1), market_history
        ) == pytest.approx(portfolio.total_value(date(2026, 1, 1), market_history))

    def test_rebalance_restores_asymmetric_target_weights(self):
        """Also test moving from 50/50 to 75/25 on rebalance."""
        strategy = AnnualRebalance(
            AssetAllocation([HoldingTarget("A", 3), HoldingTarget("B", 1)]),
            max_deviation=0.05,
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
                p.Holding("A", date(2026, 1, 1), 10.0, 5.0),
                p.Holding("B", date(2026, 1, 1), 10.0, 5.0),
            ],
        )

        transition = strategy.rebalance(portfolio, market_history, date(2026, 1, 1))
        values = transition.portfolio.value_by_ticker(date(2026, 1, 1), market_history)
        total = transition.portfolio.total_value(date(2026, 1, 1), market_history)

        assert total == pytest.approx(100.0)
        assert values["A"] == pytest.approx(75.0)
        assert values["B"] == pytest.approx(25.0)

    def test_rebalance_converges_for_three_asset_overweight(self):
        """Tests prorating behavior."""
        strategy = AnnualRebalance(
            AssetAllocation(
                [
                    HoldingTarget("A", 1),
                    HoldingTarget("B", 1),
                    HoldingTarget("C", 1),
                ]
            ),
            max_deviation=0.05,
        )
        market_history = h.MarketHistory(
            {
                "A": h.SecurityHistory("A", [d.Price(date(2026, 1, 1), 1.0)], []),
                "B": h.SecurityHistory("B", [d.Price(date(2026, 1, 1), 1.0)], []),
                "C": h.SecurityHistory("C", [d.Price(date(2026, 1, 1), 1.0)], []),
                "D": h.SecurityHistory("D", [d.Price(date(2026, 1, 1), 1.0)], []),
            }
        )
        portfolio = p.Portfolio(
            date(2026, 1, 1),
            [
                p.Holding("A", date(2026, 1, 1), 1.0, 72.0),
                p.Holding("B", date(2026, 1, 1), 1.0, 9.0),
                p.Holding("C", date(2026, 1, 1), 1.0, 9.0),
            ],
        )

        transition = strategy.rebalance(portfolio, market_history, date(2026, 1, 1))
        values = transition.portfolio.value_by_ticker(date(2026, 1, 1), market_history)

        assert transition.portfolio.total_value(
            date(2026, 1, 1), market_history
        ) == pytest.approx(90.0)
        for ticker in ("A", "B", "C"):
            assert values[ticker] == pytest.approx(30.0)

    def test_rebalance_converges_for_three_asset_underweight(self):
        """Underweight names are topped up when another leg is materially overweight."""
        strategy = AnnualRebalance(
            AssetAllocation(
                [
                    HoldingTarget("A", 1),
                    HoldingTarget("B", 1),
                    HoldingTarget("C", 1),
                ]
            ),
            max_deviation=0.05,
        )
        market_history = h.MarketHistory(
            {
                "A": h.SecurityHistory("A", [d.Price(date(2026, 1, 1), 1.0)], []),
                "B": h.SecurityHistory("B", [d.Price(date(2026, 1, 1), 1.0)], []),
                "C": h.SecurityHistory("C", [d.Price(date(2026, 1, 1), 1.0)], []),
                "D": h.SecurityHistory("D", [d.Price(date(2026, 1, 1), 1.0)], []),
            }
        )
        portfolio = p.Portfolio(
            date(2026, 1, 1),
            [
                p.Holding("A", date(2026, 1, 1), 1.0, 9.0),
                p.Holding("B", date(2026, 1, 1), 1.0, 9.0),
                p.Holding("C", date(2026, 1, 1), 1.0, 72.0),
            ],
        )

        transition = strategy.rebalance(portfolio, market_history, date(2026, 1, 1))
        values = transition.portfolio.value_by_ticker(date(2026, 1, 1), market_history)

        assert transition.portfolio.total_value(
            date(2026, 1, 1), market_history
        ) == pytest.approx(90.0)
        for ticker in ("A", "B", "C"):
            assert values[ticker] == pytest.approx(30.0)

    def test_rebalance_with_two_overweighted(self):
        """Ensure rebalance only buys underweighted assets."""
        strategy = AnnualRebalance(
            AssetAllocation(
                [
                    HoldingTarget("A", 1),
                    HoldingTarget("B", 1),
                    HoldingTarget("C", 1),
                    HoldingTarget("D", 1),
                ]
            ),
            max_deviation=0.05,
        )
        market_history = h.MarketHistory(
            {
                "A": h.SecurityHistory("A", [d.Price(date(2026, 1, 1), 1.0)], []),
                "B": h.SecurityHistory("B", [d.Price(date(2026, 1, 1), 1.0)], []),
                "C": h.SecurityHistory("C", [d.Price(date(2026, 1, 1), 1.0)], []),
                "D": h.SecurityHistory("D", [d.Price(date(2026, 1, 1), 1.0)], []),
            }
        )
        portfolio = p.Portfolio(
            date(2026, 1, 1),
            [
                p.Holding("A", date(2026, 1, 1), 1.0, 31),
                p.Holding("B", date(2026, 1, 1), 1.0, 29),
                p.Holding("C", date(2026, 1, 1), 1.0, 21),
                p.Holding("D", date(2026, 1, 1), 1.0, 19),
            ],
        )

        transition = strategy.rebalance(portfolio, market_history, date(2026, 1, 1))
        values = transition.portfolio.value_by_ticker(date(2026, 1, 1), market_history)

        assert values["A"] == pytest.approx(25)
        assert values["B"] == pytest.approx(29)
        assert values["C"] == pytest.approx(23.4)
        assert values["D"] == pytest.approx(22.6)

    def test_rebalance_restores_equal_weights_when_only_underallocation_triggers(self):
        """No leg is over the band, but one name is far enough under to require buys."""
        strategy = AnnualRebalance(
            AssetAllocation(
                [
                    HoldingTarget("A", 1),
                    HoldingTarget("B", 1),
                    HoldingTarget("C", 1),
                    HoldingTarget("D", 1),
                ]
            ),
            max_deviation=0.05,
        )
        market_history = h.MarketHistory(
            {
                "A": h.SecurityHistory("A", [d.Price(date(2026, 1, 1), 1.0)], []),
                "B": h.SecurityHistory("B", [d.Price(date(2026, 1, 1), 1.0)], []),
                "C": h.SecurityHistory("C", [d.Price(date(2026, 1, 1), 1.0)], []),
                "D": h.SecurityHistory("D", [d.Price(date(2026, 1, 1), 1.0)], []),
            }
        )
        portfolio = p.Portfolio(
            date(2026, 1, 1),
            [
                p.Holding("A", date(2026, 1, 1), 1.0, 30.0),
                p.Holding("B", date(2026, 1, 1), 1.0, 60.0),
                p.Holding("C", date(2026, 1, 1), 1.0, 55.0),
                p.Holding("D", date(2026, 1, 1), 1.0, 55.0),
            ],
        )

        transition = strategy.rebalance(portfolio, market_history, date(2026, 1, 1))
        values = transition.portfolio.value_by_ticker(date(2026, 1, 1), market_history)

        assert transition.portfolio.total_value(
            date(2026, 1, 1), market_history
        ) == pytest.approx(200.0)
        for ticker in ("A", "B", "C", "D"):
            assert values[ticker] == pytest.approx(50.0)

    def test_rebalance_with_two_underweighted(self):
        """Ensure rebalance only sells overweight names when funding underweights."""
        strategy = AnnualRebalance(
            AssetAllocation(
                [
                    HoldingTarget("A", 1),
                    HoldingTarget("B", 1),
                    HoldingTarget("C", 1),
                    HoldingTarget("D", 1),
                ]
            ),
            max_deviation=0.05,
        )
        market_history = h.MarketHistory(
            {
                "A": h.SecurityHistory("A", [d.Price(date(2026, 1, 1), 1.0)], []),
                "B": h.SecurityHistory("B", [d.Price(date(2026, 1, 1), 1.0)], []),
                "C": h.SecurityHistory("C", [d.Price(date(2026, 1, 1), 1.0)], []),
                "D": h.SecurityHistory("D", [d.Price(date(2026, 1, 1), 1.0)], []),
            }
        )
        portfolio = p.Portfolio(
            date(2026, 1, 1),
            [
                p.Holding("A", date(2026, 1, 1), 1.0, 19),
                p.Holding("B", date(2026, 1, 1), 1.0, 21),
                p.Holding("C", date(2026, 1, 1), 1.0, 29),
                p.Holding("D", date(2026, 1, 1), 1.0, 31),
            ],
        )

        transition = strategy.rebalance(portfolio, market_history, date(2026, 1, 1))
        values = transition.portfolio.value_by_ticker(date(2026, 1, 1), market_history)

        assert values["A"] == pytest.approx(22.6)
        assert values["B"] == pytest.approx(23.4)
        assert values["C"] == pytest.approx(29)
        assert values["D"] == pytest.approx(25)
