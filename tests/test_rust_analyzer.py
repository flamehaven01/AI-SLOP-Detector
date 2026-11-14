"""Rust adapter v1: todo!/unimplemented!/dbg! calls and TODO comments.

Both parser paths (tree-sitter-rust, the [rust] extra; the token scanner,
always available) must report the same findings; calls in strings, comments
and macro_rules! bodies are not calls; test code is not reported; a file a
path cannot read fails, it is never a file with no findings.
"""

import pytest

from slop_detector.languages import rust_analyzer

POS = """pub fn parse(input: &str) -> Result<u8, Error> {
    todo!("parse the header")
}

pub fn render() {
    unimplemented!()
}

fn debug(x: u8) -> u8 {
    dbg!(x) + 1
}

// TODO: support streaming
/* FIXME handle EOF */
fn two() { todo!(); todo!() }
"""
POS_EXPECTED = {
    ("rust_todo_macro", 2),
    ("rust_unimplemented_macro", 6),
    ("rust_dbg_macro", 10),
    ("rust_todo_comment", 13),
    ("rust_todo_comment", 14),
    ("rust_todo_macro", 15),
}
SEVERITY = {
    "rust_todo_macro": "high",
    "rust_unimplemented_macro": "high",
    "rust_dbg_macro": "medium",
    "rust_todo_comment": "low",
}

NEG = """fn strings() {
    let a = "todo!() inside a string";
    let b = r#"unimplemented!() in a "raw" string"#;
    let c = b"dbg!(x)";
    let d = br##"todo!()"##;
    let e = "escaped \\" quote then todo!()";
    let ch = '!';
    let q = '"';
    let esc = '\\'';
}
fn lifetimes<'a>(x: &'a str) -> &'a str { x }
// a todo!() written in a line comment is not a call
/* outer /* nested todo!() */ still comment unimplemented!() */
macro_rules! stub { () => { todo!() }; }
fn names() { my_todo!(); let todo = 1; let dbg = todo; }
/// Notes about TODO lists are prose, not a marker
"""

TESTS = """fn prod() { dbg!(1); }
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn t() { todo!(); dbg!(2); }
    // TODO: more tests
}
#[test]
fn standalone() { unimplemented!() }
#[tokio::test]
async fn async_t() { todo!() }
#[cfg(test)]
fn helper() { dbg!(3) }
"""

UNTERMINATED = 'fn f() {\n    let s = "never closed;\n    todo!()\n}\n'


def _paths():
    return ["tokens", "ast"]


def _analyze(kind, text, tmp_path, monkeypatch, name="lib.rs"):
    if kind == "ast" and not rust_analyzer._TS_AVAILABLE:
        pytest.skip("tree-sitter-rust not installed")
    monkeypatch.setattr(rust_analyzer, "_TS_AVAILABLE", kind == "ast")
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return rust_analyzer.RustAnalyzer().analyze(str(path))


@pytest.mark.parametrize("kind", _paths())
def test_each_rule_is_reported_with_its_severity_and_fix(kind, tmp_path, monkeypatch):
    result = _analyze(kind, POS, tmp_path, monkeypatch)
    assert {(i.pattern_id, i.line) for i in result.issues} == POS_EXPECTED
    for issue in result.issues:
        assert issue.severity == SEVERITY[issue.pattern_id], issue
        assert issue.suggestion, issue  # every finding carries a fix
    assert result.ast_mode == (kind == "ast")


@pytest.mark.parametrize("kind", _paths())
def test_two_calls_on_one_line_keep_two_ids(kind, tmp_path, monkeypatch):
    result = _analyze(kind, POS, tmp_path, monkeypatch)
    on_15 = [i for i in result.issues if i.line == 15]
    assert len(on_15) == 2 and len({i.locator for i in on_15}) == 2, on_15


@pytest.mark.parametrize("kind", _paths())
def test_strings_comments_and_macro_bodies_are_not_calls(kind, tmp_path, monkeypatch):
    result = _analyze(kind, NEG, tmp_path, monkeypatch)
    assert result.issues == [], result.issues


