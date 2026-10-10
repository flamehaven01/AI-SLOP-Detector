"""v3.10 analysis capability: a score says which checks it could run.

Found by the cross-domain study: JS/TS without the [js] extra is analyzed by a
regex fallback that cannot find god functions, dead code or complexity
(hermes-agent: 0 god functions vs 2,703 with tree-sitter; project 33.35 vs
39.72). v3.9.3 put the mode in `scan_coverage.analysis_modes` (JSON only, JS
only); the human reports mixed fallback scores into the project score without
a word, and Go was not described at all.

Contract:
- `analysis_modes` describes every analyzed non-Python language (JavaScript,
  Go) with its mode, whether AST analysis is available, and `not_measured`:
  the checks the mode could not run (empty when nothing is missing);
- the text, rich and markdown reports name a language whose mode left checks
  unmeasured, and how to measure them.
"""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from slop_detector.core import SlopDetector
from slop_detector.languages import js_analyzer
from slop_detector.renderer_markdown import generate_markdown_report
from slop_detector.renderer_text import generate_text_report

JS = "function add(a, b) {\n  return a + b;\n}\n"
GO = "package main\n\nfunc add(a int, b int) int {\n\treturn a + b\n}\n"
PY = "def double(x):\n    total = x * 2\n    return total\n"
JS_FALLBACK_GAPS = ["js_dead_code", "js_god_function", "max_complexity"]


def _project(root: Path) -> Path:
    (root / "main.py").write_text(PY, encoding="utf-8")
    (root / "app.js").write_text(JS, encoding="utf-8")
    (root / "main.go").write_text(GO, encoding="utf-8")
    return root


def _analyze_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(js_analyzer, "_TS_AVAILABLE", False)
    return SlopDetector(read_only=True).analyze_project(str(_project(tmp_path)))


def test_fallback_states_what_it_did_not_measure(tmp_path, monkeypatch):
    result = _analyze_fallback(tmp_path, monkeypatch)

    javascript = result.scan_coverage["analysis_modes"]["javascript"]
    assert javascript == {
        "mode": "regex_fallback",
        "ast_available": False,
        "not_measured": JS_FALLBACK_GAPS,
    }


def test_go_is_described_with_nothing_missing(tmp_path, monkeypatch):
    result = _analyze_fallback(tmp_path, monkeypatch)

    go = result.scan_coverage["analysis_modes"]["go"]
    assert go["not_measured"] == []
    assert go["mode"] in {"regex", "tree_sitter_ast"}


def test_reports_name_the_unmeasured_checks(tmp_path, monkeypatch):
    result = _analyze_fallback(tmp_path, monkeypatch)

    text = generate_text_report(result)
    markdown = generate_markdown_report(result)
    buffer = io.StringIO()
    from slop_detector.renderer_rich import _render_rich_project

    _render_rich_project(Console(file=buffer, width=200, no_color=True), result)
    for report in (text, markdown, buffer.getvalue()):
        assert "javascript: regex_fallback" in report, report[-800:]
        assert "js_god_function" in report
        assert "ai-slop-detector[js]" in report


def test_fully_measured_scan_adds_no_capability_line(tmp_path):
    (tmp_path / "main.py").write_text(PY, encoding="utf-8")
    (tmp_path / "main.go").write_text(GO, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))

    assert set(result.scan_coverage["analysis_modes"]) == {"go"}
    assert "not measured" not in generate_text_report(result)
    assert "not measured" not in generate_markdown_report(result)
