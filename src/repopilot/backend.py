"""Repository tool backends.

The local backend mirrors ToolForge's policy defaults so RepoPilot remains
useful without a compiled helper. The harness backend speaks plain JSONL and
lets a Rust process own execution policy.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


MAX_FILE_BYTES = 256 * 1024
MAX_OUTPUT_CHARS = 32 * 1024
SKIP_DIRS = {".git", ".hg", ".svn", ".venv", "__pycache__", "node_modules", "target", "dist", "build"}
ALLOWED_COMMANDS = {"cargo", "pytest", "python", "python3", "npm", "go", "dotnet"}


class ToolBackend(Protocol):
    def list_files(self, path: str = ".", max_results: int = 200) -> dict[str, Any]: ...

    def read_file(self, path: str) -> dict[str, Any]: ...

    def search_code(self, query: str, path: str = ".", max_results: int = 50) -> dict[str, Any]: ...

    def run_test(self, command: list[str], timeout_ms: int = 30_000) -> dict[str, Any]: ...


def _bounded(value: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 18)] + "\n...[truncated]"


def _safe_path(root: Path, requested: str, *, must_exist: bool = True) -> Path:
    if not requested.strip():
        raise ValueError("path must not be empty")
    candidate = (root / requested).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes the configured workspace") from exc
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"path does not exist: {requested}")
    return candidate


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


@dataclass
class LocalBackend:
    root: Path
    max_file_bytes: int = MAX_FILE_BYTES
    max_output_chars: int = MAX_OUTPUT_CHARS

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        if not self.root.is_dir():
            raise ValueError(f"repository is not a directory: {self.root}")

    def list_files(self, path: str = ".", max_results: int = 200) -> dict[str, Any]:
        base = _safe_path(self.root, path)
        if not base.is_dir():
            raise ValueError(f"not a directory: {path}")
        limit = max(1, min(max_results, 1_000))
        files: list[str] = []
        for current, directories, names in os.walk(base, topdown=True, followlinks=False):
            directories[:] = sorted(
                name
                for name in directories
                if name not in SKIP_DIRS
                and not name.startswith(".")
                and not (Path(current) / name).is_symlink()
            )
            for name in sorted(name for name in names if not name.startswith(".")):
                candidate = Path(current) / name
                if candidate.is_symlink():
                    continue
                files.append(_relative(self.root, candidate))
                if len(files) >= limit:
                    return {"files": files, "truncated": True}
        return {"files": files, "truncated": False}

    def read_file(self, path: str) -> dict[str, Any]:
        target = _safe_path(self.root, path)
        if not target.is_file():
            raise ValueError(f"not a file: {path}")
        if target.stat().st_size > self.max_file_bytes:
            raise ValueError(f"file is larger than the {self.max_file_bytes} byte limit")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("file is not valid UTF-8 text") from exc
        return {"path": _relative(self.root, target), "content": content}

    def search_code(self, query: str, path: str = ".", max_results: int = 50) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("query must not be empty")
        limit = max(1, min(max_results, 500))
        matches: list[dict[str, Any]] = []
        for relative in self.list_files(path, 10_000)["files"]:
            target = self.root / relative
            if target.stat().st_size > self.max_file_bytes:
                continue
            try:
                content = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if query in line:
                    matches.append({"path": relative, "line": number, "text": _bounded(line, 1_000)})
                    if len(matches) >= limit:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    def run_test(self, command: list[str], timeout_ms: int = 30_000) -> dict[str, Any]:
        if not command or command[0] not in ALLOWED_COMMANDS:
            raise ValueError("command is not allow-listed")
        if any("\x00" in argument for argument in command):
            raise ValueError("command contains a NUL byte")
        timeout = min(max(timeout_ms, 1), 120_000) / 1_000
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=False,
                check=False,
            )
            return {
                "command": command,
                "exit_code": completed.returncode,
                "success": completed.returncode == 0,
                "stdout": _bounded(completed.stdout, self.max_output_chars),
                "stderr": _bounded(completed.stderr, self.max_output_chars),
                "timed_out": False,
                "duration_ms": round((time.monotonic() - started) * 1_000),
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "command": command,
                "exit_code": None,
                "success": False,
                "stdout": _bounded((exc.stdout or "") if isinstance(exc.stdout, str) else ""),
                "stderr": _bounded((exc.stderr or "") if isinstance(exc.stderr, str) else ""),
                "timed_out": True,
                "duration_ms": round((time.monotonic() - started) * 1_000),
            }


class HarnessBackend:
    """Client for a running ToolForge-compatible JSONL process."""

    def __init__(self, executable: str | Path, root: Path, *, max_calls: int = 24) -> None:
        self.root = root.resolve()
        self.max_calls = max_calls
        self.calls = 0
        self.process = subprocess.Popen(
            [str(executable), "serve", "--workspace", str(self.root), "--max-calls", str(max_calls)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def __enter__(self) -> "HarnessBackend":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.calls >= self.max_calls:
            raise RuntimeError("harness call budget exceeded")
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("harness pipes are unavailable")
        self.calls += 1
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            error = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"harness exited before responding: {error[-500:]}")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "harness request failed"))
        return response.get("result", {})

    def list_files(self, path: str = ".", max_results: int = 200) -> dict[str, Any]:
        return self._request({"tool": "list_files", "path": path, "max_results": max_results})

    def read_file(self, path: str) -> dict[str, Any]:
        return self._request({"tool": "read_file", "path": path})

    def search_code(self, query: str, path: str = ".", max_results: int = 50) -> dict[str, Any]:
        return self._request({"tool": "search_code", "query": query, "path": path, "max_results": max_results})

    def run_test(self, command: list[str], timeout_ms: int = 30_000) -> dict[str, Any]:
        return self._request({"tool": "run_test", "command": command, "timeout_ms": timeout_ms})


def detect_test_command(files: list[str]) -> list[str] | None:
    names = set(files)
    if "Cargo.toml" in names:
        return ["cargo", "test"]
    if any(name in names for name in ("pytest.ini", "tox.ini")):
        return ["pytest", "-q"]
    if "pyproject.toml" in names or "setup.cfg" in names:
        return ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
    if "package.json" in names:
        return ["npm", "test", "--", "--runInBand"]
    if "go.mod" in names:
        return ["go", "test", "./..."]
    if any(name.endswith(".csproj") for name in names):
        return ["dotnet", "test", "--nologo"]
    return None


def issue_terms(issue: str) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}", issue)
    stop = {"the", "and", "for", "with", "that", "this", "from", "when", "then", "into", "have", "does"}
    terms: list[str] = []
    for word in words:
        normalized = word.strip("._-")
        if normalized.lower() in stop or normalized.lower() in {term.lower() for term in terms}:
            continue
        terms.append(normalized)
    return terms[:8]
