"""3.16.2 P1: a verification oracle for self-calibration.

Two parts, both with a known answer:

1. Counterexamples, one file each, in one history: a declared false positive,
   a plain suppression, a real fix, an unresolved real warning, a
   configuration change, a parser change, the same bytes scanned five times
   and a file gutted to a stub. The exact events and evidence states are
   asserted. An unresolved real warning is still a weights-search
   "stable flag" (the false-positive side): the evidence state reports it as
   an unchanged warning, never as a false positive.
2. Held out (tests/calibration_oracle.py): synthetic files whose truth is a
   weight vector; two thirds are calibrated on, one third is scored. With
   honest labels the learner's winner is the true weights; when real slop is
   left unfixed its labels say the opposite of the truth, the winner is worse
   than the current weights on the held-out files, and the confidence gate
   withholds it. False positive and false negative rates are each compared.
"""

from __future__ import annotations

import json

from slop_detector import __version__
from slop_detector.config import Config
from slop_detector.history import HistoryEntry, HistoryTracker
from slop_detector.ml import calibration_evidence as ev
from slop_detector.ml.self_calibrator import SelfCalibrator
from tests.calibration_oracle import TRUE_WEIGHTS, run_oracle

ROOT = "/proj"
WEIGHTS = Config.DEFAULT_CONFIG["weights"]
FLAGGED = (0.30, 0.9, 0.5)  # metric-only deficit 55 under the defaults
CLEAN = (0.95, 0.0, 1.0)  # 2
NOTHING = {"suppressed": [], "unmeasured": [], "masked": [], "ignored": []}


def _withheld(**changes):
    return dict(NOTHING, **changes)


def _sup(rule, state, line=4):
    item = {"rule": rule, "line": line, "state": state}
    if state == ev.USER_DECLARED_FALSE_POSITIVE:
        item["reason_sha256"] = "0" * 64
    return item


def _row(tracker, rel, ts, file_hash, metrics, fired=None, withheld=NOTHING,
         fingerprint="m1", parser="python_ast"):
    entry = HistoryEntry(
        timestamp=ts,
        file_path=f"{ROOT}/{rel}",
        file_hash=file_hash,
        deficit_score=50.0,
        ldr_score=metrics[0],
        inflation_score=metrics[1],
        ddc_usage_ratio=metrics[2],
        pattern_count=sum((fired or {}).values()),
        fired_rules=json.dumps(fired) if fired else None,
        withheld_evidence=json.dumps(withheld),
    )
    entry.detector_version = __version__
    entry.measurement_fingerprint = fingerprint
    entry.weights_vector = json.dumps(WEIGHTS, sort_keys=True)
    entry.project_root = ROOT
    entry.file_rel_path = rel
    entry.provenance_state = "v7"
    entry.parser_mode = parser
    tracker._insert(entry)


def _counterexamples(tracker):
    t1, t2 = "2026-11-01T00:00:00", "2026-11-02T00:00:00"
    declared = _withheld(suppressed=[_sup("bare_except", ev.USER_DECLARED_FALSE_POSITIVE)])
    plain = _withheld(suppressed=[_sup("broad_except", ev.USER_SUPPRESSED_UNVERIFIED)])
    # a declared false positive: the comment changes the bytes, not the metrics
    _row(tracker, "declared.py", t1, "a", FLAGGED, {"bare_except": 1})
    _row(tracker, "declared.py", t2, "b", FLAGGED, withheld=declared)
    # a plain suppression: the user's judgment, not a false positive
    _row(tracker, "plain.py", t1, "a", FLAGGED, {"broad_except": 1})
    _row(tracker, "plain.py", t2, "b", FLAGGED, withheld=plain)
    # a real fix
    _row(tracker, "fixed.py", t1, "a", FLAGGED, {"pass_placeholder": 1})
    _row(tracker, "fixed.py", t2, "b", CLEAN)
    # an unresolved real warning
    _row(tracker, "unresolved.py", t1, "a", FLAGGED, {"mutable_default_arg": 1})
    _row(tracker, "unresolved.py", t2, "a", FLAGGED, {"mutable_default_arg": 1})
    # a configuration change between the runs: not comparable
    _row(tracker, "config.py", t1, "a", FLAGGED, {"todo_comment": 1}, fingerprint="m1")
    _row(tracker, "config.py", t2, "b", CLEAN, fingerprint="m2")
    # a parser change between the runs: not comparable
    _row(tracker, "parser.js", t1, "a", (None,) * 3, {"js_var_usage": 1}, parser="regex_fallback")
    _row(tracker, "parser.js", t2, "b", (None,) * 3, parser="tree_sitter_ast")
    # the same bytes scanned five times
    for day in range(1, 6):
        _row(tracker, "repeated.py", f"2026-11-0{day}T00:00:00", "a", FLAGGED,
             {"ignored_parameter": 1})
    # gutted to a stub: no pattern ran, no LDR, so nothing stopped firing
    _row(tracker, "gutted.py", t1, "a", FLAGGED, {"nested_complexity": 1})
    _row(tracker, "gutted.py", t2, "b", (None, 0.0, 1.0), withheld=_withheld(unmeasured=["all"]))


