"""v3.9.3 coverage integrity: a file whose analysis fails is counted, never lost.

Found by the cross-domain precision study on the published 3.9.2: project
analysis caught a per-file exception, logged it and dropped the file
(`core.py` Python and JS loops), and `scan_coverage.analyzed` counted results,
so the file appeared nowhere (not analyzed, excluded or unsupported) and the
project score and gate silently covered fewer files. Observed once on
hermes-agent: 167 Python files missing under memory pressure.

Contract: the failed file is listed in `scan_coverage.failed` (path, language,
error type, totals by language and error type), the scan says it is not
complete, the soft gate reports the incomplete scan without failing, and the
hard gate fails closed. The failed file is not scored: an analyzer or
environment failure is not a defect of the analyzed code (a syntax error keeps
its own `parse_error` semantics).

The failure is injected deterministically (no real out-of-memory).
"""

from __future__ import annotations

from pathlib import Path

from slop_detector.ci_gate import CIGate, GateMode
from slop_detector.core import SlopDetector
from slop_detector.languages.js_analyzer import JSAnalyzer

PY = "def double(x):\n    total = x * 2\n    return total\n"


def _project(root: Path) -> Path:
    for name in ("good.py", "bad.py", "other.py"):
        (root / name).write_text(PY, encoding="utf-8")
    return root


def _fail_python_file(monkeypatch, name: str) -> None:
    original = SlopDetector.analyze_file

    def failing(self, file_path, *args, **kwargs):
        if Path(file_path).name == name:
            raise RuntimeError("analyzer exploded")
        return original(self, file_path, *args, **kwargs)

    monkeypatch.setattr(SlopDetector, "analyze_file", failing)


def _analyze(root: Path):
    return SlopDetector(read_only=True).analyze_project(str(root))


def test_failed_python_file_is_counted_and_named(tmp_path, monkeypatch):
    _fail_python_file(monkeypatch, "bad.py")
    coverage = _analyze(_project(tmp_path)).scan_coverage
    failed = coverage["failed"]
    assert failed["total"] == 1
    assert failed["files"] == [
        {"path": "bad.py", "language": "python", "error_type": "RuntimeError"}
    ]
    assert failed["by_language"] == {"python": 1}
    assert failed["by_error_type"] == {"RuntimeError": 1}
    assert coverage["complete"] is False
    assert coverage["analyzed"]["python"] == 2


def test_other_files_are_still_analyzed(tmp_path, monkeypatch):
    """Control."""
    _fail_python_file(monkeypatch, "bad.py")
    result = _analyze(_project(tmp_path))
    assert sorted(Path(r.file_path).name for r in result.file_results) == ["good.py", "other.py"]


def test_failed_file_is_not_scored(tmp_path, monkeypatch):
    """Preservation: the project score covers the analyzed files only; the failed
    file is not counted as a 100-point file."""
    reference_root = tmp_path / "ref"
    reference_root.mkdir()
    for name in ("good.py", "other.py"):
        (reference_root / name).write_text(PY, encoding="utf-8")
    reference = _analyze(reference_root)
    root = tmp_path / "proj"
    root.mkdir()
    _fail_python_file(monkeypatch, "bad.py")
    result = _analyze(_project(root))
    assert result.weighted_deficit_score == reference.weighted_deficit_score


def test_complete_scan_says_so(tmp_path):
    coverage = _analyze(_project(tmp_path)).scan_coverage
    assert coverage["failed"]["total"] == 0
    assert coverage["complete"] is True


def test_hard_gate_fails_closed_on_an_incomplete_scan(tmp_path, monkeypatch):
    _fail_python_file(monkeypatch, "bad.py")
    gate = CIGate(mode=GateMode.HARD).evaluate(_analyze(_project(tmp_path)))
    assert gate.should_fail_build
    assert gate.verdict.value == "fail"
    assert "incomplete" in gate.message.lower()


def test_soft_gate_reports_an_incomplete_scan_without_failing(tmp_path, monkeypatch):
    _fail_python_file(monkeypatch, "bad.py")
    gate = CIGate(mode=GateMode.SOFT).evaluate(_analyze(_project(tmp_path)))
    assert not gate.should_fail_build
    assert "incomplete" in gate.message.lower()


def test_failed_js_file_is_counted(tmp_path, monkeypatch):
    root = _project(tmp_path)
    (root / "ok.js").write_text("function a() {\n  return 1;\n}\n", encoding="utf-8")
    (root / "broken.js").write_text("function b() {\n  return 2;\n}\n", encoding="utf-8")
    original = JSAnalyzer.analyze

    def failing(self, file_path):
        if Path(file_path).name == "broken.js":
            raise RuntimeError("js analyzer exploded")
        return original(self, file_path)

    monkeypatch.setattr(JSAnalyzer, "analyze", failing)
    coverage = _analyze(root).scan_coverage
    assert coverage["failed"]["by_language"] == {"javascript": 1}
    assert coverage["failed"]["files"] == [
        {"path": "broken.js", "language": "javascript", "error_type": "RuntimeError"}
    ]
    assert coverage["complete"] is False


def test_failed_coverage_is_in_the_json(tmp_path, monkeypatch):
    _fail_python_file(monkeypatch, "bad.py")
    payload = _analyze(_project(tmp_path)).to_dict()
    assert payload["scan_coverage"]["failed"]["total"] == 1
    assert payload["scan_coverage"]["complete"] is False
