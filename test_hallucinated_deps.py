"""Test hallucinated dependencies detection without requiring heavy installs."""

import ast
import pytest
from unittest.mock import MagicMock
from slop_detector.metrics.hallucination_deps import HallucinationDepsDetector

# Sample code that *would* cause ImportError if imported directly
BAD_CODE = """
import torch
import tensorflow as tf
from transformers import AutoModel
import numpy as np
import json

def do_something():
    print(json.dumps({"a": 1}))
"""

@pytest.fixture
def detector():
    return HallucinationDepsDetector(config={})

def test_hallucination_detection_logic(detector):
    """Test that the detector finds unused ML imports."""
    
    # 1. Parse the bad code into AST
    tree = ast.parse(BAD_CODE)
    
    # 2. Mock the DDC result (Deep Dependency Check)
    # DDC would say: imported everything, used only json
    mock_ddc = MagicMock()
    mock_ddc.imported = ["torch", "tensorflow", "transformers", "numpy", "json"]
    mock_ddc.used = ["json"]
    mock_ddc.unused = ["torch", "tensorflow", "transformers", "numpy"]
    
    # 3. Run analysis
    result = detector.analyze(
        file_path="dummy.py",
        content=BAD_CODE,
        tree=tree,
        ddc_result=mock_ddc
    )
    
    # 4. Assertions
    assert result.total_hallucinated == 4
    assert result.status in ("WARNING", "CRITICAL")
    
    # Check specific hallucinations
    hallucinated_libs = {h.library for h in result.hallucinated_deps}
    assert "torch" in hallucinated_libs
    assert "tensorflow" in hallucinated_libs
    assert "transformers" in hallucinated_libs
    assert "numpy" in hallucinated_libs
    assert "json" not in hallucinated_libs

def test_category_mapping(detector):
    """Test that libraries map to correct categories."""
    assert "torch" in detector.CATEGORY_MAP["ml"]
    assert "requests" in detector.CATEGORY_MAP["http"]
    
    # Check reverse map
    assert "torch" in detector.lib_to_categories
    assert "ml" in detector.lib_to_categories["torch"]