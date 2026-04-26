"""Retirement-oriented aggregate metrics for simulated portfolio paths.

See ``docs/simulation-metrics.md`` for definitions and interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt
from statistics import fmean, pstdev
from typing import Sequence

from investing.history import MarketHistory
from investing.portfolio import Portfolio
from investing.reporting import (
    REPORTING_FREQUENCY_ERROR,
    ReportingFrequency,
    total_value_series,
)

_DAYS_PER_YEAR = 365.25


def _periods_per_year(reporting_frequency: ReportingFrequency) -> int:
    if reporting_frequency == "daily":
        return 252
    if reporting_frequency == "weekly":
        return 52
    if reporting_frequency == "monthly":
        return 12
    raise ValueError(REPORTING_FREQUENCY_ERROR)


def _fmean_or_none(values: list[float]) -> float | None:
    return fmean(values) if values else None


def _percentile_linear(values: Sequence[float], p: float) -> float | None:
    """Linear interpolation between closest ranks (common P10/P50/P90)."""
    if not values:
        return None
    xs = sorted(values)
    n = len(xs)
    if n == 1:
        return float(xs[0])
    k = (n - 1) * p
    f0 = int(k)
    f1 = min(f0 + 1, n - 1)
    w = k - f0
    return float(xs[f0] * (1 - w) + xs[f1] * w)


def _horizon_years(dates: Sequence[date]) -> float:
    if len(dates) < 2:
        return 0.0
    return (dates[-1] - dates[0]).days / _DAYS_PER_YEAR


def _cagr(start_value: float, end_value: float, years: float) -> float | None:
    if years <= 0 or start_value <= 0 or end_value <= 0:
        return None
    return (end_value / start_value) ** (1.0 / years) - 1.0


def _max_drawdown(values: Sequence[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = v / peak - 1.0
            if dd < worst:
                worst = dd
    return worst


def _simple_returns(values: Sequence[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        if prev <= 0:
            continue
        out.append((cur - prev) / prev)
    return out


def _annualized_std(
    returns: Sequence[float], reporting_frequency: ReportingFrequency
) -> float | None:
    if len(returns) < 2:
        return None
    m = _periods_per_year(reporting_frequency)
    # Population stdev of periodic returns, scaled to annual
    sigma = pstdev(returns)
    return float(sigma * sqrt(m))


def _sortino_ratio(
    returns: Sequence[float],
    reporting_frequency: ReportingFrequency,
    mar_annual: float,
) -> float | None:
    if not returns:
        return None
    m = _periods_per_year(reporting_frequency)
    mar_period = mar_annual / m
    # Downside deviation (population) of underperformance vs MAR per period
    squared_downsides = [min(0.0, r - mar_period) ** 2 for r in returns]
    downside_var = fmean(squared_downsides) if squared_downsides else 0.0
    downside_sigma = sqrt(downside_var)
    if downside_sigma == 0.0:
        # Undefined / unstable; callers aggregate across runs without infinities.
        return None

    mean_ann = fmean(returns) * m
    downside_ann = downside_sigma * sqrt(m)
    return (mean_ann - mar_annual) / downside_ann


@dataclass(frozen=True)
class SimulationMetrics:
    """Aggregated metrics for one or many simulation runs."""

    cagr: float | None
    max_drawdown: float | None
    std_dev_returns: float | None
    sortino_ratio: float | None
    success_probability: float | None
    terminal_wealth_p10: float | None
    terminal_wealth_p50: float | None
    terminal_wealth_p90: float | None
    sortino_target_return_used: float | None = None
    success_target_wealth_used: float | None = None


@dataclass(frozen=True)
class _SingleRunMetrics:
    cagr: float | None
    max_drawdown: float | None
    std_dev_returns: float | None
    sortino_ratio: float | None
    terminal_wealth: float | None


@dataclass(frozen=True)
class _ResolvedTargets:
    sortino_target_return: float | None
    success_target_wealth: float | None


def _path_metrics_single_run(
    portfolios: Sequence[Portfolio],
    history: MarketHistory,
    reporting_frequency: ReportingFrequency,
    mar_annual: float | None,
) -> _SingleRunMetrics:
    """Returns cagr, max_dd, std_ann, sortino, terminal_wealth."""
    dates, vals = total_value_series(list(portfolios), history, reporting_frequency)
    if len(vals) < 2 or len(dates) < 2:
        terminal = vals[-1] if vals else None
        return _SingleRunMetrics(
            cagr=None,
            max_drawdown=None,
            std_dev_returns=None,
            sortino_ratio=None,
            terminal_wealth=float(terminal) if terminal is not None else None,
        )

    years = _horizon_years(dates)
    start_v, end_v = vals[0], vals[-1]
    cagr = _cagr(start_v, end_v, years)
    mdd = _max_drawdown(vals)
    rets = _simple_returns(vals)
    std_ann = _annualized_std(rets, reporting_frequency) if rets else None
    sortino = (
        _sortino_ratio(rets, reporting_frequency, mar_annual)
        if mar_annual is not None and rets
        else None
    )
    return _SingleRunMetrics(
        cagr=cagr,
        max_drawdown=mdd,
        std_dev_returns=std_ann,
        sortino_ratio=sortino,
        terminal_wealth=end_v,
    )


def _resolve_mar_and_success_wealth(
    *,
    plan_target_return: float | None,
    sortino_target_return: float | None,
    success_target_wealth: float | None,
    initial_wealth: float,
    horizon_years: float,
) -> _ResolvedTargets:
    mar = (
        sortino_target_return
        if sortino_target_return is not None
        else plan_target_return
    )
    if success_target_wealth is not None:
        stw = success_target_wealth
    elif plan_target_return is not None:
        if horizon_years > 0:
            stw = initial_wealth * (1.0 + plan_target_return) ** horizon_years
        else:
            stw = initial_wealth
    else:
        stw = None
    return _ResolvedTargets(sortino_target_return=mar, success_target_wealth=stw)


def _normalize_runs(
    runs: Sequence[Portfolio] | Sequence[Sequence[Portfolio]],
) -> list[list[Portfolio]]:
    """Accept either one path ``[p0, p1, ...]`` or multiple paths ``[[...], [...]]``."""
    if not runs:
        return []
    first = runs[0]
    if isinstance(first, Portfolio):
        return [list(runs)]  # type: ignore[arg-type]
    return [list(r) for r in runs]  # type: ignore[union-attr]


def aggregate_simulation_metrics(
    run_metrics: Sequence[SimulationMetrics],
    *,
    sortino_target_return_used: float | None = None,
    success_target_wealth_used: float | None = None,
) -> SimulationMetrics:
    """Aggregate precomputed per-run metrics into one combined metric set."""
    cagrs = [m.cagr for m in run_metrics if m.cagr is not None]
    mdds = [m.max_drawdown for m in run_metrics if m.max_drawdown is not None]
    stds = [m.std_dev_returns for m in run_metrics if m.std_dev_returns is not None]
    sortinos = [m.sortino_ratio for m in run_metrics if m.sortino_ratio is not None]
    terminals = [
        m.terminal_wealth_p50 for m in run_metrics if m.terminal_wealth_p50 is not None
    ]
    successes = [
        m.success_probability for m in run_metrics if m.success_probability is not None
    ]

    return SimulationMetrics(
        cagr=_fmean_or_none(cagrs),
        max_drawdown=_fmean_or_none(mdds),
        std_dev_returns=_fmean_or_none(stds),
        sortino_ratio=_fmean_or_none(sortinos),
        success_probability=_fmean_or_none(successes),
        terminal_wealth_p10=_percentile_linear(terminals, 0.10) if terminals else None,
        terminal_wealth_p50=_percentile_linear(terminals, 0.50) if terminals else None,
        terminal_wealth_p90=_percentile_linear(terminals, 0.90) if terminals else None,
        sortino_target_return_used=sortino_target_return_used,
        success_target_wealth_used=success_target_wealth_used,
    )


def compute_simulation_metrics(
    runs: Sequence[Portfolio] | Sequence[Sequence[Portfolio]],
    history: MarketHistory,
    *,
    plan_target_return: float | None = None,
    sortino_target_return: float | None = None,
    success_target_wealth: float | None = None,
    reporting_frequency: ReportingFrequency = "monthly",
    start_funds: float | None = None,
) -> SimulationMetrics:
    """Compute retirement-oriented metrics for one or many portfolio path runs.

    **Single run:** pass ``runs=portfolios`` (a single path) or ``runs=[portfolios]``.

    **Multiple runs:** pass ``runs=[run1_portfolios, run2_portfolios, ...]``.
    Path metrics (CAGR, max drawdown, std dev, Sortino) are **averaged** across
    runs. Success probability and terminal wealth percentiles use the
    distribution of ending values across runs.

    **Planning target:** ``plan_target_return`` (annual, e.g. ``0.04`` for 4%)
    defaults both Sortino MAR and success wealth threshold unless overridden
    via ``sortino_target_return`` or ``success_target_wealth``. Success wealth
    when derived is ``start * (1 + plan_target_return) ** horizon_years``,
    where ``horizon_years`` is from the first run's reporting dates and
    ``start`` is ``start_funds`` if given, else the first total portfolio value
    on that run.
    """
    run_list = _normalize_runs(runs)
    if not run_list:
        return SimulationMetrics(
            cagr=None,
            max_drawdown=None,
            std_dev_returns=None,
            sortino_ratio=None,
            success_probability=None,
            terminal_wealth_p10=None,
            terminal_wealth_p50=None,
            terminal_wealth_p90=None,
            sortino_target_return_used=None,
            success_target_wealth_used=None,
        )

    first = run_list[0]
    dates0, vals0 = total_value_series(first, history, reporting_frequency)
    horizon_years = _horizon_years(dates0)
    if start_funds is not None:
        initial_wealth = float(start_funds)
    elif vals0:
        initial_wealth = float(vals0[0])
    else:
        initial_wealth = 0.0

    resolved_targets = _resolve_mar_and_success_wealth(
        plan_target_return=plan_target_return,
        sortino_target_return=sortino_target_return,
        success_target_wealth=success_target_wealth,
        initial_wealth=initial_wealth,
        horizon_years=horizon_years,
    )

    cagrs: list[float] = []
    mdds: list[float] = []
    stds: list[float] = []
    sortinos: list[float] = []
    terminals: list[float] = []

    for run in run_list:
        run_metrics = _path_metrics_single_run(
            run,
            history,
            reporting_frequency,
            resolved_targets.sortino_target_return,
        )
        if run_metrics.cagr is not None:
            cagrs.append(run_metrics.cagr)
        if run_metrics.max_drawdown is not None:
            mdds.append(run_metrics.max_drawdown)
        if run_metrics.std_dev_returns is not None:
            stds.append(run_metrics.std_dev_returns)
        if run_metrics.sortino_ratio is not None:
            sortinos.append(run_metrics.sortino_ratio)
        if run_metrics.terminal_wealth is not None:
            terminals.append(run_metrics.terminal_wealth)

    cagr_mean = _fmean_or_none(cagrs)
    mdd_mean = _fmean_or_none(mdds)
    std_mean = _fmean_or_none(stds)

    sortino_mean = _fmean_or_none(sortinos)

    success_prob: float | None
    if resolved_targets.success_target_wealth is None or not terminals:
        success_prob = None
    else:
        success_prob = sum(
            1 for t in terminals if t >= resolved_targets.success_target_wealth
        ) / len(terminals)

    p10 = _percentile_linear(terminals, 0.10) if terminals else None
    p50 = _percentile_linear(terminals, 0.50) if terminals else None
    p90 = _percentile_linear(terminals, 0.90) if terminals else None

    return SimulationMetrics(
        cagr=cagr_mean,
        max_drawdown=mdd_mean,
        std_dev_returns=std_mean,
        sortino_ratio=sortino_mean,
        success_probability=success_prob,
        terminal_wealth_p10=p10,
        terminal_wealth_p50=p50,
        terminal_wealth_p90=p90,
        sortino_target_return_used=resolved_targets.sortino_target_return,
        success_target_wealth_used=resolved_targets.success_target_wealth,
    )
