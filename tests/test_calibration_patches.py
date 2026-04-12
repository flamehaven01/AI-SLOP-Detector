"""
Unit tests for v3.5.0 self-calibration patches P1-P4.

P1 — project_id column: stored in history.db, filters _load_history
P2 — count_files_with_multiple_runs: correct count, project_id scoping
P3 — domain-anchored grid search: candidates stay within DOMAIN_TOLERANCE
P4 — CalibrationResult.warnings: populated when optimal drifts > DOMAIN_DRIFT_LIMIT
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from slop_detector.history import HistoryEntry, HistoryTracker
from slop_detector.ml.self_calibrator import (
    DOMAIN_DRIFT_LIMIT,
    DOMAIN_TOLERANCE,
    MAX_W,
    MIN_W,
    CalibrationEvent,
    CalibrationResult,
    SelfCalibrator,
    WeightCandidate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(
    file_path: str,
    *,
    deficit: float = 30.0,
    ldr: float = 0.5,
    inflation: float = 0.3,
    ddc: float = 0.7,
    ts: str = "",
    file_hash: str = "aabbccdd1234",
    project_id: str | None = None,
) -> HistoryEntry:
    return HistoryEntry(
        timestamp=ts or datetime.now().isoformat(),
        file_path=file_path,
        file_hash=file_hash,
        deficit_score=deficit,
        ldr_score=ldr,
        inflation_score=inflation,
        ddc_usage_ratio=ddc,
        pattern_count=0,
        n_critical_patterns=0,
        project_id=project_id,
    )


def _insert(tracker: HistoryTracker, *entries: HistoryEntry) -> None:
    for e in entries:
        tracker._insert(e)


def _improvement_event(**kw) -> CalibrationEvent:
    kw.setdefault("file_path", "f.py")
    kw.setdefault("ldr", 0.6)
    kw.setdefault("inflation", 0.2)
    kw.setdefault("ddc", 0.8)
    kw.setdefault("n_critical_patterns", 0)
    kw["label"] = "improvement"
    return CalibrationEvent(**kw)


def _fp_event(**kw) -> CalibrationEvent:
    kw.setdefault("file_path", "g.py")
    kw.setdefault("ldr", 0.6)
    kw.setdefault("inflation", 0.5)
    kw.setdefault("ddc", 0.5)
    kw.setdefault("n_critical_patterns", 0)
    kw["label"] = "fp_candidate"
    return CalibrationEvent(**kw)


# ---------------------------------------------------------------------------
# P2 — count_files_with_multiple_runs
# ---------------------------------------------------------------------------


class TestCountFilesWithMultipleRuns:
    def test_empty_db_returns_zero(self, tmp_path):
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        assert tracker.count_files_with_multiple_runs() == 0

    def test_single_run_files_not_counted(self, tmp_path):
        """Files scanned exactly once produce no calibration pairs."""
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        _insert(tracker, _entry("a.py"), _entry("b.py"), _entry("c.py"))
        assert tracker.count_files_with_multiple_runs() == 0

    def test_counts_only_repeat_files(self, tmp_path):
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        _insert(
            tracker,
            _entry("a.py", ts="2026-01-01T00:00:00"),
            _entry("a.py", ts="2026-01-02T00:00:00"),  # repeat
            _entry("b.py"),  # single run
        )
        assert tracker.count_files_with_multiple_runs() == 1

    def test_three_runs_still_counts_as_one_file(self, tmp_path):
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        for i in range(3):
            _insert(tracker, _entry("a.py", ts=f"2026-01-0{i+1}T00:00:00"))
        assert tracker.count_files_with_multiple_runs() == 1

    def test_project_id_scoping(self, tmp_path):
        """count_files_with_multiple_runs(project_id=X) only counts files from project X."""
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        # proj_a: file_a scanned twice
        _insert(
            tracker,
            _entry("file_a.py", project_id="proj_a", ts="2026-01-01T00:00:00"),
            _entry("file_a.py", project_id="proj_a", ts="2026-01-02T00:00:00"),
        )
        # proj_b: file_b scanned twice
        _insert(
            tracker,
            _entry("file_b.py", project_id="proj_b", ts="2026-01-01T00:00:00"),
            _entry("file_b.py", project_id="proj_b", ts="2026-01-02T00:00:00"),
        )
        assert tracker.count_files_with_multiple_runs(project_id="proj_a") == 1
        assert tracker.count_files_with_multiple_runs(project_id="proj_b") == 1
        assert tracker.count_files_with_multiple_runs() == 2  # global, no filter

    def test_project_id_no_cross_contamination(self, tmp_path):
        """A file scanned twice in proj_a must not count toward proj_b."""
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        _insert(
            tracker,
            _entry("file_a.py", project_id="proj_a", ts="2026-01-01T00:00:00"),
            _entry("file_a.py", project_id="proj_a", ts="2026-01-02T00:00:00"),
        )
        assert tracker.count_files_with_multiple_runs(project_id="proj_b") == 0


# ---------------------------------------------------------------------------
# P1 — project_id stored and filtered
# ---------------------------------------------------------------------------


class TestProjectIdIsolation:
    def test_project_id_persisted(self, tmp_path):
        """record() stores project_id in the database."""
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        tracker._insert(_entry("a.py", project_id="abc123"))
        with tracker._conn() as conn:
            row = conn.execute("SELECT project_id FROM history WHERE file_path = 'a.py'").fetchone()
        assert row[0] == "abc123"

    def test_null_project_id_stored_as_null(self, tmp_path):
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        tracker._insert(_entry("a.py", project_id=None))
        with tracker._conn() as conn:
            row = conn.execute("SELECT project_id FROM history").fetchone()
        assert row[0] is None

    def test_load_history_filters_by_project_id(self, tmp_path):
        """SelfCalibrator._load_history(project_id=X) returns only X's rows."""
        tracker = HistoryTracker(db_path=tmp_path / "history.db")
        _insert(
            tracker,
            _entry("proj1/a.py", project_id="proj1"),
            _entry("proj1/b.py", project_id="proj1"),
            _entry("proj2/c.py", project_id="proj2"),
        )
        calibrator = SelfCalibrator(db_path=tmp_path / "history.db")
        rows_p1 = calibrator._load_history(project_id="proj1")
        rows_p2 = calibrator._load_history(project_id="proj2")
        rows_all = calibrator._load_history()

        assert len(rows_p1) == 2
        assert all("proj1" in r["file_path"] for r in rows_p1)
        assert len(rows_p2) == 1
        assert all("proj2" in r["file_path"] for r in rows_p2)
        assert len(rows_all) == 3


