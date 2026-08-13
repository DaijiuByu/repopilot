import unittest

from repopilot.agent import analyze
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
