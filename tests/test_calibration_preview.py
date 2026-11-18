"""3.16.2 P1: calibration is a preview that writes nothing and says what its evidence is.

Contract:
- reading history for calibration writes nothing, not even a schema
  migration of an older database (the preview opens it read-only);
- two runs are comparable only when the same parser measured them: a JS file
  read by the regex fallback and then by tree-sitter is not a pair;
- scanning the same bytes again adds no evidence: a state is counted once
  per file, rule, state and bytes;
- a pair with a metric that was not measured (NULL in history) is never a
  weights-search event; its rule evidence is still reported;
- `--self-calibrate --json` prints the preview (current and recommended
  weights, evidence states, unchanged-warning rates) with `applied: false`;
- no option or CI environment makes calibration write: `--apply-calibration`
  stays refused (exit 2), `--read-only` refuses `--self-calibrate`;
- the screen shows the evidence states per rule and calls the per-rule
  number what it is (an unchanged-warning rate, not a false-positive rate),
  without advising to suppress or weaken a rule.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from slop_detector import __version__
from slop_detector.cli import main
from slop_detector.config import Config
from slop_detector.history import HistoryEntry, HistoryTracker
from slop_detector.ml import calibration_evidence as ev
from slop_detector.ml.self_calibrator import CalibrationResult, SelfCalibrator

ROOT = "/proj"
WEIGHTS = Config.DEFAULT_CONFIG["weights"]
CONFIG = "weights:\n  ldr: 0.40\n  inflation: 0.30\n  ddc: 0.20\n  purity: 0.10\n"
SLOP = "def f(x, acc=[]):\n    try:\n        return int(x)\n    except:\n        pass\n"
FLAGGED = dict(ldr=0.30, inflation=0.9, ddc=0.5)


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    db = tmp_path / "home" / ".slop-detector" / "history.db"
    monkeypatch.setattr(HistoryTracker, "DEFAULT_DB", db)
    monkeypatch.setattr(SelfCalibrator, "DEFAULT_DB", db)
    monkeypatch.setenv("COLUMNS", "200")
    return db


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".slopconfig.yaml").write_text(CONFIG, encoding="utf-8")
    for i in range(3):
        (root / f"mod_{i}.py").write_text(SLOP.replace("def f", f"def f{i}"), encoding="utf-8")
    monkeypatch.chdir(root)
    return root


def _row(
    tracker,
    rel,
    ts,
    file_hash,
    *,
    fired=None,
    metrics=FLAGGED,
    parser="python_ast",
    language="python",
    withheld=None,
    fingerprint="m1",
):
    entry = HistoryEntry(
        timestamp=ts,
        file_path=f"{ROOT}/{rel}",
        file_hash=file_hash,
        deficit_score=50.0,
        ldr_score=metrics["ldr"] if metrics else None,
        inflation_score=metrics["inflation"] if metrics else None,
        ddc_usage_ratio=metrics["ddc"] if metrics else None,
        pattern_count=sum((fired or {}).values()),
        fired_rules=json.dumps(fired) if fired else None,
        withheld_evidence=json.dumps(
            withheld or {"suppressed": [], "unmeasured": [], "masked": [], "ignored": []}
        ),
    )
    entry.detector_version = __version__
    entry.measurement_fingerprint = fingerprint
    entry.weights_vector = json.dumps(WEIGHTS, sort_keys=True)
    entry.project_root = ROOT
    entry.file_rel_path = rel
    entry.provenance_state = "v7"
    entry.language = language
    entry.parser_mode = parser
    tracker._insert(entry)


def _calibrate(db: Path) -> CalibrationResult:
    return SelfCalibrator(db_path=db).calibrate(project_root=ROOT)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(root: Path):
    return {p.relative_to(root).as_posix(): _digest(p) for p in root.rglob("*") if p.is_file()}


# --- reading writes nothing -------------------------------------------------


def test_calibration_reads_an_older_database_without_changing_it(tmp_path):
    db = tmp_path / "history.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,"
            " file_path TEXT NOT NULL, file_hash TEXT NOT NULL, deficit_score REAL NOT NULL,"
            " ldr_score REAL NOT NULL DEFAULT 0.0)"
        )
        conn.execute(
            "INSERT INTO history (timestamp, file_path, file_hash, deficit_score)"
            " VALUES ('2026-01-01T00:00:00', 'a.py', 'h', 40.0)"
        )
    before = _digest(db)

    result = _calibrate(db)

    assert result.legacy_rows_ignored == 1
    assert _digest(db) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["history.db"]


def test_calibration_reads_a_current_database_without_changing_it(tmp_path):
    db = tmp_path / "history.db"
    tracker = HistoryTracker(db_path=db)
    for i in range(3):
        _row(tracker, "a.py", f"2026-11-0{i + 1}", "h1", fired={"bare_except": 1})
    before = _digest(db)

    _calibrate(db)

    assert _digest(db) == before


# --- what counts as evidence ------------------------------------------------


def test_runs_read_by_different_parsers_are_not_paired(tmp_path):
    tracker = HistoryTracker(db_path=tmp_path / "history.db")
    _row(
        tracker,
        "b.js",
        "2026-11-01",
        "h1",
        fired={"js_todo": 1},
        metrics=None,
        language="javascript",
        parser="regex_fallback",
    )
    _row(
        tracker,
        "b.js",
        "2026-11-02",
        "h2",
        metrics=None,
        language="javascript",
        parser="tree_sitter_ast",
    )

    result = _calibrate(tmp_path / "history.db")

    assert result.comparable_pairs == 0
    assert result.evidence_states == {}


def test_scanning_the_same_bytes_again_adds_no_evidence(tmp_path):
    tracker = HistoryTracker(db_path=tmp_path / "history.db")
    declared = {
        "suppressed": [
            {
                "rule": "bare_except",
                "line": 4,
                "state": ev.USER_DECLARED_FALSE_POSITIVE,
                "reason_sha256": "0" * 64,
            }
        ],
        "unmeasured": [],
        "masked": [],
        "ignored": [],
    }
    for i in range(6):
        _row(tracker, "a.py", f"2026-11-0{i + 1}", "h1", fired={"mutable_default_arg": 1})
    _row(tracker, "b.py", "2026-11-01", "g1", fired={"bare_except": 1})
    for i in range(4):
        _row(tracker, "b.py", f"2026-11-0{i + 2}", "g2", withheld=declared)

    result = _calibrate(tmp_path / "history.db")

    assert result.comparable_pairs == 5 + 4
    assert result.evidence_states["mutable_default_arg"] == {ev.UNCHANGED_WARNING: 1}
    assert result.evidence_states["bare_except"] == {ev.USER_DECLARED_FALSE_POSITIVE: 1}
    assert len(result.declared_false_positives) == 1


def test_a_pair_with_an_unmeasured_metric_is_never_learned(tmp_path):
    tracker = HistoryTracker(db_path=tmp_path / "history.db")
    for i in range(6):
        rel = f"m{i}.py"
        _row(
            tracker,
            rel,
            "2026-11-01",
            "h1",
            fired={"bare_except": 1},
            metrics=dict(FLAGGED, ldr=None),
        )
        _row(tracker, rel, "2026-11-02", "h1", fired={"bare_except": 1})
        _row(
            tracker,
            f"r{i}.rs",
            "2026-11-01",
            "k1",
            fired={"rust_todo": 1},
            metrics=None,
            language="rust",
            parser="token_scanner",
        )
        _row(
            tracker,
            f"r{i}.rs",
            "2026-11-02",
            "k2",
            metrics=None,
            language="rust",
            parser="token_scanner",
        )

    result = _calibrate(tmp_path / "history.db")

    assert result.improvement_events == 0 and result.stable_flag_candidates == 0
    assert result.unmeasured_metric_pairs == 12
    assert result.evidence_states["bare_except"] == {ev.UNCHANGED_WARNING: 6}
    assert result.evidence_states["rust_todo"] == {ev.VERIFIED_FIX: 6}


# --- the preview ------------------------------------------------------------


def _scan_twice(project: Path, capsys):
    main([str(project), "--json", "--no-color"])
    main([str(project), "--json", "--no-color"])
    capsys.readouterr()


def test_the_json_preview_says_it_applied_nothing_and_writes_nothing(project, history_db, capsys):
    _scan_twice(project, capsys)
    tree, db = _tree(project), _digest(history_db)

    code = main(["--self-calibrate", "--json", str(project)])

    preview = json.loads(capsys.readouterr().out)
    assert code == 1  # three files are not enough evidence: the same exit as the screen
    assert preview["applied"] is False
    assert preview["status"] == "insufficient_data"
    assert preview["evidence_states"]["mutable_default_arg"] == {ev.UNCHANGED_WARNING: 3}
    for key in (
        "current_weights",
        "optimal_weights",
        "unchanged_warning_rate",
        "declared_false_positives",
        "comparable_pairs",
        "unmeasured_metric_pairs",
    ):
        assert key in preview
    assert "per_rule_fp_rates" not in preview  # the misnamed alias stays out of new output
    assert preview["candidate_gap_passed"] is False
    assert preview["externally_validated"] == "not_tested"
    assert _tree(project) == tree and _digest(history_db) == db


@pytest.mark.parametrize("environment", [{}, {"CI": "true"}, {"GITHUB_ACTIONS": "true"}])
@pytest.mark.parametrize("extra", [[], ["--json"]])
def test_no_option_or_ci_environment_lets_calibration_write(
    project, history_db, capsys, monkeypatch, environment, extra
):
    _scan_twice(project, capsys)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    tree, db = _tree(project), _digest(history_db)

    assert main(["--self-calibrate", "--apply-calibration", *extra, str(project)]) == 2
    assert main(["--read-only", "--self-calibrate", *extra, str(project)]) == 2
    capsys.readouterr()
    assert _tree(project) == tree and _digest(history_db) == db


# --- the screen -------------------------------------------------------------


def _reported() -> CalibrationResult:
    return CalibrationResult(
        status="insufficient_data",
        project_root=ROOT,
        current_weights=dict(WEIGHTS),
        per_rule_fp_rates={"bare_except": 0.8},
        unchanged_warning_rate={"bare_except": 0.8},
        evidence_states={
            "bare_except": {ev.UNCHANGED_WARNING: 4, ev.USER_DECLARED_FALSE_POSITIVE: 1},
            "mutable_default_arg": {ev.VERIFIED_FIX: 2, ev.USER_SUPPRESSED_UNVERIFIED: 1},
        },
        declared_false_positives=[
            {
                "rule": "bare_except",
                "file": "a.py",
                "line": 4,
                "file_hash": "h",
                "state": ev.USER_DECLARED_FALSE_POSITIVE,
                "reason_sha256": "0" * 64,
                "measurement_fingerprint": "m",
            }
        ],
        message="Need more evidence.",
    )


def _recommended() -> CalibrationResult:
    """A result the gap test passed: status ok, nothing validated it."""
    result = _reported()
    result.status = "ok"
    result.candidate_gap_passed = True
    result.confidence_gap = 0.15
    result.optimal_weights = {"ldr": 0.2, "inflation": 0.6, "ddc": 0.1, "purity": 0.1}
    return result


# "Verified fix" read as a proven repair: the screen says what the state is.
FORBIDDEN = (
    "FP Rate",
    "HIGH NOISE",
    "MOD NOISE",
    "candidates for suppression",
    "Noisy",
    "Verified fix",
)
RESOLVED = "Warning resolved - code correctness not verified"
NOT_VALIDATED = "candidate gap passed; detection accuracy not validated (not_tested)"


def test_the_screen_shows_the_evidence_states_and_no_false_positive_claim(
    project, history_db, capsys, monkeypatch
):
    monkeypatch.setattr(SelfCalibrator, "calibrate", lambda self, *a, **k: _reported())
    main(["--self-calibrate", "--no-color", str(project)])
    out = " ".join(capsys.readouterr().out.split())

    for label in (
        RESOLVED,
        "Unchanged warning",
        "Suppressed (unverified)",
        "Declared false positive",
        "Unchanged-warning rate",
    ):
        assert label in out, label
    assert "bare_except" in out and "mutable_default_arg" in out
    assert NOT_VALIDATED not in out  # the gap test did not pass here
    for word in FORBIDDEN:
        assert word not in out, word


def test_an_ok_screen_says_the_gap_passed_not_that_detection_improved(
    project, history_db, capsys, monkeypatch
):
    monkeypatch.setattr(SelfCalibrator, "calibrate", lambda self, *a, **k: _recommended())
    assert main(["--self-calibrate", "--no-color", str(project)]) == 0  # the exit is unchanged
    out = " ".join(capsys.readouterr().out.split())

    assert NOT_VALIDATED in out


def test_the_plain_report_shows_the_same(capsys):
    from slop_detector.cli_history import _print_calibration_plain

    _print_calibration_plain(_reported(), dict(WEIGHTS))
    out = capsys.readouterr().out

    assert "evidence bare_except: unchanged_warning=4 user_declared_false_positive=1" in out
    assert "unchanged_warning_rate bare_except: 80%" in out
    assert f"verified_fix = {RESOLVED}" in out
    assert "candidate_gap_passed=False externally_validated=not_tested" in out
    for word in FORBIDDEN:
        assert word.lower() not in out.lower(), word
