"""SNP-compatible gate module for slop analysis."""

from slop_detector.gate.models import (
    GateMode,
    GateResult,
    GateThresholds,
    GateVerdict,
    QuarantineRecord,
)
from slop_detector.gate.slop_gate import SlopGate, SlopGateDecision

__all__ = [
    "SlopGate",
    "SlopGateDecision",
    "GateMode",
    "GateVerdict",
    "GateThresholds",
    "QuarantineRecord",
    "GateResult",
]
