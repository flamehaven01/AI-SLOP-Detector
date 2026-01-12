"""Test docstring inflation detection."""

import ast
import pytest
from slop_detector.metrics.docstring_inflation import DocstringInflationDetector


@pytest.fixture
def detector():
    return DocstringInflationDetector(config={})


def test_critical_inflation(detector):
    """Test detection of massively inflated docstrings."""
    # Create a docstring with 20+ lines and 1 line of implementation
    docstring_content = "\n".join([f"Line {i}" for i in range(30)])
    code = f'''
def simple_add(a, b):
    """
{docstring_content}
    """
    return a + b
'''
    tree = ast.parse(code)
    result = detector.analyze("test.py", code, tree)

    assert result.inflated_count == 1
    assert result.status != "PASS"
    assert result.details[0].severity == "critical"


def test_acceptable_docstring(detector):
    """Test acceptable documentation."""
    code = '''
def complex_logic(x):
    """Calculate factorial."""
    if x <= 1:
        return 1
    result = 1
    for i in range(2, x + 1):
        result *= i
    return result
'''
    tree = ast.parse(code)
    result = detector.analyze("test.py", code, tree)

    assert result.inflated_count == 0
    assert result.status == "PASS"


def test_module_level_check(detector):
    """Test module docstring analysis."""
    code = '''"""
Module docstring.
Very long.
"""
import os
'''
    tree = ast.parse(code)
    result = detector.analyze("test.py", code, tree)

    # Implementation is just import (1 line)
    # Docstring is 3 lines -> ratio 3.0 -> critical/warning
    assert len(result.details) > 0
    assert result.details[0].type == "module"
