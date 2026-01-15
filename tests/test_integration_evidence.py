"""Tests for integration test evidence detection."""

import ast
import pytest

from slop_detector.metrics.context_jargon import ContextJargonDetector
from slop_detector.config import Config


@pytest.fixture
def detector():
    """Create detector instance with default config."""
    config = Config()
    return ContextJargonDetector(config)


def test_integration_detected_by_path(detector):
    """Integration tests detected by directory path."""
    file_path = "tests/integration/test_api.py"
    content = "def test_api_endpoint():\n    assert True\n"
    tree = ast.parse(content)

    evidence = detector._collect_evidence(content, tree, file_path)

    assert evidence["tests_integration"] is True
    assert evidence["tests_unit"] is False  # integration path excludes unit


def test_integration_detected_by_marker(detector):
    """Integration tests detected by pytest marker."""
    file_path = "tests/test_db.py"
    content = "@pytest.mark.integration\ndef test_db_query():\n    assert True\n"
    tree = ast.parse(content)

    evidence = detector._collect_evidence(content, tree, file_path)

    assert evidence["tests_integration"] is True


def test_integration_detected_by_runtime_signal(detector):
    """Integration tests detected by runtime signals (TestClient)."""
    file_path = "tests/test_service_integration.py"
    content = """from fastapi.testclient import TestClient

def test_call_api():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
"""
    tree = ast.parse(content)

    evidence = detector._collect_evidence(content, tree, file_path)

    assert evidence["tests_integration"] is True


def test_unit_tests_detected(detector):
    """Unit tests detected correctly."""
    file_path = "tests/test_utils.py"
    content = "def test_calculate_sum():\n    assert 1 + 1 == 2\n"
    tree = ast.parse(content)

    evidence = detector._collect_evidence(content, tree, file_path)

    assert evidence["tests_unit"] is True
    assert evidence["tests_integration"] is False


def test_helper_file_not_detected_as_integration_test(detector):
    """Helper files in integration/ directory not detected as tests."""
    file_path = "tests/integration/utils.py"
    content = "def helper_function():\n    return True\n"
    tree = ast.parse(content)

    evidence = detector._collect_evidence(content, tree, file_path)

    # No test_ functions, so not a test file
    assert evidence["tests_integration"] is False
    assert evidence["tests_unit"] is False