@pytest.mark.parametrize("kind", _paths())
def test_test_code_is_not_reported(kind, tmp_path, monkeypatch):
    result = _analyze(kind, TESTS, tmp_path, monkeypatch)
    assert [(i.pattern_id, i.line) for i in result.issues] == [("rust_dbg_macro", 1)]


@pytest.mark.parametrize("kind", _paths())
def test_a_file_under_cfg_test_is_not_reported(kind, tmp_path, monkeypatch):
    result = _analyze(kind, "#![cfg(test)]\nfn f() { todo!() }\n", tmp_path, monkeypatch)
    assert result.issues == []


@pytest.mark.parametrize("kind", _paths())
def test_a_file_that_cannot_be_read_fails(kind, tmp_path, monkeypatch):
    with pytest.raises(Exception, match="Rust"):
        _analyze(kind, UNTERMINATED, tmp_path, monkeypatch)


@pytest.mark.parametrize("kind", _paths())
def test_stub_calls_raise_the_score(kind, tmp_path, monkeypatch):
    from slop_detector.diagnostic_bands import classify_deficit

    stub = _analyze(kind, POS, tmp_path, monkeypatch)
    clean = _analyze(kind, "fn f(x: u8) -> u8 {\n    x + 1\n}\n", tmp_path, monkeypatch, "c.rs")
    assert clean.slop_score == 0.0 and clean.status == "clean"
    assert stub.slop_score > 0.0
    assert stub.status == classify_deficit(stub.slop_score).value
    assert (stub.code_lines, stub.comment_lines, stub.blank_lines) == (10, 2, 3)


@pytest.mark.parametrize("kind", _paths())
def test_a_call_is_located_at_its_path_in_characters(kind, tmp_path, monkeypatch):
    text = 'fn f() { let s = "\u00e9"; core::todo!() }\n'  # e-acute: 2 bytes, 1 character
    result = _analyze(kind, text, tmp_path, monkeypatch)
    assert [(i.line, i.column) for i in result.issues] == [(1, text.index("core"))]


@pytest.mark.parametrize("kind", _paths())
def test_a_debug_call_weighs_less_than_a_stub(kind, tmp_path, monkeypatch):
    body = "fn f(x: u8) -> u8 {\n" + "    let _ = x;\n" * 97 + "    NAME!(x)\n}\n"
    scores = {}
    for name in ("todo", "dbg"):
        result = _analyze(kind, body.replace("NAME", name), tmp_path, monkeypatch, f"{name}.rs")
        assert result.total_lines == 100, result.total_lines
        scores[name] = result.slop_score
    assert scores == {"todo": rust_analyzer.STUB_WEIGHT, "dbg": rust_analyzer.DEBUG_WEIGHT}


def test_both_paths_read_a_string_as_one_literal():
    if not rust_analyzer._TS_AVAILABLE:
        pytest.skip("tree-sitter-rust not installed")
    ast, ast_comments = rust_analyzer._ast_tokens(NEG)
    scan, scan_comments = rust_analyzer._scan(NEG)

    def literals(tokens):
        return [(t.line, t.col, t.end_line) for t in tokens if t.kind == "lit"]

    def idents(tokens):
        return [(t.text, t.line, t.col) for t in tokens if t.kind == "ident"]

    assert literals(ast) == literals(scan) and len(literals(scan)) == 10
    assert idents(ast) == idents(scan)
    assert [(c.line, c.col, c.text) for c in ast_comments] == [
        (c.line, c.col, c.text) for c in scan_comments
    ]


def test_both_paths_report_the_same(tmp_path, monkeypatch):
    if not rust_analyzer._TS_AVAILABLE:
        pytest.skip("tree-sitter-rust not installed")
    text = POS + NEG + TESTS
    views = []
    for kind in ("ast", "tokens"):
        r = _analyze(kind, text, tmp_path, monkeypatch, f"{kind}.rs")
        views.append(
            (
                [
                    (i.pattern_id, i.line, i.column, i.locator, i.fingerprint, i.suggestion)
                    for i in r.issues
                ],
                (r.total_lines, r.code_lines, r.comment_lines, r.blank_lines, r.slop_score),
            )
        )
    assert views[0] == views[1]


