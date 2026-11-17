"""Rust file score: a short file does not multiply one finding (R5, 2026-11-15).

The score weighed each stub call (todo!/unimplemented!) 25 points per 100
lines of the file, with the file's own length as the divisor: one todo!() in
a 35-line file scored 71.4, critical, and failed --ci-mode hard; in a 1-line
file it scored 100. The divisor is now at least 100 lines
(density = 100 / max(lines, 100)).

Contract:
- one stub call alone never fails the hard gate, whatever the file's length,
  also with the low logic density penalty (at most 40 + 25 = 65 < 70);
- three stub calls in a file of up to 100 lines reach 75, the critical band,
  and fail it: the gate judges several unfinished paths, not one;
- the weights (stub 25, dbg 5 per 100 lines) and the severities are unchanged.
"""

import pytest

from slop_detector.core import SlopDetector
from slop_detector.languages import rust_analyzer
from slop_detector.service.policy import evaluate_gate


def _source(lines, stubs=1, comments=0):
    """A dense file of `lines` lines whose code holds `stubs` todo!() calls."""
    if lines == 1:
        return "pub fn f() -> u8 { " + "todo!(); " * stubs + "}\n"
    body = ["pub fn f() -> u8 {"]
    body += ["    // note"] * comments
    body += ["    todo!();"] * stubs
    body += ["    let _a = 1;"] * (lines - 2 - stubs - comments)
    body += ["}"]
    assert len(body) == lines
    return "\n".join(body) + "\n"


def _scan(tmp_path, text):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "d"\n', encoding="utf-8")
    (tmp_path / "lib.rs").write_text(text, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    gate = evaluate_gate(result, mode="hard", claims_strict=False, read_only=True)
    return result.rust_file_results[0], gate


@pytest.mark.parametrize("lines", [1, 35, 36, 80, 100, 200])
def test_one_stub_call_never_fails_the_hard_gate(tmp_path, lines):
    analysis, gate = _scan(tmp_path, _source(lines))
    assert analysis.total_lines == lines
    expected = rust_analyzer.STUB_WEIGHT * 100.0 / max(lines, 100)
    if lines > 1:  # the 1-line file is all code too, but has no line to spare
        assert analysis.slop_score == pytest.approx(expected), analysis.slop_score
    assert gate.verdict.value != "fail", (lines, analysis.slop_score, gate.message)


def test_one_stub_call_with_the_low_density_penalty_does_not_fail(tmp_path):
    analysis, gate = _scan(tmp_path, _source(40, comments=36))
    assert analysis.ldr_equivalent < 0.20
    assert analysis.slop_score == pytest.approx(40.0 + rust_analyzer.STUB_WEIGHT)
    assert gate.verdict.value != "fail", gate.message


def test_three_stub_calls_in_a_short_file_fail_the_hard_gate(tmp_path):
    analysis, gate = _scan(tmp_path, _source(60, stubs=3))
    assert analysis.slop_score == pytest.approx(3 * rust_analyzer.STUB_WEIGHT)
    assert gate.verdict.value == "fail", gate.message


def test_debug_calls_keep_their_weight(tmp_path):
    text = _source(50, stubs=0).replace("    let _a = 1;\n", "    dbg!(1);\n", 1)
    analysis, _ = _scan(tmp_path, text)
    assert [i.pattern_id for i in analysis.issues] == ["rust_dbg_macro"]
    assert analysis.issues[0].severity == "medium"
    assert analysis.slop_score == pytest.approx(rust_analyzer.DEBUG_WEIGHT)
