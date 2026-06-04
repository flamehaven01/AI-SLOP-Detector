"""Tests for deterministic framework boilerplate masking."""

from slop_detector.core import SlopDetector
from slop_detector.languages.js_analyzer import JSAnalyzer


def test_pytest_noop_hook_is_masked_before_suppression_ledger():
    detector = SlopDetector()
    code = """
# slop-disable-next-line pass_placeholder
def setup_module(module):
    pass
"""

    result = detector.analyze_code_string(code, filename="tests/conftest.py")

    assert all(issue.pattern_id != "pass_placeholder" for issue in result.pattern_issues)
    assert result.suppression_ledger == []
    assert any(item.pattern_id == "pass_placeholder" for item in result.masked_issues)


def test_python_test_masking_does_not_hide_critical_findings():
    detector = SlopDetector()
    code = """
def test_example():
    try:
        risky()
    except:
        pass
"""

    result = detector.analyze_code_string(code, filename="tests/test_example.py")

    assert any(issue.pattern_id == "bare_except" for issue in result.pattern_issues)


def test_js_console_log_is_masked_in_test_file(tmp_path):
    path = tmp_path / "widget.test.js"
    path.write_text("console.log('debug');\n", encoding="utf-8")

    result = JSAnalyzer().analyze(str(path))

    assert result.console_log_count == 0
    assert all(issue.pattern_id != "js_console_log" for issue in result.issues)
    assert any(item.pattern_id == "js_console_log" for item in result.masked_issues)


def test_js_empty_hook_is_masked_in_test_file(tmp_path):
    path = tmp_path / "hooks.spec.ts"
    path.write_text("beforeEach(() => {});\n", encoding="utf-8")

    result = JSAnalyzer().analyze(str(path))

    assert result.empty_arrow_count == 0
    assert all(issue.pattern_id != "js_empty_arrow" for issue in result.issues)
    assert any(item.pattern_id == "js_empty_arrow" for item in result.masked_issues)


def test_js_console_log_is_not_masked_in_non_test_file(tmp_path):
    path = tmp_path / "widget.js"
    path.write_text("console.log('debug');\n", encoding="utf-8")

    result = JSAnalyzer().analyze(str(path))

    assert result.console_log_count == 1
    assert any(issue.pattern_id == "js_console_log" for issue in result.issues)
    assert result.masked_issues == []
