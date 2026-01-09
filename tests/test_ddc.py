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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
