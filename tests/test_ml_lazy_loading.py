"""Controls for when the optional ML classifier (numpy, scikit-learn) is imported.

The classifier module is imported only for a model artifact that has the
classifier shape. No artifact, an unreadable one, or one of another shape is
reported as before, without paying for numpy and scikit-learn.
"""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
from pathlib import Path

import pytest

from slop_detector.ml.scorer import MLScorer

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")
HEAVY = ("slop_detector.ml.classifier", "sklearn", "numpy")

_PROBE = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "from slop_detector.ml.scorer import MLScorer\n"
    "scorer, status = MLScorer.from_model_with_status(Path(sys.argv[1]))\n"
    "heavy = [m for m in sys.argv[2:] if m in sys.modules]\n"
    "print(json.dumps({'status': status.status, 'reason': status.reason,"
    " 'scorer': scorer is not None, 'imported': heavy}))\n"
)


def _probe(model_path: Path) -> dict:
    env = dict(os.environ, PYTHONPATH=REPO_SRC)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE, str(model_path), *HEAVY],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-400:]
    return json.loads(result.stdout)


def _pickle(path: Path, obj) -> Path:
    path.write_bytes(pickle.dumps(obj))
    return path


# ---------------------------------------------------------------------------
# Paths that never need the classifier
# ---------------------------------------------------------------------------


def test_preservation_no_artifact_is_disabled_and_imports_nothing(tmp_path):
    """PRESERVATION: a missing artifact was already reported without the classifier."""
    out = _probe(tmp_path / "missing.pkl")
    assert out["status"] == "disabled" and out["scorer"] is False
    assert out["imported"] == []


def test_artifact_of_another_shape_is_rejected_before_the_classifier_is_imported(tmp_path):
    artifact = _pickle(tmp_path / "m.pkl", {"type": "naive", "class_priors": [0.5, 0.5]})
    out = _probe(artifact)
    assert out["status"] == "unavailable" and out["scorer"] is False
    assert out["reason"].startswith(
        "ML model could not be loaded: Incompatible ML model artifact: expected classifier keys"
    )
    assert "missing [feature_names, model_type, rf_model, xgb_model]" in out["reason"]
    assert out["imported"] == []


def test_non_mapping_artifact_is_rejected_before_the_classifier_is_imported(tmp_path):
    out = _probe(_pickle(tmp_path / "m.pkl", ["not", "a", "mapping"]))
    assert out["status"] == "unavailable"
    assert "expected a classifier metadata mapping" in out["reason"]
    assert out["imported"] == []


def test_unreadable_artifact_is_rejected_before_the_classifier_is_imported(tmp_path):
    artifact = tmp_path / "m.pkl"
    artifact.write_bytes(b"this is not a pickle")
    out = _probe(artifact)
    assert out["status"] == "unavailable"
    assert out["reason"].startswith("ML model could not be loaded:")
    assert out["imported"] == []


# ---------------------------------------------------------------------------
# A classifier-shaped artifact still loads and scores as before
# ---------------------------------------------------------------------------


class FakeForest:
    """Stands in for a fitted RandomForestClassifier: fixed class probabilities."""

    def predict_proba(self, x):
        import numpy as np

        return np.array([[0.25, 0.75]] * len(x))


def _classifier_artifact(path: Path) -> Path:
    return _pickle(
        path,
        {
            "schema_version": 1,
            "model_type": "random_forest",
            "rf_model": FakeForest(),
            "xgb_model": None,
            "feature_names": [],
        },
    )


def test_classifier_shaped_artifact_is_available_and_scores(tmp_path):
    pytest.importorskip("numpy")
    from slop_detector.models import FileAnalysis

    scorer, status = MLScorer.from_model_with_status(_classifier_artifact(tmp_path / "m.pkl"))
    assert status.status == "available" and scorer is not None
    analysis = FileAnalysis.__new__(FileAnalysis)
    analysis.deficit_score = 40.0
    score = scorer.score(analysis)
    assert score is not None
    assert score.slop_probability == pytest.approx(0.75)
    assert score.confidence == pytest.approx(0.75)
    assert bool(score.agreement) is True  # numpy bool today; compare the value


def test_preservation_classifier_load_keeps_its_messages(tmp_path):
    """PRESERVATION: SlopClassifier.load() still rejects other shapes with the same text."""
    pytest.importorskip("numpy")
    from slop_detector.ml.classifier import SlopClassifier

    clf = SlopClassifier.__new__(SlopClassifier)
    with pytest.raises(ValueError, match="expected classifier keys"):
        clf.load(_pickle(tmp_path / "a.pkl", {"type": "naive"}))
    with pytest.raises(ValueError, match="expected a classifier metadata mapping"):
        clf.load(_pickle(tmp_path / "b.pkl", [1, 2]))
    clf.load(_classifier_artifact(tmp_path / "c.pkl"))
    assert clf.is_trained and clf.model_type == "random_forest"
