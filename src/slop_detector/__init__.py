"""AI SLOP Detector - Production-ready code quality analyzer."""

from typing import Any

__version__ = "3.7.9"
__author__ = "Flamehaven Labs"
__email__ = "info@flamehaven.space"

from slop_detector.autofix.engine import FixEngine, FixResult
from slop_detector.core import SlopDetector
from slop_detector.decorators import ignore, slop  # v2.6.3
from slop_detector.gate.slop_gate import SlopGate, SlopGateDecision
from slop_detector.models import (
    DDCResult,
    FileAnalysis,
    IgnoredFunction,
    InflationResult,
    LDRResult,
    PriorityHotspot,
    ProjectAnalysis,
    SlopStatus,
)

__all__ = [
    "SlopDetector",
    "SlopStatus",
    "LDRResult",
    "InflationResult",
    "DDCResult",
    "FileAnalysis",
    "ProjectAnalysis",
    "PriorityHotspot",
    "IgnoredFunction",  # v2.6.3
    "slop",  # v2.6.3: for @slop.ignore syntax
    "ignore",  # v2.6.3: for @ignore syntax
    "SlopGate",
    "SlopGateDecision",
    "FixEngine",
    "FixResult",
]

try:  # v2.8.0: optional ML surface should not hard-fail core imports
    from slop_detector.ml.scorer import MLScore as _MLScore
    from slop_detector.ml.scorer import MLScorer as _MLScorer
except ImportError:  # pragma: no cover - optional dependency path
    MLScore: Any = None
    MLScorer: Any = None
else:
    MLScore = _MLScore
    MLScorer = _MLScorer
    __all__ += [
        "MLScore",  # v2.8.0
        "MLScorer",  # v2.8.0
    ]
