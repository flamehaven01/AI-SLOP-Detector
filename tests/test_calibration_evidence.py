"""3.16.2 P0: where a judgment about a finding comes from, and how much it is worth.

Four evidence states per rule, from two comparable runs of one file:

- VERIFIED_FIX: the file changed and the rule stopped firing while it was
  measured, not suppressed, not masked and not ignored. It shows the warning
  was resolved under the same measurement; it does not prove the code works.
- UNCHANGED_WARNING: the rule fires on the same bytes again. A warning nobody
  acted on; not a false positive.
- USER_SUPPRESSED_UNVERIFIED: a plain `# slop-disable` hides it now. Not a
  false positive either: the user may have accepted the risk.
- USER_DECLARED_FALSE_POSITIVE: an `fp:` declaration hides it now. The user
  says it is a false positive; nothing verified it.

None of these is a learning label in 3.16.2: the weights search still learns
from the metric-only labels it had, and the evidence states are reported
beside them. A judgment is bound to the file, the line, the rule, the hash
of the bytes it was made on and the measurement fingerprint; the reason text
of a declaration is never stored.
"""

from __future__ import annotations

import json
import sqlite3

from slop_detector.core import SlopDetector
from slop_detector.history import HistoryTracker, measurement_provenance
from slop_detector.ml import calibration_evidence as ev
from slop_detector.ml.self_calibrator import SelfCalibrator

REASON = "External callback contract requires this handler"


def _row(file_hash, fired=None, suppressed=(), unmeasured=(), masked=(), ignored=()):
    return {
        "file_hash": file_hash,
        "fired_rules": dict(fired or {}),
        "withheld": {
            "suppressed": list(suppressed),
            "unmeasured": list(unmeasured),
            "masked": list(masked),
            "ignored": list(ignored),
        },
    }


def _states(now, nxt):
    return {r["rule"]: r["state"] for r in ev.classify_pair(now, nxt)}


def _sup(rule, state=ev.USER_SUPPRESSED_UNVERIFIED, line=5):
    item = {"rule": rule, "line": line, "state": state}
    if state == ev.USER_DECLARED_FALSE_POSITIVE:
        item["reason_sha256"] = "0" * 64
    return item


def test_a_rule_that_stops_firing_on_a_changed_file_is_a_verified_fix():
    assert _states(_row("h1", {"bare_except": 1}), _row("h2")) == {"bare_except": ev.VERIFIED_FIX}


def test_a_rule_that_fires_again_on_the_same_bytes_is_an_unchanged_warning():
    now = _row("h1", {"bare_except": 1})
    assert _states(now, _row("h1", {"bare_except": 1})) == {"bare_except": ev.UNCHANGED_WARNING}
    # the file changed and the rule still fires: no judgment either way
    assert _states(now, _row("h2", {"bare_except": 1})) == {}


def test_a_suppressed_rule_is_the_users_judgment_never_a_fix():
    now = _row("h1", {"bare_except": 1})
    plain = _row("h2", suppressed=[_sup("bare_except")])
    declared = _row("h2", suppressed=[_sup("bare_except", ev.USER_DECLARED_FALSE_POSITIVE)])
    assert _states(now, plain) == {"bare_except": ev.USER_SUPPRESSED_UNVERIFIED}
    assert _states(now, declared) == {"bare_except": ev.USER_DECLARED_FALSE_POSITIVE}


def test_a_rule_that_was_not_looked_at_is_no_fix():
    now = _row("h1", {"bare_except": 1})
    for withheld in (
        _row("h2", unmeasured=["bare_except"]),
        _row("h2", masked=["bare_except"]),
        _row("h2", ignored=["bare_except"]),
        _row("h2", ignored=["all"]),
    ):
        assert _states(now, withheld) == {}, withheld["withheld"]


def test_a_declaration_counts_only_for_the_bytes_it_was_made_on():
    """Made on h2, the declaration is evidence for h2; on h3 the rule fires
    again without it, so the earlier declaration says nothing about h3."""
    declared = _row("h2", suppressed=[_sup("bare_except", ev.USER_DECLARED_FALSE_POSITIVE)])
    assert _states(declared, _row("h3", {"bare_except": 1})) == {}
    records = ev.classify_pair(_row("h1", {"bare_except": 1}), declared)
    assert records[0]["file_hash"] == "h2" and records[0]["line"] == 5


def test_a_row_without_a_withheld_record_shows_no_fix():
    """Rows recorded before 3.16.2 cannot show the rule was looked at."""
    legacy = {"file_hash": "h2", "fired_rules": {}, "withheld": None}
    assert _states(_row("h1", {"bare_except": 1}), legacy) == {}


