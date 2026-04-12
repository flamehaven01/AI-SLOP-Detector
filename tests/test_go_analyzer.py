"""
Tests for GoAnalyzer (Phase 3c) — regex fallback mode.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from slop_detector.languages.go_analyzer import (
    GOD_FUNCTION_LINES,
    GoAnalyzer,
    GoFileAnalysis,
    GoIssue,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer():
    return GoAnalyzer()


def write_go(tmp_path: Path, name: str, content: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# GoIssue
# ---------------------------------------------------------------------------


class TestGoIssue:
    def test_to_dict_shape(self):
        issue = GoIssue("go_panic", "medium", 10, "panic call", "Return error instead")
        d = issue.to_dict()
        assert d["pattern_id"] == "go_panic"
        assert d["severity"] == "medium"
        assert d["line"] == 10
        assert d["message"] == "panic call"
        assert d["suggestion"] == "Return error instead"

    def test_to_dict_no_suggestion(self):
        issue = GoIssue("go_todo_comment", "low", 5, "TODO found")
        assert issue.to_dict()["suggestion"] is None


# ---------------------------------------------------------------------------
# GoFileAnalysis
# ---------------------------------------------------------------------------


class TestGoFileAnalysis:
    def test_to_dict_keys(self, tmp_path):
        fa = GoFileAnalysis(
            file_path="x.go",
            total_lines=10,
            code_lines=8,
            comment_lines=1,
            blank_lines=1,
            ldr_equivalent=0.8,
        )
        d = fa.to_dict()
        required = {
            "file_path",
            "total_lines",
            "code_lines",
            "ldr_equivalent",
            "slop_score",
            "status",
            "issues",
            "god_function_count",
            "empty_func_count",
            "panic_count",
            "fmt_print_count",
            "ignored_error_count",
            "max_function_lines",
            "ast_mode",
        }
        assert required.issubset(d.keys())

    def test_ldr_rounded(self, tmp_path):
        fa = GoFileAnalysis(
            file_path="x.go",
            total_lines=3,
            code_lines=1,
            comment_lines=1,
            blank_lines=1,
            ldr_equivalent=1 / 3,
        )
        assert fa.to_dict()["ldr_equivalent"] == round(1 / 3, 4)


# ---------------------------------------------------------------------------
# GoAnalyzer — basic
# ---------------------------------------------------------------------------


class TestGoAnalyzerBasic:
    def test_returns_go_file_analysis(self, analyzer, tmp_path):
        fp = write_go(tmp_path, "hello.go", "package main\n\nfunc main() {\n}\n")
        result = analyzer.analyze(fp)
        assert isinstance(result, GoFileAnalysis)

    def test_nonexistent_file(self, analyzer):
        result = analyzer.analyze("/nonexistent/path/file.go")
        assert result.total_lines == 0
        assert result.slop_score == 0.0

    def test_empty_file(self, analyzer, tmp_path):
        fp = write_go(tmp_path, "empty.go", "")
        result = analyzer.analyze(fp)
        assert result.total_lines == 0
        assert result.slop_score == 0.0

    def test_clean_file_no_issues(self, analyzer, tmp_path):
        code = """\
package main

import "fmt"

// greet returns a greeting message.
func greet(name string) string {
    return "Hello, " + name
}

