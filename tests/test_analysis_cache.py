"""Tests for SQLite-backed repeated-run file analysis cache."""

from hashlib import sha256

from slop_detector.analysis_cache import (
    CACHE_ENGINE_VERSION,
    FileAnalysisCache,
    deserialize_file_analysis,
    fingerprint_config,
    serialize_file_analysis,
)
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


def test_cache_round_trip_preserves_file_analysis_contract(tmp_path):
    detector = SlopDetector()
    file_path = tmp_path / "sample.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    result = detector.analyze_file(str(file_path))
    payload = serialize_file_analysis(result)
    restored = deserialize_file_analysis(payload)

    assert restored.file_path == result.file_path
    assert restored.deficit_score == result.deficit_score
    assert restored.status == result.status
    assert restored.deficit_breakdown == result.deficit_breakdown
    assert restored.suppression_ledger == result.suppression_ledger
    assert restored.dcf == result.dcf


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


def test_analyze_file_invalidates_cache_when_engine_version_changes(tmp_path):
    cache = FileAnalysisCache(tmp_path / "analysis_cache.db")
    file_path = tmp_path / "sample.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    detector = SlopDetector()
    result = detector.analyze_file(str(file_path))
    stat = file_path.stat()
    content_hash = sha256(file_path.read_bytes()).hexdigest()

    cache.put(
        file_path=str(file_path.resolve()),
        file_size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        content_hash=content_hash,
        config_fingerprint=fingerprint_config(detector.config.config),
        result=result,
        engine_version="old-engine-version",
    )

    cached = cache.get(
        file_path=str(file_path.resolve()),
        file_size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        content_hash=content_hash,
        config_fingerprint=fingerprint_config(detector.config.config),
        engine_version=CACHE_ENGINE_VERSION,
    )

    assert cached is None


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
