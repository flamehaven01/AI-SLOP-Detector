"""Test suite for LDR calculator."""

import ast

import pytest

from slop_detector.config import Config
from slop_detector.metrics.ldr import LDRCalculator


@pytest.fixture
def ldr_calc():
    """Create LDR calculator with default config."""
    return LDRCalculator(Config())


def test_empty_function_detection(ldr_calc):
    """Test detection of empty functions."""
    code = """
def empty_function():
    pass

def another_empty():
    ...

def returns_none():
    return None
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should detect empty patterns
    assert result.ldr_score < 0.5


def test_real_code_high_ldr(ldr_calc):
    """Test real code has high LDR."""
    code = """
def calculate_mean(data):
    if len(data) == 0:
        raise ValueError("Empty data")
    return sum(data) / len(data)

def process_items(items):
    results = []
    for item in items:
        if item > 0:
            results.append(item * 2)
    return results
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should have high LDR
    assert result.ldr_score > 0.8
    assert result.grade in ["S++", "S", "A"]


def test_abc_interface_exception(ldr_calc):
    """Test ABC interface gets reduced penalty."""
    code = """
from abc import ABC, abstractmethod

class DataProcessor(ABC):
    @abstractmethod
    def process(self, data):
        pass

    @abstractmethod
    def validate(self, data):
        pass
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should be recognized as ABC interface
    assert result.is_abc_interface is True
    # Should have reduced penalty
    assert result.ldr_score > 0.5


def test_type_stub_file(ldr_calc):
    """Test .pyi files are handled correctly."""
    code = """
def function(x: int) -> str: ...
class MyClass: ...
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.pyi", code, tree)

    # Should recognize as type stub
    assert result.is_type_stub is True


def test_empty_file(ldr_calc):
    """Test handling of empty file."""
    code = ""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    assert result.total_lines == 0
    assert result.logic_lines == 0
    assert result.ldr_score == 0.0


def test_comments_only(ldr_calc):
    """Test file with only comments."""
    code = """
# This is a comment
# Another comment
# TODO: implement this
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Comments should not count as logic lines
    assert result.total_lines == 0
    assert result.logic_lines == 0


def test_mixed_empty_patterns(ldr_calc):
    """Test detection of various empty patterns."""
    code = """
def func1():
    pass

def func2():
    ...

def func3():
    raise NotImplementedError

def func4():
    # TODO: implement
    pass

def func5():
    # implementation details
    pass

def func6():
    # placeholder
    pass

def func7():
    # FIXME: broken
    pass
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should detect all empty patterns
    assert result.empty_lines > result.logic_lines


def test_truly_empty_function_variations(ldr_calc):
    """Test various truly empty function patterns."""
    code = """
def func_pass():
    pass

def func_ellipsis():
    ...

def func_return_none_explicit():
    return None

def func_return_none_implicit():
    return

def func_with_docstring_only():
    \"\"\"This has a docstring.\"\"\"
    pass

async def async_empty():
    pass
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Most functions should be detected as empty
    assert result.empty_lines >= result.logic_lines


def test_non_empty_functions(ldr_calc):
    """Test that non-empty functions are not flagged."""
    code = """
def real_logic():
    x = 10
    return x * 2

def with_loop():
    for i in range(10):
        print(i)

def with_condition():
    if True:
        return 1
    return 0
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should have high LDR
    assert result.ldr_score > 0.8
    assert result.logic_lines > result.empty_lines


def test_abc_interface_detection_complex(ldr_calc):
    """Test ABC interface detection with various patterns."""
    code = """
from abc import ABC, abstractmethod

class Interface1(ABC):
    @abstractmethod
    def method1(self):
        pass

    @abstractmethod
    def method2(self):
        pass

    def concrete_method(self):
        return "real"

class Interface2(ABC):
    @abstractmethod
    def abstract_only(self):
        ...
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should detect as ABC interface (>50% abstract methods)
    assert result.is_abc_interface is True


def test_not_abc_interface(ldr_calc):
    """Test that regular classes are not detected as ABC."""
    code = """
class RegularClass:
    def method1(self):
        return "real"

    def method2(self):
        return "also real"
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    assert result.is_abc_interface is False


def test_grade_thresholds(ldr_calc):
    """Test grade calculation for different LDR scores."""
    # High quality code
    code_high = """
def process(data):
    result = []
    for item in data:
        if item > 0:
            result.append(item * 2)
    return result
"""
    tree_high = ast.parse(code_high)
    result_high = ldr_calc.calculate("test.py", code_high, tree_high)
    assert result_high.grade in ["S++", "S", "A"]

    # Low quality (mostly empty)
    code_low = """
def empty1():
    pass

def empty2():
    pass

def empty3():
    pass

def one_line():
    return 1
"""
    tree_low = ast.parse(code_low)
    result_low = ldr_calc.calculate("test.py", code_low, tree_low)
    assert result_low.grade in ["C", "D", "F"]


def test_line_counting_accuracy(ldr_calc):
    """Test accurate line counting with various formats."""
    code = """
def func():
    x = 1
    y = 2
    z = x + y
    return z

# Comment line

def another():
    pass
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should accurately count non-empty, non-comment lines
    assert result.total_lines > 0
    assert result.logic_lines > 0
    assert result.empty_lines >= 0


def test_async_function_detection(ldr_calc):
    """Test async function handling."""
    code = """
async def async_empty():
    pass

async def async_real():
    await some_operation()
    return result
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should handle async functions correctly
    assert result.total_lines > 0


def test_nested_functions(ldr_calc):
    """Test nested function detection."""
    code = """
def outer():
    def inner_empty():
        pass

    def inner_real():
        return 42

    return inner_real()
"""
    tree = ast.parse(code)
    result = ldr_calc.calculate("test.py", code, tree)

    # Should detect nested empty functions
    assert result.ldr_score > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
