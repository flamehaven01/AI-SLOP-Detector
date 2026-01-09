"""
Integration tests for real-world slop detection on test cases.
"""

import tempfile
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector
from slop_detector.models import SlopStatus

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"


@pytest.fixture
def detector():
    """Create detector with default config."""
    return SlopDetector()


def test_case_1_ai_slop(detector):
    """
    Test Case 1: AI Slop with empty functions and buzzwords.

    Expected issues:
    - High inflation (many buzzwords)
    - Low LDR (many empty functions)
    - Pattern issues (bare except, TODO, FIXME, XXX)
    """
    test_file = CORPUS_DIR / "test_case_1_ai_slop.py"

    result = detector.analyze_file(str(test_file))

    # Should detect as slop
    assert result.status in [
        SlopStatus.CRITICAL_DEFICIT,
        SlopStatus.SUSPICIOUS,
        SlopStatus.INFLATED_SIGNAL,
    ]

    # High inflation due to buzzwords
    assert (
        result.inflation.inflation_score > 0.5
    ), f"Inflation too low: {result.inflation.inflation_score:.2f}"

    # Low LDR due to empty functions
    assert result.ldr.ldr_score < 0.5, f"LDR too high: {result.ldr.ldr_score:.2f}"

    # Should detect multiple pattern issues
    assert (
        len(result.pattern_issues) >= 3
    ), f"Expected >= 3 pattern issues, got {len(result.pattern_issues)}"

    # Check for specific patterns
    pattern_ids = [issue.pattern_id for issue in result.pattern_issues]
    assert any("bare_except" in pid for pid in pattern_ids), "Should detect bare except"

    # High deficit score
    assert result.deficit_score > 30, f"Deficit score too low: {result.deficit_score:.2f}"

    # Should have warnings
    assert len(result.warnings) > 0, "Should generate warnings"

    print(f"\n[TEST CASE 1] AI Slop Detection:")
    print(f"  Status: {result.status.value}")
    print(f"  Deficit Score: {result.deficit_score:.1f}/100")
    print(f"  LDR: {result.ldr.ldr_score:.2%} (logic density)")
    print(f"  Inflation: {result.inflation.inflation_score:.2f}x")
    print(f"  DDC: {result.ddc.usage_ratio:.2%} (import usage)")
    print(f"  Patterns: {len(result.pattern_issues)} issues found")
    print(f"  Jargon: {result.inflation.jargon_count} buzzwords")
    print(f"  Warnings: {len(result.warnings)}")


def test_case_2_fake_docs(detector):
    """
    Test Case 2: Fake documentation with overhyped claims.

    Expected issues:
    - Very high inflation (excessive buzzwords in docs)
    - Moderate LDR (simple implementations)
    - Mutable default argument pattern
    """
    test_file = CORPUS_DIR / "test_case_2_fake_docs.py"

    result = detector.analyze_file(str(test_file))

    # Should detect inflated signal
    assert result.status in [
        SlopStatus.INFLATED_SIGNAL,
        SlopStatus.SUSPICIOUS,
        SlopStatus.CRITICAL_DEFICIT,
    ]

    # Very high inflation - lots of buzzwords in docstrings
    assert (
        result.inflation.inflation_score > 1.0
    ), f"Inflation should be > 1.0, got {result.inflation.inflation_score:.2f}"

    # Many jargon terms
    assert (
        result.inflation.jargon_count > 10
    ), f"Expected > 10 jargon terms, got {result.inflation.jargon_count}"

    # Should detect mutable default
    pattern_ids = [issue.pattern_id for issue in result.pattern_issues]
    assert any("mutable" in pid for pid in pattern_ids), "Should detect mutable default"

    print(f"\n[TEST CASE 2] Fake Documentation:")
    print(f"  Status: {result.status.value}")
    print(f"  Deficit Score: {result.deficit_score:.1f}/100")
    print(f"  LDR: {result.ldr.ldr_score:.2%}")
    print(f"  Inflation: {result.inflation.inflation_score:.2f}x [CRITICAL]")
    print(f"  Jargon Count: {result.inflation.jargon_count} buzzwords")
    print(f"  Top Jargon: {', '.join(result.inflation.jargon_found[:5])}")
    print(f"  Patterns: {len(result.pattern_issues)} issues")