def test_a_declaration_on_the_rule_is_its_state_beside_a_plain_suppression():
    both = _row(
        "h2",
        suppressed=[
            _sup("bare_except", line=4),
            _sup("bare_except", ev.USER_DECLARED_FALSE_POSITIVE, line=9),
        ],
    )
    assert _states(_row("h1", {"bare_except": 2}), both) == {
        "bare_except": ev.USER_DECLARED_FALSE_POSITIVE
    }


# --- recorded by a real scan -------------------------------------------------

CODE = """def load(path):
    try:
        return open(path).read()
    {directive}
    except:
        return None
"""
NONE = ""
PLAIN = "# slop-disable-next-line bare_except"
DECLARED = PLAIN + " fp: " + REASON


def _scan_and_record(tmp_path, db, directive):
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    path = project / "loader.py"
    path.write_text(CODE.format(directive=directive), encoding="utf-8")
    detector = SlopDetector(read_only=True)
    result = detector.analyze_file(str(path))
    HistoryTracker(db_path=db).record(
        result, provenance=measurement_provenance(detector.config, project)
    )
    return result


def test_a_scan_records_what_it_withheld_and_never_the_reason(tmp_path):
    db = tmp_path / "history.db"
    _scan_and_record(tmp_path, db, DECLARED)
    _scan_and_record(tmp_path, db, PLAIN)
    with sqlite3.connect(db) as conn:
        rows = [
            json.loads(r[0])
            for r in conn.execute("SELECT withheld_evidence FROM history ORDER BY id")
        ]
    assert [s["state"] for s in rows[0]["suppressed"]] == [ev.USER_DECLARED_FALSE_POSITIVE]
    assert [s["state"] for s in rows[1]["suppressed"]] == [ev.USER_SUPPRESSED_UNVERIFIED]
    assert rows[0]["suppressed"][0]["rule"] == "bare_except"
    assert len(rows[0]["suppressed"][0]["reason_sha256"]) == 64
    assert REASON.encode("utf-8") not in db.read_bytes()


def test_an_older_database_gains_the_column_and_keeps_its_rows(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT,
               timestamp TEXT NOT NULL, file_path TEXT NOT NULL, file_hash TEXT NOT NULL,
               deficit_score REAL NOT NULL, git_commit TEXT, git_branch TEXT);
               INSERT INTO history (timestamp, file_path, file_hash, deficit_score)
               VALUES ('2026-01-01T00:00:00', '/p/a.py', 'h0', 42.0);"""
        )
    HistoryTracker(db_path=db)
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT file_hash, deficit_score, withheld_evidence FROM history"
        ).fetchone()
    assert row == ("h0", 42.0, None)


def test_the_calibration_report_states_evidence_per_rule_beside_its_old_fields(tmp_path):
    """The rule fires, then the user declares it a false positive: one
    declared state, bound to file, line, bytes and measurement."""
    db = tmp_path / "history.db"
    first = _scan_and_record(tmp_path, db, NONE)
    second = _scan_and_record(tmp_path, db, DECLARED)
    assert [i.pattern_id for i in first.pattern_issues].count("bare_except") == 1
    root = str((tmp_path / "proj").resolve())
    result = SelfCalibrator(db_path=db).calibrate(project_root=root)
    assert result.evidence_states == {"bare_except": {ev.USER_DECLARED_FALSE_POSITIVE: 1}}
    (declared,) = result.declared_false_positives
    assert declared["file"] == "loader.py" and declared["line"] == 5
    assert declared["rule"] == "bare_except" and len(declared["reason_sha256"]) == 64
    assert declared["file_hash"] != "" and declared["measurement_fingerprint"]
    assert second.suppression_ledger[0].reason_sha256 == declared["reason_sha256"]
    assert REASON not in json.dumps(declared)
    # the old fields keep their meaning; the new one names what it counts
    assert result.unchanged_warning_rate == result.per_rule_fp_rates


def test_suppressions_change_no_learning_label(tmp_path):
    """The weights search learns from metric-only labels; the same history
    with no, a plain or a declared suppression gives the same label counts."""
    counts = []
    for directive in (NONE, PLAIN, DECLARED):
        db = tmp_path / f"h{len(counts)}.db"
        _scan_and_record(tmp_path, db, directive)
        _scan_and_record(tmp_path, db, directive)
        r = SelfCalibrator(db_path=db).calibrate(project_root=str((tmp_path / "proj").resolve()))
        counts.append((r.improvement_events, r.stable_flag_candidates, r.comparable_pairs))
    assert counts[0] == counts[1] == counts[2]
