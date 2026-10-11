"""v3.10 P3-3: JS findings point at their evidence.

Measured: js_callback_hell was placed at line 1, column 0 in both modes, and a
function assigned to a variable (`const run = () => {}`) was named
"(anonymous)" although the declarator names it.

Contract (finding count, severity and score unchanged; location and name only):
- AST mode: js_callback_hell is at the start of the first function (in source
  order) whose nesting reaches the file's maximum depth.
- Regex mode: js_callback_hell is at the first line where the counted
  nesting reaches its maximum (the regex counts braces; it knows no function).
- A function expression or arrow function that is the value of a variable
  declarator takes the declarator's name; with no such evidence it stays
  "(anonymous)".
"""

from __future__ import annotations

import pytest

import slop_detector.languages.js_analyzer as js_analyzer_module
from slop_detector.languages.js_analyzer import JSAnalyzer

requires_ts = pytest.mark.skipif(
    not js_analyzer_module._TS_AVAILABLE,
    reason="tree-sitter-javascript not installed (optional [js] dep)",
)

NESTED = """function shallow() {
  return 1;
}

const runQueue = () => {
  load(function () {
    step(function () {
      more(function () {
        if (ready) {
          finish();
        }
      });
    });
  });
};
"""


def _hell(tmp_path, source=NESTED):
    path = tmp_path / "queue.js"
    path.write_text(source, encoding="utf-8")
    result = JSAnalyzer().analyze(str(path))
    hells = [i for i in result.issues if i.pattern_id == "js_callback_hell"]
    assert len(hells) == 1
    return result, hells[0]


TWICE = NESTED + NESTED.replace("shallow", "again").replace("runQueue", "q2")


@requires_ts
def test_ast_callback_hell_is_at_the_deepest_function(tmp_path):
    _, issue = _hell(tmp_path)
    assert (issue.line, issue.column) == (5, 17)  # `() => {` of runQueue


@requires_ts
def test_ast_keeps_the_first_function_at_the_maximum(tmp_path):
    _, issue = _hell(tmp_path, TWICE)
    assert (issue.line, issue.column) == (5, 17)


def test_regex_callback_hell_is_at_the_deepest_line(tmp_path, monkeypatch):
    monkeypatch.setattr(js_analyzer_module, "_TS_AVAILABLE", False)
    _, issue = _hell(tmp_path)
    assert issue.line == 9  # `if (ready) {`: the fifth counted level


def test_regex_keeps_the_first_line_at_the_maximum(tmp_path, monkeypatch):
    monkeypatch.setattr(js_analyzer_module, "_TS_AVAILABLE", False)
    _, issue = _hell(tmp_path, TWICE)
    assert issue.line == 9


@requires_ts
def test_declarator_names_the_function(tmp_path):
    result, _ = _hell(tmp_path)
    names = [(m.name, m.start_line) for m in result.function_metrics]
    assert ("shallow", 1) in names
    assert ("runQueue", 5) in names
    # The callbacks have no name evidence.
    assert [n for n, line in names if line in (6, 7, 8)] == ["(anonymous)"] * 3


@requires_ts
def test_no_identifier_no_name(tmp_path):
    path = tmp_path / "d.js"
    path.write_text("const [first] = function () {\n  return 1;\n};\n", encoding="utf-8")
    result = JSAnalyzer().analyze(str(path))
    assert [m.name for m in result.function_metrics] == ["(anonymous)"]


@requires_ts
def test_only_a_variable_declarator_names_a_function(tmp_path):
    # v3.10 boundary: a TypeScript class field has a name field too, but only
    # declarators are read (class fields are a v3.11 candidate).
    path = tmp_path / "w.ts"
    path.write_text("class W {\n  handle = () => {\n    return 1;\n  };\n}\n", encoding="utf-8")
    result = JSAnalyzer().analyze(str(path))
    assert [m.name for m in result.function_metrics] == ["(anonymous)"]
