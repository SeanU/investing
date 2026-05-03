"""CLI: run portfolio simulations from a JSON config and save raw results to Parquet.

Reads a JSON config describing market data, run count, time horizon, starting
value, target annual return (Sortino MAR and success wealth), RNG seed, and a
list of strategies (allocation + rebalancing). Runs the
existing :func:`investing.simulation.simulate_many` engine and writes the full
raw output (portfolios, holdings, trades, dividends, metrics) to one Parquet
file per table under ``output/<config_stem>/``.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import polars as pl

from investing.history import load_market_history
from investing.metrics import SimulationMetrics
from investing.portfolio import AssetAllocation, HoldingTarget
from investing.simulation import (
    AnnualRebalance,
    BuyAndHold,
    MultiSimulationResult,
    MultiStrategySimulationResult,
    Strategy,
    simulate_many,
)

SIMULATIONS_CONFIG_DIR = Path("config/simulations")


def simulation_config_path(config_root: str) -> Path:
    """Path to ``config/simulations/<config_root>.json`` (relative to the process cwd).

    *config_root* is the basename without ``.json`` (e.g. ``simulation.example``).
    """
    name = config_root.strip()
    if not name:
        raise ValueError("Config name must be non-empty.")
    if name in (".", ".."):
        raise ValueError("Invalid config name.")
    if "/" in name or "\\" in name:
        raise ValueError("Config name must not contain path separators.")
    filename = f"{name}.json"
    if Path(filename).name != filename:
        raise ValueError("Invalid config name.")
    return SIMULATIONS_CONFIG_DIR / filename


def _simulation_config_root_arg(value: str) -> Path:
    try:
        return simulation_config_path(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


RebalancingType = Literal["annual", "buy_and_hold"]


@dataclass(frozen=True)
class RebalancingConfig:
    type: RebalancingType
    max_deviation: float | None


@dataclass(frozen=True)
class StrategyConfig:
    name: str
    allocation: dict[str, int]
    rebalancing: RebalancingConfig


# TODO: tidy this
@dataclass(frozen=True)
class SimulationConfig:
    path: Path
    market_data: str
    num_simulations: int
    years: int
    starting_value: float
    # Annual decimal (e.g. 0.04); Sortino MAR and basis for success wealth threshold.
    target_annual_return: float
    seed: int
    strategies: list[StrategyConfig]

    @property
    def stem(self) -> str:
        return self.path.stem


# ---------- Config loading & validation ----------


def _is_pure_int(value: Any) -> bool:
    # bool is an int subclass; reject it explicitly.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_allocation(name: str, allocation: Any) -> dict[str, int]:
    if not isinstance(allocation, dict):
        raise ValueError(f"strategy {name!r}: allocation must be an object")
    if not allocation:
        raise ValueError(f"strategy {name!r}: allocation must not be empty")
    out: dict[str, int] = {}
    for ticker, weight in allocation.items():
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError(
                f"strategy {name!r}: allocation keys must be non-empty strings"
            )
        if not _is_pure_int(weight):
            raise ValueError(
                f"strategy {name!r}: allocation weight for {ticker!r} must be an integer"
            )
        if weight <= 0:
            raise ValueError(
                f"strategy {name!r}: allocation weight for {ticker!r} must be positive"
            )
        out[ticker] = weight
    return out


def _validate_rebalancing(name: str, rb: Any) -> RebalancingConfig:
    if not isinstance(rb, dict):
        raise ValueError(f"strategy {name!r}: rebalancing must be an object")
    rb_type = rb.get("type")
    if rb_type == "buy_and_hold":
        return RebalancingConfig(type="buy_and_hold", max_deviation=None)
    if rb_type == "annual":
        max_dev = rb.get("max_deviation")
        if not _is_number(max_dev):
            raise ValueError(
                f"strategy {name!r}: rebalancing.max_deviation must be a number"
            )
        if max_dev < 0:
            raise ValueError(
                f"strategy {name!r}: rebalancing.max_deviation must be >= 0"
            )
        return RebalancingConfig(type="annual", max_deviation=float(max_dev))
    raise ValueError(
        f"strategy {name!r}: rebalancing.type must be 'annual' or 'buy_and_hold' "
        f"(got {rb_type!r})"
    )


def _validate_strategy(raw: Any, seen_names: set[str]) -> StrategyConfig:
    if not isinstance(raw, dict):
        raise ValueError("each strategy must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("strategy.name must be a non-empty string")
    if name in seen_names:
        raise ValueError(f"strategy name {name!r} is duplicated")
    seen_names.add(name)
    allocation = _validate_allocation(name, raw.get("allocation"))
    rebalancing = _validate_rebalancing(name, raw.get("rebalancing"))
    return StrategyConfig(name=name, allocation=allocation, rebalancing=rebalancing)


def load_simulation_config(path: str | Path) -> SimulationConfig:
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Config not found: {p}")
    with p.open(encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, dict):
        raise ValueError("config root must be a JSON object")

    market_data = raw.get("market_data")
    if not isinstance(market_data, str) or not market_data.strip():
        raise ValueError("config.market_data must be a non-empty string")

    num_simulations = raw.get("num_simulations")
    if not _is_pure_int(num_simulations) or num_simulations <= 0:
        raise ValueError("config.num_simulations must be a positive integer")

    years = raw.get("years")
    if not _is_pure_int(years) or years <= 0:
        raise ValueError("config.years must be a positive integer")

    starting_value = raw.get("starting_value")
    if not _is_number(starting_value) or starting_value <= 0:
        raise ValueError("config.starting_value must be a positive number")

    target_annual_return = raw.get("target_annual_return")
    if target_annual_return is None:
        raise ValueError(
            "config.target_annual_return is required (annual decimal, e.g. 0.04); "
            "it sets the Sortino MAR and the success wealth threshold"
        )
    if not _is_number(target_annual_return):
        raise ValueError("config.target_annual_return must be a number")

    seed = raw.get("seed")
    if not _is_pure_int(seed):
        raise ValueError("config.seed must be an integer")

    strategies_raw = raw.get("strategies")
    if not isinstance(strategies_raw, list) or not strategies_raw:
        raise ValueError("config.strategies must be a non-empty array")

    seen_names: set[str] = set()
    strategies = [_validate_strategy(s, seen_names) for s in strategies_raw]

    return SimulationConfig(
        path=p,
        market_data=market_data.strip(),
        num_simulations=int(num_simulations),
        years=int(years),
        starting_value=float(starting_value),
        target_annual_return=float(target_annual_return),
        seed=int(seed),
        strategies=strategies,
    )


# ---------- Strategy construction ----------


def _build_allocation(allocation: dict[str, int]) -> AssetAllocation:
    return AssetAllocation(
        [HoldingTarget(ticker, weight) for ticker, weight in allocation.items()]
    )


def build_strategy(cfg: StrategyConfig) -> Strategy:
    allocation = _build_allocation(cfg.allocation)
    if cfg.rebalancing.type == "buy_and_hold":
        return BuyAndHold(allocation)
    if cfg.rebalancing.type == "annual":
        assert cfg.rebalancing.max_deviation is not None
        return AnnualRebalance(allocation, cfg.rebalancing.max_deviation)
    raise ValueError(f"unknown rebalancing type: {cfg.rebalancing.type!r}")


# ---------- Parquet schemas ----------

_RUNS_SCHEMA: dict[str, Any] = {
    "strategy": pl.Utf8,
    "run_index": pl.Int64,
    "start_date": pl.Date,
    "end_date": pl.Date,
    "start_funds": pl.Float64,
    "seed": pl.Int64,
}

_PORTFOLIOS_SCHEMA: dict[str, Any] = {
    "strategy": pl.Utf8,
    "run_index": pl.Int64,
    "snapshot_index": pl.Int64,
    "as_of_date": pl.Date,
}

_HOLDINGS_SCHEMA: dict[str, Any] = {
    "strategy": pl.Utf8,
    "run_index": pl.Int64,
    "snapshot_index": pl.Int64,
    "ticker": pl.Utf8,
    "purchase_date": pl.Date,
    "purchase_price": pl.Float64,
    "quantity": pl.Float64,
    "basis": pl.Float64,
}

_TRADES_SCHEMA: dict[str, Any] = {
    "strategy": pl.Utf8,
    "run_index": pl.Int64,
    "kind": pl.Utf8,
    "ticker": pl.Utf8,
    "trade_date": pl.Date,
    "price": pl.Float64,
    "quantity": pl.Float64,
}

_DIVIDENDS_SCHEMA: dict[str, Any] = {
    "strategy": pl.Utf8,
    "run_index": pl.Int64,
    "payment_date": pl.Date,
    "ticker": pl.Utf8,
    "shares_held": pl.Float64,
    "amount_per_share": pl.Float64,
    "total_payment": pl.Float64,
}

_METRIC_VALUE_FIELDS = (
    "cagr",
    "max_drawdown",
    "std_dev_returns",
    "sortino_ratio",
    "success_probability",
    "terminal_wealth_p10",
    "terminal_wealth_p50",
    "terminal_wealth_p90",
    "sortino_target_return_used",
    "success_target_wealth_used",
)

_RUN_METRICS_SCHEMA: dict[str, Any] = {
    "strategy": pl.Utf8,
    "run_index": pl.Int64,
    **{field: pl.Float64 for field in _METRIC_VALUE_FIELDS},
}

_AGGREGATE_METRICS_SCHEMA: dict[str, Any] = {
    "strategy": pl.Utf8,
    **{field: pl.Float64 for field in _METRIC_VALUE_FIELDS},
}


# ---------- Row builders ----------


def _metrics_to_row(metrics: SimulationMetrics) -> dict[str, float | None]:
    return {field: getattr(metrics, field) for field in _METRIC_VALUE_FIELDS}


def _build_runs_rows(
    cfg: SimulationConfig,
    labeled: dict[str, MultiSimulationResult],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_name, result in labeled.items():
        for run_index, run in enumerate(result.simulations):
            rows.append(
                {
                    "strategy": strategy_name,
                    "run_index": run_index,
                    "start_date": run.portfolios[0].as_of_date,
                    "end_date": run.portfolios[-1].as_of_date,
                    "start_funds": cfg.starting_value,
                    "seed": cfg.seed,
                }
            )
    return rows


def _build_portfolio_rows(
    labeled: dict[str, MultiSimulationResult],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    portfolio_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    for strategy_name, result in labeled.items():
        for run_index, run in enumerate(result.simulations):
            for snapshot_index, portfolio in enumerate(run.portfolios):
                portfolio_rows.append(
                    {
                        "strategy": strategy_name,
                        "run_index": run_index,
                        "snapshot_index": snapshot_index,
                        "as_of_date": portfolio.as_of_date,
                    }
                )
                for holding in portfolio.holdings:
                    holding_rows.append(
                        {
                            "strategy": strategy_name,
                            "run_index": run_index,
                            "snapshot_index": snapshot_index,
                            "ticker": holding.ticker,
                            "purchase_date": holding.purchase_date,
                            "purchase_price": holding.purchase_price,
                            "quantity": holding.quantity,
                            "basis": holding.basis,
                        }
                    )
    return portfolio_rows, holding_rows


def _build_trade_rows(
    labeled: dict[str, MultiSimulationResult],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_name, result in labeled.items():
        for run_index, run in enumerate(result.simulations):
            for trade in run.trades:
                rows.append(
                    {
                        "strategy": strategy_name,
                        "run_index": run_index,
                        "kind": trade.kind,
                        "ticker": trade.ticker,
                        "trade_date": trade.trade_date,
                        "price": trade.price,
                        "quantity": trade.quantity,
                    }
                )
    return rows


def _build_dividend_rows(
    labeled: dict[str, MultiSimulationResult],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_name, result in labeled.items():
        for run_index, run in enumerate(result.simulations):
            for dividend in run.dividends:
                rows.append(
                    {
                        "strategy": strategy_name,
                        "run_index": run_index,
                        "payment_date": dividend.payment_date,
                        "ticker": dividend.ticker,
                        "shares_held": dividend.shares_held,
                        "amount_per_share": dividend.amount_per_share,
                        "total_payment": dividend.total_payment,
                    }
                )
    return rows


def _build_run_metrics_rows(
    labeled: dict[str, MultiSimulationResult],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_name, result in labeled.items():
        for run_index, metrics in enumerate(result.run_metrics):
            row: dict[str, Any] = {
                "strategy": strategy_name,
                "run_index": run_index,
            }
            row.update(_metrics_to_row(metrics))
            rows.append(row)
    return rows


def _build_aggregate_metrics_rows(
    labeled: dict[str, MultiSimulationResult],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for strategy_name, result in labeled.items():
        row: dict[str, Any] = {"strategy": strategy_name}
        row.update(_metrics_to_row(result.metrics))
        rows.append(row)
    return rows


# ---------- Output ----------


def _write(path: Path, rows: list[dict[str, Any]], schema: dict[str, Any]) -> None:
    pl.DataFrame(rows, schema=schema).write_parquet(path)


def write_outputs(
    output_dir: Path,
    cfg: SimulationConfig,
    labeled: dict[str, MultiSimulationResult],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)

    portfolio_rows, holding_rows = _build_portfolio_rows(labeled)

    _write(
        output_dir / "runs.parquet",
        _build_runs_rows(cfg, labeled),
        _RUNS_SCHEMA,
    )
    _write(
        output_dir / "portfolios.parquet",
        portfolio_rows,
        _PORTFOLIOS_SCHEMA,
    )
    _write(
        output_dir / "holdings.parquet",
        holding_rows,
        _HOLDINGS_SCHEMA,
    )
    _write(
        output_dir / "trades.parquet",
        _build_trade_rows(labeled),
        _TRADES_SCHEMA,
    )
    _write(
        output_dir / "dividends.parquet",
        _build_dividend_rows(labeled),
        _DIVIDENDS_SCHEMA,
    )
    _write(
        output_dir / "run_metrics.parquet",
        _build_run_metrics_rows(labeled),
        _RUN_METRICS_SCHEMA,
    )
    _write(
        output_dir / "aggregate_metrics.parquet",
        _build_aggregate_metrics_rows(labeled),
        _AGGREGATE_METRICS_SCHEMA,
    )

    shutil.copyfile(cfg.path, output_dir / "config.json")


# ---------- Orchestration ----------


def _resolve_data_paths(market_data: str) -> tuple[Path, Path]:
    data_dir = Path("data")
    return (
        data_dir / f"{market_data}-prices.xlsx",
        data_dir / f"{market_data}-dividends.xlsx",
    )


def output_dir_for(cfg: SimulationConfig) -> Path:
    return Path("output") / cfg.stem


def _ensure_output_does_not_exist(output_dir: Path) -> None:
    if output_dir.exists():
        raise SystemExit(
            f"Output already exists at {output_dir}. "
            "Move or delete it before re-running."
        )


def _label_results(
    cfg: SimulationConfig,
    result: MultiSimulationResult | MultiStrategySimulationResult,
) -> dict[str, MultiSimulationResult]:
    if isinstance(result, MultiStrategySimulationResult):
        ordered = list(result.by_strategy.values())
    else:
        ordered = [result]
    return dict(zip((s.name for s in cfg.strategies), ordered))


def run(cfg: SimulationConfig) -> None:
    output_dir = output_dir_for(cfg)
    _ensure_output_does_not_exist(output_dir)

    prices_path, dividends_path = _resolve_data_paths(cfg.market_data)
    if not prices_path.is_file():
        raise SystemExit(f"Market data prices file not found: {prices_path}")
    if not dividends_path.is_file():
        raise SystemExit(f"Market data dividends file not found: {dividends_path}")

    history = load_market_history(str(prices_path), str(dividends_path))
    strategies = [build_strategy(s) for s in cfg.strategies]

    result = simulate_many(
        strategy=strategies,
        history=history,
        years=cfg.years,
        start_funds=cfg.starting_value,
        num_simulations=cfg.num_simulations,
        plan_target_return=cfg.target_annual_return,
        seed=cfg.seed,
        show_progress=True,
    )

    labeled = _label_results(cfg, result)
    write_outputs(output_dir, cfg, labeled)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run portfolio simulations from a JSON config and save raw results "
            "to Parquet under output/<config_stem>/."
        )
    )
    p.add_argument(
        "config",
        metavar="NAME",
        type=_simulation_config_root_arg,
        help="Config stem: reads config/simulations/NAME.json",
    )
    return p


def main() -> None:
    args = _parser().parse_args()
    cfg = load_simulation_config(args.config)
    run(cfg)
