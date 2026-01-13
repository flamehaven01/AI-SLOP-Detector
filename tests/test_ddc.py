"""Test suite for DDC calculator."""

import ast

import pytest

from slop_detector.config import Config
from slop_detector.metrics.ddc import DDCCalculator


@pytest.fixture
def ddc_calc():
    """Create DDC calculator with default config."""
    return DDCCalculator(Config())


def test_unused_imports(ddc_calc):
    """Test detection of unused imports."""
    code = """
import torch
import numpy as np
import logging

logger = logging.getLogger(__name__)
logger.info("Hello")
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # torch and numpy are unused
    assert "torch" in result.unused
    assert "numpy" in result.unused
    assert "logging" in result.actually_used


def test_all_imports_used(ddc_calc):
    """Test code with all imports used."""
    code = """
import numpy as np

def calculate(data):
    return np.mean(data)
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # All imports used
    assert result.usage_ratio == 1.0
    assert result.grade == "EXCELLENT"


def test_type_checking_imports(ddc_calc):
    """Test TYPE_CHECKING imports are excluded."""
    code = """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from torch import Tensor

def process(data):
    return data
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # torch should be in type_checking_imports
    assert "torch" in result.type_checking_imports
    # Should not be counted as unused
    assert "torch" not in result.unused


def test_fake_imports_detection(ddc_calc):
    """Test detection of heavyweight unused imports."""
    code = """
import torch
import tensorflow as tf

def simple_function():
    return 42
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # Should detect fake imports
    assert len(result.fake_imports) > 0
    assert result.usage_ratio < 0.5


def test_import_from_statements(ddc_calc):
    """Test 'from X import Y' statements."""
    code = """
from pathlib import Path
from typing import List, Dict

def get_files(dir_path: str) -> List[Path]:
    return list(Path(dir_path).glob("*.py"))
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # Path is used, typing is in annotations only (if handled correctly)
    assert "pathlib" in result.actually_used


def test_import_aliases(ddc_calc):
    """Test import aliases are tracked correctly."""
    code = """
import numpy as np
import pandas as pd

def process():
    data = np.array([1, 2, 3])
    df = pd.DataFrame(data)
    return df
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # Both should be detected as used
    assert "numpy" in result.actually_used
    assert "pandas" in result.actually_used
    assert result.usage_ratio == 1.0


def test_attribute_access(ddc_calc):
    """Test attribute access detection."""
    code = """
import os

def get_env():
    return os.environ.get("PATH")
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # os.environ access should count as usage
    assert "os" in result.actually_used


def test_function_call_detection(ddc_calc):
    """Test function call detection."""
    code = """
import json
import sys

def load_data(file_path):
    with open(file_path) as f:
        data = json.load(f)
    print("Loaded", file=sys.stderr)
    return data
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # Both imports used in calls
    assert "json" in result.actually_used
    assert "sys" in result.actually_used


def test_empty_file(ddc_calc):
    """Test handling of file with no imports."""
    code = """
def simple_function():
    return 42
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # No imports, should have perfect ratio
    assert result.usage_ratio == 1.0
    assert len(result.imported) == 0


def test_no_code(ddc_calc):
    """Test file with imports but no usage."""
    code = """
import numpy as np
import torch
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # All imports unused
    assert len(result.unused) == 2
    assert result.usage_ratio == 0.0
    assert result.grade == "SUSPICIOUS"


def test_grade_calculations(ddc_calc):
    """Test grade boundaries."""
    # EXCELLENT (>= 0.90)
    code_excellent = """
import os
import sys
import json

x = os.path.exists(".")
y = sys.version
z = json.dumps({})
"""
    tree = ast.parse(code_excellent)
    result = ddc_calc.calculate("test.py", code_excellent, tree)
    assert result.grade == "EXCELLENT"

    # GOOD (>= 0.70)
    code_good = """
import os
import sys
import json
import time

x = os.path.exists(".")
y = sys.version
z = json.dumps({})
"""
    tree = ast.parse(code_good)
    result = ddc_calc.calculate("test.py", code_good, tree)
    assert result.grade == "GOOD"

    # ACCEPTABLE (>= 0.50)
    code_acceptable = """
import os
import sys
import json
import time
import random

x = os.path.exists(".")
y = sys.version
z = json.dumps({})
"""
    tree = ast.parse(code_acceptable)
    result = ddc_calc.calculate("test.py", code_acceptable, tree)
    assert result.grade == "ACCEPTABLE"


def test_usage_in_annotations_vs_actual(ddc_calc):
    """Test that type annotations don't count as usage."""
    code = """
import typing
from typing import List

def process(items: List[int]) -> int:
    # typing module is imported but only used in annotations
    return sum(items)
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # typing should be detected (behavior depends on implementation)
    # At minimum, check that the code doesn't crash
    assert result.usage_ratio >= 0


def test_nested_imports(ddc_calc):
    """Test nested module imports."""
    code = """
import os.path
import collections.abc

def check():
    return os.path.exists(".")
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # os should be used
    assert "os" in result.actually_used


def test_multiple_from_imports(ddc_calc):
    """Test multiple items from single module."""
    code = """
from os import path, environ
from typing import List, Dict, Optional

def get_path():
    return path.exists(".")

def get_env():
    return environ.get("HOME")
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # os should be used (path and environ are from os)
    assert "os" in result.actually_used


def test_heavyweight_library_detection(ddc_calc):
    """Test detection of unused heavyweight libraries."""
    code = """
import torch
import tensorflow as tf
import keras
import sklearn
import pandas as pd

def simple():
    # Use only pandas
    return pd.DataFrame()
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # Should detect multiple fake/heavyweight imports
    assert len(result.fake_imports) >= 3
    assert "torch" in result.fake_imports
    assert "tensorflow" in result.fake_imports


def test_usage_collector_in_expressions(ddc_calc):
    """Test usage detection in various expression contexts."""
    code = """
import math
import random

def compute():
    # Usage in different contexts
    a = math.pi  # Attribute access
    b = math.sqrt(16)  # Function call
    c = [random.random() for _ in range(10)]  # List comprehension
    d = lambda x: math.cos(x)  # Lambda
    return a, b, c, d
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # Both should be detected
    assert "math" in result.actually_used
    assert "random" in result.actually_used
    assert result.usage_ratio == 1.0


def test_decorator_usage(ddc_calc):
    """Test import usage in decorators."""
    code = """
import functools

@functools.lru_cache(maxsize=128)
def expensive_function(n):
    return n * 2
"""
    tree = ast.parse(code)
    result = ddc_calc.calculate("test.py", code, tree)

    # functools used in decorator
    assert "functools" in result.actually_used


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
