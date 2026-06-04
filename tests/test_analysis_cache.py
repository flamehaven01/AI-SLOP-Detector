"""Tests for SQLite-backed repeated-run file analysis cache."""

from slop_detector.analysis_cache import FileAnalysisCache
from slop_detector.core import SlopDetector


def test_analyze_file_reuses_cached_result_without_recomputing(tmp_path, monkeypatch):
    detector = SlopDetector()
    detector._analysis_cache = FileAnalysisCache(tmp_path / "analysis_cache.db")

    file_path = tmp_path / "sample.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    first = detector.analyze_file(str(file_path))

    def explode(*args, **kwargs):
        raise AssertionError("cache hit should skip recalculation")

    monkeypatch.setattr(detector.ldr_calc, "calculate", explode)
    second = detector.analyze_file(str(file_path))

    assert second.deficit_score == first.deficit_score
    assert second.status == first.status


def test_analyze_file_invalidates_cache_when_file_changes(tmp_path, monkeypatch):
    detector = SlopDetector()
    detector._analysis_cache = FileAnalysisCache(tmp_path / "analysis_cache.db")

    file_path = tmp_path / "sample.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    detector.analyze_file(str(file_path))

    calls = {"count": 0}
    original = detector.ldr_calc.calculate

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(detector.ldr_calc, "calculate", wrapped)
    file_path.write_text("def add(a, b):\n    return a + b + 1\n", encoding="utf-8")
    detector.analyze_file(str(file_path))

    assert calls["count"] == 1


def test_analyze_file_invalidates_cache_when_config_changes(tmp_path, monkeypatch):
    cache_db = tmp_path / "analysis_cache.db"
    file_path = tmp_path / "sample.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    detector_a = SlopDetector()
    detector_a._analysis_cache = FileAnalysisCache(cache_db)
    detector_a.analyze_file(str(file_path))

    detector_b = SlopDetector()
    detector_b._analysis_cache = FileAnalysisCache(cache_db)
    detector_b.config.config["weights"]["ldr"] = 0.55

    calls = {"count": 0}
    original = detector_b.ldr_calc.calculate

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(detector_b.ldr_calc, "calculate", wrapped)
    detector_b.analyze_file(str(file_path))

    assert calls["count"] == 1


def test_analyze_project_reuses_cached_results_for_unchanged_files(tmp_path, monkeypatch):
    detector = SlopDetector()
    detector._analysis_cache = FileAnalysisCache(tmp_path / "analysis_cache.db")
    detector.config.config["ignore"] = []

    file_a = tmp_path / "a.py"
    file_b = tmp_path / "b.py"
    file_a.write_text("def a():\n    return 1\n", encoding="utf-8")
    file_b.write_text("def b():\n    return 2\n", encoding="utf-8")

    detector.analyze_project(str(tmp_path))

    calls = {"count": 0}
    original = detector.ldr_calc.calculate

    def wrapped(*args, **kwargs):
        calls["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(detector.ldr_calc, "calculate", wrapped)
    file_b.write_text("def b():\n    return 20\n", encoding="utf-8")
    detector.analyze_project(str(tmp_path))

    assert calls["count"] == 1
