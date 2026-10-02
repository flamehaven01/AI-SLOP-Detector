"""Controls for the ML model contract: explicit, JSON-only, fail-closed.

The detector never reads a model it was not given. A model is a versioned JSON
threshold classifier; nothing at runtime unpickles anything. Training and
scoring share one feature extractor.
"""

from __future__ import annotations

import ast
import json
import math
import os
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector
from slop_detector.ml.scorer import MLScorer

REPO = Path(__file__).resolve().parents[1]
REPO_SRC = str(REPO / "src")

# The contract, written out independently of the implementation.
FEATURES = [
    "ldr_score",
    "inflation_score",
    "ddc_score",
    "pattern_count_critical",
    "pattern_count_high",
    "pattern_count_medium",
    "pattern_count_low",
    "god_function_count",
    "dead_code_count",
    "deep_nesting_count",
    "avg_complexity",
    "cross_language_patterns",
    "hallucination_count",
    "total_lines",
    "logic_lines",
    "empty_lines",
]
MODEL_TYPE = "threshold_classifier_gaussian_nb"


def _model(**overrides) -> dict:
    stats = {
        "good": {f: {"mean": 0.5, "stdev": 1.0} for f in FEATURES},
        "bad": {f: {"mean": 2.0, "stdev": 1.5} for f in FEATURES},
    }
    model = {
        "schema_version": 1,
        "model_type": MODEL_TYPE,
        "features": list(FEATURES),
        "class_priors": {"good": 0.5, "bad": 0.5},
        "class_stats": stats,
        "thresholds": {f: 1.25 for f in FEATURES},
        "feature_importance": {f: 0.3 for f in FEATURES},
    }
    model.update(overrides)
    return model


def _load_status(path):
    """(scorer, status) or an assertion failure, never a raw exception."""
    try:
        return MLScorer.from_model_with_status(path)
    except Exception as exc:  # the contract is: report, do not raise
        raise AssertionError(f"from_model_with_status raised {exc!r}") from exc


def _threshold_model():
    try:
        import slop_detector.ml.threshold_model as module
    except ImportError as exc:
        raise AssertionError("slop_detector.ml.threshold_model is missing") from exc
    return module


