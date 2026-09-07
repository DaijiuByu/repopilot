"""Command-line interface for RepoPilot."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .agent import analyze, build_research_plan, build_synthesizer
from .backend import HarnessBackend, LocalBackend
from .orchestrator import run_factorlab_experiment


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only issue triage for code repositories")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze_parser = subparsers.add_parser("analyze", help="analyze an issue against a repository")
    analyze_parser.add_argument("--repo", type=Path, default=Path("."), help="repository directory")
    source = analyze_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--issue", help="issue text")
    source.add_argument("--issue-file", type=Path, help="read issue text from a UTF-8 file")
    analyze_parser.add_argument("--harness", type=Path, help="ToolForge executable to use as the backend")
    analyze_parser.add_argument("--no-model", action="store_true", help="disable optional model synthesis")
    analyze_parser.add_argument("--output", type=Path, help="write Markdown report to this path")
    analyze_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    plan_parser = subparsers.add_parser(
        "research-plan", help="turn a quant research question into a safe FactorLab plan"
    )
    plan_parser.add_argument("--question", required=True)
    plan_parser.add_argument("--dataset", default="demo_panel")
    plan_parser.add_argument("--lookback", type=int, default=20)
    plan_parser.add_argument("--quantile", type=float, default=0.2)
    plan_parser.add_argument("--cost-bps", type=float, default=5.0)
    plan_parser.add_argument("--json", action="store_true")
    run_parser = subparsers.add_parser(
        "run-research", help="plan and run a fixed FactorLab experiment CLI"
    )
    run_parser.add_argument("--question", required=True)
    run_parser.add_argument("--input", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, default=Path("research_run"))
    run_parser.add_argument("--factorlab-root", type=Path, required=True)
    run_parser.add_argument("--lookback", type=int, default=20)
    run_parser.add_argument("--quantile", type=float, default=0.2)
    run_parser.add_argument("--cost-bps", type=float, default=5.0)
    run_parser.add_argument("--timeout-seconds", type=float, default=180.0)
    run_parser.add_argument("--min-assets", type=int, default=10)
    run_parser.add_argument("--max-position-weight", type=float)
    run_parser.add_argument("--max-turnover", type=float)
    run_parser.add_argument("--commission-bps", type=float, default=0.0)
    run_parser.add_argument("--spread-bps", type=float, default=0.0)
    run_parser.add_argument("--slippage-bps", type=float, default=0.0)
    run_parser.add_argument("--impact-bps", type=float, default=0.0)
    run_parser.add_argument("--borrow-bps-annual", type=float, default=0.0)
    run_parser.add_argument("--portfolio-notional", type=float, default=1_000_000.0)
    run_parser.add_argument("--impact-exponent", type=float, default=0.5)
    run_parser.add_argument("--adv-window", type=int, default=20)
    run_parser.add_argument("--research-trials", type=int, default=1)
    run_parser.add_argument("--sector-neutral", action="store_true")
    run_parser.add_argument("--split-date")
    run_parser.add_argument(
        "--harness",
        type=Path,
        help="optional ToolForge executable used to validate the plan before execution",
    )
    run_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in {"research-plan", "run-research"}:
        try:
            if args.command == "run-research":
                result = run_factorlab_experiment(
                    args.question,
                    input_path=args.input,
                    output_dir=args.output,
                    factorlab_root=args.factorlab_root,
                    lookback=args.lookback,
                    quantile=args.quantile,
                    cost_bps=args.cost_bps,
                    timeout_seconds=args.timeout_seconds,
                    harness=args.harness,
                    min_assets=args.min_assets,
                    max_position_weight=args.max_position_weight,
                    max_turnover=args.max_turnover,
                    commission_bps=args.commission_bps,
                    spread_bps=args.spread_bps,
                    slippage_bps=args.slippage_bps,
                    impact_bps=args.impact_bps,
                    borrow_bps_annual=args.borrow_bps_annual,
                    portfolio_notional=args.portfolio_notional,
                    impact_exponent=args.impact_exponent,
                    adv_window=args.adv_window,
                    research_trials=args.research_trials,
                    sector_neutral=args.sector_neutral,
                    split_date=args.split_date,
                )
                print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result["stdout"])
                return 0 if result["success"] else 1
            plan = build_research_plan(
                args.question,
                dataset=args.dataset,
                default_lookback=args.lookback,
                quantile=args.quantile,
                cost_bps=args.cost_bps,
            )
            rendered = json.dumps(plan.as_dict(), ensure_ascii=False, indent=2)
            print(rendered)
            return 0
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"repopilot: {exc}", file=sys.stderr)
            return 1
    if args.command != "analyze":
        return 2
    try:
        issue = args.issue if args.issue is not None else args.issue_file.read_text(encoding="utf-8")
        if not issue.strip():
            raise ValueError("issue text must not be empty")
        if args.harness:
            with HarnessBackend(args.harness, args.repo) as backend:
                report = analyze(issue, backend, None if args.no_model else build_synthesizer())
        else:
            report = analyze(issue, LocalBackend(args.repo), None if args.no_model else build_synthesizer())
        rendered = json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if args.json else report.markdown()
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
            print(f"Wrote {args.output}")
        else:
            print(rendered)
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, TimeoutError, subprocess.SubprocessError) as exc:
        print(f"repopilot: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
