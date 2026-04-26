from datetime import date

import pytest

from investing import data as d
from investing import history as h
from investing import portfolio as p
from investing.history import MarketHistory
from investing.metrics import SimulationMetrics, compute_simulation_metrics


def _mh(
    ticker: str, prices: list[tuple[date, float]]
) -> MarketHistory:
    return h.MarketHistory(
        {
            ticker: h.SecurityHistory(
                ticker,
                [d.Price(dt, px) for dt, px in prices],
                [],
            )
        }
    )


def _single_holding_portfolio(
    as_of: date, ticker: str, purchase_price: float, quantity: float
) -> p.Portfolio:
    return p.Portfolio(as_of, [p.Holding(ticker, as_of, purchase_price, quantity)])


def test_compute_metrics_empty_runs_returns_none_fields():
    hist = _mh("A", [(date(2026, 1, 1), 1.0), (date(2026, 2, 1), 1.0)])
    m = compute_simulation_metrics([], hist)
    assert isinstance(m, SimulationMetrics)
    assert m.cagr is None
    assert m.success_probability is None


def test_cagr_and_max_drawdown_single_run():
    """Monotonic growth ~21% over one year; max drawdown ~0."""
    hist = _mh(
        "A",
        [
            (date(2026, 1, 1), 100.0),
            (date(2027, 1, 1), 121.0),
        ],
    )
    port = _single_holding_portfolio(date(2026, 1, 1), "A", 100.0, 1.0)
    m = compute_simulation_metrics(
        [port],
        hist,
        plan_target_return=0.0,
        start_funds=100.0,
    )
    assert m.cagr is not None
    assert m.cagr == pytest.approx(0.21, rel=1e-2)
    assert m.max_drawdown is not None
    assert m.max_drawdown == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown_negative_path():
    hist = _mh(
        "A",
        [
            (date(2026, 1, 1), 100.0),
            (date(2026, 2, 1), 200.0),
            (date(2026, 3, 1), 50.0),
        ],
    )
    port = _single_holding_portfolio(date(2026, 1, 1), "A", 100.0, 1.0)
    m = compute_simulation_metrics(
        [port],
        hist,
        plan_target_return=0.0,
        start_funds=100.0,
    )
    # Peak 200, trough 50 -> 50/200 - 1 = -0.75
    assert m.max_drawdown == pytest.approx(-0.75, rel=1e-6)


def test_sortino_with_explicit_mar():
    # Source example:
    # https://protraderdashboard.com/blog/sortino-ratio-guide/
    # "Portfolio return: 12%, target: 2%, downside deviation: 8% -> Sortino = 1.25"
    #
    # We synthesize two monthly returns so our implementation yields:
    # - annualized mean return ~= 12%
    # - annualized downside deviation ~= 8%
    # with MAR = 2%, therefore expected Sortino ~= 1.25.
    mar_annual = 0.02
    mar_monthly = mar_annual / 12
    downside_monthly = 0.08 / (12**0.5)
    r1 = mar_monthly - (2**0.5) * downside_monthly
    r2 = 0.02 - r1  # makes average monthly return exactly 1% (12% annualized)

    v0 = 100.0
    v1 = v0 * (1 + r1)
    v2 = v1 * (1 + r2)

    hist = _mh(
        "A",
        [
            (date(2026, 1, 1), v0),
            (date(2026, 2, 1), v1),
            (date(2026, 3, 1), v2),
        ],
    )
    port = _single_holding_portfolio(date(2026, 1, 1), "A", 100.0, 1.0)
    m = compute_simulation_metrics(
        [port],
        hist,
        sortino_target_return=mar_annual,
        success_target_wealth=0.0,
    )
    assert m.sortino_target_return_used == pytest.approx(mar_annual)
    assert m.sortino_ratio is not None
    # value_history rounds valuations to cents, so allow a small tolerance.
    assert m.sortino_ratio == pytest.approx(1.25, rel=2e-3)


def test_sortino_undefined_when_no_downside_vs_mar():
    """Constant growth above MAR => downside deviation 0 => Sortino None."""
    hist = _mh(
        "A",
        [
            (date(2026, 1, 1), 100.0),
            (date(2026, 2, 1), 110.0),
            (date(2026, 3, 1), 121.0),
        ],
    )
    port = _single_holding_portfolio(date(2026, 1, 1), "A", 100.0, 1.0)
    m = compute_simulation_metrics(
        [port],
        hist,
        plan_target_return=0.0,
        success_target_wealth=1.0,
    )
    assert m.sortino_ratio is None


def test_success_probability_and_terminal_percentiles_multi_run():
    hist = h.MarketHistory(
        {
            "A": h.SecurityHistory(
                "A",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                    d.Price(date(2026, 3, 1), 10.0),
                ],
                [],
            ),
            "B": h.SecurityHistory(
                "B",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                    d.Price(date(2026, 3, 1), 20.0),
                ],
                [],
            ),
            "C": h.SecurityHistory(
                "C",
                [
                    d.Price(date(2026, 1, 1), 10.0),
                    d.Price(date(2026, 2, 1), 10.0),
                    d.Price(date(2026, 3, 1), 30.0),
                ],
                [],
            ),
        }
    )
    # 10 shares -> terminal totals 100, 200, 300 on last price date
    p_a = _single_holding_portfolio(date(2026, 1, 1), "A", 10.0, 10.0)
    p_b = _single_holding_portfolio(date(2026, 1, 1), "B", 10.0, 10.0)
    p_c = _single_holding_portfolio(date(2026, 1, 1), "C", 10.0, 10.0)

    m = compute_simulation_metrics(
        [[p_a], [p_b], [p_c]],
        hist,
        success_target_wealth=150.0,
        plan_target_return=None,
        sortino_target_return=0.0,
    )
    assert m.success_probability == pytest.approx(2 / 3)
    assert m.terminal_wealth_p10 == pytest.approx(120.0)
    assert m.terminal_wealth_p50 == pytest.approx(200.0)
    assert m.terminal_wealth_p90 == pytest.approx(280.0)


def test_plan_target_return_derives_success_wealth():
    hist = _mh(
        "A",
        [
            (date(2026, 1, 1), 100.0),
            (date(2027, 1, 1), 121.0),
        ],
    )
    port = _single_holding_portfolio(date(2026, 1, 1), "A", 100.0, 1.0)
    m = compute_simulation_metrics(
        [port],
        hist,
        plan_target_return=0.15,
        start_funds=100.0,
    )
    # ~1 calendar year -> target ~115; terminal 121 -> success
    assert m.success_target_wealth_used is not None
    assert m.success_target_wealth_used == pytest.approx(115.0, rel=0.02)
    assert m.success_probability == pytest.approx(1.0)


def test_success_override_does_not_use_plan_compounding():
    hist = _mh(
        "A",
        [
            (date(2026, 1, 1), 100.0),
            (date(2027, 1, 1), 110.0),
        ],
    )
    port = _single_holding_portfolio(date(2026, 1, 1), "A", 100.0, 1.0)
    m = compute_simulation_metrics(
        [port],
        hist,
        plan_target_return=0.50,
        success_target_wealth=200.0,
        start_funds=100.0,
    )
    assert m.success_target_wealth_used == pytest.approx(200.0)
    assert m.success_probability == pytest.approx(0.0)
