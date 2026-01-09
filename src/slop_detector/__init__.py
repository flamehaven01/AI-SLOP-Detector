"""AI SLOP Detector - Production-ready code quality analyzer."""

__version__ = "2.0.0"
__author__ = "Flamehaven Labs"
__email__ = "slop-detector@flamehaven.io"

from slop_detector.core import SlopDetector
from slop_detector.models import (
    DDCResult,
    FileAnalysis,
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
]
