"""Tests for investing.simulation_output."""

from __future__ import annotations

import json
from pathlib import Path
import polars as pl
import pytest

from investing import simulate_cli
from investing.simulation_output import (
    extreme_cagr_runs,
    load_run_portfolios,
    run_total_value_series,
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
    assert vals[-1] == pytest.approx(row["terminal_wealth_p50"], rel=1e-6)
