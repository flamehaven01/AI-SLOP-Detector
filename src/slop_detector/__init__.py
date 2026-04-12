"""AI SLOP Detector - Production-ready code quality analyzer."""

__version__ = "3.5.0"
__author__ = "Flamehaven Labs"
__email__ = "info@flamehaven.space"

from slop_detector.autofix.engine import FixEngine, FixResult
from slop_detector.core import SlopDetector
from slop_detector.decorators import ignore, slop  # v2.6.3
from slop_detector.gate.slop_gate import SlopGate, SlopGateDecision
from slop_detector.ml.scorer import MLScore, MLScorer  # v2.8.0
from slop_detector.models import (
    DDCResult,
    FileAnalysis,
    IgnoredFunction,
    InflationResult,
    LDRResult,
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
    "IgnoredFunction",  # v2.6.3
    "slop",  # v2.6.3: for @slop.ignore syntax
    "ignore",  # v2.6.3: for @ignore syntax
    "SlopGate",
    "SlopGateDecision",
    "FixEngine",
    "FixResult",
    "MLScore",  # v2.8.0
    "MLScorer",  # v2.8.0
]
