"""Tests for investing.simulate_cli."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from investing import simulate_cli
from investing.portfolio import AssetAllocation
from investing.simulate_cli import (
    SIMULATIONS_CONFIG_DIR,
    StrategyConfig,
    RebalancingConfig,
    build_strategy,
    load_simulation_config,
    simulation_config_path,
)
from investing.simulation import AnnualRebalance, BuyAndHold


def test_simulation_config_path():
    assert (
        simulation_config_path("simulation.example")
        == SIMULATIONS_CONFIG_DIR / "simulation.example.json"
    )
    assert simulation_config_path("  my_run ") == SIMULATIONS_CONFIG_DIR / "my_run.json"


@pytest.mark.parametrize(
    "bad",
    ["", " ", ".", "..", "a/b", "a\\b", "x/../y"],
)
def test_simulation_config_path_rejects_invalid_names(bad: str):
    with pytest.raises(ValueError):
        simulation_config_path(bad)


_VALID_RAW: dict[str, Any] = {
    "market_data": "market_data.example",
    "num_simulations": 1,
    "years": 1,
    "starting_value": 1000.0,
    "target_annual_return": 0.04,
    "seed": 1,
    "strategies": [
        {
            "name": "Test 60/40",
            "allocation": {"VTSAX": 60, "VBTLX": 40},
            "rebalancing": {"type": "annual", "max_deviation": 0.05},
        }
    ],
}


def _write_config(
    tmp_path: Path, data: dict[str, Any], filename: str = "test.json"
) -> Path:
    p = tmp_path / filename
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _with_strategies(strategies: list[dict[str, Any]]) -> dict[str, Any]:
    return {**_VALID_RAW, "strategies": strategies}


# ---------- Successful loads ----------


def test_load_valid_config(tmp_path: Path):
    p = _write_config(tmp_path, _VALID_RAW)
    cfg = load_simulation_config(p)

    assert cfg.stem == "test"
    assert cfg.market_data == "market_data.example"
    assert cfg.num_simulations == 1
    assert cfg.years == 1
    assert cfg.starting_value == 1000.0
    assert cfg.target_annual_return == 0.04
    assert cfg.seed == 1
    assert len(cfg.strategies) == 1

    strategy = cfg.strategies[0]
    assert strategy.name == "Test 60/40"
    assert strategy.allocation == {"VTSAX": 60, "VBTLX": 40}
    assert strategy.rebalancing.type == "annual"
    assert strategy.rebalancing.max_deviation == 0.05


def test_load_buy_and_hold_strategy(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "BH",
                "allocation": {"A": 1, "B": 2},
                "rebalancing": {"type": "buy_and_hold"},
            }
        ]
    )
    cfg = load_simulation_config(_write_config(tmp_path, raw))

    assert cfg.strategies[0].rebalancing.type == "buy_and_hold"
    assert cfg.strategies[0].rebalancing.max_deviation is None


# ---------- Top-level validation errors ----------


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_simulation_config(tmp_path / "does_not_exist.json")


def test_root_must_be_object(tmp_path: Path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    with pytest.raises(ValueError, match="root must be a JSON object"):
        load_simulation_config(p)


def test_market_data_must_be_non_empty_string(tmp_path: Path):
    raw = {**_VALID_RAW, "market_data": ""}
    with pytest.raises(ValueError, match="market_data"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_num_simulations_must_be_positive_int(tmp_path: Path):
    for bad in (0, -1, 1.5, "1", True):
        raw = {**_VALID_RAW, "num_simulations": bad}
        with pytest.raises(ValueError, match="num_simulations"):
            load_simulation_config(_write_config(tmp_path, raw))


def test_years_must_be_positive_int(tmp_path: Path):
    for bad in (0, -3, 1.0, None):
        raw = {**_VALID_RAW, "years": bad}
        with pytest.raises(ValueError, match="years"):
            load_simulation_config(_write_config(tmp_path, raw))


def test_starting_value_must_be_positive_number(tmp_path: Path):
    for bad in (0, -100, "100", True):
        raw = {**_VALID_RAW, "starting_value": bad}
        with pytest.raises(ValueError, match="starting_value"):
            load_simulation_config(_write_config(tmp_path, raw))


def test_target_annual_return_is_required(tmp_path: Path):
    raw = {k: v for k, v in _VALID_RAW.items() if k != "target_annual_return"}
    with pytest.raises(ValueError, match="target_annual_return"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_target_annual_return_must_be_number(tmp_path: Path):
    for bad in ("0.04", None, True):
        raw = {**_VALID_RAW, "target_annual_return": bad}
        with pytest.raises(ValueError, match="target_annual_return"):
            load_simulation_config(_write_config(tmp_path, raw))


def test_seed_must_be_int(tmp_path: Path):
    for bad in (1.5, "42", None, True):
        raw = {**_VALID_RAW, "seed": bad}
        with pytest.raises(ValueError, match="seed"):
            load_simulation_config(_write_config(tmp_path, raw))


def test_strategies_must_be_non_empty_array(tmp_path: Path):
    for bad in ([], {}, None):
        raw = {**_VALID_RAW, "strategies": bad}
        with pytest.raises(ValueError, match="strategies"):
            load_simulation_config(_write_config(tmp_path, raw))


# ---------- Strategy validation errors ----------


def test_strategy_name_must_be_non_empty_string(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "",
                "allocation": {"A": 1},
                "rebalancing": {"type": "buy_and_hold"},
            }
        ]
    )
    with pytest.raises(ValueError, match="strategy.name"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_strategy_names_must_be_unique(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "S",
                "allocation": {"A": 1},
                "rebalancing": {"type": "buy_and_hold"},
            },
            {
                "name": "S",
                "allocation": {"B": 1},
                "rebalancing": {"type": "buy_and_hold"},
            },
        ]
    )
    with pytest.raises(ValueError, match="duplicated"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_allocation_rejects_float_weights(tmp_path: Path):
    """Floats (e.g. 0.60) must be rejected; users encode finer scale via larger ints."""
    raw = _with_strategies(
        [
            {
                "name": "S",
                "allocation": {"VTSAX": 0.6, "VBTLX": 0.4},
                "rebalancing": {"type": "buy_and_hold"},
            }
        ]
    )
    with pytest.raises(ValueError, match="must be an integer"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_allocation_rejects_zero_or_negative(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "S",
                "allocation": {"A": 0, "B": 1},
                "rebalancing": {"type": "buy_and_hold"},
            }
        ]
    )
    with pytest.raises(ValueError, match="must be positive"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_allocation_rejects_bool_weights(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "S",
                "allocation": {"A": True},
                "rebalancing": {"type": "buy_and_hold"},
            }
        ]
    )
    with pytest.raises(ValueError, match="must be an integer"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_allocation_must_not_be_empty(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "S",
                "allocation": {},
                "rebalancing": {"type": "buy_and_hold"},
            }
        ]
    )
    with pytest.raises(ValueError, match="must not be empty"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_rebalancing_type_must_be_known(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "S",
                "allocation": {"A": 1},
                "rebalancing": {"type": "monthly"},
            }
        ]
    )
    with pytest.raises(ValueError, match="rebalancing.type"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_annual_requires_max_deviation(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "S",
                "allocation": {"A": 1},
                "rebalancing": {"type": "annual"},
            }
        ]
    )
    with pytest.raises(ValueError, match="max_deviation"):
        load_simulation_config(_write_config(tmp_path, raw))


def test_annual_max_deviation_must_be_non_negative(tmp_path: Path):
    raw = _with_strategies(
        [
            {
                "name": "S",
                "allocation": {"A": 1},
                "rebalancing": {"type": "annual", "max_deviation": -0.01},
            }
        ]
    )
    with pytest.raises(ValueError, match="max_deviation"):
        load_simulation_config(_write_config(tmp_path, raw))


# ---------- Strategy builder ----------


def test_build_strategy_buy_and_hold():
    cfg = StrategyConfig(
        name="BH",
        allocation={"A": 3, "B": 1},
        rebalancing=RebalancingConfig(type="buy_and_hold", max_deviation=None),
    )
    strategy = build_strategy(cfg)
    assert isinstance(strategy, BuyAndHold)
    assert strategy.starting_allocation.proportions == pytest.approx(
        {"A": 0.75, "B": 0.25}
    )


def test_build_strategy_annual_uses_max_deviation():
    cfg = StrategyConfig(
        name="AR",
        allocation={"A": 60, "B": 40},
        rebalancing=RebalancingConfig(type="annual", max_deviation=0.07),
    )
    strategy = build_strategy(cfg)
    assert isinstance(strategy, AnnualRebalance)
    assert strategy.max_deviation == 0.07
    assert strategy.starting_allocation.proportions == pytest.approx(
        {"A": 0.6, "B": 0.4}
    )


def test_build_strategy_passes_integer_weights_through_unchanged():
    cfg = StrategyConfig(
        name="BP",
        allocation={"A": 6000, "B": 4000},
        rebalancing=RebalancingConfig(type="buy_and_hold", max_deviation=None),
    )
    strategy = build_strategy(cfg)
    assert isinstance(strategy.starting_allocation, AssetAllocation)
    weights = {t.ticker: t.weight for t in strategy.starting_allocation.targets}
    assert weights == {"A": 6000, "B": 4000}
    assert strategy.starting_allocation.proportions == pytest.approx(
        {"A": 0.6, "B": 0.4}
    )


# ---------- End-to-end ----------


def _smoke_config(tmp_path: Path) -> Path:
    return _write_config(
        tmp_path,
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
        },
        filename="smoke.json",
    )


def test_run_writes_all_expected_parquets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg = load_simulation_config(_smoke_config(tmp_path))
    output_dir = tmp_path / "out"
    monkeypatch.setattr(simulate_cli, "output_dir_for", lambda _cfg: output_dir)

    simulate_cli.run(cfg)

    expected_files = {
        "runs.parquet",
        "portfolios.parquet",
        "holdings.parquet",
        "trades.parquet",
        "dividends.parquet",
        "run_metrics.parquet",
        "aggregate_metrics.parquet",
        "config.json",
    }
    assert {p.name for p in output_dir.iterdir()} == expected_files


def test_run_outputs_have_expected_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg = load_simulation_config(_smoke_config(tmp_path))
    output_dir = tmp_path / "out"
    monkeypatch.setattr(simulate_cli, "output_dir_for", lambda _cfg: output_dir)

    simulate_cli.run(cfg)

    runs = pl.read_parquet(output_dir / "runs.parquet")
    assert runs.columns == [
        "strategy",
        "run_index",
        "start_date",
        "end_date",
        "start_funds",
        "seed",
    ]
    assert runs.height == 4  # 2 strategies x 2 simulations
    assert set(runs["strategy"].to_list()) == {"Equal Pair", "Annual"}
    assert all(seed == 7 for seed in runs["seed"].to_list())

    aggregate = pl.read_parquet(output_dir / "aggregate_metrics.parquet")
    assert aggregate.height == 2
    assert set(aggregate["strategy"].to_list()) == {"Equal Pair", "Annual"}

    run_metrics = pl.read_parquet(output_dir / "run_metrics.parquet")
    assert run_metrics.height == 4

    portfolios = pl.read_parquet(output_dir / "portfolios.parquet")
    holdings = pl.read_parquet(output_dir / "holdings.parquet")
    assert portfolios.height >= 4  # at least starting + ending snapshot per run
    assert holdings.height >= portfolios.height

    config_copy = json.loads((output_dir / "config.json").read_text(encoding="utf-8"))
    assert config_copy["market_data"] == "5-way"


def test_run_aborts_when_output_dir_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg = load_simulation_config(_smoke_config(tmp_path))
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    monkeypatch.setattr(simulate_cli, "output_dir_for", lambda _cfg: output_dir)

    with pytest.raises(SystemExit, match="already exists"):
        simulate_cli.run(cfg)

    assert list(output_dir.iterdir()) == []


def test_run_errors_when_market_data_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cfg = load_simulation_config(
        _write_config(
            tmp_path,
            {
                **_VALID_RAW,
                "market_data": "definitely_not_real_market_data_12345",
            },
            filename="missing.json",
        )
    )
    output_dir = tmp_path / "out"
    monkeypatch.setattr(simulate_cli, "output_dir_for", lambda _cfg: output_dir)

    with pytest.raises(SystemExit, match="prices file not found"):
        simulate_cli.run(cfg)

    assert not output_dir.exists()
