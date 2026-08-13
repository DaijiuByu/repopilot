"""Command-line interface for RepoPilot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import analyze, build_synthesizer
from .backend import HarnessBackend, LocalBackend


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
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
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"repopilot: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
