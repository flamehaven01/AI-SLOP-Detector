"""deep_nesting adds no penalty where nested_complexity fires on the same function.

nested_complexity is deep nesting plus a complexity condition, created at the
same function location as deep_nesting. Both findings are kept, severities and
the CRITICAL purity contribution are unchanged; only the additive +5 of the
deep_nesting part is not charged a second time. god_function is an
independent condition (length, or its own complexity limit) and keeps its
penalty. In the RExSyn dogfood, all 26 nested_complexity findings shared their
function with a deep_nesting finding.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from slop_detector.core import SlopDetector
from slop_detector.core_scoring import calculate_pattern_penalty, calculate_slop_status
from slop_detector.gate.slop_gate import SlopGate
from slop_detector.models import SlopStatus
from slop_detector.patterns.base import Axis, Issue, Severity

WEIGHTS = {"ldr": 0.40, "inflation": 0.30, "ddc": 0.20, "purity": 0.10}


def _issue(pattern_id: str, severity: Severity, line: int, column: int = 4) -> Issue:
    return Issue(
        pattern_id=pattern_id,
        severity=severity,
        axis=Axis.QUALITY,
        file=Path("m.py"),
        line=line,
        column=column,
        message=pattern_id,
    )


def _deep(line: int, column: int = 4) -> Issue:
    return _issue("deep_nesting", Severity.HIGH, line, column)


def _nested(line: int, column: int = 4) -> Issue:
    return _issue("nested_complexity", Severity.CRITICAL, line, column)


def _god(line: int, column: int = 4) -> Issue:
    return _issue("god_function", Severity.HIGH, line, column)


def test_same_function_is_charged_once():
    assert calculate_pattern_penalty([_deep(120), _nested(120)]) == 10.0


def test_different_functions_are_both_charged():
    assert calculate_pattern_penalty([_deep(120), _nested(180)]) == 15.0


def test_god_function_keeps_its_own_penalty():
    assert calculate_pattern_penalty([_deep(120), _nested(120), _god(120)]) == 15.0


def _metrics():
    ldr = SimpleNamespace(ldr_score=1.0)
    inflation = SimpleNamespace(inflation_score=0.0)
    ddc = SimpleNamespace(usage_ratio=1.0, fake_imports=[])
    return ldr, inflation, ddc


def test_purity_still_counts_the_critical():
    """Score-only: nested_complexity stays CRITICAL in the purity dimension."""
    ldr, inflation, ddc = _metrics()
    score, _, warnings, breakdown = calculate_slop_status(
        WEIGHTS, ldr, inflation, ddc, [_deep(120), _nested(120)]
    )
    assert breakdown["purity_penalty"] > 0
    assert "PATTERNS: 1 critical issues found" in warnings
    assert "PATTERNS: 1 high-severity issues found" in warnings
    assert round(score - breakdown["purity_penalty"], 2) == 10.0


def test_band_boundary():
    """The structure_validator.py shape: 32.88 (suspicious) becomes 27.88 (clean)."""
    ldr, inflation, ddc = _metrics()
    others = [_issue("other", Severity.MEDIUM, line) for line in (10, 20, 30, 40)]
    score, status, _, _ = calculate_slop_status(
        WEIGHTS, ldr, inflation, ddc, [_deep(120), _nested(120), _god(120)] + others
    )
    assert round(score, 2) == 27.88
    assert status == SlopStatus.CLEAN


NESTED_SOURCE = """\
def walk(data):
    for a in data:
        if a:
            for b in a:
                if b:
                    while b:
                        if b > 1:
                            b -= 1
                        else:
                            break
    return data
"""


def test_findings_are_kept_and_share_the_location(tmp_path):
    """Both findings stay in the result, at one (line, column); the score
    charges the CRITICAL only."""
    source = tmp_path / "m.py"
    source.write_text(NESTED_SOURCE, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(source))
    found = {
        issue.pattern_id: (issue.line, issue.column)
        for issue in result.pattern_issues
        if issue.pattern_id in ("deep_nesting", "nested_complexity")
    }
    assert found == {"deep_nesting": (1, 0), "nested_complexity": (1, 0)}
    others = [
        issue
        for issue in result.pattern_issues
        if issue.pattern_id not in ("deep_nesting", "nested_complexity")
    ]
    assert calculate_pattern_penalty(result.pattern_issues) == (
        10.0 + calculate_pattern_penalty(others)
    )


def test_gate_uses_the_same_penalty():
    seen = {}
    gate = SlopGate()
    gate.evaluate = lambda **kwargs: seen.update(kwargs)  # type: ignore[method-assign]
    ldr, inflation, ddc = _metrics()
    analysis = SimpleNamespace(
        ldr=ldr,
        inflation=inflation,
        ddc=ddc,
        pattern_issues=[_deep(120), _nested(120)],
        file_path="m.py",
    )
    gate.evaluate_from_file_analysis(analysis)
    assert seen["pattern_penalty"] == 10.0