# ---------------------------------------------------------------------------
# P3 — domain-anchored grid search
# ---------------------------------------------------------------------------


class TestDomainAnchoredGridSearch:
    _ANCHOR = {"ldr": 0.40, "inflation": 0.30, "ddc": 0.20, "purity": 0.10}
    _EVENTS_IMP = [_improvement_event() for _ in range(6)]
    _EVENTS_FP = [_fp_event() for _ in range(6)]

    def test_unconstrained_covers_full_ldr_range(self, tmp_path):
        """Without domain_anchor grid spans MIN_W to MAX_W for ldr."""
        calibrator = SelfCalibrator(db_path=tmp_path / "history.db")
        candidates = calibrator._grid_search(self._EVENTS_IMP, self._EVENTS_FP)
        ldr_vals = {c.w_ldr for c in candidates}
        assert min(ldr_vals) == pytest.approx(MIN_W, abs=0.001)
        assert max(ldr_vals) == pytest.approx(MAX_W, abs=0.01)

    def test_constrained_candidates_within_tolerance(self, tmp_path):
        """With domain_anchor every candidate is within +/-DOMAIN_TOLERANCE on each axis."""
        calibrator = SelfCalibrator(db_path=tmp_path / "history.db")
        candidates = calibrator._grid_search(
            self._EVENTS_IMP, self._EVENTS_FP, domain_anchor=self._ANCHOR
        )
        assert len(candidates) > 0, "Expected at least one valid candidate"
        for c in candidates:
            assert abs(c.w_ldr - self._ANCHOR["ldr"]) <= DOMAIN_TOLERANCE + 0.001
            assert abs(c.w_inflation - self._ANCHOR["inflation"]) <= DOMAIN_TOLERANCE + 0.001
            assert abs(c.w_purity - self._ANCHOR["purity"]) <= DOMAIN_TOLERANCE + 0.001

    def test_constrained_search_has_fewer_candidates(self, tmp_path):
        """Constrained grid must produce strictly fewer candidates than unconstrained."""
        calibrator = SelfCalibrator(db_path=tmp_path / "history.db")
        all_cands = calibrator._grid_search(self._EVENTS_IMP, self._EVENTS_FP)
        anchored_cands = calibrator._grid_search(
            self._EVENTS_IMP, self._EVENTS_FP, domain_anchor=self._ANCHOR
        )
        assert len(anchored_cands) < len(all_cands)


