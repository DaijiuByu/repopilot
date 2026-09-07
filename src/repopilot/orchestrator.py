"""One-command bridge from a reviewed RepoPilot plan to FactorLab."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from .agent import QuantResearchPlan, build_research_plan
from .backend import HarnessBackend, ToolBackend


def run_factorlab_experiment(
    question: str,
    *,
    input_path: str | Path,
    output_dir: str | Path,
    factorlab_root: str | Path,
    lookback: int = 20,
    quantile: float = 0.2,
    cost_bps: float = 5.0,
    timeout_seconds: float = 180.0,
    harness: str | Path | None = None,
    min_assets: int = 10,
    max_position_weight: float | None = None,
    max_turnover: float | None = None,
    commission_bps: float = 0.0,
    spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
    impact_bps: float = 0.0,
    borrow_bps_annual: float = 0.0,
    portfolio_notional: float = 1_000_000.0,
    impact_exponent: float = 0.5,
    adv_window: int = 20,
    research_trials: int = 1,
    sector_neutral: bool = False,
    split_date: str | None = None,
) -> dict[str, Any]:
    """Generate a plan and execute only the fixed FactorLab experiment CLI.

    The subprocess uses ``shell=False`` and a bounded timeout. The question is
    parsed by RepoPilot; it is never interpolated into a shell command.
    """

    source = Path(input_path).resolve()
    root = Path(factorlab_root).resolve()
    output = Path(output_dir).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not root.is_dir():
        raise ValueError(f"factorlab root is not a directory: {root}")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    plan: QuantResearchPlan = build_research_plan(
        question,
        dataset="local_dataset",
        default_lookback=lookback,
        quantile=quantile,
        cost_bps=cost_bps,
    )
    validation: dict[str, Any] | None = None
    backend: ToolBackend | None = None
    harness_context: HarnessBackend | None = None
    if harness is not None:
        harness_context = HarnessBackend(harness, root)
        backend = harness_context
    try:
        if backend is not None:
            validation = backend.research(
                task="backtest",
                dataset="local_dataset",
                factor=plan.factor,
                lookback=plan.lookback,
                quantile=plan.quantile,
                cost_bps=plan.cost_bps,
            )
    except Exception:
        if harness_context is not None:
            harness_context.close()
        raise
    output.mkdir(parents=True, exist_ok=True)
    config_path = output / "research_plan.json"
    config = {
        "input": str(source),
        "output": str(output / "factorlab_artifacts"),
        "factor": plan.factor,
        "lookback": plan.lookback,
        "quantile": plan.quantile,
        "cost_bps": plan.cost_bps,
        "min_assets": min_assets,
        "max_position_weight": max_position_weight,
        "max_turnover": max_turnover,
        "commission_bps": commission_bps,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "impact_bps": impact_bps,
        "borrow_bps_annual": borrow_bps_annual,
        "portfolio_notional": portfolio_notional,
        "impact_exponent": impact_exponent,
        "adv_window": adv_window,
        "research_trials": research_trials,
        "sector_neutral": sector_neutral,
        "split_date": split_date,
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    environment = os.environ.copy()
    source_root = root / "src"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(source_root), environment.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "factorlab.cli", "experiment", "--config", str(config_path)],
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=min(timeout_seconds, 600.0),
            shell=False,
            check=False,
        )
        timeout = False
    except subprocess.TimeoutExpired as exc:
        completed = None
        timeout = True
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
    finally:
        if harness_context is not None:
            harness_context.close()
    if completed is not None:
        stdout = completed.stdout
        stderr = completed.stderr
    artifacts = output / "factorlab_artifacts"
    experiment_result: dict[str, Any] | None = None
    metrics_path = artifacts / "metrics.json"
    if completed is not None and completed.returncode == 0 and metrics_path.is_file():
        try:
            experiment_result = json.loads(metrics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # The subprocess status remains authoritative; malformed optional
            # artifacts are surfaced as a missing result instead of masking it.
            experiment_result = None
    return {
        "plan": plan.as_dict(),
        "validation": validation,
        "config": str(config_path),
        "artifacts": str(artifacts),
        "experiment_result": experiment_result,
        "command": completed.args if completed is not None else [sys.executable, "-m", "factorlab.cli", "experiment", "--config", str(config_path)],
        "success": completed is not None and completed.returncode == 0,
        "exit_code": completed.returncode if completed is not None else None,
        "timed_out": timeout,
        "stdout": stdout[-32_000:],
        "stderr": stderr[-32_000:],
        "duration_ms": round((time.monotonic() - started) * 1_000),
    }