func main() {
    msg := greet("world")
    fmt.Println(msg)
}
"""
        fp = write_go(tmp_path, "clean.go", code)
        result = analyzer.analyze(fp)
        assert isinstance(result, GoFileAnalysis)
        # fmt.Println present but otherwise clean
        assert result.fmt_print_count == 1

    def test_line_counts(self, analyzer, tmp_path):
        code = "package main\n\n// comment\nfunc main() {\n}\n"
        fp = write_go(tmp_path, "counts.go", code)
        result = analyzer.analyze(fp)
        assert result.total_lines == 5
        assert result.blank_lines >= 1
        assert result.comment_lines >= 1


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------


class TestGoPatterns:
    def test_empty_func_detection(self, analyzer, tmp_path):
        code = "package main\n\nfunc doNothing() {}\n"
        fp = write_go(tmp_path, "stub.go", code)
        result = analyzer.analyze(fp)
        assert result.empty_func_count >= 1
        ids = [i.pattern_id for i in result.issues]
        assert "go_empty_func" in ids

    def test_fmt_print_detection(self, analyzer, tmp_path):
        code = 'package main\nimport "fmt"\nfunc main() {\n    fmt.Println("debug")\n    fmt.Printf("%v", 1)\n}\n'
        fp = write_go(tmp_path, "debug.go", code)
        result = analyzer.analyze(fp)
        assert result.fmt_print_count == 2

    def test_panic_detection(self, analyzer, tmp_path):
        code = 'package main\nfunc run() {\n    panic("oops")\n}\n'
        fp = write_go(tmp_path, "panic.go", code)
        result = analyzer.analyze(fp)
        assert result.panic_count == 1
        ids = [i.pattern_id for i in result.issues]
        assert "go_panic" in ids

    def test_ignored_error_detection(self, analyzer, tmp_path):
        code = "package main\nfunc run() {\n    _ = doThing()\n}\n"
        fp = write_go(tmp_path, "ignore_err.go", code)
        result = analyzer.analyze(fp)
        assert result.ignored_error_count >= 1
        ids = [i.pattern_id for i in result.issues]
        assert "go_ignored_error" in ids

    def test_todo_comment_detection(self, analyzer, tmp_path):
        code = "package main\n\n// TODO: implement this\nfunc stub() {}\n"
        fp = write_go(tmp_path, "todo.go", code)
        result = analyzer.analyze(fp)
        ids = [i.pattern_id for i in result.issues]
        assert "go_todo_comment" in ids

    def test_fixme_comment_detection(self, analyzer, tmp_path):
        code = "package main\n\n// FIXME: broken\nfunc broken() {}\n"
        fp = write_go(tmp_path, "fixme.go", code)
        result = analyzer.analyze(fp)
        ids = [i.pattern_id for i in result.issues]
        assert "go_todo_comment" in ids

    def test_god_function_detection(self, analyzer, tmp_path):
        body = "\n".join(f"    _ = {i}" for i in range(GOD_FUNCTION_LINES + 5))
        code = f"package main\n\nfunc huge() {{\n{body}\n}}\n"
        fp = write_go(tmp_path, "god.go", code)
        result = analyzer.analyze(fp)
        assert result.god_function_count >= 1
        ids = [i.pattern_id for i in result.issues]
        assert "go_god_function" in ids

    def test_no_false_positive_normal_func(self, analyzer, tmp_path):
        code = "package main\n\nfunc add(a, b int) int {\n    return a + b\n}\n"
        fp = write_go(tmp_path, "normal.go", code)
        result = analyzer.analyze(fp)
        assert result.empty_func_count == 0
        assert result.god_function_count == 0


# ---------------------------------------------------------------------------
# Slop score and status
# ---------------------------------------------------------------------------


class TestGoSlopScore:
    def test_clean_file_low_score(self, analyzer, tmp_path):
        code = """\
package main

// Package main is an example.
func add(a, b int) int {
    return a + b
}

func multiply(a, b int) int {
    return a * b
}
"""
        fp = write_go(tmp_path, "math.go", code)
        result = analyzer.analyze(fp)
        assert result.slop_score < 30.0
        assert result.status == "clean"

    def test_suspicious_status(self, analyzer, tmp_path):
        code = (
            "package main\n"
            + "func a() {}\nfunc b() {}\nfunc c() {}\n"
            + "func run() {\n    _ = doThing()\n    _ = doOther()\n}\n"
        )
        fp = write_go(tmp_path, "suspicious.go", code)
        result = analyzer.analyze(fp)
        # 3 stubs + 2 ignored errors in small file → should be suspicious or critical
        assert result.slop_score > 0

    def test_to_dict_slop_score_rounded(self, analyzer, tmp_path):
        fp = write_go(tmp_path, "x.go", "package main\n")
        d = analyzer.analyze(fp).to_dict()
        assert isinstance(d["slop_score"], float)


# ---------------------------------------------------------------------------
# Integration with SlopDetector.analyze_project
# ---------------------------------------------------------------------------


class TestSlopDetectorGoIntegration:
    def test_analyze_project_includes_go_results(self, tmp_path):
        """analyze_project() must populate go_file_results for .go files."""
        (tmp_path / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        from slop_detector.core import SlopDetector

        detector = SlopDetector()
        result = detector.analyze_project(str(tmp_path))
        assert hasattr(result, "go_file_results")
        assert len(result.go_file_results) == 1
        assert result.go_file_results[0].file_path.endswith("main.go")

    def test_analyze_go_file_public_api(self, tmp_path):
        """SlopDetector.analyze_go_file() public API must work."""
        fp = str(tmp_path / "util.go")
        Path(fp).write_text("package main\nfunc noop() {}\n", encoding="utf-8")
        from slop_detector.core import SlopDetector

        detector = SlopDetector()
        result = detector.analyze_go_file(fp)
        assert isinstance(result, GoFileAnalysis)

    def test_go_results_in_to_dict(self, tmp_path):
        """ProjectAnalysis.to_dict() must contain go_file_results."""
        (tmp_path / "x.go").write_text("package main\n", encoding="utf-8")
        from slop_detector.core import SlopDetector

        detector = SlopDetector()
        result = detector.analyze_project(str(tmp_path))
        d = result.to_dict()
        assert "go_file_results" in d
        assert isinstance(d["go_file_results"], list)

    def test_python_only_project_go_results_empty(self, tmp_path):
        """Projects with no .go files should have empty go_file_results."""
        (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
        from slop_detector.core import SlopDetector

        detector = SlopDetector()
        result = detector.analyze_project(str(tmp_path))
        assert result.go_file_results == []