# ---------------------------------------------------------------------------
# P4 — CalibrationResult.warnings
# ---------------------------------------------------------------------------


class TestCalibrationWarnings:
    def test_warnings_field_exists_and_defaults_empty(self):
        r = CalibrationResult(status="ok")
        assert isinstance(r.warnings, list)
        assert r.warnings == []

    def test_warnings_independent_per_instance(self):
        """Each CalibrationResult has its own warnings list (mutable default safety)."""
        r1 = CalibrationResult(status="ok")
        r2 = CalibrationResult(status="ok")
        r1.warnings.append("x")
        assert r2.warnings == []

    def test_calibrate_populates_warnings_on_large_drift(self, tmp_path):
        """calibrate() adds a warning for each dimension drifting > DOMAIN_DRIFT_LIMIT."""
        db = tmp_path / "history.db"
        HistoryTracker(db_path=db)  # creates the DB file
        calibrator = SelfCalibrator(db_path=db)

        # Current weights have ldr=0.10; force grid to return winner with ldr=0.60 -> drift=0.50
        current = {"ldr": 0.10, "inflation": 0.40, "ddc": 0.40, "purity": 0.10}
        winner = WeightCandidate(
            w_ldr=0.60,
            w_inflation=0.15,
            w_ddc=0.15,
            w_purity=0.10,
            fn_rate=0.0,
            fp_rate=0.0,
            combined_score=0.0,
            tiebreak_score=0.0,
        )
        runner_up = WeightCandidate(
            w_ldr=0.55,
            w_inflation=0.15,
            w_ddc=0.20,
            w_purity=0.10,
            fn_rate=0.2,
            fp_rate=0.2,
            combined_score=0.4,
            tiebreak_score=0.0,
        )
        imp_events = [_improvement_event() for _ in range(6)]
        fp_events = [_fp_event() for _ in range(6)]
        all_events = imp_events + fp_events

        with (
            patch.object(calibrator, "_extract_events", return_value=(all_events, 12)),
            patch.object(calibrator, "_grid_search", return_value=[winner, runner_up]),
            patch.object(calibrator, "_score_weights", return_value=(0.3, 0.3, 0.0)),
        ):
            result = calibrator.calibrate(current_weights=current)

        # Mocked setup guarantees confidence_gap=0.4, improvement=0.6 -> status="ok"
        assert result.status == "ok"
        # ldr drift = abs(0.60 - 0.10) = 0.50 > DOMAIN_DRIFT_LIMIT(0.25)
        assert any(
            "ldr" in w for w in result.warnings
        ), f"Expected ldr drift warning. warnings={result.warnings}"

    def test_no_warnings_when_drift_small(self, tmp_path):
        """No warnings when optimal weights stay within DOMAIN_DRIFT_LIMIT of anchor."""
        db = tmp_path / "history.db"
        HistoryTracker(db_path=db)  # creates the DB file
        calibrator = SelfCalibrator(db_path=db)

        current = {"ldr": 0.40, "inflation": 0.30, "ddc": 0.20, "purity": 0.10}
        # Winner very close to current weights (drift = 0.05 on each)
        winner = WeightCandidate(
            w_ldr=0.45,
            w_inflation=0.25,
            w_ddc=0.20,
            w_purity=0.10,
            fn_rate=0.0,
            fp_rate=0.0,
            combined_score=0.0,
            tiebreak_score=0.0,
        )
        runner_up = WeightCandidate(
            w_ldr=0.40,
            w_inflation=0.30,
            w_ddc=0.20,
            w_purity=0.10,
            fn_rate=0.3,
            fp_rate=0.3,
            combined_score=0.6,
            tiebreak_score=0.0,
        )
        imp_events = [_improvement_event() for _ in range(6)]
        fp_events = [_fp_event() for _ in range(6)]
        all_events = imp_events + fp_events

        with (
            patch.object(calibrator, "_extract_events", return_value=(all_events, 12)),
            patch.object(calibrator, "_grid_search", return_value=[winner, runner_up]),
            patch.object(calibrator, "_score_weights", return_value=(0.3, 0.3, 0.0)),
        ):
            result = calibrator.calibrate(current_weights=current)

        assert result.status == "ok"
        assert result.warnings == [], f"Expected no warnings but got: {result.warnings}"
