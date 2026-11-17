"""Work order code fences, its target, and same-line findings in human tables
(R7, R8, R10, 2026-11-14 review of the actual outputs).

- Every code block of the work order was fenced ```python, Rust, Go and JS
  included: the fence now names the file's language.
- `--project .` gave the work order an empty "target:" field.
- Two findings of one rule on one line were two identical rows in report.md,
  the HTML report, --details and the terminal; they are told apart by their
  locator (an address the scan already gives, never an invented column).
"""

import re

from slop_detector.core import SlopDetector

SAME_LINE_RS = "pub fn f(flag: bool) -> u8 { if flag { todo!() } else { todo!() } }\n"


def _project(root, files):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "loc"\n', encoding="utf-8")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


FILES = {
    "src/lib.rs": SAME_LINE_RS,
    "src/one.rs": "pub fn g() -> u8 {\n    todo!()\n}\n",
    "svc/main.go": 'package main\n\nfunc main() {\n\tpanic("x")\n}\n',
    "web/a.js": "var a = 1;\n",
    "web/b.ts": "export function f(x: any): string { return String(x); }\n",
    "app/core.py": "def f(items=[]):\n    return items\n",
}


def test_work_order_fences_name_each_files_language(tmp_path):
    from slop_detector.ai_report_md import render_ai_report_md

    root = _project(tmp_path / "p", FILES)
    text = render_ai_report_md(SlopDetector(read_only=True).analyze_project(str(root)))
    fences = dict(re.findall(r"span \[FACT\]: (\S+?):\d+-\d+.*\n```(\w*)", text))
    want = {
        "src/lib.rs": "rust",
        "svc/main.go": "go",
        "web/a.js": "javascript",
        "web/b.ts": "typescript",
        "app/core.py": "python",
    }
    assert {k: fences.get(k) for k in want} == want, fences


def test_work_order_target_is_never_empty(tmp_path, monkeypatch):
    from slop_detector.ai_report_md import render_ai_report_md

    root = _project(tmp_path / "p", {"app/core.py": "def f(items=[]):\n    return items\n"})
    monkeypatch.chdir(root)
    text = render_ai_report_md(SlopDetector(read_only=True).analyze_project("."))
    target = re.search(r"^target: (.*?) \|", text, re.M)
    assert target and target.group(1).strip() == ".", text[:400]


def test_same_line_findings_are_told_apart_in_every_human_table(tmp_path):
    import io

    from rich.console import Console

    from slop_detector.renderer_html import generate_html_report
    from slop_detector.renderer_markdown import generate_markdown_report
    from slop_detector.renderer_terminal import print_summary
    from slop_detector.renderer_text import generate_text_report
    from slop_detector.report_view import build_report_view

    root = _project(tmp_path / "p", FILES)
    result = SlopDetector(read_only=True).analyze_project(str(root))
    rust = [
        r
        for r in result.rust_file_results
        if r.file_path.replace(chr(92), "/").endswith("src/lib.rs")
    ]
    locators = sorted(i.locator for i in rust[0].issues)
    assert len(locators) == 2 and locators[0] != locators[1], locators
    out = io.StringIO()
    print_summary(
        build_report_view(result), console=Console(file=out, width=240, color_system=None)
    )
    for name, text in (
        ("markdown", generate_markdown_report(result)),
        ("html", generate_html_report(result)),
        ("details", generate_text_report(result)),
        ("terminal", out.getvalue()),
    ):
        for locator in locators:
            assert f"src/lib.rs:1 ({locator})" in text, (name, locator)
        # A finding alone on its line keeps the plain location.
        assert "src/one.rs:2 (" not in text, name
        if name != "terminal":  # the terminal shows the top items only
            assert "src/one.rs:2" in text, name
