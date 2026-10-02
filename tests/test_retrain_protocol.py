"""Controls for how scripts/retrain_model.py evaluates and describes the model.

An evaluation fit never sees the rows it is scored on, and the report says what
its numbers measure: agreement with labels derived from the detector's own
deficit score, not independent slop-detection accuracy.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import pytest

from slop_detector.ml.threshold_model import FEATURES, ThresholdClassifier

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def retrain():
    spec = importlib.util.spec_from_file_location(
        "retrain_model", REPO / "scripts" / "retrain_model.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _vec(tag: float) -> dict:
    return {f: tag + 0.01 * i for i, f in enumerate(FEATURES)}


def _rows():
    """(repository, vector, label): three repos, each with both classes; tags are unique."""
    rows = []
    tag = 0.0
    for repo in ("alpha", "beta", "gamma"):
        for label in (0, 1, 0, 1, 1):
            tag += 1.0
            rows.append((repo, _vec(tag + (5.0 if label else 0.0)), label))
    return rows


def _key(vec: dict) -> float:
    return vec["ldr_score"]


def _recording_fit(monkeypatch, retrain, calls):
    real_fit = ThresholdClassifier.fit

    def fit(self, good, bad):
        calls.append({_key(v) for v in list(good) + list(bad)})
        return real_fit(self, good, bad)

    monkeypatch.setattr(retrain.ThresholdClassifier, "fit", fit)


def _require(retrain, name):
    assert hasattr(retrain, name), f"scripts/retrain_model.py has no {name}()"
    return getattr(retrain, name)


def _train(retrain):
    train = _require(retrain, "train")
    params = list(inspect.signature(train).parameters)
    assert params == ["rows"], f"train() takes {params}, expected (rows) with repository provenance"
    return train


# ---------------------------------------------------------------------------
# Evaluation never fits on what it scores
# ---------------------------------------------------------------------------


def test_random_holdout_splits_before_fitting(retrain, monkeypatch):
    holdout = _require(retrain, "evaluate_random_holdout")
    calls = []
    _recording_fit(monkeypatch, retrain, calls)
    result = holdout(_rows(), seed=42, test_fraction=0.2)
    assert len(calls) == 1, "holdout must fit exactly once, on the training split"
    tested = {_key(v) for _, v, _ in result["test_rows"]}
    assert tested and not tested & calls[0], "the holdout fit saw rows it was scored on"
    assert len(tested) + len(calls[0]) == len(_rows())


def test_leave_one_repository_out_holds_out_each_repository(retrain, monkeypatch):
    loro = _require(retrain, "evaluate_leave_one_repository_out")
    rows = _rows()
    calls = []
    _recording_fit(monkeypatch, retrain, calls)
    result = loro(rows)
    assert sorted(result["folds"]) == ["alpha", "beta", "gamma"]
    assert len(calls) == 3
    for repo, seen in zip(sorted(result["folds"]), calls):
        held_out = {_key(v) for r, v, _ in rows if r == repo}
        assert not held_out & seen, f"fold {repo} fit on its own repository"
        assert seen == {_key(v) for r, v, _ in rows if r != repo}
    assert result["pooled"]["n"] == len(rows)


def test_final_model_is_fit_on_all_rows_after_evaluation(retrain):
    train = _train(retrain)
    rows = _rows()
    clf, _ = train(rows)
    good = [v for _, v, y in rows if y == 0]
    bad = [v for _, v, y in rows if y == 1]
    assert clf.to_dict() == ThresholdClassifier().fit(good, bad).to_dict()


# ---------------------------------------------------------------------------
# The report says what it measures
# ---------------------------------------------------------------------------


def _check_provenance(report: dict) -> None:
    assert report.get("independent_ground_truth") is False
    assert report.get("model_role") == "secondary_rule_distillation_signal"
    assert "deficit_score" in report.get("label_source", "")
    assert "agreement" in report.get("metrics_meaning", "")
    evaluation = report.get("evaluation", {})
    assert set(evaluation.get("protocols", [])) == {
        "random_holdout_split_before_fit",
        "leave_one_repository_out",
    }
    assert report.get("model_path") == "models/slop_classifier.json"
    assert "accuracy" not in json.dumps(report.get("metrics", {})), "unqualified top-level metrics"


def test_report_states_what_its_numbers_measure(retrain):
    train = _train(retrain)
    _, report = train(_rows())
    _check_provenance(report)
    assert report["training_repositories"] == {
        "alpha": {"good": 2, "bad": 3},
        "beta": {"good": 2, "bad": 3},
        "gamma": {"good": 2, "bad": 3},
    }


def test_tracked_report_matches_the_contract():
    report = json.loads((REPO / "models" / "pipeline_report.json").read_text(encoding="utf-8"))
    _check_provenance(report)
    assert report["n_samples"] == 784
    assert len(report["training_repositories"]) == 7


def test_tracked_model_is_the_full_fit_of_the_tracked_data():
    data = json.loads((REPO / "models" / "training_data.json").read_text(encoding="utf-8"))
    model = json.loads((REPO / "models" / "slop_classifier.json").read_text(encoding="utf-8"))
    assert ThresholdClassifier().fit(data["good"], data["bad"]).to_dict() == model
