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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
