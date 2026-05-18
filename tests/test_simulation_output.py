"""Tests for investing.simulation_output."""

from __future__ import annotations

import json
from pathlib import Path
import polars as pl
import pytest

from investing import simulate_cli
from investing.simulation_output import (
    _wealth_paths_cache_path,
    extreme_cagr_runs,
    load_run_portfolios,
    run_total_value_series,
    slug_strategy_filename,
    wealth_paths,
)
from investing.simulate_cli import load_simulation_config


def _smoke_config(tmp_path: Path) -> Path:
    p = tmp_path / "smoke.json"
    p.write_text(
        json.dumps(
            {
                "market_data": "5-way",
                "num_simulations": 2,
                "years": 1,
                "starting_value": 10000.0,
                "target_annual_return": 0.04,
                "seed": 7,
                "strategies": [
                    {
                        "name": "Equal Pair",
                        "allocation": {"VTSAX": 1, "VTIAX": 1},
                        "rebalancing": {"type": "buy_and_hold"},
                    },
                    {
                        "name": "Annual",
                        "allocation": {
                            "VTSAX": 1,
                            "VTIAX": 1,
                            "VBTLX": 1,
                            "VTABX": 1,
                            "VGSLX": 1,
                        },
                        "rebalancing": {"type": "annual", "max_deviation": 0.05},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def smoke_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = load_simulation_config(_smoke_config(tmp_path))
    output_dir = tmp_path / "out"
    monkeypatch.setattr(simulate_cli, "output_dir_for", lambda _cfg: output_dir)
    simulate_cli.run(cfg)
    return output_dir


def test_extreme_cagr_runs_picks_min_and_max(smoke_output: Path):
    runs = pl.read_parquet(smoke_output / "runs.parquet")
    metrics = pl.read_parquet(smoke_output / "run_metrics.parquet")
    strategy = "Equal Pair"

    result = extreme_cagr_runs(runs, metrics, strategy)
    assert result is not None
    best, worst = result

    strat_metrics = metrics.filter(pl.col("strategy") == strategy).filter(
        pl.col("cagr").is_finite()
    )
    assert best["cagr"] == pytest.approx(strat_metrics["cagr"].max())
    assert worst["cagr"] == pytest.approx(strat_metrics["cagr"].min())
    assert best["run_index"] != worst["run_index"] or strat_metrics.height == 1


def test_load_run_portfolios_rebuilds_snapshots(smoke_output: Path):
    portfolios = load_run_portfolios(smoke_output, "Equal Pair", 0)
    assert len(portfolios) >= 2
    assert portfolios[0].as_of_date <= portfolios[-1].as_of_date
    assert len(portfolios[0].holdings) > 0


def test_run_total_value_series_matches_terminal_wealth(smoke_output: Path):
    metrics = pl.read_parquet(smoke_output / "run_metrics.parquet")
    row = metrics.filter(
        (pl.col("strategy") == "Equal Pair") & (pl.col("run_index") == 0)
    ).row(0, named=True)

    dates, vals = run_total_value_series(
        smoke_output, "Equal Pair", 0, "5-way", reporting_frequency="monthly"
    )
    assert len(dates) >= 2
    assert len(vals) == len(dates)
    assert vals[-1] == pytest.approx(row["terminal_wealth"], rel=1e-6)


def test_wealth_paths_returns_expected_schema(smoke_output: Path):
    df = wealth_paths(smoke_output, "Equal Pair", "5-way")
    assert df.columns == ["run_index", "date", "value", "period_offset", "month_offset"]
    assert df.schema["run_index"] == pl.Int64
    assert df.schema["date"] == pl.Date
    assert df.schema["value"] == pl.Float64
    assert df.schema["period_offset"] == pl.Int64
    assert df.schema["month_offset"] == pl.Int64


def test_wealth_paths_month_offset_starts_at_zero(smoke_output: Path):
    df = wealth_paths(smoke_output, "Equal Pair", "5-way")
    for run_index in sorted(set(df["run_index"].to_list())):
        run_rows = df.filter(pl.col("run_index") == run_index).sort("period_offset")
        assert run_rows["month_offset"][0] == 0
        assert run_rows["month_offset"][-1] >= run_rows["month_offset"][0]


def test_wealth_paths_covers_every_run(smoke_output: Path):
    """Each run in runs.parquet appears in wealth_paths with period_offset starting at 0."""
    runs = pl.read_parquet(smoke_output / "runs.parquet").filter(
        pl.col("strategy") == "Equal Pair"
    )
    expected_run_indices = set(runs["run_index"].to_list())

    df = wealth_paths(smoke_output, "Equal Pair", "5-way")
    assert set(df["run_index"].to_list()) == expected_run_indices
    for run_index in expected_run_indices:
        run_rows = df.filter(pl.col("run_index") == run_index).sort("period_offset")
        assert run_rows["period_offset"][0] == 0
        # period_offset increases monotonically across the run
        offsets = run_rows["period_offset"].to_list()
        assert offsets == sorted(offsets)
        assert len(set(offsets)) == len(offsets)


def test_wealth_paths_matches_run_total_value_series(smoke_output: Path):
    """wealth_paths and run_total_value_series should agree on each run's values."""
    df = wealth_paths(smoke_output, "Equal Pair", "5-way")
    for run_index in sorted(set(df["run_index"].to_list())):
        run_rows = df.filter(pl.col("run_index") == run_index).sort("period_offset")
        dates, vals = run_total_value_series(
            smoke_output, "Equal Pair", int(run_index), "5-way",
            reporting_frequency="monthly",
        )
        assert run_rows["date"].to_list() == dates
        assert run_rows["value"].to_list() == pytest.approx(vals, rel=1e-9)


def test_wealth_paths_writes_and_reuses_cache(smoke_output: Path):
    """Second call should read from the cached parquet (no recompute)."""
    cache_path = _wealth_paths_cache_path(smoke_output, "Equal Pair", "monthly")
    assert not cache_path.is_file()

    df_first = wealth_paths(smoke_output, "Equal Pair", "5-way")
    assert cache_path.is_file()
    mtime_after_write = cache_path.stat().st_mtime_ns

    df_second = wealth_paths(smoke_output, "Equal Pair", "5-way")
    assert cache_path.stat().st_mtime_ns == mtime_after_write
    assert df_first.equals(df_second)


def test_wealth_paths_cache_path_uses_slug_and_frequency(tmp_path: Path):
    """Strategy names with awkward characters become a filesystem-safe slug."""
    path = _wealth_paths_cache_path(tmp_path, "60/40 Annual Rebalance", "monthly")
    assert path.parent == tmp_path / "wealth_paths"
    expected_slug = slug_strategy_filename("60/40 Annual Rebalance")
    assert path.name == f"{expected_slug}__monthly.parquet"
