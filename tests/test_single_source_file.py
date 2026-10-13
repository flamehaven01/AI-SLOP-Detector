"""A single JS/TS or Go file is analyzed in its own language.

`slop-detector app.js` parsed the file as Python: every JS/TS/Go file scored
100 with "Parse error: invalid syntax", status critical_deficit, and a CI gate
on it failed. A single file in a supported non-Python language is now a
project of that one file, analyzed by its language analyzer. The engine's
analyze_file (Python only) refuses such files, and the MCP file tool reports
an unsupported_language error instead of a score.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.mcp.server import _call_tool


def _json(capsys, argv) -> dict:
    assert main(argv) == 0
    return json.loads(capsys.readouterr().out)


def test_single_js_file_is_not_a_python_parse_error(tmp_path: Path, capsys):
    path = tmp_path / "app.js"
    path.write_text("function add(a, b) {\n  return a + b;\n}\n", encoding="utf-8")
    data = _json(capsys, [str(path), "--json"])
    assert "Parse error" not in json.dumps(data)
    assert [r["file_path"] for r in data["js_file_results"]] == [str(path)]
    assert data["weighted_deficit_score"] < 100.0


def test_single_go_file_is_analyzed_as_go(tmp_path: Path, capsys):
    path = tmp_path / "main.go"
    path.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
    data = _json(capsys, [str(path), "--json"])
    assert "Parse error" not in json.dumps(data)
    assert len(data["go_file_results"]) == 1


def test_sibling_files_are_not_analyzed(tmp_path: Path, capsys):
    path = tmp_path / "app.js"
    path.write_text("function f() { return 1; }\n", encoding="utf-8")
    (tmp_path / "other.js").write_text("function g() { return 2; }\n", encoding="utf-8")
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    data = _json(capsys, [str(path), "--json"])
    assert data["total_files"] == 1


def test_single_python_file_is_still_a_file_result(tmp_path: Path, capsys):
    """Preservation: a .py target keeps the file-level contract."""
    path = tmp_path / "mod.py"
    path.write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    data = _json(capsys, [str(path), "--json"])
    assert data["file_path"] == str(path) and "js_file_results" not in data


@pytest.mark.parametrize("name", ["app.js", "view.tsx", "main.go"])
def test_analyze_file_refuses_non_python_source(tmp_path: Path, name: str):
    """The engine's Python-file entry point does not score other languages."""
    path = tmp_path / name
    path.write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not Python"):
        SlopDetector(read_only=True).analyze_file(str(path))


def test_mcp_analyze_file_on_js_is_a_tool_error_not_a_score(tmp_path: Path):
    path = tmp_path / "app.js"
    path.write_text("function f() { return 1; }\n", encoding="utf-8")
    result = _call_tool("slop_analyze_file", {"file_path": str(path)})
    assert result["isError"] is True
    assert result["structuredContent"]["error"] == "unsupported_language"
