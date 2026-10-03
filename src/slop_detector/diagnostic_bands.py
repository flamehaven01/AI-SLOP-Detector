"""Canonical deficit bands: the one meaning of a 0-100 deficit score.

Product semantics, not configuration. Every score on the deficit scale (a
Python file, a project, a Go or JS file) is classified here, so `suspicious`
means the same thing in every repository and on every surface. A consumer that
wants a stricter policy (CI thresholds) applies it to these canonical values;
it does not redefine the bands. Orthogonal conditions are flags on the result
(for example `dependency_noise`) and never replace the band.
"""

from __future__ import annotations

from slop_detector.models import SlopStatus

SUSPICIOUS_AT = 30.0
INFLATED_AT = 50.0
CRITICAL_AT = 70.0


def classify_deficit(score: float) -> SlopStatus:
    """The band of a deficit score: CLEAN <30, SUSPICIOUS <50, INFLATED_SIGNAL <70, else CRITICAL."""
    if score >= CRITICAL_AT:
        return SlopStatus.CRITICAL_DEFICIT
    if score >= INFLATED_AT:
        return SlopStatus.INFLATED_SIGNAL
    if score >= SUSPICIOUS_AT:
        return SlopStatus.SUSPICIOUS
    return SlopStatus.CLEAN


def bands_text() -> str:
    """One-line description of the bands for human output."""
    return (
        f"CLEAN <{SUSPICIOUS_AT:g}  |  SUSPICIOUS {SUSPICIOUS_AT:g}-{INFLATED_AT:g}  |  "
        f"INFLATED {INFLATED_AT:g}-{CRITICAL_AT:g}  |  CRITICAL >={CRITICAL_AT:g}"
    )
