"""v3.9.3 JS contract: one JS pass, one JSON document, a disclosed analysis mode.

Found by the cross-domain precision study on the published 3.9.2:

- Project analysis runs the JS/TS pass, then `--js` ran a second pass
  (`run_optional_features` -> `_run_js_analysis`) that ignored the exclusions
  and printed a text block after the JSON, so `--json --js` stdout was not
  JSON (also with no JS file at all) and the two passes disagreed on the file
  count (typia: 2,216 vs 1,500).
- Each JS result carries `ast_mode`, but no project-level surface said whether
  JS was analyzed with tree-sitter or the regex fallback; on hermes-agent the
  project score is 33.35 in regex mode and 39.72 with tree-sitter.
"""

from __future__ import annotations

import json
from pathlib import Path

from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.languages import js_analyzer
from slop_detector.languages.js_analyzer import JSAnalyzer

JS = "function add(a, b) {\n  return a + b;\n}\n"
PY = "def double(x):\n    total = x * 2\n    return total\n"


def _project(root: Path, with_js: bool = True) -> Path:
    (root / "app.py").write_text(PY, encoding="utf-8")
    if with_js:
        (root / "src").mkdir()
        (root / "src" / "app.js").write_text(JS, encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "app.test.js").write_text(JS, encoding="utf-8")
    return root


def _record_js_calls(monkeypatch, root: Path) -> list:
    calls = []
    original = JSAnalyzer.analyze

    def recording(self, file_path):
        calls.append(Path(file_path).resolve().relative_to(root.resolve()).as_posix())
        return original(self, file_path)

    monkeypatch.setattr(JSAnalyzer, "analyze", recording)
    return calls


def test_json_js_stdout_is_one_json_document(tmp_path, capsys):
    root = _project(tmp_path)
    assert main([str(root), "--json", "--js", "--no-history"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert [Path(f["file_path"]).name for f in payload["js_file_results"]] == ["app.js"]


def test_json_js_without_js_files_is_one_json_document(tmp_path, capsys):
    root = _project(tmp_path, with_js=False)
    assert main([str(root), "--json", "--js", "--no-history"]) == 0
    json.loads(capsys.readouterr().out)


def test_each_js_file_is_analyzed_once_json(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path)
    calls = _record_js_calls(monkeypatch, root)
    main([str(root), "--json", "--js", "--no-history"])
    capsys.readouterr()
    assert calls == ["src/app.js"]


def test_each_js_file_is_analyzed_once_text(tmp_path, monkeypatch, capsys):
    """Text mode renders the same project JS results: excluded test files are
    not analyzed by a second pass."""
    root = _project(tmp_path)
    calls = _record_js_calls(monkeypatch, root)
    main([str(root), "--js", "--no-history"])
    capsys.readouterr()
    assert calls == ["src/app.js"]


def _expected_mode(js_results) -> str:
    modes = {bool(r.ast_mode) for r in js_results}
    if modes == {True}:
        return "tree_sitter_ast"
    if modes == {False}:
        return "regex_fallback"
    return "mixed"


def test_project_discloses_js_analysis_mode(tmp_path):
    result = SlopDetector(read_only=True).analyze_project(str(_project(tmp_path)))
    javascript = result.scan_coverage["analysis_modes"]["javascript"]
    assert javascript["mode"] == _expected_mode(result.js_file_results)
    assert javascript["ast_available"] is js_analyzer._TS_AVAILABLE


def test_regex_fallback_is_disclosed(tmp_path, monkeypatch):
    monkeypatch.setattr(js_analyzer, "_TS_AVAILABLE", False)
    result = SlopDetector(read_only=True).analyze_project(str(_project(tmp_path)))
    assert [r.ast_mode for r in result.js_file_results] == [False]
    javascript = result.scan_coverage["analysis_modes"]["javascript"]
    assert javascript == {
        "mode": "regex_fallback",
        "ast_available": False,
        # v3.10: the checks the fallback cannot run
        "not_measured": ["js_dead_code", "js_god_function", "max_complexity"],
    }


def test_analysis_mode_is_in_the_json(tmp_path, capsys):
    root = _project(tmp_path)
    main([str(root), "--json", "--no-history"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["scan_coverage"]["analysis_modes"]["javascript"]["mode"] in (
        "tree_sitter_ast",
        "regex_fallback",
        "mixed",
    )
