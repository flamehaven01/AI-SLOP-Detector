"""Two JS/TS or Go findings of one rule on one line keep two ids.

`(a: any, b: any)` gives two js_any_type findings on one line. Their
locator was the line alone, so both had one id and the AI report, the work
order and --report-dir refused the whole project ("two items with one id").
A finding that shares its rule and line with another is now told apart by its
column (JS/TS) or its order on the line (Go); a finding alone on its line
keeps the line locator, and so its id.
"""

import pytest

from slop_detector.ai_report import render_ai_report
from slop_detector.core import SlopDetector
from slop_detector.finding_identity import bind_lines
from slop_detector.languages import js_analyzer
from slop_detector.languages.go_analyzer import GoIssue
from slop_detector.languages.js_analyzer import JSIssue


class _Result:
    def __init__(self, issues):
        self.issues = issues


def test_js_findings_sharing_a_rule_and_a_line_get_distinct_locators():
    issues = [
        JSIssue("js_any_type", "medium", 3, 14, "any"),
        JSIssue("js_any_type", "medium", 3, 22, "any"),
        JSIssue("js_any_type", "medium", 5, 4, "any"),
        JSIssue("js_console_log", "low", 3, 2, "log"),
    ]
    bind_lines(_Result(issues), "a\nb\nc\nd\ne\n", "0" * 64)
    assert [i.locator for i in issues] == ["L3C14", "L3C22", "L5", "L3"]


def test_go_findings_sharing_a_rule_and_a_line_get_distinct_locators():
    issues = [
        GoIssue("go_ignored_error", "medium", 7, "e"),
        GoIssue("go_ignored_error", "medium", 7, "e"),
        GoIssue("go_ignored_error", "medium", 9, "e"),
    ]
    bind_lines(_Result(issues), "\n" * 10, "0" * 64)
    assert [i.locator for i in issues] == ["L7#1", "L7#2", "L9"]


@pytest.mark.skipif(
    not js_analyzer._TS_AVAILABLE, reason="needs tree-sitter (ai-slop-detector[js])"
)
def test_a_typescript_line_with_two_any_types_is_reported(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a.ts").write_text(
        "export function f(a: any, b: any): number {\n  return 1;\n}\n", encoding="utf-8"
    )
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    text = render_ai_report(result)  # refused before: "two items with one id"
    assert text.count('"rule": "js_any_type"') == 2