def test_case_3_hyped_comments(detector):
    """
    Test Case 3: Overhyped inline comments.

    Expected issues:
    - High inflation (buzzwords in comments)
    - Multiple TODO/FIXME/XXX patterns
    - Bare except pattern
    """
    test_file = CORPUS_DIR / "test_case_3_hyped_comments.py"

    result = detector.analyze_file(str(test_file))

    # Should detect as problematic
    assert result.status in [
        SlopStatus.SUSPICIOUS,
        SlopStatus.INFLATED_SIGNAL,
        SlopStatus.CRITICAL_DEFICIT,
    ]

    # High inflation from comments
    assert (
        result.inflation.inflation_score > 0.5
    ), f"Inflation too low: {result.inflation.inflation_score:.2f}"

    # Should detect TODO/FIXME/XXX/HACK comments
    pattern_ids = [issue.pattern_id for issue in result.pattern_issues]
    comment_patterns = [
        pid for pid in pattern_ids if any(x in pid for x in ["todo", "fixme", "xxx", "hack"])
    ]
    assert (
        len(comment_patterns) >= 2
    ), f"Expected >= 2 comment patterns, got {len(comment_patterns)}"

    # Should detect bare except
    assert any("bare_except" in pid for pid in pattern_ids), "Should detect bare except"

    print(f"\n[TEST CASE 3] Overhyped Comments:")
    print(f"  Status: {result.status.value}")
    print(f"  Deficit Score: {result.deficit_score:.1f}/100")
    print(f"  LDR: {result.ldr.ldr_score:.2%}")
    print(f"  Inflation: {result.inflation.inflation_score:.2f}x")
    print(f"  Comment Issues: {len(comment_patterns)} (TODO/FIXME/XXX/HACK)")
    print(f"  Total Patterns: {len(result.pattern_issues)}")

    for issue in result.pattern_issues[:5]:  # Show first 5
        print(f"    - Line {issue.line}: {issue.pattern_id} ({issue.severity.value})")


def test_generate_markdown_report(detector, tmp_path):
    """
    Generate comprehensive markdown report for all test cases.
    """
    test_files = [
        ("Test Case 1: AI Slop", CORPUS_DIR / "test_case_1_ai_slop.py"),
        ("Test Case 2: Fake Docs", CORPUS_DIR / "test_case_2_fake_docs.py"),
        ("Test Case 3: Hyped Comments", CORPUS_DIR / "test_case_3_hyped_comments.py"),
    ]

    report_lines = [
        "# AI-SLOP Detector - Test Results Report",
        "",
        f"**Generated:** 2026-01-09",
        "",
        "---",
        "",
    ]

    for title, file_path in test_files:
        result = detector.analyze_file(file_path)

        report_lines.extend(
            [
                f"## {title}",
                "",
                f"**File:** `{Path(file_path).name}`",
                "",
                "### Summary",
                "",
                f"- **Status:** `{result.status.value.upper()}`",
                f"- **Deficit Score:** {result.deficit_score:.1f}/100",
                f"- **Logic Density (LDR):** {result.ldr.ldr_score:.2%} ({result.ldr.grade})",
                f"- **Inflation Ratio:** {result.inflation.inflation_score:.2f}x",
                f"- **Import Usage (DDC):** {result.ddc.usage_ratio:.2%}",
                "",
                "### Metrics Breakdown",
                "",
                f"| Metric | Value | Status |",
                f"|--------|-------|--------|",
                f"| Logic Lines | {result.ldr.logic_lines}/{result.ldr.total_lines} | {result.ldr.grade} |",
                f"| Empty Lines | {result.ldr.empty_lines} | - |",
                f"| Jargon Count | {result.inflation.jargon_count} | {result.inflation.status} |",
                f"| Unused Imports | {len(result.ddc.unused)} | - |",
                "",
            ]
        )

        if result.inflation.jargon_found:
            report_lines.extend(
                [
                    "### Buzzwords Detected",
                    "",
                    ", ".join(f"`{w}`" for w in result.inflation.jargon_found[:10]),
                    "",
                ]
            )

        if result.pattern_issues:
            report_lines.extend(
                [
                    "### Pattern Issues",
                    "",
                    f"Found **{len(result.pattern_issues)}** anti-patterns:",
                    "",
                ]
            )

            for issue in result.pattern_issues[:10]:  # Top 10
                severity_emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(
                    issue.severity.value, "⚪"
                )

                report_lines.append(
                    f"- {severity_emoji} **Line {issue.line}:** {issue.message} "
                    f"(`{issue.pattern_id}` - {issue.severity.value})"
                )

            report_lines.append("")

        if result.warnings:
            report_lines.extend(
                [
                    "### Warnings",
                    "",
                ]
            )
            for warning in result.warnings:
                report_lines.append(f"- ⚠️ {warning}")
            report_lines.append("")

        report_lines.extend(["", "---", ""])

    # Summary table
    report_lines.extend(
        [
            "## Overall Comparison",
            "",
            "| Test Case | Status | Deficit | LDR | Inflation | Patterns |",
            "|-----------|--------|---------|-----|-----------|----------|",
        ]
    )

    for title, file_path in test_files:
        result = detector.analyze_file(file_path)
        report_lines.append(
            f"| {title} | {result.status.value} | {result.deficit_score:.1f} | "
            f"{result.ldr.ldr_score:.2%} | {result.inflation.inflation_score:.2f}x | "
            f"{len(result.pattern_issues)} |"
        )

    # Write report
    report_path = tmp_path / "slop_detection_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    # Also write to test corpus directory for easy access
    corpus_report = CORPUS_DIR / "DETECTION_REPORT.md"
    corpus_report.write_text("\n".join(report_lines), encoding="utf-8")

    print(f"\n📊 Report generated: {corpus_report}")
    print(f"   Total test cases: {len(test_files)}")

    assert report_path.exists()
    assert len(report_lines) > 50  # Should have substantial content
