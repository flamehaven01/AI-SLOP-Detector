"""Threshold classifier model: the one contract for training and scoring.

Standard library only. A model is a versioned JSON artifact; it is read with
`json` and validated field by field before use (fail closed). Nothing here
unpickles anything. `scripts/retrain_model.py` trains with the same
`ThresholdClassifier` and the same `features_from_result`, so a model is
scored on the features it was trained on.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
MODEL_TYPE = "threshold_classifier_gaussian_nb"
LABELS = ("good", "bad")
LEVELS = ("critical", "high", "medium", "low")

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


class ModelArtifactError(ValueError):
    """The model artifact is not a valid threshold classifier."""


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------


def _block(fr: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = fr.get(key) or {}
    return value if isinstance(value, dict) else {}


# Pattern id substrings per feature, checked in order; the first match counts.
_PATTERN_FEATURES = (
    ("god_function_count", ("god_function",)),
    ("dead_code_count", ("dead_code",)),
    ("deep_nesting_count", ("deep_nesting", "nested_complexity")),
    ("hallucination_count", ("hallucin",)),
    ("cross_language_patterns", ("cross", "language")),
)


def _pattern_feature(pattern_id: str) -> Optional[str]:
    for feature, needles in _PATTERN_FEATURES:
        if any(needle in pattern_id for needle in needles):
            return feature
    return None


def _pattern_counts(patterns: List[Dict[str, Any]]) -> Dict[str, float]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    kinds = {feature: 0 for feature, _ in _PATTERN_FEATURES}
    for p in patterns:
        sev = (p.get("severity") or "low").lower()
        counts[sev] = counts.get(sev, 0) + 1
        feature = _pattern_feature((p.get("pattern_id") or "").lower())
        if feature:
            kinds[feature] += 1
    out = {f"pattern_count_{sev}": float(counts.get(sev, 0)) for sev in LEVELS}
    out.update({feature: float(n) for feature, n in kinds.items()})
    return out


def features_from_result(fr: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Feature vector from one file result (`FileAnalysis.to_dict()` or scan JSON).

    Returns None for an empty file (no lines and no metric signal).
    """
    ldr = _block(fr, "ldr")
    inflation = _block(fr, "inflation")
    ddc = _block(fr, "ddc")
    vec = {
        "ldr_score": float(ldr.get("ldr_score", 0.0)),
        "inflation_score": float(inflation.get("inflation_score", 0.0)),
        "ddc_score": float(ddc.get("usage_ratio", ddc.get("ddc_score", 0.0))),
        "avg_complexity": float(inflation.get("avg_complexity", 0.0)),
        "total_lines": float(ldr.get("total_lines", 0)),
        "logic_lines": float(ldr.get("logic_lines", 0)),
        "empty_lines": float(ldr.get("empty_lines", 0)),
    }
    vec.update(_pattern_counts(fr.get("pattern_issues") or []))
    signal = ("ldr_score", "inflation_score", "ddc_score", "total_lines")
    if all(vec[key] == 0 for key in signal):
        return None
    return {feat: vec[feat] for feat in FEATURES}


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def _mean(vals: List[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _stdev(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def _log_likelihood(x: float, mean: float, stdev: float) -> float:
    """Gaussian log-likelihood."""
    return -0.5 * math.log(2 * math.pi * stdev**2) - (x - mean) ** 2 / (2 * stdev**2)


class ThresholdClassifier:
    """Gaussian naive Bayes over the feature vector, plus per-feature midpoints.

    Per class and feature it keeps mean and stdev; a sample is scored by the
    summed Gaussian log-likelihood and a softmax over the two classes.
    """

    def __init__(self) -> None:
        self.class_stats: Dict[str, Dict[str, Dict[str, float]]] = {}
        self.class_priors: Dict[str, float] = {}
        self.thresholds: Dict[str, float] = {}
        self.feature_importance: Dict[str, float] = {}

    def fit(self, good: List[dict], bad: List[dict]) -> "ThresholdClassifier":
        self.class_priors = {"good": 0.5, "bad": 0.5}  # balanced
        for label, vecs in (("good", good), ("bad", bad)):
            self.class_stats[label] = {}
            for feat in FEATURES:
                vals = [v[feat] for v in vecs]
                self.class_stats[label][feat] = {
                    "mean": _mean(vals),
                    "stdev": max(_stdev(vals), 1e-6),  # avoid zero division
                }
        for feat in FEATURES:
            g = self.class_stats["good"][feat]
            b = self.class_stats["bad"][feat]
            sep = abs(b["mean"] - g["mean"]) / (g["stdev"] + b["stdev"] + 1e-9)
            self.feature_importance[feat] = round(sep, 6)
            self.thresholds[feat] = round((g["mean"] + b["mean"]) / 2, 4)
        return self

    def predict_proba(self, vec: Dict[str, float]) -> Dict[str, float]:
        """Return {good: p, bad: p}."""
        scores = {}
        for label in LABELS:
            log_p = math.log(self.class_priors[label])
            for feat in FEATURES:
                stats = self.class_stats[label][feat]
                log_p += _log_likelihood(vec.get(feat, 0.0), stats["mean"], stats["stdev"])
            scores[label] = log_p
        top = max(scores.values())
        exp_s = {k: math.exp(v - top) for k, v in scores.items()}
        total = sum(exp_s.values())
        return {k: v / total for k, v in exp_s.items()}

    def predict(self, vec: Dict[str, float]) -> str:
        proba = self.predict_proba(vec)
        return max(proba, key=proba.__getitem__)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_type": MODEL_TYPE,
            "features": list(FEATURES),
            "class_priors": self.class_priors,
            "class_stats": self.class_stats,
            "thresholds": self.thresholds,
            "feature_importance": self.feature_importance,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThresholdClassifier":
        """Build from a mapping that passed validate_model()."""
        obj = cls()
        obj.class_priors = data["class_priors"]
        obj.class_stats = data["class_stats"]
        obj.thresholds = data["thresholds"]
        obj.feature_importance = data["feature_importance"]
        return obj


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


def _number(value: Any, where: str, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelArtifactError(f"{where} must be a number")
    if not math.isfinite(value):
        raise ModelArtifactError(f"{where} must be finite")
    if positive and value <= 0:
        raise ModelArtifactError(f"{where} must be greater than 0")


def _mapping(value: Any, where: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelArtifactError(f"{where} must be a mapping")
    return value


def _per_feature(data: Dict[str, Any], key: str) -> None:
    values = _mapping(data.get(key), key)
    for feat in FEATURES:
        if feat not in values:
            raise ModelArtifactError(f"{key} lacks {feat}")
        _number(values[feat], f"{key}.{feat}")


def validate_model(data: Any) -> Dict[str, Any]:
    """Check every field the classifier reads; raise ModelArtifactError otherwise."""
    data = _mapping(data, "model artifact")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ModelArtifactError(
            f"schema_version must be {SCHEMA_VERSION}, got {data.get('schema_version')!r}"
        )
    if data.get("model_type") != MODEL_TYPE:
        raise ModelArtifactError(
            f"model_type must be {MODEL_TYPE!r}, got {data.get('model_type')!r}"
        )
    if data.get("features") != FEATURES:
        raise ModelArtifactError("features must list the 16 contract features in order")
    priors = _mapping(data.get("class_priors"), "class_priors")
    stats = _mapping(data.get("class_stats"), "class_stats")
    for label in LABELS:
        if label not in priors:
            raise ModelArtifactError(f"class_priors lacks {label!r}")
        _number(priors[label], f"class_priors.{label}", positive=True)
        per_label = _mapping(stats.get(label), f"class_stats.{label}")
        for feat in FEATURES:
            entry = _mapping(per_label.get(feat), f"class_stats.{label}.{feat}")
            _number(entry.get("mean"), f"class_stats.{label}.{feat}.mean")
            _number(entry.get("stdev"), f"class_stats.{label}.{feat}.stdev", positive=True)
    _per_feature(data, "thresholds")
    _per_feature(data, "feature_importance")
    return data


def load_model(path: Path) -> ThresholdClassifier:
    """Read and validate a JSON threshold model. Only `.json` files are read."""
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise ModelArtifactError(
            f"ML model artifact must be a JSON threshold model (.json), got {path.suffix!r}; "
            "other formats are not deserialized"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ModelArtifactError(f"not valid JSON: {exc}") from exc
    return ThresholdClassifier.from_dict(validate_model(data))
