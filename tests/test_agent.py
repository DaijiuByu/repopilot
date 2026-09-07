import unittest

from repopilot.agent import analyze, build_research_plan
from repopilot.orchestrator import run_factorlab_experiment
from pathlib import Path
import tempfile
from datetime import date, timedelta


class FakeBackend:
    def __init__(self):
        self.calls = []

    def list_files(self, path=".", max_results=200):
        self.calls.append(("list_files", path))
        return {"files": ["pyproject.toml", "src/auth.py"], "truncated": False}

    def search_code(self, query, path=".", max_results=50):
        self.calls.append(("search_code", query))
        return {"matches": [{"path": "src/auth.py", "line": 4, "text": "timeout = 1"}]}

    def read_file(self, path):
        self.calls.append(("read_file", path))
        return {"path": path, "content": "timeout = 1\n"}

    def run_test(self, command, timeout_ms=30_000):
        self.calls.append(("run_test", command))
        return {"success": True, "stderr": "", "timed_out": False}


class AgentTests(unittest.TestCase):
    def test_research_plan_is_allow_listed_and_deterministic(self):
        plan = build_research_plan("检查 20 日动量因子，成本 5bp", dataset="demo_v1")
        self.assertEqual(plan.factor, "momentum")
        self.assertEqual(plan.lookback, 20)
        self.assertEqual(len(plan.plan_id), 16)
        self.assertEqual(plan.as_dict()["schema_version"], 1)
        self.assertEqual(plan.as_dict()["factorlab_args"]["lookback"], 20)
        self.assertEqual(plan.as_dict()["execution"], "requires_explicit_backend_confirmation")

    def test_research_plan_rejects_unsafe_parameters(self):
        with self.assertRaises(ValueError):
            build_research_plan("momentum", dataset="../secret")
        with self.assertRaises(ValueError):
            build_research_plan("momentum", quantile=0.9)

    def test_run_research_bridge_uses_fixed_factorlab_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            panel = root / "panel.csv"
            rows = ["date,ticker,close"]
            for day in range(40):
                day_text = (date(2024, 1, 1) + timedelta(days=day)).isoformat()
                for asset in range(8):
                    rows.append(f"{day_text},A{asset},{100 + day + asset / 10:.4f}")
            panel.write_text("\n".join(rows), encoding="utf-8")
            result = run_factorlab_experiment(
                "检查 5 日动量因子的样本外表现",
                input_path=panel,
                output_dir=root / "run",
                factorlab_root=Path("D:/1_d_github/factorlab"),
                lookback=5,
                timeout_seconds=120,
            )
            self.assertTrue(result["success"], result["stderr"])
            self.assertIn("factorlab.cli", " ".join(result["command"]))
            self.assertTrue((root / "run" / "research_plan.json").exists())
            self.assertEqual(result["timed_out"], False)
            self.assertEqual(result["experiment_result"]["config"]["lookback"], 5)
            self.assertTrue(Path(result["artifacts"]).joinpath("run_manifest.json").exists())

    def test_analysis_is_structured_and_does_not_modify_files(self):
        backend = FakeBackend()
        report = analyze("login timeout", backend)
        self.assertEqual(report.test_command, ["python", "-m", "unittest", "discover", "-s", "tests", "-v"])
        self.assertTrue(report.relevant_matches)
        self.assertIsNone(report.model_summary)
        self.assertIn("read_file", [call[0] for call in backend.calls])

    def test_markdown_is_handoff_ready(self):
        report = analyze("missing config", FakeBackend())
        markdown = report.markdown()
        self.assertIn("# RepoPilot triage report", markdown)
        self.assertIn("does not modify the repository", markdown)
