"""A hung Rust discovery helper falls back to the Python walk in bounded time.

The helper ran without a timeout, so a hang stalled the whole scan. It now
stops after RUST_SCAN_TIMEOUT_SECONDS; the project is then discovered by the
Python walk, the same file set, and the timeout is neither an analysis
failure nor part of any score.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import slop_detector.rust_scan as rust_scan
from slop_detector.core import SlopDetector

CODE = "def f(x):\n    return x + 1\n"


def _hang(monkeypatch, tmp_path: Path) -> None:
    binary = tmp_path / "slop_scan_stub"
    binary.write_text("", encoding="utf-8")  # exists; the command below is what runs
    monkeypatch.setattr(rust_scan, "_candidate_binary_paths", lambda: [binary])
    monkeypatch.setattr(
        rust_scan,
        "_scan_command",
        lambda *args: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    monkeypatch.setattr(rust_scan, "RUST_SCAN_TIMEOUT_SECONDS", 0.5)


def test_hung_helper_returns_within_the_timeout(tmp_path, monkeypatch):
    _hang(monkeypatch, tmp_path)
    started = time.perf_counter()
    assert rust_scan._run_rust_scan(tmp_path, ["**/*.py"], []) is None
    assert time.perf_counter() - started < 10


def test_timeout_falls_back_to_the_same_files(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "pkg").mkdir(parents=True)
    for name in ("a.py", "pkg/b.py", "pkg/c.py"):
        (project / name).write_text(CODE, encoding="utf-8")
    monkeypatch.setattr(rust_scan, "_candidate_binary_paths", lambda: [])
    baseline = SlopDetector(read_only=True).analyze_project(str(project))

    _hang(monkeypatch, tmp_path)
    result = SlopDetector(read_only=True).analyze_project(str(project))

    def files(r):
        return sorted(Path(f.file_path).name for f in r.file_results)

    assert files(result) == files(baseline) == ["a.py", "b.py", "c.py"]
    assert result.scan_coverage["failed"]["total"] == 0
    assert result.scan_coverage["measurement_state"] == "COMPLETE"
    assert result.weighted_deficit_score == baseline.weighted_deficit_score
