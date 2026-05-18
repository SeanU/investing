"""Load simulation Parquet output for report generation."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from investing.history import load_market_history
from investing.portfolio import Holding, Portfolio
from investing.reporting import ReportingFrequency, total_value_series


def slug_strategy_filename(name: str) -> str:
    """Filesystem-safe stem for report and cache filenames (Windows-safe)."""
    s = re.sub(r'[<>:"/\\|?*"\u0000-\u001f]', "_", name.strip())
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s).strip("._")
    return (s or "strategy")[:180]


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


_WEALTH_PATHS_SCHEMA: dict[str, Any] = {
    "run_index": pl.Int64,
    "date": pl.Date,
    "value": pl.Float64,
    "period_offset": pl.Int64,
    "month_offset": pl.Int64,
}


def _wealth_paths_cache_path(
    output_dir: Path,
    strategy: str,
    reporting_frequency: ReportingFrequency,
) -> Path:
    return (
        output_dir
        / "wealth_paths"
        / f"{slug_strategy_filename(strategy)}__{reporting_frequency}.parquet"
    )


def wealth_paths(
    output_dir: Path,
    strategy: str,
    market_data: str,
    *,
    reporting_frequency: ReportingFrequency = "monthly",
    use_cache: bool = True,
) -> pl.DataFrame:
    """Aligned per-run portfolio value paths for one strategy.

    Walks every run's snapshots, expands holdings onto the reporting cadence,
    and prices each step via ``MarketHistory``. Returns a Polars frame with
    columns ``run_index, date, value, period_offset, month_offset`` — one row
    per (run, reporting date).

    ``period_offset`` counts reporting periods since each run's first
    reporting date (0-indexed). ``month_offset`` counts whole calendar months
    since the run's start date; it is robust to trade-date insertions that
    cause runs to have different reporting-date counts, so cross-run
    aggregations (fan charts) should align by ``month_offset``.

    The result is cached under
    ``output_dir/wealth_paths/<strategy_slug>__<freq>.parquet`` and re-read on
    subsequent calls. Pass ``use_cache=False`` to force recompute.
    """
    cache_path = _wealth_paths_cache_path(output_dir, strategy, reporting_frequency)
    if use_cache and cache_path.is_file():
        return pl.read_parquet(cache_path)

    runs_df = pl.read_parquet(output_dir / "runs.parquet").filter(
        pl.col("strategy") == strategy
    )
    if runs_df.height == 0:
        return pl.DataFrame(schema=_WEALTH_PATHS_SCHEMA)

    prices_path, dividends_path = repo_data_paths(market_data)
    history = load_market_history(str(prices_path), str(dividends_path))

    rows: list[dict[str, Any]] = []
    for run_index in sorted(runs_df["run_index"].to_list()):
        portfolios = load_run_portfolios(output_dir, strategy, int(run_index))
        dates, vals = total_value_series(portfolios, history, reporting_frequency)
        if not dates:
            continue
        start = dates[0]
        for period_offset, (d, v) in enumerate(zip(dates, vals, strict=True)):
            month_offset = (d.year - start.year) * 12 + (d.month - start.month)
            rows.append(
                {
                    "run_index": int(run_index),
                    "date": d,
                    "value": float(v),
                    "period_offset": period_offset,
                    "month_offset": month_offset,
                }
            )

    df = pl.DataFrame(rows, schema=_WEALTH_PATHS_SCHEMA)

    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(cache_path)

    return df
