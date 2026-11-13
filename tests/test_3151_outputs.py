"""3.15.1: every finding reaches every human report with its fix.

Root cause (.internal RCA): the analysis was right; two generations of report
code coexisted. --details (text and rich) listed findings only for files in a
deficit band, so "9 findings open, review them" came with no list; and the
JS/TS regex fallback (default install) and two Go rules produced findings
with no fix, shown as "fix: MISSING" in every report.
"""

import io
import re
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector
from slop_detector.languages import go_analyzer, js_analyzer
from slop_detector.renderer_text import generate_text_report
from slop_detector.report_view import build_report_view, short_path

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_project"

JS_ALL_RULES = (
    "var a = 1;\n"
    "console.log(a);\n"
    "const f = () => {};\n"
    "if (a == 1) {\n"
    "  if (a) {\n    if (a) {\n      if (a) {\n        if (a) {\n          a = 2;\n"
    "        }\n      }\n    }\n  }\n}\n"
)
TS_ANY = "function g(x: any) {\n  return x;\n}\n"
GO_ALL_RULES = (
    'package main\n\nimport "fmt"\n\n'
    "// TODO: finish\n"
    "func stub() {}\n\n"
    "func main() {\n"
    '\tfmt.Println("x")\n'
    "\t_ = doit()\n"
    '\tpanic("no")\n'
    "}\n"
)


def _regex_js(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    is_ts = path.suffix in (".ts", ".tsx")
    return js_analyzer.JSAnalyzer()._analyze_regex(
        str(path), text, "typescript" if is_ts else "javascript", is_ts
    )


def test_every_js_regex_fallback_finding_has_a_fix(tmp_path):
    issues = _regex_js(tmp_path, "a.js", JS_ALL_RULES).issues
    issues += _regex_js(tmp_path, "b.ts", TS_ANY).issues
    rules = {i.pattern_id for i in issues}
    assert rules >= {
        "js_var_usage",
        "js_console_log",
        "js_empty_arrow",
        "js_double_equals",
        "js_callback_hell",
        "js_any_type",
    }, rules  # the case this control is about: every regex rule fires
    missing = sorted({i.pattern_id for i in issues if not i.suggestion})
    assert not missing, missing


def test_every_go_finding_has_a_fix(tmp_path):
    path = tmp_path / "main.go"
    path.write_text(GO_ALL_RULES, encoding="utf-8")
    issues = go_analyzer.GoAnalyzer()._analyze_regex(str(path), GO_ALL_RULES).issues
    rules = {i.pattern_id for i in issues}
    assert {"go_todo_comment", "go_fmt_print", "go_empty_func"} <= rules, rules
    missing = sorted({i.pattern_id for i in issues if not i.suggestion})
    assert not missing, missing


@pytest.mark.skipif(not js_analyzer._TS_AVAILABLE, reason="tree-sitter not installed")
def test_js_fallback_fix_equals_the_tree_sitter_fix(tmp_path):
    # one fix text per rule, whichever parser found it
    path = tmp_path / "a.js"
    path.write_text(JS_ALL_RULES, encoding="utf-8")
    regex = {i.pattern_id: i.suggestion for i in _regex_js(tmp_path, "a.js", JS_ALL_RULES).issues}
    ast_issues = js_analyzer.JSAnalyzer().analyze(str(path)).issues
    for issue in ast_issues:
        if issue.pattern_id in regex:
            assert regex[issue.pattern_id] == issue.suggestion, issue.pattern_id


def _demo():
    result = SlopDetector(read_only=True).analyze_project(str(DEMO))
    return result, build_report_view(result)


def test_text_details_list_every_finding_and_candidate():
    result, view = _demo()
    text = generate_text_report(result)
    assert view.findings and view.candidates  # the demo has both
    for item in view.findings + view.candidates:
        where = f"{short_path(item.file, result.project_path)}:{item.line}"
        assert re.search(re.escape(where) + r"\s+" + re.escape(item.rule), text), (where, item.rule)
    for item in view.findings:
        if item.suggestion:
            assert item.suggestion in text, item.rule


def test_rich_details_list_every_finding_and_candidate(monkeypatch):
    rich_console = pytest.importorskip("rich.console")
    from slop_detector import renderer_rich

    buffer = io.StringIO()
    monkeypatch.setattr(
        renderer_rich,
        "Console",
        lambda *a, **k: rich_console.Console(file=buffer, width=400, color_system=None),
    )
    result, view = _demo()
    renderer_rich.print_rich_report(result)
    out = buffer.getvalue()
    for item in view.findings + view.candidates:
        assert item.rule in out, item.rule
    assert "No deficit detected" not in out