def _write_json(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


class _Marker:
    """Unpickling this creates a file: proof that a pickle was deserialized."""

    def __init__(self, target: str) -> None:
        self.target = target

    def __reduce__(self):
        return (open, (self.target, "w"))


def _malicious_pickle(path: Path, marker: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pickle.dumps(_Marker(str(marker))))
    return path


def _gaussian_nb_bad_probability(model: dict, vec: dict) -> float:
    """Independent restatement of the scoring rule."""
    scores = {}
    for label in ("good", "bad"):
        log_p = math.log(model["class_priors"][label])
        for f in FEATURES:
            m = model["class_stats"][label][f]["mean"]
            s = model["class_stats"][label][f]["stdev"]
            x = vec[f]
            log_p += -0.5 * math.log(2 * math.pi * s * s) - (x - m) ** 2 / (2 * s * s)
        scores[label] = log_p
    top = max(scores.values())
    exp = {k: math.exp(v - top) for k, v in scores.items()}
    return exp["bad"] / sum(exp.values())


# ---------------------------------------------------------------------------
# SEC-01 falsifier: an untrusted working directory is never deserialized
# ---------------------------------------------------------------------------


def test_untrusted_cwd_pickle_is_never_deserialized_by_a_read_only_scan(tmp_path):
    repo = tmp_path / "untrusted"
    marker = tmp_path / "PICKLE_RAN"
    _malicious_pickle(repo / "models" / "slop_classifier.pkl", marker)
    _write_json(repo / "models" / "slop_classifier.json", _model())
    (repo / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=REPO_SRC)
    result = subprocess.run(
        [sys.executable, "-m", "slop_detector.cli", "scan", "m.py", "--read-only", "--json"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr[-400:]
    assert not marker.exists(), "a pickle in the working directory was deserialized"
    payload = json.loads(result.stdout)
    assert payload["ml_scoring"]["status"] == "disabled"
    assert "deficit_score" in payload and "ml_score" not in payload


def test_default_detector_reads_no_model_from_the_working_directory(tmp_path, monkeypatch):
    marker = tmp_path / "PICKLE_RAN"
    _malicious_pickle(tmp_path / "models" / "slop_classifier.pkl", marker)
    _write_json(tmp_path / "models" / "slop_classifier.json", _model())
    monkeypatch.chdir(tmp_path)
    detector = SlopDetector()
    assert not marker.exists()
    assert detector._ml_scorer is None
    assert detector._ml_scoring["status"] == "disabled"


def test_an_explicit_pickle_path_is_refused_without_being_opened(tmp_path):
    marker = tmp_path / "PICKLE_RAN"
    path = _malicious_pickle(tmp_path / "model.pkl", marker)
    scorer, status = _load_status(path)
    assert not marker.exists()
    assert scorer is None and status.status == "unavailable"
    assert "other formats are not deserialized" in (status.reason or "")


def test_runtime_ml_modules_do_not_import_pickle():
    for rel in ("ml/scorer.py", "ml/threshold_model.py"):
        path = REPO / "src" / "slop_detector" / rel
        assert path.exists(), f"{rel} missing"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        assert "pickle" not in names, f"{rel} imports pickle"


# ---------------------------------------------------------------------------
# Explicit JSON model: valid, invalid, missing
# ---------------------------------------------------------------------------


def test_no_model_is_disabled():
    scorer, status = _load_status(None)
    assert scorer is None and status.status == "disabled"


def test_explicit_missing_model_is_unavailable(tmp_path):
    scorer, status = _load_status(tmp_path / "absent.json")
    assert scorer is None and status.status == "unavailable"
    assert "not found" in (status.reason or "")


def _bad_stats():
    stats = _model()["class_stats"]
    stats["bad"]["ldr_score"]["stdev"] = 0.0
    return stats


def _nan_stats():
    stats = _model()["class_stats"]
    stats["good"]["ldr_score"]["mean"] = float("nan")
    return stats


def _missing_feature_stats():
    stats = _model()["class_stats"]
    del stats["good"]["empty_lines"]
    return stats


INVALID = {
    "not_a_mapping": [1, 2, 3],
    "schema_version": _model(schema_version=2),
    "model_type": _model(model_type="random_forest"),
    "features_order": _model(features=list(reversed(FEATURES))),
    "features_subset": _model(features=FEATURES[:-1]),
    "priors_not_positive": _model(class_priors={"good": 0.0, "bad": 1.0}),
    "priors_missing_class": _model(class_priors={"good": 1.0}),
    "stdev_zero": _model(class_stats=_bad_stats()),
    "mean_nan": _model(class_stats=_nan_stats()),
    "stats_missing_feature": _model(class_stats=_missing_feature_stats()),
    "thresholds_missing": {k: v for k, v in _model().items() if k != "thresholds"},
    "legacy_threshold_dict": {"type": "threshold_classifier", "version": "1.0"},
}


@pytest.mark.parametrize("case", sorted(INVALID))
def test_invalid_model_fails_closed(tmp_path, case):
    valid = _write_json(tmp_path / "valid.json", _model())
    scorer, status = _load_status(valid)
    assert status.status == "available", "the loader rejects a valid model; this control is blind"
    path = tmp_path / "model.json"
    path.write_text(json.dumps(INVALID[case], allow_nan=True), encoding="utf-8")
    scorer, status = _load_status(path)
    assert scorer is None and status.status == "unavailable", case
    assert status.reason, case


def test_malformed_json_fails_closed(tmp_path):
    assert _load_status(_write_json(tmp_path / "valid.json", _model()))[1].status == "available"
    path = tmp_path / "model.json"
    path.write_text("{not json", encoding="utf-8")
    scorer, status = _load_status(path)
    assert scorer is None and status.status == "unavailable"


def test_valid_model_scores_by_the_gaussian_rule(tmp_path):
    model = _model()
    path = _write_json(tmp_path / "model.json", model)
    target = tmp_path / "f.py"
    target.write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    detector = SlopDetector(model_path=str(path))
    assert detector._ml_scoring["status"] == "available"
    analysis = detector.analyze_file(str(target))
    score = analysis.ml_score
    assert score is not None
    vec = _threshold_model().features_from_result(analysis.to_dict())
    expected = _gaussian_nb_bad_probability(model, vec)
    assert score.slop_probability == pytest.approx(expected, abs=5e-5)  # rounded to 4 places
    assert score.confidence == pytest.approx(max(expected, 1 - expected), abs=5e-5)
    assert score.model_type == MODEL_TYPE
    assert score.features_used == len(FEATURES)
    assert type(score.agreement) is bool


# ---------------------------------------------------------------------------
# One contract for training and runtime
# ---------------------------------------------------------------------------


def test_feature_list_is_the_contract():
    assert list(_threshold_model().FEATURES) == FEATURES


def test_features_are_computed_as_the_trainer_computed_them():
    """Hand-computed vector; missing blocks are 0.0 and patterns count by id substring."""
    result = {
        "ldr": {"ldr_score": 0.4, "total_lines": 10, "logic_lines": 6, "empty_lines": 2},
        "inflation": {"inflation_score": 1.5, "avg_complexity": 3.0},
        "ddc": {"usage_ratio": 0.8},
        "pattern_issues": [
            {"severity": "high", "pattern_id": "god_function"},
            {"severity": "low", "pattern_id": "nested_complexity"},
            {"severity": "medium", "pattern_id": "cross_language_x"},
            {"severity": "critical", "pattern_id": "phantom_import"},
        ],
    }
    expected = dict.fromkeys(FEATURES, 0.0)
    expected.update(
        ldr_score=0.4,
        inflation_score=1.5,
        ddc_score=0.8,
        avg_complexity=3.0,
        total_lines=10.0,
        logic_lines=6.0,
        empty_lines=2.0,
        pattern_count_critical=1.0,
        pattern_count_high=1.0,
        pattern_count_medium=1.0,
        pattern_count_low=1.0,
        god_function_count=1.0,
        deep_nesting_count=1.0,
        cross_language_patterns=1.0,
    )
    module = _threshold_model()
    assert module.features_from_result(result) == expected
    sparse = module.features_from_result({"ldr": {"total_lines": 3}})
    assert sparse["avg_complexity"] == 0.0 and sparse["ddc_score"] == 0.0
    assert module.features_from_result({"ldr": {}, "inflation": {}, "ddc": {}}) is None


def test_trainer_round_trip_through_json(tmp_path):
    module = _threshold_model()
    good = [{f: 0.2 + 0.1 * i for f in FEATURES} for i in range(4)]
    bad = [{f: 2.0 + 0.3 * i for f in FEATURES} for i in range(4)]
    clf = module.ThresholdClassifier().fit(good, bad)
    path = _write_json(tmp_path / "model.json", clf.to_dict())
    loaded = module.load_model(path)
    for vec in good + bad:
        assert loaded.predict_proba(vec) == pytest.approx(clf.predict_proba(vec))


def test_training_script_uses_the_shared_contract():
    script = (REPO / "scripts" / "retrain_model.py").read_text(encoding="utf-8")
    assert "slop_detector.ml.threshold_model" in script
    assert "class ThresholdClassifier" not in script
    assert "def _extract_feature_vector" not in script
    assert "import pickle" not in script


def test_tracked_artifact_is_json_and_valid():
    assert not (REPO / "models" / "slop_classifier.pkl").exists()
    _threshold_model().load_model(REPO / "models" / "slop_classifier.json")


# ---------------------------------------------------------------------------
# Preservation: the sklearn training tool keeps its own loader
# ---------------------------------------------------------------------------


def test_preservation_classifier_load_keeps_its_messages(tmp_path):
    """PRESERVATION: SlopClassifier.load() still rejects other shapes with the same text."""
    pytest.importorskip("numpy")
    from slop_detector.ml.classifier import SlopClassifier

    clf = SlopClassifier.__new__(SlopClassifier)
    with pytest.raises(ValueError, match="expected classifier keys"):
        clf.load(_pickle(tmp_path / "a.pkl", {"type": "naive"}))
    with pytest.raises(ValueError, match="expected a classifier metadata mapping"):
        clf.load(_pickle(tmp_path / "b.pkl", [1, 2]))


def _pickle(path: Path, obj) -> Path:
    path.write_bytes(pickle.dumps(obj))
    return path
