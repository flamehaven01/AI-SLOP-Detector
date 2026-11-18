"""A HALT recommends fixing only what failed.

The recommendation named all four metrics whatever stopped the gate, so a
project without Python files (DDC not measured, so it cannot fail) was told to
remove unused imports (DDC). It now names the conditions that failed, in the
order the gate checks them; when all four fail it is the sentence it always was.
"""

from __future__ import annotations

from slop_detector.gate.slop_gate import SlopGate

ALL_FOUR = (
    "Reduce empty/placeholder code (LDR), "
    "remove unused imports (DDC), "
    "eliminate buzzword inflation (jsd), "
    "fix structural patterns (ove)."
)


def _gate() -> SlopGate:
    return SlopGate(
        ldr_threshold=0.6, ddc_threshold=0.5, inflation_threshold=1.0, pattern_threshold=10
    )


def test_a_pattern_halt_without_ddc_does_not_recommend_ddc():
    d = _gate().evaluate(ldr_score=0.9, ddc_ratio=None, inflation_score=None, pattern_penalty=30)
    assert d.status == "HALT"
    assert d.recommendation == "Fix structural patterns (ove)."
    assert "DDC" not in d.recommendation


def test_each_failed_metric_is_named_alone():
    gate = _gate()
    assert (
        gate.evaluate(0.1, 0.9, 0.1, 0.0).recommendation == "Reduce empty/placeholder code (LDR)."
    )
    assert gate.evaluate(0.9, 0.1, 0.1, 0.0).recommendation == "Remove unused imports (DDC)."
    assert gate.evaluate(0.9, 0.9, 5.0, 0.0).recommendation == "Eliminate buzzword inflation (jsd)."


def test_two_failures_keep_the_gate_order():
    d = _gate().evaluate(ldr_score=0.1, ddc_ratio=0.9, inflation_score=0.1, pattern_penalty=30)
    assert d.recommendation == "Reduce empty/placeholder code (LDR), fix structural patterns (ove)."


def test_all_four_failing_is_the_sentence_it_always_was():
    d = _gate().evaluate(ldr_score=0.1, ddc_ratio=0.1, inflation_score=5.0, pattern_penalty=30)
    assert d.recommendation == ALL_FOUR


def test_a_blocking_halt_keeps_its_own_advice():
    d = _gate().evaluate(None, None, None, None, blocking=("nothing measured",))
    assert d.status == "HALT"
    assert d.recommendation == (
        "Fix what stopped the measurement (see scan coverage), then run the gate again."
    )


def test_a_pass_has_no_recommendation():
    assert _gate().evaluate(0.9, 0.9, 0.1, 0.0).recommendation is None
