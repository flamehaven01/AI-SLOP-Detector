"""Non-ASCII paths survive git and helper-process output.

git prints non-ASCII paths quoted ("\\355\\225\\234...") unless core.quotepath
is off, and the output was decoded with the locale codec (cp949 on Korean
Windows). Staged files, changed files, churn and the git root all lost files
or directories with Korean names; the optional Rust discovery helper's UTF-8
JSON raised a decode error in a reader thread.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_detector.git_integration import GitIntegration
from slop_detector.operations_payloads import get_changed_files
from slop_detector.prioritization import ProjectPrioritizer
from slop_detector.rust_scan import _run_rust_scan

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

NAME = "한글"  # Korean "hangul", kept ASCII-escaped in source


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / f"{NAME} repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "base.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    return root


def test_staged_file_with_korean_name_is_listed(repo: Path):
    (repo / f"{NAME}.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    assert GitIntegration.get_staged_files(str(repo)) == [f"{NAME}.py"]


def test_changed_file_with_korean_name_is_listed(repo: Path):
    (repo / "base.py").write_text("x = 2\n", encoding="utf-8")
    (repo / f"{NAME}.py").write_text("y = 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "change")
    (repo / f"{NAME}.py").write_text("y = 3\n", encoding="utf-8")
    assert get_changed_files(repo) == [f"{NAME}.py"]


def test_churn_counts_korean_file_in_korean_repo(repo: Path):
    target = repo / f"{NAME}.py"
    for i in range(2):
        target.write_text(f"y = {i}\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-q", "-m", f"c{i}")
    prioritizer = ProjectPrioritizer(SimpleNamespace(get_churn_commit_window=lambda: 25))
    counts = prioritizer._load_git_churn(str(repo), [target])
    assert counts == {str(target.resolve()): 2}


def test_rust_helper_utf8_output_is_decoded(tmp_path: Path, monkeypatch):
    korean = str(tmp_path / f"{NAME}.py")
    stub = tmp_path / "stub.py"
    stub.write_text(
        "import sys\n"
        # Raw UTF-8 bytes, as the Rust helper writes them (not ASCII escapes).
        "sys.stdout.buffer.write("
        f"{json.dumps({'files': [korean]}, ensure_ascii=False).encode('utf-8')!r})\n",
        encoding="utf-8",
    )
    if os.name == "nt":
        binary = tmp_path / "slop_scan.cmd"
        binary.write_text(f'@"{sys.executable}" "{stub}"\r\n', encoding="utf-8")
    else:
        binary = tmp_path / "slop_scan"
        binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{stub}"\n', encoding="utf-8")
        binary.chmod(0o755)
    monkeypatch.setattr("slop_detector.rust_scan._candidate_binary_paths", lambda: [binary])
    assert _run_rust_scan(tmp_path, [], []) == [korean]
