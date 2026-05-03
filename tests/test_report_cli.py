import json
import sys
from pathlib import Path

import pytest

from investing.report_cli import _inject_report_parameters
from investing.report_cli import main as report_main
from investing.report_cli import slug_strategy_filename


def test_inject_report_parameters_inserts_literals(tmp_path):
    template = """x
# <<investing-report-parameters>>
old
# <</investing-report-parameters>>
y"""
    out = _inject_report_parameters(template, tmp_path, "My Strategy")
    assert "old" not in out
    assert f"output_dir = {repr(str(tmp_path.resolve()))}" in out
    assert "strategy = 'My Strategy'" in out


def test_slug_strategy_filename_basic():
    assert slug_strategy_filename("60/40 Annual Rebalance") == "60_40_Annual_Rebalance"
    assert slug_strategy_filename("  hello world  ") == "hello_world"
    assert slug_strategy_filename('a<b>:"x"') == "a_b_x"


def test_slug_strategy_filename_empty_fallback():
    assert slug_strategy_filename("???") == "strategy"


def test_report_cli_exits_when_output_dir_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sim_dir = tmp_path / "config" / "simulations"
    sim_dir.mkdir(parents=True)
    cfg = {
        "market_data": "md",
        "num_simulations": 1,
        "years": 1,
        "starting_value": 1000,
        "seed": 1,
        "strategies": [
            {
                "name": "S1",
                "allocation": {"A": 100},
                "rebalancing": {"type": "buy_and_hold"},
            }
        ],
    }
    (sim_dir / "foo.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["investing-report", "foo"])
    with pytest.raises(SystemExit) as exc:
        report_main()
    assert "Simulation output not found" in str(exc.value)


def test_report_cli_exits_when_quarto_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sim_dir = tmp_path / "config" / "simulations"
    sim_dir.mkdir(parents=True)
    cfg = {
        "market_data": "md",
        "num_simulations": 1,
        "years": 1,
        "starting_value": 1000,
        "seed": 1,
        "strategies": [
            {
                "name": "S1",
                "allocation": {"A": 100},
                "rebalancing": {"type": "buy_and_hold"},
            }
        ],
    }
    (sim_dir / "foo.json").write_text(json.dumps(cfg), encoding="utf-8")
    out = tmp_path / "output" / "foo"
    out.mkdir(parents=True)
    for name in ("run_metrics.parquet", "aggregate_metrics.parquet", "config.json"):
        (out / name).write_bytes(b"")
    monkeypatch.setattr(sys, "argv", ["investing-report", "foo"])
    monkeypatch.setattr("investing.report_cli.which", lambda _x: None)
    with pytest.raises(SystemExit) as exc:
        report_main()
    assert "Quarto is not on PATH" in str(exc.value)
