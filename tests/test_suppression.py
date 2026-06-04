"""Tests for inline comment-based suppression support."""

from slop_detector.core import SlopDetector
from slop_detector.suppression_handler import SuppressionHandler


def test_parse_comment_suppressions_supports_next_line_and_block():
    content = """# slop-disable-next-line bare_except, mutable_default_arg
# slop-disable all
# slop-enable bare_except
"""
    directives = SuppressionHandler.parse_comment_suppressions(content)

    assert len(directives) == 3
    assert directives[0].scope == "next_line"
    assert directives[0].action == "disable"
    assert directives[0].rules == ["bare_except", "mutable_default_arg"]
    assert directives[1].scope == "block"
    assert directives[1].rules == ["all"]
    assert directives[2].action == "enable"
    assert directives[2].rules == ["bare_except"]


def test_inline_suppression_next_line_records_ledger():
    detector = SlopDetector()
    code = """
def guarded():
    try:
        risky()
    # slop-disable-next-line bare_except
    except:
        pass
"""
    result = detector.analyze_code_string(code, filename="sample.py")

    assert all(issue.pattern_id != "bare_except" for issue in result.pattern_issues)
    assert any(entry.pattern_id == "bare_except" for entry in result.suppression_ledger)
    assert any(d.scope == "next_line" for d in result.suppression_directives)


def test_inline_suppression_block_disable_enable_restores_reporting():
    detector = SlopDetector()
    code = """
# slop-disable all
def muted():
    try:
        risky()
    except:
        pass

# slop-enable all
def live():
    try:
        risky_again()
    except:
        pass
"""
    result = detector.analyze_code_string(code, filename="sample.py")

    assert any(entry.pattern_id == "bare_except" for entry in result.suppression_ledger)
    assert any(issue.pattern_id == "bare_except" for issue in result.pattern_issues)


def test_project_analysis_aggregates_suppression_ledger(tmp_path):
    detector = SlopDetector()
    detector.config.config["ignore"] = []

    (tmp_path / "suppressed.py").write_text(
        """
def guarded():
    try:
        risky()
    # slop-disable-next-line bare_except
    except:
        pass
""",
        encoding="utf-8",
    )
    (tmp_path / "live.py").write_text(
        """
def live():
    try:
        risky()
    except:
        pass
""",
        encoding="utf-8",
    )

    result = detector.analyze_project(str(tmp_path))

    assert result.suppressed_issue_count >= 1
    assert len(result.suppression_ledger) == result.suppressed_issue_count


def test_high_inline_suppression_usage_emits_warning():
    detector = SlopDetector()
    code = """
def f1():
    try:
        a()
    # slop-disable-next-line bare_except
    except:
        pass

def f2():
    try:
        b()
    # slop-disable-next-line bare_except
    except:
        pass

def f3():
    try:
        c()
    # slop-disable-next-line bare_except
    except:
        pass

def f4():
    try:
        d()
    # slop-disable-next-line bare_except
    except:
        pass

def f5():
    try:
        e()
    # slop-disable-next-line bare_except
    except:
        pass
"""
    result = detector.analyze_code_string(code, filename="sample.py")

    assert any("SUPPRESSIONS: high inline suppression usage" in warning for warning in result.warnings)


def test_file_analysis_to_dict_includes_suppression_ledger():
    detector = SlopDetector()
    code = """
def guarded():
    try:
        risky()
    # slop-disable-next-line bare_except
    except:
        pass
"""
    result = detector.analyze_code_string(code, filename="sample.py")
    payload = result.to_dict()

    assert "suppression_directives" in payload
    assert "suppression_ledger" in payload
    assert payload["suppression_ledger"][0]["pattern_id"] == "bare_except"
