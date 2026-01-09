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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
