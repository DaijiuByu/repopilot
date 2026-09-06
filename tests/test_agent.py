import unittest

from repopilot.agent import analyze, build_research_plan
from repopilot.backend import LocalBackend


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
