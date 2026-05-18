"""CLI: render per-strategy and comparison Quarto PDF reports from simulation Parquet output."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from shutil import move, rmtree, which

from investing.simulate_cli import load_simulation_config, simulation_config_path
from investing.simulation_output import slug_strategy_filename

_PARAM_START = "# <<investing-report-parameters>>\n"
_PARAM_END = "# <</investing-report-parameters>>\n"


def _config_stem_arg(value: str) -> Path:
    try:
        return simulation_config_path(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _quarto_project_dir() -> Path:
    return _repo_root() / "reports" / "quarto"


def _strategy_report_qmd() -> Path:
    return _quarto_project_dir() / "strategy_report.qmd"


def _comparison_report_qmd() -> Path:
    return _quarto_project_dir() / "comparison_report.qmd"


def _inject_report_parameters(
    template: str,
    output_dir: Path,
    strategy: str | None = None,
) -> str:
    """Replace the marked parameters block with literals so the Jupyter kernel always sees them."""
    start = template.find(_PARAM_START)
    end = template.find(_PARAM_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError("Template must contain investing-report parameter markers.")
    start += len(_PARAM_START)
    inner = f"output_dir = {str(output_dir.resolve())!r}\n"
    if strategy is not None:
        inner += f"strategy = {strategy!r}\n"
    return template[:start] + inner + template[end:]


def _render_pdf(
    *,
    quarto_exe: str,
    env: Mapping[str, str],
    quarto_cwd: Path,
    render_qmd: Path,
    pdf_name: str,
    pdf_path: Path,
    title: str,
    subtitle: str,
) -> None:
    cmd = [
        quarto_exe,
        "render",
        str(render_qmd),
        "-M",
        f"title:{title}",
        "-M",
        f"subtitle:{subtitle}",
        "-o",
        pdf_name,
    ]
    subprocess.run(cmd, check=True, env=env, cwd=str(quarto_cwd))
    rendered_pdf = quarto_cwd / pdf_name
    if rendered_pdf.resolve() != pdf_path.resolve():
        move(str(rendered_pdf), str(pdf_path))


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Render Typst PDF reports per strategy plus a strategy comparison PDF "
            "from output/<NAME>/ Parquet. Requires Quarto on PATH and a prior "
            "investing-simulate run."
        )
    )
    p.add_argument(
        "config",
        metavar="NAME",
        type=_config_stem_arg,
        help="Config stem: reads output from output/<NAME>/ (same as investing-simulate)",
    )
    return p


def main() -> None:
    args = _parser().parse_args()
    cfg_path: Path = args.config
    cfg = load_simulation_config(cfg_path)
    stem = cfg.stem

    output_dir = Path("output") / stem
    if not output_dir.is_dir():
        raise SystemExit(
            f"Simulation output not found: {output_dir}. Run investing-simulate first."
        )
    for name in (
        "run_metrics.parquet",
        "aggregate_metrics.parquet",
        "runs.parquet",
        "portfolios.parquet",
        "holdings.parquet",
        "config.json",
    ):
        if not (output_dir / name).is_file():
            raise SystemExit(
                f"Missing {name} in {output_dir}. Re-run investing-simulate."
            )

    strategy_qmd = _strategy_report_qmd()
    comparison_qmd = _comparison_report_qmd()
    if not strategy_qmd.is_file():
        raise SystemExit(f"Quarto template not found: {strategy_qmd}")
    if not comparison_qmd.is_file():
        raise SystemExit(f"Quarto template not found: {comparison_qmd}")

    reports_dir = Path("reports") / stem
    reports_dir.mkdir(parents=True, exist_ok=True)

    quarto_exe = which("quarto")
    if quarto_exe is None:
        raise SystemExit(
            "Quarto is not on PATH. Install from https://quarto.org/docs/get-started/ "
            "and ensure `quarto --version` works."
        )

    env = os.environ.copy()
    env["QUARTO_PYTHON"] = env.get("QUARTO_PYTHON", sys.executable)

    strategy_template = strategy_qmd.read_text(encoding="utf-8")
    comparison_template = comparison_qmd.read_text(encoding="utf-8")
    reports_abs = reports_dir.resolve()
    quarto_cwd = _quarto_project_dir().resolve()
    freeze_dir = quarto_cwd / ".quarto" / "_freeze"
    if freeze_dir.is_dir():
        rmtree(freeze_dir)
    safe_stem = slug_strategy_filename(stem)
    subtitle = "Monte Carlo simulation report"

    for strat in cfg.strategies:
        slug = slug_strategy_filename(strat.name)
        pdf_name = f"{slug}.pdf"
        pdf_path = reports_abs / pdf_name
        render_qmd = quarto_cwd / f"_render_{safe_stem}_{slug}.qmd"
        try:
            render_qmd.write_text(
                _inject_report_parameters(strategy_template, output_dir, strat.name),
                encoding="utf-8",
            )
            print(f"Rendering {pdf_name} ({strat.name!r})...", flush=True)
            _render_pdf(
                quarto_exe=quarto_exe,
                env=env,
                quarto_cwd=quarto_cwd,
                render_qmd=render_qmd,
                pdf_name=pdf_name,
                pdf_path=pdf_path,
                title=strat.name,
                subtitle=subtitle,
            )
        finally:
            render_qmd.unlink(missing_ok=True)

    comparison_pdf = "comparison.pdf"
    comparison_path = reports_abs / comparison_pdf
    comparison_render_qmd = quarto_cwd / f"_render_{safe_stem}_comparison.qmd"
    try:
        comparison_render_qmd.write_text(
            _inject_report_parameters(comparison_template, output_dir),
            encoding="utf-8",
        )
        print(f"Rendering {comparison_pdf}...", flush=True)
        _render_pdf(
            quarto_exe=quarto_exe,
            env=env,
            quarto_cwd=quarto_cwd,
            render_qmd=comparison_render_qmd,
            pdf_name=comparison_pdf,
            pdf_path=comparison_path,
            title="Strategy comparison",
            subtitle=subtitle,
        )
    finally:
        comparison_render_qmd.unlink(missing_ok=True)

    print(f"Wrote reports under {reports_dir.resolve()}", flush=True)
