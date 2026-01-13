"""Test suite for Inflation calculator."""

import ast

import pytest

from slop_detector.config import Config
from slop_detector.metrics.inflation import InflationCalculator


@pytest.fixture
def bcr_calc():
    """Create BCR calculator with default config."""
    config = Config()
    # Ensure config pattern matches settings.py
    config.config = {
        "exceptions": {
            "config_files": {"enabled": True, "patterns": ["settings.py", "*.conf", "*.config"]}
        },
        "inflation": {"enabled": True},
        "use_radon": False,
    }
    return InflationCalculator(config)


def test_high_jargon_ratio(bcr_calc):
    """Test code with high jargon ratio."""
    code = '''
"""
State-of-the-art Byzantine fault-tolerant neural optimizer
with cutting-edge global consensus from NeurIPS 2025.
Leveraging hyper-scale synergy for deep learning mission-critical
resilient cloud-native microservices architecture.
"""
def optimize():
    pass
'''
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should detect high Inflation
    assert result.inflation_score > 1.0
    assert result.status == "FAIL"


def test_justified_jargon(bcr_calc):
    """Test jargon justified by implementation."""
    code = """
import torch

def neural_network_training():
    model = torch.nn.Linear(10, 5)
    optimizer = torch.optim.Adam(model.parameters())
    return model, optimizer
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # "neural" should be justified
    assert len(result.justified_jargon) > 0


def test_config_file_exception(bcr_calc):
    """Test config files get Inflation exemption."""
    code = """
DATABASE_URL = "postgresql://localhost/db"
API_KEY = "abc123"
TIMEOUT = 30
DEBUG = True
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("settings.py", code, tree)

    # Should be recognized as config file
    assert result.is_config_file is True
    # Should have Inflation = 0.0
    assert result.inflation_score == 0.0


def test_clean_code_low_inflation(bcr_calc):
    """Test clean code has low Inflation."""
    code = """
def calculate_statistics(data):
    mean = sum(data) / len(data)
    variance = sum((x - mean) ** 2 for x in data) / len(data)
    return mean, variance
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should have low Inflation
    assert result.inflation_score < 0.5
    assert result.status == "PASS"


def test_multiple_jargon_categories(bcr_calc):
    """Test detection of jargon from different categories."""
    code = """
def process_data():
    # AI/ML: neural, deep learning, transformer
    # Architecture: scalable, cloud-native, microservices
    # Quality: robust, performant, state-of-the-art
    # Academic: neurips, theorem, equation
    pass
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should detect jargon from multiple categories
    assert result.jargon_count > 0
    # Check details include category
    categories = set(d["category"] for d in result.jargon_details)
    assert len(categories) > 1


def test_jargon_count_multiple_occurrences(bcr_calc):
    """Test counting multiple occurrences of same jargon."""
    code = """
# neural neural neural
# robust robust
def process():
    pass
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should count each occurrence
    assert result.jargon_count >= 5


def test_complexity_calculation_no_functions(bcr_calc):
    """Test complexity when there are no functions."""
    code = """
x = 10
y = 20
# robust, scalable, neural
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should handle gracefully
    assert result.avg_complexity >= 0


def test_complexity_with_conditionals(bcr_calc):
    """Test complexity calculation with control flow."""
    code = """
def complex_function(x):
    if x > 0:
        if x > 10:
            return "high"
        else:
            return "low"
    elif x == 0:
        return "zero"
    else:
        for i in range(abs(x)):
            print(i)
        while x < 0:
            x += 1
        return "negative"
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should detect higher complexity
    assert result.avg_complexity > 1.0


def test_infinite_inflation_no_complexity(bcr_calc):
    """Test high inflation when jargon without functions."""
    code = """
# State-of-the-art neural transformer architecture
# Byzantine fault-tolerant cloud-native solution
x = 10
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should have high inflation (defaults to complexity 1.0)
    assert result.inflation_score > 0.5
    assert result.status in ["WARNING", "FAIL"]


