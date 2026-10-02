"""Controls for the pre-commit adapter.

pre-commit passes every changed file; `scan` takes one path. The adapter runs
the unchanged `scan` once per file, in input order, with the hook's flags, and
fails if any file fails. It has no scoring of its own.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
REPO_SRC = str(REPO / "src")
CLEAN = "def add(a, b):\n    return a + b\n"
STUB = "def later():\n    pass\n"  # one HIGH finding: 5.0 with --patterns-only


def _adapter():
    try:
        return importlib.import_module("slop_detector.precommit")
    except ImportError as exc:
        raise AssertionError("slop_detector.precommit is missing") from exc


def _files(tmp_path, *sources):
    paths = []
    for i, source in enumerate(sources):
        path = tmp_path / f"f{i}.py"
        path.write_text(source, encoding="utf-8")
        paths.append(str(path))
    return paths


def _run(argv):
    return _adapter().main(argv)


FLAGS = ["--patterns-only", "--fail-threshold", "4", "--read-only"]


@pytest.mark.parametrize(
    "sources, expected",
    [
        ((CLEAN, CLEAN), 0),
        ((CLEAN, STUB), 1),
        ((STUB, CLEAN), 1),
        ((CLEAN,), 0),
        ((STUB,), 1),
    ],
)
def test_any_failing_file_fails_the_hook(tmp_path, sources, expected):
    assert _run(FLAGS + _files(tmp_path, *sources)) == expected


def test_every_file_is_scanned_once_in_input_order_with_the_hook_flags(tmp_path, monkeypatch):
    adapter = _adapter()
    calls = []
    monkeypatch.setattr(adapter, "scan_main", lambda argv: calls.append(argv) or 0)
    files = _files(tmp_path, CLEAN, STUB, CLEAN)
    assert adapter.main(["--patterns-only", "--fail-threshold", "50", *files]) == 0
    assert calls == [["scan", f, "--patterns-only", "--fail-threshold", "50"] for f in files]


def test_no_files_scans_nothing(monkeypatch):
    adapter = _adapter()
    calls = []
    monkeypatch.setattr(adapter, "scan_main", lambda argv: calls.append(argv) or 0)
    assert adapter.main(["--patterns-only"]) == 0
    assert calls == []


def test_usage_errors_are_not_masked(tmp_path):
    files = _files(tmp_path, CLEAN)
    assert _run(["--disable", "no_such_pattern", "--read-only", *files]) == 2


def test_worst_exit_code_wins(tmp_path, monkeypatch):
    adapter = _adapter()
    codes = iter([1, 2, 0])
    monkeypatch.setattr(adapter, "scan_main", lambda argv: next(codes))
    assert adapter.main(_files(tmp_path, CLEAN, CLEAN, CLEAN)) == 2


def test_the_shipped_hook_runs_with_several_files(tmp_path):
    """The exact hook entry and args from .pre-commit-hooks.yaml, with two files."""
    import yaml

    hooks = {
        h["id"]: h
        for h in yaml.safe_load((REPO / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    }
    hook = hooks["slop-detector-patterns"]
    assert hook["pass_filenames"] is True
    entry = hook["entry"].split()
    assert entry[:2] == ["python", "-m"]
    files = _files(tmp_path, CLEAN, CLEAN)
    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path), PYTHONPATH=REPO_SRC)
    result = subprocess.run(
        [sys.executable, *entry[1:], *hook["args"], *files],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert "unrecognized arguments" not in result.stderr, result.stderr[-300:]
    assert result.returncode == 0, result.stderr[-300:]
