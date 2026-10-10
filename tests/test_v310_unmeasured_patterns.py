"""v3.10 partial measurement: a pattern that could not measure a file is visible.

Found by the P0-1 differential: under resource exhaustion one rerun lost two
import findings in sentence-transformers' reranking.py while the scan still
said `complete: true`. `_module_exists` turned any lookup exception into
"installed" (no finding, no trace), and a pattern that raised was recorded
per file (`pattern_errors`, state "unmeasured") but never reached the scan
coverage or the gate; the partial result was also cached.

Contract:
- an environment lookup that raises makes phantom_import unmeasured for that
  file instead of answering "installed";
- `scan_coverage.unmeasured` counts partially measured files (total, by
  pattern) and such a scan is not complete: the hard gate fails closed, the
  soft gate warns;
- a partially measured result is not cached.

Failures are injected deterministically.
"""

from __future__ import annotations

from pathlib import Path

from slop_detector.analysis_cache import FileAnalysisCache
from slop_detector.ci_gate import CIGate, GateMode
from slop_detector.core import SlopDetector
from slop_detector.patterns import python_imports

USER = "import zzunmeasuredpkg\n\n\ndef f():\n    return zzunmeasuredpkg.VALUE\n"


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _raise_lookup(name, excluded=()):
    raise OSError("resource temporarily unavailable")


def test_lookup_error_is_unmeasured_not_installed(tmp_path, monkeypatch):
    _write(tmp_path, "requirements.txt", "")
    user = _write(tmp_path, "user.py", USER)
    monkeypatch.setattr(python_imports, "find_installed_spec", _raise_lookup)

    result = SlopDetector(read_only=True).analyze_file(str(user))

    assert [i.pattern_id for i in result.pattern_issues if "phantom" in i.pattern_id] == []
    assert result.pattern_errors == [
        {"pattern_id": "phantom_import", "error_type": "OSError", "state": "unmeasured"}
    ]


def test_partially_measured_files_make_the_scan_incomplete(tmp_path, monkeypatch):
    _write(tmp_path, "requirements.txt", "")
    _write(tmp_path, "user.py", USER)
    _write(tmp_path, "other.py", "def g():\n    return 1\n")
    monkeypatch.setattr(python_imports, "find_installed_spec", _raise_lookup)

    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    coverage = result.scan_coverage

    assert coverage["unmeasured"] == {
        "total": 1,
        "files": [{"path": "user.py", "patterns": ["phantom_import"]}],
        "by_pattern": {"phantom_import": 1},
    }
    assert coverage["complete"] is False
    hard = CIGate(mode=GateMode.HARD).evaluate(result)
    assert hard.should_fail_build is True
    assert "1 files partially measured" in hard.message
    soft = CIGate(mode=GateMode.SOFT).evaluate(result)
    assert soft.should_fail_build is False
    assert "1 files partially measured" in soft.message


def test_complete_scan_reports_no_unmeasured_files(tmp_path):
    _write(tmp_path, "other.py", "def g():\n    return 1\n")

    coverage = SlopDetector(read_only=True).analyze_project(str(tmp_path)).scan_coverage

    assert coverage["unmeasured"] == {"total": 0, "files": [], "by_pattern": {}}
    assert coverage["complete"] is True


def test_partial_result_is_not_cached(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    _write(root, "requirements.txt", "")
    user = _write(root, "user.py", USER)
    db = tmp_path / "cache.db"

    def analyze():
        detector = SlopDetector()
        detector._analysis_cache = FileAnalysisCache(db)
        return detector.analyze_file(str(user))

    with monkeypatch.context() as patch:
        patch.setattr(python_imports, "find_installed_spec", _raise_lookup)
        assert analyze().pattern_errors

    second = analyze()
    assert second.pattern_errors == []
    assert "phantom_import" in [i.pattern_id for i in second.pattern_issues]
