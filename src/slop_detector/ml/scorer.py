"""
ML-based secondary scorer for SlopDetector.

Scores a FileAnalysis with a threshold classifier model and produces MLScore
as an optional secondary signal alongside the rule-based deficit_score.

Integration philosophy:
  - ML score is ADDITIVE evidence, NOT a replacement for rule-based scoring
  - The rule-based deficit_score remains the authoritative primary signal
  - No model is read unless one is given explicitly (no default path)
  - A model is a JSON threshold classifier (ml/threshold_model.py); nothing is
    unpickled, and an invalid model is reported as unavailable (fail closed)

Usage:
    scorer, status = MLScorer.from_model_with_status(Path("models/slop_classifier.json"))
    ml_score = scorer.score(file_analysis) if scorer else None
    # ml_score.slop_probability in [0, 1]
    # ml_score.confidence in [0, 1]
    # ml_score.agreement: True if ML and rule-based agree
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from slop_detector.ml.threshold_model import (
    FEATURES,
    MODEL_TYPE,
    ThresholdClassifier,
    features_from_result,
    load_model,
)

logger = logging.getLogger(__name__)


@dataclass
class MLScore:
    """ML-based slop probability for a single file."""

    slop_probability: float  # [0, 1]: probability of being slop
    confidence: float  # [0, 1]: model confidence (max class probability)
    model_type: str  # threshold_model.MODEL_TYPE
    agreement: bool  # True if ML and rule-based scores agree
    features_used: int  # number of features the model was fed

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


@dataclass(frozen=True)
class MLScoringAvailability:
    """Capability state for the optional ML secondary scorer."""

    status: str  # "available" | "disabled" | "unavailable"
    reason: Optional[str] = None
    model_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "status": self.status,
            "reason": self.reason,
            "model_path": self.model_path,
        }


class MLScorer:
    """
    Wraps a ThresholdClassifier and scores FileAnalysis objects.

    Zero cost when no model is given: from_model_with_status(None) reads nothing.
    """

    def __init__(self, classifier: ThresholdClassifier) -> None:
        self._clf = classifier

    @classmethod
    def from_model(cls, model_path: Optional[Path]) -> Optional["MLScorer"]:
        """Compatibility loader that preserves the original optional return type."""
        scorer, _ = cls.from_model_with_status(model_path)
        return scorer

    @classmethod
    def from_model_with_status(
        cls, model_path: Optional[Path]
    ) -> Tuple[Optional["MLScorer"], MLScoringAvailability]:
        """Load an explicitly given JSON model; return the scorer and its capability state."""
        if model_path is None:
            return None, MLScoringAvailability(
                status="disabled",
                reason="No ML model artifact was configured for this run.",
            )
        model_path = Path(model_path)
        if model_path.suffix.lower() == ".json" and not model_path.exists():
            return None, MLScoringAvailability(
                status="unavailable",
                reason=f"ML model artifact not found: {model_path}",
                model_path=str(model_path),
            )
        try:
            clf = load_model(model_path)
        except (OSError, ValueError) as exc:
            logger.warning("[MLScorer] Model not loaded: %s", exc)
            return None, MLScoringAvailability(
                status="unavailable",
                reason=f"ML model could not be loaded: {exc}",
                model_path=str(model_path),
            )
        logger.info("[MLScorer] Loaded model from %s", model_path)
        return cls(clf), MLScoringAvailability(status="available", model_path=str(model_path))

    def score(self, file_analysis: Any) -> Optional[MLScore]:
        """
        Score a FileAnalysis and return MLScore.

        Returns None for an empty file or if scoring fails. Agreement is True when
        both rule-based and ML classify the file the same way (slop if
        deficit_score >= 30 and slop_probability >= 0.40).
        """
        try:
            features = features_from_result(file_analysis.to_dict())
            if features is None:
                return None
            proba = self._clf.predict_proba(features)
            slop_prob = proba["bad"]
            rule_is_slop = getattr(file_analysis, "deficit_score", 0.0) >= 30.0
            return MLScore(
                slop_probability=round(slop_prob, 4),
                confidence=round(max(proba.values()), 4),
                model_type=MODEL_TYPE,
                agreement=rule_is_slop == (slop_prob >= 0.40),
                features_used=len(FEATURES),
            )
        except Exception as e:
            logger.debug("[MLScorer] Scoring failed: %s", e)
            return None
