"""Tests for temporal drift summaries derived from history.db."""

from slop_detector.history import HistoryEntry, HistoryTracker


def _entry(file_path: str, deficit: float, *, ts: str) -> HistoryEntry:
    return HistoryEntry(
        timestamp=ts,
        file_path=file_path,
        file_hash="abc123",
        deficit_score=deficit,
        ldr_score=0.5,
        inflation_score=0.3,
        ddc_usage_ratio=0.7,
        pattern_count=0,
    )


def test_get_file_drift_summary_reports_direction_and_delta(tmp_path):
    tracker = HistoryTracker(db_path=tmp_path / "history.db")
    tracker._insert(_entry("sample.py", 20.0, ts="2026-01-01T00:00:00"))
    tracker._insert(_entry("sample.py", 30.0, ts="2026-01-02T00:00:00"))

    summary = tracker.get_file_drift_summary("sample.py", current_score=45.0, limit=5)

    assert summary is not None
    assert summary["history_count"] == 2
    assert summary["recent_average"] == 25.0
    assert summary["delta"] == 20.0
    assert summary["direction"] == "degraded"
    assert summary["is_regression"] is True


def test_get_file_drift_summary_returns_none_without_history(tmp_path):
    tracker = HistoryTracker(db_path=tmp_path / "history.db")

    assert tracker.get_file_drift_summary("missing.py", current_score=12.0) is None


def test_detect_regression_reuses_drift_summary(tmp_path):
    tracker = HistoryTracker(db_path=tmp_path / "history.db")
    tracker._insert(_entry("sample.py", 40.0, ts="2026-01-01T00:00:00"))
    tracker._insert(_entry("sample.py", 38.0, ts="2026-01-02T00:00:00"))

    summary = tracker.detect_regression("sample.py", current_score=55.0)

    assert summary is not None
    assert summary["history_count"] == 2
    assert summary["delta"] == 16.0
    assert summary["is_regression"] is True