# --- project level: the adapter is registered and reaches every surface ------


def _project(tmp_path, files):
    from slop_detector.core import SlopDetector

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "r"\n', encoding="utf-8")
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def test_cargo_target_is_excluded_for_rust_only(tmp_path):
    result = _project(
        tmp_path,
        {
            "src/lib.rs": "pub fn f() { todo!() }\n",
            "target/debug/deps/gen.rs": "pub fn g() { todo!() }\n",
            "target/helper.py": "def h(x):\n    return x + 1\n",
            "target/tool.go": "package tool\n\nfunc T() int { return 1 }\n",
        },
    )
    rust = [r.file_path.replace("\\", "/") for r in result.rust_file_results]
    assert len(rust) == 1 and rust[0].endswith("src/lib.rs"), rust
    excluded = {
        e["path"].replace("\\", "/"): e["reason"] for e in result.scan_coverage["excluded"]["files"]
    }
    assert excluded == {"target/debug/deps/gen.rs": "pattern:target/**"}, excluded
    # Cargo's target/ is a built-in exclusion of the Rust adapter, not a user's rule.
    by_source = result.scan_coverage["excluded"]["by_source"]
    assert by_source == {"default": 1, "custom": 0}, by_source
    others = result.file_results + result.go_file_results
    for name in ("target/helper.py", "target/tool.go"):
        assert any(r.file_path.replace("\\", "/").endswith(name) for r in others), name


def test_a_mixed_project_reports_rust_everywhere(tmp_path):
    from slop_detector.ai_report import render_ai_report
    from slop_detector.renderer_markdown import generate_markdown_report
    from slop_detector.renderer_text import generate_text_report
    from slop_detector.service.policy import evaluate_gate

    result = _project(
        tmp_path,
        {
            "app/core.py": "def f(x):\n    return x + 1\n",
            "web/ui.js": "var a = 1;\n",
            "svc/main.go": "package main\n\nfunc main() {}\n",
            "native/src/lib.rs": POS,
        },
    )
    analyzed = result.scan_coverage["analyzed"]
    assert analyzed["rust"] == 1 and analyzed["total"] == 4, analyzed
    assert all(f["extension"] != ".rs" for f in result.scan_coverage["unsupported"]["files"])
    for text in (
        generate_markdown_report(result),
        generate_text_report(result),
        render_ai_report(result),
    ):
        assert "rust_todo_macro" in text
    assert "rust_file_results" in result.to_dict()
    gate = evaluate_gate(result, mode="hard", claims_strict=False, read_only=False)
    assert any(
        p.replace("\\", "/").endswith("lib.rs") for p in gate.failed_files + gate.warned_files
    )


def test_a_rust_file_that_cannot_be_read_is_a_failed_file(tmp_path):
    result = _project(
        tmp_path, {"src/lib.rs": "pub fn f() { todo!() }\n", "src/bad.rs": UNTERMINATED}
    )
    failed = result.scan_coverage["failed"]
    assert failed["by_language"] == {"rust": 1}, failed
    assert failed["files"] == [
        {"path": "src/bad.rs", "language": "rust", "error_type": "RustReadError"}
    ]
    assert [r.file_path.replace("\\", "/")[-10:] for r in result.rust_file_results] == [
        "src/lib.rs"
    ]


def test_a_rust_item_holds_when_its_file_changes(tmp_path):
    from slop_detector.ai_report_md import render_ai_report_md

    result = _project(tmp_path, {"src/lib.rs": "pub fn f() { todo!() }\n"})
    (tmp_path / "src" / "lib.rs").write_text(
        "pub fn f() { todo!() }\n// edited\n", encoding="utf-8"
    )
    assert "(VOID:" in render_ai_report_md(result)
