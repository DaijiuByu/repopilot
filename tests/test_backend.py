import sys
import tempfile
import unittest
from pathlib import Path

from repopilot.backend import LocalBackend, detect_test_command, issue_terms


class LocalBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("def login():\n    return False  # bug\n", encoding="utf-8")
        (self.root / ".hidden").write_text("must not appear", encoding="utf-8")
        self.backend = LocalBackend(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_lists_reads_and_searches(self):
        result = self.backend.list_files()
        self.assertEqual(result["files"], ["src/main.py"])
        self.assertEqual(self.backend.read_file("src/main.py")["content"].splitlines()[0], "def login():")
        matches = self.backend.search_code("bug")["matches"]
        self.assertEqual(matches[0]["path"], "src/main.py")
        self.assertEqual(matches[0]["line"], 2)

    def test_rejects_escape_and_shell(self):
        with self.assertRaises(ValueError):
            self.backend.read_file("../outside")
        with self.assertRaises(ValueError):
            self.backend.run_test(["sh", "-c", "echo unsafe"])

    def test_run_test_without_shell(self):
        result = self.backend.run_test(["python", "-c", "print('ok')"])
        self.assertTrue(result["success"])
        self.assertIn("ok", result["stdout"])


class ParsingTests(unittest.TestCase):
    def test_terms_and_test_detection(self):
        self.assertEqual(issue_terms("Login timeout in auth_handler"), ["Login", "timeout", "auth_handler"])
        self.assertEqual(
            detect_test_command(["pyproject.toml"]),
            ["python", "-m", "unittest", "discover", "-s", "tests", "-v"],
        )
        self.assertIsNone(detect_test_command(["README.md"]))
