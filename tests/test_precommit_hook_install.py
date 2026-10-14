"""The installed git pre-commit hook runs the supported adapter on staged files.

The old generated hook called options the CLI does not have (--files,
--record-history, --fail-on) and split staged paths on whitespace; it also
overwrote any existing hook and wrote to .git/hooks even where .git is a file.

The hook now runs `python -m slop_detector.precommit --staged --ci-mode hard`
with the installing interpreter. Policy: every staged added/copied/modified/
renamed .py file is scanned with --ci-mode hard; the commit is blocked when a
scan fails or cannot run. Files whose working tree differs from the index are
refused (the scan reads the working tree, not the staged blob).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from slop_detector.git_integration import HOOK_MARKER, GitIntegration

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

CLEAN = "def add(a, b):\n    return a + b\n"
BROKEN = "def f(:\n"
ODD_NAME = "한글 파일 $(x) 'q'.py"  # Korean, spaces, shell characters


def _git(cwd: Path, *args: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        capture_output=True,
        env=env,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _git(root, "add", ".")
    assert _git(root, "commit", "-q", "-m", "base", "--no-verify").returncode == 0
    return root


def _commit(root: Path, env=None) -> subprocess.CompletedProcess:
    # The hook's Python writes to a pipe here; fix its encoding so the output
    # (with the Korean file name) decodes the same on every platform.
    env = dict(env or os.environ, PYTHONIOENCODING="utf-8")
    return _git(root, "commit", "-m", "c", env=env)


def _hook_path(root: Path) -> Path:
    out = _git(root, "rev-parse", "--git-path", "hooks").stdout.decode().strip()
    return (root / out / "pre-commit").resolve()


def _output(result: subprocess.CompletedProcess) -> str:
    return (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_clean_staged_file_commits(repo):
    assert GitIntegration.install_pre_commit_hook(str(repo))
    assert HOOK_MARKER in _hook_path(repo).read_text(encoding="utf-8")
    (repo / "ok.py").write_text(CLEAN, encoding="utf-8")
    _git(repo, "add", "ok.py")
    result = _commit(repo)
    assert result.returncode == 0, _output(result)


def test_korean_space_and_shell_characters_reach_the_scan(repo):
    assert GitIntegration.install_pre_commit_hook(str(repo))
    (repo / ODD_NAME).write_text(BROKEN, encoding="utf-8")
    _git(repo, "add", ".")
    result = _commit(repo)
    assert result.returncode != 0
    assert ODD_NAME in _output(result)  # the one file, intact, was scanned


def test_no_staged_python_files_skips(repo):
    assert GitIntegration.install_pre_commit_hook(str(repo))
    (repo / "notes.md").write_text("y\n", encoding="utf-8")
    _git(repo, "add", ".")
    result = _commit(repo)
    assert result.returncode == 0 and "No staged Python files" in _output(result)


def test_detector_that_cannot_run_blocks_the_commit(repo, tmp_path):
    assert GitIntegration.install_pre_commit_hook(str(repo))
    (repo / "ok.py").write_text(CLEAN, encoding="utf-8")
    _git(repo, "add", "ok.py")
    env = dict(os.environ, SLOP_CONFIG=str(tmp_path / "missing.yaml"))
    assert _commit(repo, env=env).returncode != 0


def test_unstaged_changes_to_a_staged_file_are_refused(repo):
    assert GitIntegration.install_pre_commit_hook(str(repo))
    path = repo / "ok.py"
    path.write_text(CLEAN, encoding="utf-8")
    _git(repo, "add", "ok.py")
    path.write_text(CLEAN + "\nx = 1\n", encoding="utf-8")
    result = _commit(repo)
    assert result.returncode != 0
    assert "ok.py" in _output(result) and "not staged" in _output(result)


def test_existing_hook_is_never_overwritten(repo):
    hook = _hook_path(repo)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# AI SLOP Detector Pre-Commit Hook\nexit 0\n", encoding="utf-8")
    assert GitIntegration.install_pre_commit_hook(str(repo)) is False
    assert "exit 0" in hook.read_text(encoding="utf-8") and HOOK_MARKER not in hook.read_text(
        encoding="utf-8"
    )


def test_own_hook_is_updated(repo):
    assert GitIntegration.install_pre_commit_hook(str(repo))
    assert GitIntegration.install_pre_commit_hook(str(repo))


def test_worktree_installs_where_git_runs_hooks(repo, tmp_path):
    worktree = tmp_path / "wt"
    assert _git(repo, "worktree", "add", "-q", str(worktree)).returncode == 0
    assert (worktree / ".git").is_file()
    assert GitIntegration.install_pre_commit_hook(str(worktree))
    (worktree / "bad.py").write_text(BROKEN, encoding="utf-8")
    _git(worktree, "add", "bad.py")
    assert _commit(worktree).returncode != 0
