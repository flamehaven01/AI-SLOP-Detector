"""Tests for Phase 3b: JSAnalyzer (regex fallback + optional AST mode)."""

from pathlib import Path

import pytest

from slop_detector.languages.js_analyzer import JSAnalyzer, JSFileAnalysis

# ---------------------------------------------------------------------------
# Skip guard for AST mode (tree-sitter optional)
# ---------------------------------------------------------------------------

try:
    import tree_sitter_javascript  # noqa: F401

    _TS_AVAILABLE = True
except ImportError:
    _TS_AVAILABLE = False

requires_ts = pytest.mark.skipif(
    not _TS_AVAILABLE, reason="tree-sitter-javascript not installed (optional [js] dep)"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_js(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


CLEAN_JS = """\
function greet(name) {
    return `Hello, ${name}!`;
}

export default greet;
"""

SLOP_JS = """\
var x = 1;
var y = 2;

function doStuff() {}
function doMoreStuff() {}

if (x == y) {
    console.log("debug");
}
"""

TYPESCRIPT_ANY = """\
function process(data: any): any {
    return data;
}

const handler = (event: any): void => {
    console.log(event);
};
"""

EMPTY_ARROWS = """\
const a = () => {};
const b = () => {};
const c = () => {};
"""


# ---------------------------------------------------------------------------
# JSAnalyzer — basic instantiation
# ---------------------------------------------------------------------------


class TestJSAnalyzerInstantiation:
    def test_instantiates_without_error(self):
        analyzer = JSAnalyzer()
        assert analyzer is not None

    def test_analyze_returns_jsfileanalysis(self, tmp_path):
        path = _write_js(tmp_path, "index.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert isinstance(result, JSFileAnalysis)

    def test_typescript_file_detected(self, tmp_path):
        path = _write_js(tmp_path, "app.ts", TYPESCRIPT_ANY)
        result = JSAnalyzer().analyze(path)
        assert result.language == "typescript"

    def test_javascript_file_detected(self, tmp_path):
        path = _write_js(tmp_path, "app.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert result.language == "javascript"

    def test_jsx_detected_as_javascript(self, tmp_path):
        path = _write_js(tmp_path, "App.jsx", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert result.language == "javascript"

    def test_tsx_detected_as_typescript(self, tmp_path):
        path = _write_js(tmp_path, "App.tsx", TYPESCRIPT_ANY)
        result = JSAnalyzer().analyze(path)
        assert result.language == "typescript"


# ---------------------------------------------------------------------------
# Line counting
# ---------------------------------------------------------------------------


class TestLineCountingRegex:
    """Line count tests use regex mode — valid even without tree-sitter."""

    def test_total_lines_correct(self, tmp_path):
        path = _write_js(tmp_path, "f.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert result.total_lines == len(CLEAN_JS.splitlines())

    def test_blank_lines_counted(self, tmp_path):
        content = "const x = 1;\n\nconst y = 2;\n"
        path = _write_js(tmp_path, "f.js", content)
        result = JSAnalyzer().analyze(path)
        assert result.blank_lines >= 1

    def test_code_lines_positive(self, tmp_path):
        path = _write_js(tmp_path, "f.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert result.code_lines > 0

    def test_ldr_between_zero_and_one(self, tmp_path):
        path = _write_js(tmp_path, "f.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert 0.0 <= result.ldr_equivalent <= 1.0


# ---------------------------------------------------------------------------
# Slop scoring
# ---------------------------------------------------------------------------


class TestSlopScoring:
    def test_clean_file_has_low_slop_score(self, tmp_path):
        path = _write_js(tmp_path, "clean.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert result.slop_score < 50

    def test_clean_file_status(self, tmp_path):
        path = _write_js(tmp_path, "clean.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert result.status in ("clean", "suspicious")

    def test_slop_file_has_higher_score(self, tmp_path):
        path_clean = _write_js(tmp_path, "clean.js", CLEAN_JS)
        path_slop = _write_js(tmp_path, "slop.js", SLOP_JS)
        clean_r = JSAnalyzer().analyze(path_clean)
        slop_r = JSAnalyzer().analyze(path_slop)
        assert slop_r.slop_score >= clean_r.slop_score

    def test_slop_score_range(self, tmp_path):
        path = _write_js(tmp_path, "s.js", SLOP_JS)
        result = JSAnalyzer().analyze(path)
        assert 0.0 <= result.slop_score <= 100.0

    def test_to_dict_serializable(self, tmp_path):
        path = _write_js(tmp_path, "f.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "slop_score" in d
        assert "ldr_equivalent" in d
        assert "issues" in d


# ---------------------------------------------------------------------------
# Issue detection (regex fallback)
# ---------------------------------------------------------------------------


class TestIssueDetectionRegex:
    def test_console_log_detected(self, tmp_path):
        content = "console.log('debug');\nconst x = 1;\n"
        path = _write_js(tmp_path, "f.js", content)
        result = JSAnalyzer().analyze(path)
        assert result.console_log_count >= 1

    def test_var_usage_detected(self, tmp_path):
        content = "var x = 1;\nvar y = 2;\n"
        path = _write_js(tmp_path, "f.js", content)
        result = JSAnalyzer().analyze(path)
        assert result.var_usage_count >= 2

    def test_empty_arrow_detected(self, tmp_path):
        path = _write_js(tmp_path, "f.js", EMPTY_ARROWS)
        result = JSAnalyzer().analyze(path)
        assert result.empty_arrow_count >= 2

    def test_double_equals_detected(self, tmp_path):
        content = "if (a == b) { return 1; }\n"
        path = _write_js(tmp_path, "f.js", content)
        result = JSAnalyzer().analyze(path)
        assert result.double_equals_count >= 1

    def test_issues_have_required_fields(self, tmp_path):
        path = _write_js(tmp_path, "f.js", SLOP_JS)
        result = JSAnalyzer().analyze(path)
        for issue in result.issues:
            d = issue.to_dict()
            assert "pattern_id" in d
            assert "severity" in d
            assert "line" in d
            assert "message" in d


# ---------------------------------------------------------------------------
# TypeScript-specific (any type) — regex and AST
# ---------------------------------------------------------------------------


class TestTypeScriptAnalysis:
    def test_any_type_detected_in_ts(self, tmp_path):
        path = _write_js(tmp_path, "app.ts", TYPESCRIPT_ANY)
        result = JSAnalyzer().analyze(path)
        assert result.any_type_count >= 1

    def test_any_type_not_detected_in_plain_js(self, tmp_path):
        # In JS mode, `: any` is not a keyword — regex may still match, but AST should skip
        content = "function f() { return 1; }\n"
        path = _write_js(tmp_path, "f.js", content)
        result = JSAnalyzer().analyze(path)
        assert result.any_type_count == 0


# ---------------------------------------------------------------------------
# AST mode tests (tree-sitter required)
# ---------------------------------------------------------------------------


@requires_ts
class TestASTMode:
    def test_ast_mode_flag_true(self, tmp_path):
        path = _write_js(tmp_path, "f.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert result.ast_mode is True

    def test_function_metrics_populated_ast(self, tmp_path):
        path = _write_js(tmp_path, "f.js", CLEAN_JS)
        result = JSAnalyzer().analyze(path)
        assert len(result.function_metrics) >= 1
        fn = result.function_metrics[0]
        assert fn.name == "greet"
        assert fn.start_line > 0

    def test_god_function_detected_ast(self, tmp_path):
        # Create a function with > 50 lines
        lines = ["function bigFn() {"] + [f"    const v{i} = {i};" for i in range(60)] + ["}"]
        content = "\n".join(lines) + "\n"
        path = _write_js(tmp_path, "big.js", content)
        result = JSAnalyzer().analyze(path)
        assert result.god_function_count >= 1

    def test_dead_code_detected_ast(self, tmp_path):
        content = "function f() {\n    return 1;\n    const x = 2;\n}\n"
        path = _write_js(tmp_path, "f.js", content)
        result = JSAnalyzer().analyze(path)
        assert result.dead_code_count >= 1


# ---------------------------------------------------------------------------
# SlopDetector integration — analyze_js_file + analyze_project JS routing
# ---------------------------------------------------------------------------


class TestSlopDetectorJSIntegration:
    def test_analyze_js_file_method(self, tmp_path):
        from slop_detector.core import SlopDetector

        path = _write_js(tmp_path, "index.js", CLEAN_JS)
        detector = SlopDetector()
        result = detector.analyze_js_file(path)
        assert isinstance(result, JSFileAnalysis)
        assert result.file_path == path

    def test_analyze_project_includes_js_results(self, tmp_path):
        from slop_detector.core import SlopDetector

        (tmp_path / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
        _write_js(tmp_path, "index.js", CLEAN_JS)
        detector = SlopDetector()
        project = detector.analyze_project(str(tmp_path))
        assert len(project.js_file_results) == 1
        assert isinstance(project.js_file_results[0], JSFileAnalysis)

    def test_analyze_project_no_js_files(self, tmp_path):
        from slop_detector.core import SlopDetector

        (tmp_path / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
        detector = SlopDetector()
        project = detector.analyze_project(str(tmp_path))
        assert project.js_file_results == []

    def test_project_to_dict_includes_js_field(self, tmp_path):
        from slop_detector.core import SlopDetector

        (tmp_path / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
        _write_js(tmp_path, "app.ts", TYPESCRIPT_ANY)
        detector = SlopDetector()
        project = detector.analyze_project(str(tmp_path))
        d = project.to_dict()
        assert "js_file_results" in d
