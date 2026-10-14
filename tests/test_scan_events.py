"""A project scan reports its real phases to an observer, and stops when it raises.

The engine had no progress hook, and JS/TS and Go files were discovered only
after every Python file was analyzed. Now all three languages are discovered
first (one "discovered" event with the totals), each file reports
"file_done" (analyzed or failed), and "aggregating" precedes the result.
Observer calls sit outside the per-file `except Exception`, so an exception
from the observer (a cancellation) stops the scan instead of being recorded
as a failed file. Without an observer the result is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slop_detector.core import SlopDetector

CODE = "def f(x):\n    return x + 1\n"


class StopScanError(Exception):
    pass


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / name).write_text(CODE, encoding="utf-8")
    (tmp_path / "app.js").write_text("function f(a) { return a + 1; }\n", encoding="utf-8")
    (tmp_path / "main.go").write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    return tmp_path


def _scan(project: Path, observer=None):
    return SlopDetector(read_only=True).analyze_project(str(project), observer=observer)


def test_event_sequence_matches_the_scan(project):
    events = []
    result = _scan(project, events.append)
    kinds = [e.kind for e in events]
    assert kinds[0] == "discovered" and kinds[-1] == "aggregating"
    assert kinds.count("discovered") == 1 and kinds.count("aggregating") == 1
    assert events[0].totals == {"python": 3, "javascript": 1, "go": 1}
    done = [e for e in events if e.kind == "file_done"]
    assert [e.index for e in done] == [1, 2, 3, 4, 5]
    assert {e.total for e in done} == {5}
    assert [e.language for e in done] == ["python"] * 3 + ["javascript", "go"]
    analyzed = result.scan_coverage["analyzed"]["total"] + result.scan_coverage["failed"]["total"]
    assert len(done) == analyzed


def test_a_failed_file_is_reported_and_the_scan_continues(project, monkeypatch):
    original = SlopDetector._build_file_analysis

    def build(self, file_path, *args, **kwargs):
        if Path(file_path).name == "b.py":
            raise AttributeError("analysis raised")
        return original(self, file_path, *args, **kwargs)

    monkeypatch.setattr(SlopDetector, "_build_file_analysis", build)
    events = []
    result = _scan(project, events.append)
    outcomes = {Path(e.path).name: e.outcome for e in events if e.kind == "file_done"}
    assert outcomes["b.py"] == "failed" and outcomes["a.py"] == "analyzed"
    assert result.scan_coverage["failed"]["total"] == 1


def _stop_at(kind: str, language: str = ""):
    def observer(event):
        if event.kind == kind and (not language or event.language == language):
            raise StopScanError()

    return observer


@pytest.mark.parametrize("language", ["python", "javascript", "go"])
def test_observer_exception_stops_the_scan_in_every_language(project, monkeypatch, language):
    calls = []
    original = SlopDetector.analyze_file

    def counted(self, *args, **kwargs):
        calls.append(args[0])
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SlopDetector, "analyze_file", counted)
    with pytest.raises(StopScanError):
        _scan(project, _stop_at("file_done", language))
    if language == "python":
        assert len(calls) == 1  # stopped after the first file, not recorded as failed


def test_stop_at_discovery_analyzes_nothing(project, monkeypatch):
    calls = []
    monkeypatch.setattr(SlopDetector, "analyze_file", lambda self, *a, **k: calls.append(a))
    with pytest.raises(StopScanError):
        _scan(project, _stop_at("discovered"))
    assert calls == []


def test_observer_does_not_change_the_result(project):
    plain = _scan(project).to_dict()
    observed = _scan(project, lambda event: None).to_dict()
    assert observed == plain
