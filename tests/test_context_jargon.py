"""Test context-based jargon detection."""

import ast
import pytest
from unittest.mock import MagicMock
from slop_detector.metrics.context_jargon import ContextJargonDetector


@pytest.fixture
def detector():
    return ContextJargonDetector(config={})


def test_unjustified_jargon(detector):
    """Test detection of jargon without evidence."""
    code = """
def my_func():
    # This is a production-ready system
    pass
    """
    tree = ast.parse(code)

    # Mock inflation result saying we found "production-ready"
    mock_inflation = MagicMock()
    mock_inflation.jargon_details = [{"word": "production-ready", "category": "quality", "line": 3}]

    result = detector.analyze("test.py", code, tree, mock_inflation)

    assert result.total_jargon == 1
    assert result.unjustified_jargon == 1
    assert result.status != "PASS"
    assert result.evidence_details[0].is_justified is False


def test_justified_jargon(detector):
    """Test detection of jargon WITH evidence."""
    code = """
import logging

def my_func():
    # This is a production-ready system
    try:
        if not isinstance(x, int): raise ValueError()
    except Exception:
        logging.error("Fail")
    """
    tree = ast.parse(code)

    mock_inflation = MagicMock()
    mock_inflation.jargon_details = [{"word": "production-ready", "category": "quality", "line": 4}]

    result = detector.analyze("test.py", code, tree, mock_inflation)

    assert result.justified_jargon == 1
    assert result.status == "PASS"

    # Check evidence found
    evidence = result.evidence_details[0]
    assert "error_handling" in evidence.found_evidence
    assert "logging" in evidence.found_evidence


def test_evidence_collectors(detector):
    """Test individual evidence collectors."""

    # Async support
    code = "async def foo(): await bar()"
    tree = ast.parse(code)
    assert detector._has_async_support(tree)

    # Tests
    assert detector._has_tests("tests/test_foo.py", tree)

    # Config
    assert detector._has_config_management(tree, "config = yaml.safe_load()")
