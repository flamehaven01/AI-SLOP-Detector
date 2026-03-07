"""
ML-based secondary scorer for SlopDetector (v2.8.0).

Loads a trained SlopClassifier model and produces MLScore
as an optional secondary signal alongside the rule-based deficit_score.

Integration philosophy:
  - ML score is ADDITIVE evidence, NOT a replacement for rule-based scoring
  - The rule-based deficit_score remains the authoritative primary signal
  - ML score surfaces when model is available; silently absent otherwise
  - No hard dependency on scikit-learn at import time (lazy load)

Usage:
    scorer = MLScorer.from_model(Path("models/slop_classifier.pkl"))
    ml_score = scorer.score(file_analysis)
    # ml_score.slop_probability in [0, 1]
    # ml_score.confidence in [0, 1]
    # ml_score.agreement: True if ML and rule-based agree
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class MLScore:
    """ML-based slop probability for a single file."""

    slop_probability: float   # [0, 1]: probability of being slop
    confidence: float         # [0, 1]: model confidence (max class probability)
    model_type: str           # "random_forest" | "xgboost" | "ensemble"
    agreement: bool           # True if ML and rule-based scores agree
    features_used: int        # number of features the model was fed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slop_probability": round(float(self.slop_probability), 4),
            "confidence": round(float(self.confidence), 4),
            "model_type": str(self.model_type),
            "agreement": bool(self.agreement),
            "features_used": int(self.features_used),
        }

    @property
    def label(self) -> str:
        if self.slop_probability >= 0.70:
            return "slop"
        if self.slop_probability >= 0.40:
            return "uncertain"
        return "clean"


def _extract_features_from_analysis(file_analysis: Any) -> Dict[str, float]:
    """Extract the feature dict from a FileAnalysis — mirrors pipeline._extract_features."""
    ldr = getattr(file_analysis, "ldr", None)
    inflation = getattr(file_analysis, "inflation", None)
    ddc = getattr(file_analysis, "ddc", None)
    pattern_issues = getattr(file_analysis, "pattern_issues", [])

    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    cross_lang = god_fn = dead_code = deep_nest = hallucination = 0

    for issue in pattern_issues:
        sev = getattr(getattr(issue, "severity", None), "value", "low")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        pid = getattr(issue, "pattern_id", "")
        if any(x in pid for x in ("js_push", "java_", "ruby_", "go_print", "csharp_", "php_")):
            cross_lang += 1
        if "hallucin" in pid:
            hallucination += 1
        if pid == "god_function":
            god_fn += 1
        if pid == "dead_code":
            dead_code += 1
        if pid == "deep_nesting":
            deep_nest += 1

    ldr_score = getattr(ldr, "ldr_score", 0.0) if ldr else 0.0
    total_lines = float(getattr(ldr, "total_lines", 0) if ldr else 0)
    logic_lines = float(getattr(ldr, "logic_lines", 0) if ldr else 0)
    empty_lines = float(getattr(ldr, "empty_lines", 0) if ldr else 0)

    raw_inflation = getattr(inflation, "inflation_score", 0.0) if inflation else 0.0
    inflation_score = (
        0.0 if not math.isfinite(raw_inflation) else min(raw_inflation / 2.0, 1.0)
    )
    avg_complexity = getattr(inflation, "avg_complexity", 1.0) if inflation else 1.0
    ddc_score = getattr(ddc, "usage_ratio", 1.0) if ddc else 1.0

    return {
        "ldr_score": ldr_score,
        "inflation_score": inflation_score,
        "ddc_score": ddc_score,
        "pattern_count_critical": float(severity_counts["critical"]),
        "pattern_count_high": float(severity_counts["high"]),
        "pattern_count_medium": float(severity_counts["medium"]),
        "pattern_count_low": float(severity_counts["low"]),
        "god_function_count": float(god_fn),
        "dead_code_count": float(dead_code),
        "deep_nesting_count": float(deep_nest),
        "avg_complexity": avg_complexity,
        "cross_language_patterns": float(cross_lang),
        "hallucination_count": float(hallucination),
        "total_lines": total_lines,
        "logic_lines": logic_lines,
        "empty_lines": empty_lines,
    }


class MLScorer:
    """
    Wraps a trained SlopClassifier and scores FileAnalysis objects.

    Designed for zero-cost when no model is available (from_model returns None).
    """

    def __init__(self, classifier: Any) -> None:
        self._clf = classifier

    @classmethod
    def from_model(cls, model_path: Path) -> Optional["MLScorer"]:
        """
        Load a trained model from disk.

        Returns None (not an exception) if:
          - scikit-learn is not installed
          - model file does not exist
          - model file is corrupt / incompatible

        This ensures SlopDetector works without ML deps installed.
        """
        if not model_path.exists():
            logger.debug("[MLScorer] Model not found: %s — ML scoring disabled", model_path)
            return None

        try:
            from slop_detector.ml.classifier import SlopClassifier
            clf = SlopClassifier.__new__(SlopClassifier)
            clf.load(model_path)
            logger.info("[MLScorer] Loaded model from %s", model_path)
            return cls(clf)
        except ImportError:
            logger.debug("[MLScorer] scikit-learn not installed — ML scoring disabled")
            return None
        except Exception as e:
            logger.warning("[MLScorer] Failed to load model: %s", e)
            return None

    def score(self, file_analysis: Any) -> Optional[MLScore]:
        """
        Score a FileAnalysis and return MLScore.

        Returns None if scoring fails (e.g., feature mismatch after model update).
        Agreement is True when both rule-based and ML classify the file the same way
        (slop if deficit_score >= 30 and slop_probability >= 0.40).
        """
        try:
            features = _extract_features_from_analysis(file_analysis)
            slop_prob, confidence = self._clf.predict(features)

            # Agreement: check if rule-based and ML agree on slop/clean
            rule_is_slop = getattr(file_analysis, "deficit_score", 0.0) >= 30.0
            ml_is_slop = slop_prob >= 0.40
            agreement = rule_is_slop == ml_is_slop

            return MLScore(
                slop_probability=round(slop_prob, 4),
                confidence=round(confidence, 4),
                model_type=getattr(self._clf, "model_type", "unknown"),
                agreement=agreement,
                features_used=len(features),
            )
        except Exception as e:
            logger.debug("[MLScorer] Scoring failed: %s", e)
            return None
