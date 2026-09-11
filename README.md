# RepoPilot

RepoPilot is a small, read-only coding issue triage agent. Give it an Issue and
a repository; it gathers bounded evidence, detects the project's test command,
runs that test through a policy-controlled backend, and produces a report that
a human can review.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![Tests](https://img.shields.io/badge/tests-included-success)
![License](https://img.shields.io/badge/license-MIT-blue)

## What makes it an agent

RepoPilot follows a small, inspectable loop rather than pretending to be an
autonomous software engineer:

```text
Issue -> search terms -> repository tools -> evidence -> tests -> report
                                      \-> optional model synthesis
```

The model, when enabled, receives evidence only and cannot call tools or edit
files. All file and process operations remain in the deterministic workflow.
Without an API key, the same useful evidence report works completely offline.

For quantitative research, `research-plan` turns a natural-language question
into an allow-listed FactorLab experiment plan. It extracts only registered
factors and bounded lookbacks, then records point-in-time, walk-forward,
turnover, cost, quantile, and significance checks for human review:

```bash
repopilot research-plan \
  --question "检查 20 日动量因子的样本外表现" \
  --dataset demo_panel
```

The plan is declarative and requires explicit backend confirmation; RepoPilot
never executes model-generated code.

Each plan includes a backwards-compatible schema version plus protocol version
2, a stable `plan_id`, an explicit
`factorlab_args` payload, benchmark/placebo controls, an OOS policy, and model
provenance fields. This makes plans easy to deduplicate, review, and attach to
a downstream experiment manifest without granting the planner execution
privileges.

For a local, fixed-command end-to-end run, pass the FactorLab checkout
explicitly:

```bash
repopilot run-research \
  --question "检查 20 日动量因子的样本外表现" \
  --input ../factorlab/demo_panel.csv \
  --factorlab-root ../factorlab \
  --output research_run
```

The bridge writes the reviewed plan and invokes only
`python -m factorlab.cli experiment --config ...` with `shell=False`; it never
turns model text into a shell command. The returned JSON includes optional
ToolForge `validation`, the exact config path, artifact directory, subprocess
status/timeout, and parsed `metrics.json` so an orchestrator can persist one
joinable record for the full study.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate       # Windows
# source .venv/bin/activate  # macOS/Linux
python -m pip install -e .
repopilot analyze --repo . --issue "Login requests time out after 30 seconds" --no-model
```

Write a report to a file or get JSON:

```bash
repopilot analyze --repo ./my-project --issue-file issue.md --output triage.md
repopilot analyze --repo ./my-project --issue "auth timeout" --json
```

Optional model synthesis uses the OpenAI-compatible Responses API:

```bash
copy .env.example .env  # then set OPENAI_API_KEY in your environment
repopilot analyze --repo ./my-project --issue-file issue.md
```

RepoPilot does not load `.env` automatically, so secrets stay in the process
environment rather than being accidentally committed.

## Rust Harness integration

Build the companion [ToolForge](../toolforge) project, then pass its executable:

```bash
repopilot analyze \
  --repo ./my-project \
  --issue-file issue.md \
  --harness ../toolforge/target/debug/toolforge
```

On Windows, use `toolforge.exe`. The integration uses JSONL over stdin/stdout;
ToolForge owns workspace checks, command allow-listing, call budgets, output
limits, and audit logging.

## Design and safety boundary

- RepoPilot is read-only with respect to source files. It writes only the
  requested report output.
- File paths are constrained to the repository root; symlinks and common build
  directories are skipped.
- Test commands use `shell=False` and a small executable allow-list.
- Local execution also bounds command argument count and size, matching the
  ToolForge backend defaults.
- Test execution can still mutate files inside the repository. For untrusted
  code, run the project inside a disposable container or use a separate
  sandbox. ToolForge is a policy layer, not an OS sandbox.
- A report is evidence for a human reviewer, not proof of a root cause or fix.
- Quant research plans are hypotheses, not claims of predictive power; all
  performance conclusions must come from FactorLab artifacts.

## Development

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

## License

MIT
