"""AI SLOP Detector - Production-ready code quality analyzer."""

__version__ = "2.6.3"
__author__ = "Flamehaven Labs"
__email__ = "info@flamehaven.space"

from slop_detector.core import SlopDetector
from slop_detector.decorators import ignore, slop  # v2.6.3
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
]
