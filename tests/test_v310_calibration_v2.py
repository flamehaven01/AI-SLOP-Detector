"""v3.10 Calibration v2: learn only from comparable evidence.

Measured on a read-only copy of a real history database (31,065 rows, 2026-10-10):
- 364 v1 "improvement" events, 289 of them (79%) with an unchanged file hash:
  a detector or configuration change was learned as a user fix;
- of 9,001 rows at or above 30, 5,411 (60%) were below 30 on the weighted base
  alone: pattern penalties put them there, and weights cannot move those;
- `project_id` was the working directory, so projects scanned from one
  directory shared a history, and runs measured by different detector versions
  or configurations were compared as if equal;
- the default "current weights" were the v3.7.0 values the defaults reverted.

Contract (C9, writing weights, stays out of scope):
- C1 history schema v6: detector_version, measurement_fingerprint,
  weights_vector, project_root, file_rel_path, base_deficit, pattern_penalty,
  provenance_state ("v6"); older databases gain the columns, old rows are kept
  and never rewritten;
- C2 rows without v6 provenance are never calibration evidence;
- C3 two runs are comparable only with the same measurement fingerprint,
  project root and file;
- C4 an improvement needs a changed file hash and a metric-only drop;
- C5 `stable_flag_candidate`: flagged, unchanged hash, once per file;
- C6/C7 only ldr/inflation/ddc are learned, purity is held at its current
  weight; candidates are scored with the canonical compute_gqg and the
  canonical SUSPICIOUS_AT band threshold;
- C8 calibration is per project root and reports its evidence counts; the
  default current weights are Config.DEFAULT_CONFIG's.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from slop_detector import __version__
from slop_detector.config import Config
from slop_detector.core import SlopDetector
from slop_detector.core_scoring import compute_gqg
from slop_detector.diagnostic_bands import SUSPICIOUS_AT
from slop_detector.history import HistoryEntry, HistoryTracker, measurement_provenance
from slop_detector.ml.self_calibrator import SelfCalibrator, metric_only_deficit

DEFAULT_WEIGHTS = Config.DEFAULT_CONFIG["weights"]
ROOT = "/proj"

# Metric triples with a known metric-only deficit under the default weights.
FLAGGED = dict(ldr=0.30, inflation=0.9, ddc=0.5)  # well above 30
CLEAN = dict(ldr=0.95, inflation=0.0, ddc=1.0)  # near 0


def _row(
    tracker: HistoryTracker,
    rel: str,
    ts: str,
    file_hash: str,
    metrics: dict,
    *,
    fingerprint: str = "m1",
    root: str = ROOT,
    provenance: bool = True,
    penalty: float = 0.0,
) -> None:
    base = metric_only_deficit(
        metrics["ldr"], metrics["inflation"], metrics["ddc"], DEFAULT_WEIGHTS
    )
    entry = HistoryEntry(
        timestamp=ts,
        file_path=f"{root}/{rel}",
        file_hash=file_hash,
        deficit_score=min(100.0, base + penalty),
        ldr_score=metrics["ldr"],
        inflation_score=metrics["inflation"],
        ddc_usage_ratio=metrics["ddc"],
        pattern_count=0,
    )
    if provenance:
        entry.detector_version = __version__
        entry.measurement_fingerprint = fingerprint
        entry.weights_vector = json.dumps(DEFAULT_WEIGHTS, sort_keys=True)
        entry.project_root = root
        entry.file_rel_path = rel
        entry.base_deficit = base
        entry.pattern_penalty = penalty
        entry.provenance_state = "v6"
    tracker._insert(entry)


def _tracker(tmp_path) -> HistoryTracker:
    return HistoryTracker(db_path=tmp_path / "history.db")


def _calibrate(tmp_path, root: str = ROOT):
    return SelfCalibrator(db_path=tmp_path / "history.db").calibrate(project_root=root)


# --- C1 schema ---------------------------------------------------------------


def test_record_writes_v6_provenance(tmp_path):
    source = tmp_path / "proj" / "mod.py"
    source.parent.mkdir()
    source.write_text(
        "def f(x, acc=[]):\n    try:\n        return int(x)\n    except:\n        pass\n",
        encoding="utf-8",
    )
    detector = SlopDetector(read_only=True)
    result = detector.analyze_file(str(source))
    tracker = _tracker(tmp_path)

    tracker.record(result, provenance=measurement_provenance(detector.config, source.parent))

    with sqlite3.connect(tracker.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM history").fetchone())
    assert row["detector_version"] == __version__
    assert row["provenance_state"] == "v6"
    assert row["project_root"] == str(source.parent.resolve())
    assert row["file_rel_path"] == "mod.py"
    assert json.loads(row["weights_vector"]) == detector.config.get_weights()
    assert row["base_deficit"] + row["pattern_penalty"] == pytest.approx(
        row["deficit_score"], abs=1e-3
    )
    assert row["pattern_penalty"] > 0
    assert len(row["measurement_fingerprint"]) == 64


def test_measurement_fingerprint_follows_config(tmp_path):
    other = tmp_path / "cfg.yaml"
    other.write_text(
        "weights: {ldr: 0.5, inflation: 0.2, ddc: 0.2, purity: 0.1}\n", encoding="utf-8"
    )

    first = measurement_provenance(Config(), tmp_path).measurement_fingerprint
    same = measurement_provenance(Config(), tmp_path).measurement_fingerprint
    changed = measurement_provenance(Config(str(other)), tmp_path).measurement_fingerprint

    assert first == same != changed


def test_legacy_database_gains_columns_and_keeps_rows(tmp_path):
    db = tmp_path / "history.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,"
            " file_path TEXT NOT NULL, file_hash TEXT NOT NULL, deficit_score REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO history (timestamp, file_path, file_hash, deficit_score)"
            " VALUES ('2026-01-01T00:00:00', 'a.py', 'h', 40.0)"
        )

    HistoryTracker(db_path=db)

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM history").fetchone())
    assert row["deficit_score"] == 40.0
    assert row["provenance_state"] is None
    assert row["measurement_fingerprint"] is None


# --- C2 / C3 comparability ---------------------------------------------------


def test_legacy_rows_are_never_evidence(tmp_path):
    tracker = _tracker(tmp_path)
    for i in range(6):
        _row(tracker, f"f{i}.py", "2026-01-01T00:00:00", "h1", FLAGGED, provenance=False)
        _row(tracker, f"f{i}.py", "2026-01-02T00:00:00", "h2", CLEAN, provenance=False)

    result = _calibrate(tmp_path)

    assert result.improvement_events == 0
    assert result.legacy_rows_ignored == 12
    assert result.status == "insufficient_data"


def test_runs_with_different_measurement_are_not_paired(tmp_path):
    tracker = _tracker(tmp_path)
    _row(tracker, "a.py", "2026-01-01T00:00:00", "h1", FLAGGED, fingerprint="m1")
    _row(tracker, "a.py", "2026-01-02T00:00:00", "h2", CLEAN, fingerprint="m2")

    result = _calibrate(tmp_path)

    assert result.improvement_events == 0
    assert result.comparable_pairs == 0


def test_projects_do_not_share_evidence(tmp_path):
    tracker = _tracker(tmp_path)
    _row(tracker, "a.py", "2026-01-01T00:00:00", "h1", FLAGGED, root="/other")
    _row(tracker, "a.py", "2026-01-02T00:00:00", "h2", CLEAN, root="/other")

    assert _calibrate(tmp_path).improvement_events == 0
    assert _calibrate(tmp_path, root="/other").improvement_events == 1


# --- C4 / C5 labels ----------------------------------------------------------


def test_improvement_needs_a_changed_file(tmp_path):
    tracker = _tracker(tmp_path)
    # Same hash, score dropped: the detector or config changed, not the code.
    _row(tracker, "a.py", "2026-01-01T00:00:00", "same", FLAGGED, fingerprint="m1")
    _row(tracker, "a.py", "2026-01-02T00:00:00", "same", CLEAN, fingerprint="m1")
    # Changed file, metric-only drop: a real improvement.
    _row(tracker, "b.py", "2026-01-01T00:00:00", "b1", FLAGGED)
    _row(tracker, "b.py", "2026-01-02T00:00:00", "b2", CLEAN)
    # Changed file, only the pattern penalty dropped: not a weight signal.
    _row(tracker, "c.py", "2026-01-01T00:00:00", "c1", CLEAN, penalty=40.0)
    _row(tracker, "c.py", "2026-01-02T00:00:00", "c2", CLEAN, penalty=0.0)
    # Changed file, metric-only deficit barely moved: an edit, not a fix.
    _row(tracker, "d.py", "2026-01-01T00:00:00", "d1", FLAGGED)
    _row(tracker, "d.py", "2026-01-02T00:00:00", "d2", dict(ldr=0.31, inflation=0.9, ddc=0.5))

    result = _calibrate(tmp_path)

    assert result.improvement_events == 1


def test_stable_flag_candidate_once_per_file(tmp_path):
    tracker = _tracker(tmp_path)
    for day in (1, 2, 3):
        _row(tracker, "a.py", f"2026-01-0{day}T00:00:00", "same", FLAGGED)

    result = _calibrate(tmp_path)

    assert result.stable_flag_candidates == 1
    assert result.improvement_events == 0


def test_flag_threshold_is_the_canonical_band(tmp_path):
    # Metric-only deficit between v1's 25 floor and the canonical 30.
    between = dict(ldr=0.55, inflation=0.30, ddc=0.9)
    deficit = metric_only_deficit(**between, weights=DEFAULT_WEIGHTS)
    assert 25.0 < deficit < SUSPICIOUS_AT
    tracker = _tracker(tmp_path)
    _row(tracker, "a.py", "2026-01-01T00:00:00", "same", between)
    _row(tracker, "a.py", "2026-01-02T00:00:00", "same", between)

    assert _calibrate(tmp_path).stable_flag_candidates == 0


# --- C6 / C7 scoring ---------------------------------------------------------


def test_metric_only_deficit_is_the_canonical_gate_with_purity_fixed():
    weights = {"ldr": 0.5, "inflation": 0.2, "ddc": 0.2, "purity": 0.1}
    expected = 100.0 * (
        1.0
        - compute_gqg(
            weights,
            SimpleNamespace(ldr_score=0.4),
            0.5 / 2.0,
            SimpleNamespace(usage_ratio=0.7),
            1.0,
        )
    )

    assert metric_only_deficit(0.4, 0.5, 0.7, weights) == pytest.approx(expected)


def test_grid_learns_three_weights_and_holds_purity(tmp_path):
    calibrator = SelfCalibrator(db_path=tmp_path / "history.db")
    current = {"ldr": 0.40, "inflation": 0.30, "ddc": 0.20, "purity": 0.10}

    candidates = calibrator._grid_search([], [], current)

    assert candidates
    for candidate in candidates:
        assert candidate.w_purity == pytest.approx(0.10)
        total = candidate.w_ldr + candidate.w_inflation + candidate.w_ddc
        assert total == pytest.approx(0.90)


# --- C8 state ----------------------------------------------------------------


def test_default_current_weights_are_the_config_defaults(tmp_path):
    _tracker(tmp_path)

    result = _calibrate(tmp_path)

    assert result.current_weights == DEFAULT_WEIGHTS
    assert result.project_root == ROOT


def test_calibration_without_a_project_root_is_refused(tmp_path):
    _tracker(tmp_path)

    result = SelfCalibrator(db_path=tmp_path / "history.db").calibrate()

    assert result.status == "insufficient_data"
    assert "project root" in result.message


def test_enough_comparable_evidence_produces_a_recommendation(tmp_path):
    tracker = _tracker(tmp_path)
    for i in range(6):
        _row(tracker, f"fixed{i}.py", "2026-01-01T00:00:00", f"a{i}", FLAGGED)
        _row(tracker, f"fixed{i}.py", "2026-01-02T00:00:00", f"b{i}", CLEAN)
        _row(
            tracker,
            f"kept{i}.py",
            "2026-01-01T00:00:00",
            "k",
            dict(ldr=0.45, inflation=0.2, ddc=0.6),
        )
        _row(
            tracker,
            f"kept{i}.py",
            "2026-01-02T00:00:00",
            "k",
            dict(ldr=0.45, inflation=0.2, ddc=0.6),
        )

    result = _calibrate(tmp_path)

    assert result.improvement_events == 6
    assert result.stable_flag_candidates == 6
    assert result.comparable_pairs == 12
    assert result.status in {"ok", "no_change", "insufficient_data"}
    assert result.optimal_weights.get("purity", DEFAULT_WEIGHTS["purity"]) == pytest.approx(
        DEFAULT_WEIGHTS["purity"]
    )


def test_leda_injection_calibrates_the_scanned_project_root(tmp_path, monkeypatch):
    from slop_detector import leda_injection

    seen = {}
    original = SelfCalibrator.calibrate

    def spy(self, *args, **kwargs):
        seen.update(kwargs)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SelfCalibrator, "calibrate", spy)
    monkeypatch.setattr(HistoryTracker, "DEFAULT_DB", tmp_path / "history.db")
    project = tmp_path / "proj"
    project.mkdir()
    source = project / "mod.py"
    source.write_text("def f():\n    return 1\n", encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(project))

    payload = leda_injection.build_leda_injection(result, path=str(project), profile="internal")

    assert seen["project_root"] == str(project.resolve())
    assert "comparable_pairs" in payload["calibration"]
    assert "stable_flag_candidates" in payload["calibration"]


def test_api_history_rows_carry_provenance(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from slop_detector.api.server import create_app

    db = tmp_path / "history.db"
    monkeypatch.setattr(HistoryTracker, "DEFAULT_DB", db)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "requirements.txt").write_text("", encoding="utf-8")
    (project / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    client = TestClient(create_app())

    assert (
        client.post("/analyze/file", json={"file_path": str(project / "mod.py")}).status_code == 200
    )
    assert client.post("/analyze/project", json={"project_path": str(project)}).status_code == 200

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT provenance_state, project_root, file_rel_path FROM history"
        ).fetchall()
    assert rows == [("v6", str(project.resolve()), "mod.py")] * 2


def test_calibrating_a_pre_v6_database_migrates_it_instead_of_failing(tmp_path):
    db = tmp_path / "history.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,"
            " file_path TEXT NOT NULL, file_hash TEXT NOT NULL, deficit_score REAL NOT NULL)"
        )
        conn.execute(
            "INSERT INTO history (timestamp, file_path, file_hash, deficit_score)"
            " VALUES ('2026-01-01T00:00:00', 'a.py', 'h', 40.0)"
        )

    result = SelfCalibrator(db_path=db).calibrate(project_root=ROOT)

    assert result.status == "insufficient_data"
    assert result.legacy_rows_ignored == 1
