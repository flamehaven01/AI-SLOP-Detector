"""Regex readers judge code, not the text inside strings or comments.

DF_S1 (2026-11-14) found three false positives: the JS/TS regex fallback
read console.log(...) and ": any" inside string literals, and the Go regex
reader read fmt.Println(...) and panic(...) inside a string, which made a
6-line file score 100 and fail the hard gate. A line marked
`// expect:<rule>` must report that rule; no other line may report a code
rule. The markers are comments, so they also test that comments are not code.
"""

import pytest

from slop_detector.languages import js_analyzer
from slop_detector.languages.go_analyzer import GoAnalyzer

BS = chr(92)
JS_CODE_RULES = {
    "js_console_log",
    "js_var_usage",
    "js_double_equals",
    "js_empty_arrow",
    "js_any_type",
}
GO_CODE_RULES = {"go_fmt_print", "go_panic", "go_ignored_error"}

JS = "\n".join(
    [
        'const a = "console.log(x) in a string";',
        "const b = 'it" + BS + "'s console.log(y) == z';",
        'const q = "say ' + BS + '"hi' + BS + '" then console.log(q)";',
        "const c = `template console.log(z) and var w = 1`;",
        "/* block",
        "   console.log(q); var w = 1; a == b",
        "*/",
        "const re = /console" + BS + ".log" + BS + "(/;",
        'const d = "a == b"; // console.log(trailing comment)',
        "const multi = `first line",
        "console.log(still template) var x",
        "end`;",
        'console.log("x"); // expect:js_console_log',
        'const e = "str"; console.log(e); // expect:js_console_log',
        "const f = `value ${console.log(f)}`; // expect:js_console_log",
        "var g = 1; // expect:js_var_usage",
        "if (g == 1) { g = 2; } // expect:js_double_equals",
        "const h = () => {}; // expect:js_empty_arrow",
        "const ratio = total / count / 2;",
        "const quote = /[\"']/; console.log(quote); // expect:js_console_log",
        "const half = total / 2; console.log(half / 3); // expect:js_console_log",
        "",
    ]
)

TS = "\n".join(
    [
        'const s: string = "let candidate: any = example";',
        "const t: string = `x: any`;",
        "// const u: any = 1;",
        "export function f(x: any): string { // expect:js_any_type",
        "  return String(x);",
        "}",
        "",
    ]
)

GO = "\n".join(
    [
        "package synthetic",
        "",
        "func sample(doIt func() error) {",
        '    s := "fmt.Println(x); panic(y) _ = z"',
        "    r := `raw fmt.Println(z)",
        "panic(w) still raw`",
        "    c := '\"'",
        '    t := "escaped ' + BS + '" panic(x)"',
        "    /* fmt.Println(block)",
        "       panic(block) */",
        "    x := 1 // fmt.Println(trailing)",
        '    fmt.Println("real", s, r, c, t, x) // expect:go_fmt_print',
        '    m := "msg"; panic(m) // expect:go_panic',
        "    _ = doIt() // expect:go_ignored_error",
        "}",
        "",
    ]
)


def _expected(text, rules):
    out = set()
    for number, line in enumerate(text.splitlines(), 1):
        if "// expect:" in line:
            rule = line.split("// expect:")[1].strip()
            assert rule in rules, rule
            out.add((rule, number))
    return out


def _reported(result, rules):
    return {(i.pattern_id, i.line) for i in result.issues if i.pattern_id in rules}


def _js(tmp_path, monkeypatch, text, name, ts_available):
    monkeypatch.setattr(js_analyzer, "_TS_AVAILABLE", ts_available)
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return js_analyzer.JSAnalyzer().analyze(str(path))


@pytest.mark.parametrize("text,name", [(JS, "a.js"), (TS, "a.ts")])
def test_the_js_regex_fallback_judges_code_only(tmp_path, monkeypatch, text, name):
    result = _js(tmp_path, monkeypatch, text, name, False)
    assert _reported(result, JS_CODE_RULES) == _expected(text, JS_CODE_RULES)


@pytest.mark.parametrize("text,name", [(JS, "a.js"), (TS, "a.ts")])
def test_the_js_regex_fallback_agrees_with_tree_sitter(tmp_path, monkeypatch, text, name):
    if not js_analyzer._TS_AVAILABLE:
        pytest.skip("tree-sitter-javascript not installed")
    regex = _js(tmp_path, monkeypatch, text, name, False)
    ast = _js(tmp_path, monkeypatch, text, name, True)
    assert _reported(regex, JS_CODE_RULES) == _reported(ast, JS_CODE_RULES)


def test_the_go_reader_judges_code_only(tmp_path):
    path = tmp_path / "a.go"
    path.write_text(GO, encoding="utf-8")
    result = GoAnalyzer().analyze(str(path))
    assert _reported(result, GO_CODE_RULES) == _expected(GO, GO_CODE_RULES)


def test_go_comment_rules_still_read_comments(tmp_path):
    path = tmp_path / "t.go"
    path.write_text(
        'package p\n\n// TODO: real marker\nvar s = "// TODO: not a marker"\n', encoding="utf-8"
    )
    result = GoAnalyzer().analyze(str(path))
    assert [(i.pattern_id, i.line) for i in result.issues if i.pattern_id == "go_todo_comment"] == [
        ("go_todo_comment", 3)
    ]


def test_the_view_blanks_text_and_keeps_code_and_positions():
    from slop_detector.languages.code_view import code_lines

    source = "a = 1; /* console.log(q) it's */ b = 2" + chr(10) + 'c = "x" + y'
    view = code_lines(source, "js")
    comment = "/* console.log(q) it's */"
    assert view == ["a = 1; " + " " * len(comment) + " b = 2", 'c = " " + y']
    assert [len(v) for v in view] == [len(line) for line in source.splitlines()]