def test_status_warning_threshold(bcr_calc):
    """Test WARNING status for moderate inflation."""
    code = """
def process():
    # neural
    # robust
    if True:
        return 1
    else:
        return 0
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Check status boundaries (0.5 < score <= 1.0)
    if 0.5 < result.inflation_score <= 1.0:
        assert result.status == "WARNING"


def test_jargon_details_tracking(bcr_calc):
    """Test detailed jargon tracking with line numbers."""
    code = """
# Line 2: neural transformer
def func():
    # Line 4: robust scalable
    pass
# Line 6: cloud-native
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should have details for each jargon
    assert len(result.jargon_details) == result.jargon_count
    # Check that line numbers are tracked
    for detail in result.jargon_details:
        assert "line" in detail
        assert detail["line"] > 0
        assert "word" in detail
        assert "category" in detail
        assert "justified" in detail


def test_justification_architecture_jargon(bcr_calc):
    """Test architecture jargon justification."""
    code = """
import asyncio

async def scalable_handler():
    # scalable, distributed architecture
    await asyncio.gather(task1(), task2())
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # asyncio should justify architecture jargon
    assert len(result.justified_jargon) > 0


def test_justification_quality_jargon(bcr_calc):
    """Test quality jargon justification."""
    code = """
from functools import lru_cache

@lru_cache
def optimized_function(n):
    # optimized, performant
    return n * 2
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # lru_cache should justify quality jargon
    assert len(result.justified_jargon) > 0


def test_config_file_with_functions_not_config(bcr_calc):
    """Test that files with functions are not treated as config."""
    code = """
DATABASE_URL = "postgresql://localhost/db"

def get_connection():
    return DATABASE_URL
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("settings.py", code, tree)

    # Should NOT be recognized as config file (has functions)
    assert result.is_config_file is False


def test_empty_file(bcr_calc):
    """Test handling of empty file."""
    code = ""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should handle gracefully
    assert result.jargon_count == 0
    assert result.inflation_score == 0.0
    assert result.status == "PASS"


def test_no_jargon_present(bcr_calc):
    """Test file with no jargon."""
    code = """
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should have zero jargon
    assert result.jargon_count == 0
    assert result.inflation_score == 0.0
    assert result.status == "PASS"


def test_case_insensitive_detection(bcr_calc):
    """Test that jargon detection is case-insensitive."""
    code = """
# NEURAL NETWORK transformer
# ROBUST Byzantine FAULT-TOLERANT
def process():
    pass
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should detect jargon regardless of case
    assert result.jargon_count > 0


def test_academic_jargon_detection(bcr_calc):
    """Test detection of academic/paper jargon."""
    code = """
def implement_neurips_algorithm():
    # Based on ICLR theorem and CVPR equation
    # Lemma from spotlight paper
    pass
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should detect academic jargon
    academic_jargon = [d for d in result.jargon_details if d["category"] == "academic"]
    assert len(academic_jargon) > 0


def test_complexity_with_boolean_operators(bcr_calc):
    """Test complexity calculation with boolean operators."""
    code = """
def validate(x, y, z):
    if (x > 0 and y > 0) or (z < 0 and x < 10):
        return True
    return False
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should count boolean operators
    assert result.avg_complexity > 1.0


def test_inflation_score_capping(bcr_calc):
    """Test that inflation score is capped at 10.0."""
    code = """
def tiny():
    # neural transformer attention mechanism deep learning
    # reinforcement learning policy optimization gradient descent
    # state-of-the-art cutting-edge sophisticated holistic
    # byzantine fault-tolerant distributed scalable
    # enterprise-grade production-ready mission-critical
    # neurips iclr icml cvpr theorem equation proof
    pass
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should be capped at 10.0
    assert result.inflation_score <= 10.0


def test_async_function_complexity(bcr_calc):
    """Test complexity calculation with async functions."""
    code = """
async def async_process():
    if True:
        for i in range(10):
            await something()
    return
"""
    tree = ast.parse(code)
    result = bcr_calc.calculate("test.py", code, tree)

    # Should handle async functions
    assert result.avg_complexity > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
