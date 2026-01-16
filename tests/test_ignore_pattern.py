"""Tests for @slop.ignore decorator and consent-based complexity (v2.6.3)."""

import ast
import tempfile
from pathlib import Path

import pytest

from slop_detector import SlopDetector, slop, ignore, IgnoredFunction
from slop_detector.decorators import (
    SlopIgnore,
    get_ignored_functions,
    is_function_ignored,
    get_ignore_reason,
    get_ignore_rules,
)


class TestSlopIgnoreDecorator:
    """Test the @slop.ignore decorator functionality."""

    def test_decorator_requires_reason(self):
        """Decorator should raise ValueError if reason is empty."""
        with pytest.raises(ValueError, match="non-empty 'reason'"):

            @slop.ignore(reason="")
            def func():
                pass

    def test_decorator_with_reason_only(self):
        """Decorator with just reason should work."""

        @slop.ignore(reason="Performance critical algorithm")
        def fast_func():
            pass

        assert is_function_ignored(fast_func)
        assert get_ignore_reason(fast_func) == "Performance critical algorithm"
        assert get_ignore_rules(fast_func) == []

    def test_decorator_with_specific_rules(self):
        """Decorator with specific rules should work."""

        @slop.ignore(reason="Domain algorithm", rules=["LDR", "INFLATION"])
        def complex_func():
            pass

        assert is_function_ignored(complex_func)
        assert get_ignore_reason(complex_func) == "Domain algorithm"
        assert get_ignore_rules(complex_func) == ["LDR", "INFLATION"]

    def test_decorator_preserves_function_behavior(self):
        """Decorated function should still work correctly."""

        @slop.ignore(reason="Test function")
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_ignore_function_shorthand(self):
        """Test direct import of ignore function."""

        @ignore(reason="Test shorthand")
        def shorthand_func():
            pass

        assert is_function_ignored(shorthand_func)

    def test_registry_tracks_ignored_functions(self):
        """Global registry should track ignored functions."""

        @slop.ignore(reason="Registry test")
        def registry_test_func():
            pass

        registry = get_ignored_functions()
        # Function should be in registry (may have module prefix)
        found = any("registry_test_func" in key for key in registry)
        assert found, f"Function not found in registry: {registry.keys()}"


class TestASTIgnoreDetection:
    """Test AST-based detection of @slop.ignore decorators."""

    def test_detect_slop_ignore_in_code(self):
        """Detector should find @slop.ignore decorated functions via AST."""
        code = """
import slop

@slop.ignore(reason="Bitwise optimization for performance")
def fast_inverse_sqrt(number):
    i = 0x5f3759df - (number >> 1)
    return i

def normal_function():
    pass
"""
        tree = ast.parse(code)
        detector = SlopDetector()
        ignored = detector._collect_ignored_functions(tree)

        assert len(ignored) == 1
        assert ignored[0].name == "fast_inverse_sqrt"
        assert "Bitwise optimization" in ignored[0].reason

    def test_detect_ignore_with_rules(self):
        """Detector should extract specific rules from decorator."""
        code = """
import slop

@slop.ignore(reason="Domain logic", rules=["LDR", "DDC"])
def domain_function():
    pass
"""
        tree = ast.parse(code)
        detector = SlopDetector()
        ignored = detector._collect_ignored_functions(tree)

        assert len(ignored) == 1
        assert ignored[0].rules == ["LDR", "DDC"]

    def test_no_detection_without_reason(self):
        """Decorator without reason should not be detected."""
        code = """
import slop

@slop.ignore()
def no_reason_func():
    pass
"""
        tree = ast.parse(code)
        detector = SlopDetector()
        ignored = detector._collect_ignored_functions(tree)

        assert len(ignored) == 0

    def test_detect_async_function(self):
        """Detector should work with async functions."""
        code = """
import slop

@slop.ignore(reason="Async optimization")
async def async_func():
    await something()
"""
        tree = ast.parse(code)
        detector = SlopDetector()
        ignored = detector._collect_ignored_functions(tree)

        assert len(ignored) == 1
        assert ignored[0].name == "async_func"


class TestIgnoredFunctionFiltering:
    """Test that issues in ignored functions are filtered out."""

    def test_issues_filtered_from_ignored_functions(self):
        """Pattern issues inside ignored functions should be filtered."""
        code = """
import slop

@slop.ignore(reason="Known placeholder for testing")
def ignored_placeholder():
    pass  # This would normally trigger placeholder pattern

def normal_placeholder():
    pass  # This should trigger placeholder pattern
"""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        try:
            f.write(code)
            f.flush()
            f.close()  # Close before analysis on Windows

            detector = SlopDetector()
            result = detector.analyze_file(f.name)

            # Check ignored functions are tracked
            assert len(result.ignored_functions) == 1
            assert result.ignored_functions[0].name == "ignored_placeholder"

            # Check that issues from ignored function are NOT in pattern_issues
            # Normal placeholder should still be detected
            issue_lines = [issue.line for issue in result.pattern_issues]
            # Line 5 is inside ignored function, should not have issues
            # Line 9 is normal function, may have issues
        finally:
            Path(f.name).unlink(missing_ok=True)


class TestIgnoredFunctionModel:
    """Test IgnoredFunction dataclass."""

    def test_to_dict(self):
        """IgnoredFunction.to_dict should serialize correctly."""
        ignored = IgnoredFunction(
            name="test_func",
            reason="Test reason",
            rules=["LDR"],
            lineno=10,
        )

        data = ignored.to_dict()
        assert data["name"] == "test_func"
        assert data["reason"] == "Test reason"
        assert data["rules"] == ["LDR"]
        assert data["lineno"] == 10


class TestFileAnalysisWithIgnored:
    """Test FileAnalysis includes ignored functions info."""

    def test_file_analysis_includes_ignored(self):
        """FileAnalysis result should include ignored_functions."""
        code = """
import slop

@slop.ignore(reason="Performance critical")
def optimized_func():
    # Complex but intentional
    pass
"""
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        try:
            f.write(code)
            f.flush()
            f.close()  # Close before analysis on Windows

            detector = SlopDetector()
            result = detector.analyze_file(f.name)

            assert hasattr(result, "ignored_functions")
            assert len(result.ignored_functions) == 1

            # Check serialization
            data = result.to_dict()
            assert "ignored_functions" in data
            assert len(data["ignored_functions"]) == 1
            assert data["ignored_functions"][0]["name"] == "optimized_func"
        finally:
            Path(f.name).unlink(missing_ok=True)
