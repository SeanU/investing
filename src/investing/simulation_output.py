"""Load simulation Parquet output for report generation."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from investing.history import load_market_history
from investing.portfolio import Holding, Portfolio
from investing.reporting import ReportingFrequency, total_value_series


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def repo_data_paths(market_data: str) -> tuple[Path, Path]:
    data_dir = repo_root() / "data"
    return (
        data_dir / f"{market_data}-prices.xlsx",
        data_dir / f"{market_data}-dividends.xlsx",
    )


def extreme_cagr_runs(
    runs_df: pl.DataFrame,
    metrics_df: pl.DataFrame,
    strategy: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    joined = (
        runs_df.filter(pl.col("strategy") == strategy)
        .join(
            metrics_df.filter(pl.col("strategy") == strategy).select(
                "strategy", "run_index", "cagr"
            ),
            on=["strategy", "run_index"],
            how="inner",
        )
        .filter(pl.col("cagr").is_finite())
    )
    if joined.height == 0:
        return None
    best = joined.sort(["cagr", "run_index"], descending=[True, False]).row(
        0, named=True
    )
    worst = joined.sort(["cagr", "run_index"], descending=[False, False]).row(
        0, named=True
    )
    return best, worst


def load_run_portfolios(
    output_dir: Path,
    strategy: str,
    run_index: int,
) -> list[Portfolio]:
    portfolios_df = pl.read_parquet(output_dir / "portfolios.parquet").filter(
        (pl.col("strategy") == strategy) & (pl.col("run_index") == run_index)
    )
    holdings_df = pl.read_parquet(output_dir / "holdings.parquet").filter(
        (pl.col("strategy") == strategy) & (pl.col("run_index") == run_index)
    )

    portfolios: list[Portfolio] = []
    for row in portfolios_df.sort("snapshot_index").iter_rows(named=True):
        snap = row["snapshot_index"]
        snap_holdings = holdings_df.filter(pl.col("snapshot_index") == snap)
        holdings = [
            Holding(
                ticker=h["ticker"],
                purchase_date=h["purchase_date"],
                purchase_price=float(h["purchase_price"]),
                quantity=float(h["quantity"]),
            )
            for h in snap_holdings.iter_rows(named=True)
        ]
        portfolios.append(Portfolio(as_of_date=row["as_of_date"], holdings=holdings))
    return portfolios


def run_total_value_series(
    output_dir: Path,
    strategy: str,
    run_index: int,
    market_data: str,
    *,
    reporting_frequency: ReportingFrequency = "monthly",
) -> tuple[list[date], list[float]]:
    portfolios = load_run_portfolios(output_dir, strategy, run_index)
    prices_path, dividends_path = repo_data_paths(market_data)
    history = load_market_history(str(prices_path), str(dividends_path))
    return total_value_series(portfolios, history, reporting_frequency)
