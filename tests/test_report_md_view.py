"""report.md draws on the same report view as the HTML report.

3.15.0 wrote report.md from per-file Python pattern issues: JS/TS and Go
findings were missing from it, most fixes read "Review specific line ...",
and fixed text closed it ("Files with scores > 0.5 ...") whatever the scan
found. Every finding of the view appears once, at its location, with its own
fix, and the report names the tool version that wrote it.
"""

from pathlib import Path

from slop_detector import __version__
from slop_detector.core import SlopDetector
from slop_detector.renderer_markdown import generate_markdown_report
from slop_detector.report_view import build_report_view, short_path

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_project"


def _demo():
    result = SlopDetector(read_only=True).analyze_project(str(DEMO))
    return result, build_report_view(result), generate_markdown_report(result)


def _finding_rows(text):
    head = text.index("## Findings")
    body = text[head:].split("\n#", 1)[0]  # up to the next heading of any level
    return [line for line in body.splitlines() if line.startswith("| ") and "`" in line]


def test_every_finding_of_the_view_is_in_report_md_with_its_own_fix():
    result, view, text = _demo()
    rows = _finding_rows(text)
    assert len(rows) == len(view.findings), (len(rows), len(view.findings))
    root = result.project_path
    for item in view.findings:
        where = f"`{short_path(item.file, root)}:{item.line}`"
        hits = [r for r in rows if where in r and f"`{item.rule}`" in r]
        assert len(hits) == 1, (where, item.rule, hits)
        if item.suggestion:
            assert item.suggestion.replace("|", "\\|") in hits[0], (item.rule, hits[0])


def test_js_findings_are_not_dropped():
    _, view, text = _demo()
    js = [i for i in view.findings if i.file.endswith(".js")]
    assert js  # the case this control is about: the demo has a JS file with findings
    for item in js:
        assert f"`{item.rule}`" in text, item.rule


def test_no_fixed_text_that_ignores_the_scan():
    _, _, text = _demo()
    assert "scores > 0.5" not in text
    assert "Global Recommendations" not in text
    assert "Review specific line for code quality improvements." not in text


def test_report_md_names_the_tool_version():
    _, _, text = _demo()
    assert f"ai-slop-detector {__version__}" in text