def test_each_counterexample_gives_exactly_its_known_events_and_states(tmp_path):
    db = tmp_path / "history.db"
    _counterexamples(HistoryTracker(db_path=db))

    result = SelfCalibrator(db_path=db).calibrate(project_root=ROOT)

    observed = {
        "comparable_pairs": result.comparable_pairs,
        "unmeasured_metric_pairs": result.unmeasured_metric_pairs,
        "improvement_events": result.improvement_events,
        "stable_flag_candidates": result.stable_flag_candidates,
        "evidence_states": result.evidence_states,
        "declared": [(d["file"], d["rule"], d["line"]) for d in result.declared_false_positives],
    }
    assert observed == {
        # declared, plain, fixed, unresolved, repeated (4), gutted; not config, not parser
        "comparable_pairs": 9,
        "unmeasured_metric_pairs": 1,  # gutted
        "improvement_events": 1,  # fixed
        "stable_flag_candidates": 2,  # unresolved, repeated (once)
        "evidence_states": {
            "bare_except": {ev.USER_DECLARED_FALSE_POSITIVE: 1},
            "broad_except": {ev.USER_SUPPRESSED_UNVERIFIED: 1},
            "pass_placeholder": {ev.VERIFIED_FIX: 1},
            "mutable_default_arg": {ev.UNCHANGED_WARNING: 1},
            "ignored_parameter": {ev.UNCHANGED_WARNING: 1},
        },
        "declared": [("declared.py", "bare_except", 4)],
    }


def _oracle(tmp_path, fix_rate, seed=7):
    return run_oracle(tmp_path / "history.db", seed=seed, files=300, fix_rate=fix_rate,
                      declare_rate=0.3)


def test_the_oracle_is_deterministic(tmp_path):
    first = _oracle(tmp_path / "a", 1.0)
    second = _oracle(tmp_path / "b", 1.0)
    assert first == second


def test_with_honest_labels_the_winner_is_the_truth_on_held_out_files(tmp_path):
    run = _oracle(tmp_path, fix_rate=1.0)  # every flagged real slop is fixed

    assert run.labels.get("unresolved_real_warning", 0) == 0
    assert run.winner == TRUE_WEIGHTS
    assert run.after_winner == {"fp_rate": 0.0, "fn_rate": 0.0}
    assert run.before["fp_rate"] > 0  # the current weights are wrong somewhere


# Unfixed real slop is a "stable flag": the learner reads it as a false
# positive and lowers the weights that flagged it. Measured over 20 seeds per
# fix rate (300 files, .internal evidence, 2026-11-17): the winner was the
# truth in 20/20 runs at fix rate 1.0, 2/20 at 0.4 and 0/20 at 0.1, where its
# held-out false negative rate averaged 0.192 against 0.079 for the current
# weights. The two seeds below are that finding, each on its own axis.


def test_a_misled_winner_is_withheld_by_the_confidence_gate(tmp_path):
    run = _oracle(tmp_path, fix_rate=0.1, seed=1)  # nine in ten flagged real slop left

    assert run.labels["unresolved_real_warning"] > run.labels["fixed"]
    assert run.after_winner["fn_rate"] > run.before["fn_rate"]
    assert run.after_winner["fp_rate"] > run.before["fp_rate"]
    assert run.status != "ok" and run.after_recommended == run.before


def test_the_oracle_catches_a_recommendation_that_trades_misses_for_quiet(tmp_path):
    """The gate tests how far the best candidate is from the second, not what
    its labels mean: here it passes a recommendation with fewer false
    positives and more false negatives on held-out files. Only the two rates
    compared apart show it; their sum improves."""
    run = _oracle(tmp_path, fix_rate=0.1, seed=6)

    assert run.status == "ok"
    assert run.after_recommended["fp_rate"] < run.before["fp_rate"]
    assert run.after_recommended["fn_rate"] > run.before["fn_rate"]
    assert sum(run.after_recommended.values()) < sum(run.before.values())
