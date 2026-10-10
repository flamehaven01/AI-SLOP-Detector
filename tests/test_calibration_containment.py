"""Legacy self-calibration may report, but it may not change anyone's weights.

Measured on 29,303 real history rows: 80% of the "improvement" events had an
unchanged file (the detector or its configuration changed, not the code), 61%
of flagged rows were flagged by pattern penalties the weights cannot move, and
history was scoped by the working directory, so projects scanned from one
directory shared it. A recommendation built on that evidence is not one to
apply. With Calibration v2 (v3.10) the contract is:

- scans keep recording history, now with measurement provenance (schema v6),
  and never run calibration on their own;
- `--self-calibrate` reports on the comparable runs of the scanned project
  root, says legacy rows are not evidence, and is advisory;
- `--self-calibrate --apply-calibration` writes nothing and exits non-zero.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

import pytest

from slop_detector.cli import main
from slop_detector.history import HistoryTracker
from slop_detector.ml.self_calibrator import CalibrationResult, SelfCalibrator

CONFIG = "weights:\n  ldr: 0.40\n  inflation: 0.30\n  ddc: 0.20\n  purity: 0.10\n"
SLOP = "def f(x, acc=[]):\n    try:\n        return int(x)\n    except:\n        pass\n"
CLEAN = "def add(a, b):\n    return a + b\n"


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    db = tmp_path / "home" / ".slop-detector" / "history.db"
    monkeypatch.setattr(HistoryTracker, "DEFAULT_DB", db)
    monkeypatch.setattr(SelfCalibrator, "DEFAULT_DB", db)
    return db


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".slopconfig.yaml").write_text(CONFIG, encoding="utf-8")
    for i in range(10):
        (root / f"mod_{i}.py").write_text(SLOP.replace("def f", f"def f{i}"), encoding="utf-8")
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def calibrate_calls(monkeypatch) -> List[int]:
    calls: List[int] = []
    original = SelfCalibrator.calibrate

    def spy(self, *args, **kwargs):
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SelfCalibrator, "calibrate", spy)
    return calls


def _rows(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]


def _scan(project: Path) -> int:
    return main([str(project), "--json", "--no-color"])


def test_scans_never_run_calibration_at_the_milestone(project, history_db, calibrate_calls, capsys):
    """10 files scanned twice, 5 of them fixed in between: the old milestone."""
    _scan(project)
    for i in range(5):
        (project / f"mod_{i}.py").write_text(CLEAN, encoding="utf-8")
    _scan(project)
    capsys.readouterr()
    assert calibrate_calls == []
    assert (project / ".slopconfig.yaml").read_text(encoding="utf-8") == CONFIG


def test_scans_still_record_history(project, history_db, capsys):
    """Preservation: containment stops calibration, not the history it may use later."""
    _scan(project)
    _scan(project)
    capsys.readouterr()
    assert _rows(history_db) == 20


def test_self_calibrate_says_legacy_rows_are_not_evidence(project, history_db, capsys):
    main(["--self-calibrate", "--no-color"])
    err = capsys.readouterr().err
    assert "legacy history rows are not evidence" in err
    assert "advisory" in err


def test_scans_record_provenance_for_the_scanned_root(project, history_db, capsys):
    _scan(project)
    capsys.readouterr()
    with sqlite3.connect(history_db) as conn:
        rows = conn.execute(
            "SELECT provenance_state, project_root, file_rel_path, measurement_fingerprint"
            " FROM history"
        ).fetchall()
    assert {row[0] for row in rows} == {"v6"}
    assert {row[1] for row in rows} == {str(project.resolve())}
    assert sorted(row[2] for row in rows) == sorted(f"mod_{i}.py" for i in range(10))
    assert len({row[3] for row in rows}) == 1


def test_self_calibrate_reads_the_comparable_runs_of_this_root(project, history_db, capsys):
    _scan(project)
    _scan(project)
    capsys.readouterr()
    main(["--self-calibrate", "--no-color", str(project)])
    out = " ".join(capsys.readouterr().out.split())
    # Two scans of 10 unchanged files under one measurement: 10 comparable pairs.
    assert "from 10 comparable run pairs" in out


def test_apply_calibration_writes_nothing_and_fails(project, history_db, monkeypatch, capsys):
    """Even a confident result: the evidence, not the confidence, is the problem."""
    confident = CalibrationResult(
        status="ok",
        current_weights={"ldr": 0.4, "inflation": 0.3, "ddc": 0.2, "purity": 0.1},
        optimal_weights={"ldr": 0.3, "inflation": 0.3, "ddc": 0.25, "purity": 0.15},
        confidence_gap=0.5,
        message="ok",
    )
    monkeypatch.setattr(SelfCalibrator, "calibrate", lambda self, *a, **k: confident)
    code = main(["--self-calibrate", "--apply-calibration", "--no-color"])
    err = capsys.readouterr().err
    assert (project / ".slopconfig.yaml").read_text(encoding="utf-8") == CONFIG
    assert code != 0
    assert "--apply-calibration is disabled" in err


def test_no_config_writer_remains():
    assert not hasattr(SelfCalibrator, "apply_to_config")
