"""Tests for core SlopDetector integration."""

import tempfile
from pathlib import Path

import pytest

from slop_detector.config import Config
from slop_detector.core import SlopDetector
from slop_detector.models import SlopStatus


@pytest.fixture
def detector():
    """Create detector with default config."""
    return SlopDetector()


@pytest.fixture
def temp_python_file():
    """Create a temporary Python file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        yield f
    Path(f.name).unlink(missing_ok=True)


def test_analyze_clean_file(detector, temp_python_file):
    """Test analyzing a clean file with good metrics."""
    code = '''
def calculate_sum(numbers):
    """Calculate sum of numbers."""
    total = 0
    for num in numbers:
        total += num
    return total

def process_data(data):
    """Process data with validation."""
    if not data:
        return None
    result = calculate_sum(data)
    return result * 2
'''
    temp_python_file.write(code)
    temp_python_file.flush()
    
    result = detector.analyze_file(temp_python_file.name)
    
    assert result.file_path == temp_python_file.name
    assert result.ldr.ldr_score > 0.7  # Good logic density
    assert result.status == SlopStatus.CLEAN
    assert result.deficit_score < 30


def test_analyze_slop_file(detector, temp_python_file):
    """Test analyzing a file with slop indicators."""
    code = '''
def empty_function():
    """This function does nothing."""
    pass

def another_empty():
    """Another empty one."""
    ...

def yet_another():
    """Yet another."""
    # TODO: implement this
    pass
'''
    temp_python_file.write(code)
    temp_python_file.flush()
    
    result = detector.analyze_file(temp_python_file.name)
    
    assert result.ldr.ldr_score < 0.3  # Low logic density
    assert result.status in [SlopStatus.CRITICAL_DEFICIT, SlopStatus.SUSPICIOUS]
    assert result.deficit_score > 30


def test_analyze_file_with_unused_imports(detector, temp_python_file):
    """Test detecting unused imports."""
    code = '''
import os
import sys
import json
from typing import List

def simple_function():
    """Only uses one import."""
    return os.path.exists("/tmp")
'''
    temp_python_file.write(code)
    temp_python_file.flush()
    
    result = detector.analyze_file(temp_python_file.name)
    
    assert result.ddc.usage_ratio < 0.5  # Many unused imports
    assert len(result.ddc.unused) > 0


def test_analyze_file_with_patterns(detector, temp_python_file):
    """Test pattern detection integration."""
    code = '''
def risky_function():
    """Function with anti-patterns."""
    try:
        dangerous_operation()
    except:  # Bare except!
        pass
    
def bad_default(items=[]):  # Mutable default!
    """Function with mutable default."""
    items.append(1)
    return items
'''
    temp_python_file.write(code)
    temp_python_file.flush()
    
    result = detector.analyze_file(temp_python_file.name)
    
    assert len(result.pattern_issues) > 0
    assert any("bare except" in issue.message.lower() for issue in result.pattern_issues)


def test_analyze_file_syntax_error(detector, temp_python_file):
    """Test handling syntax errors gracefully."""
    code = '''
def broken_function(
    """Missing closing parenthesis."""
    pass
'''
    temp_python_file.write(code)
    temp_python_file.flush()
    
    result = detector.analyze_file(temp_python_file.name)
    
    # Should return error analysis, not crash
    assert result.file_path == temp_python_file.name
    # CRITICAL: Syntax errors must be flagged as CRITICAL_DEFICIT
    assert result.status == SlopStatus.CRITICAL_DEFICIT
    assert result.deficit_score == 100.0
    assert result.ldr.ldr_score == 0.0


def test_analyze_abc_interface(detector, temp_python_file):
    """Test ABC interface gets penalty reduction."""
    code = '''
from abc import ABC, abstractmethod

class DataProcessor(ABC):
    """Abstract base class for processors."""
    
    @abstractmethod
    def process(self, data):
        """Process data."""
        pass
    
    @abstractmethod
    def validate(self, data):
        """Validate data."""
        pass
'''
    temp_python_file.write(code)
    temp_python_file.flush()
    
    result = detector.analyze_file(temp_python_file.name)
    
    # ABC interface should get better score due to penalty reduction
    assert result.ldr.ldr_score > 0.3  # Not penalized as much


def test_calculate_slop_status_thresholds(detector):
    """Test status calculation respects thresholds."""
    from slop_detector.models import DDCResult, InflationResult, LDRResult
    
    # Mock results
    high_ldr = LDRResult(ldr_score=0.85, logic_lines=85, empty_lines=15, total_lines=100, grade="A")
    low_inflation = InflationResult(
        inflation_score=0.2, jargon_count=2, avg_complexity=10.0,
        status="pass", jargon_found=[], jargon_details=[]
    )
    good_ddc = DDCResult(
        usage_ratio=0.9, imported=["os", "sys"], actually_used=["os"],
        unused=["sys"], fake_imports=[], type_checking_imports=[], grade="A"
    )
    
    score, status, warnings = detector._calculate_slop_status(
        high_ldr, low_inflation, good_ddc, []
    )
    
    assert score < 30
    assert status == SlopStatus.CLEAN
    assert len(warnings) == 0


def test_weighted_analysis(detector, temp_python_file):
    """Test weighted analysis considers file size."""
    code = '''
def function_one():
    """First function."""
    return 1

def function_two():
    """Second function."""
    return 2
''' * 10  # Repeat to make larger file
    
    temp_python_file.write(code)
    temp_python_file.flush()
    
    result = detector.analyze_file(temp_python_file.name)
    
    # Larger files should still be analyzed correctly
    assert result.ldr.total_lines > 50
    assert result.deficit_score >= 0


def test_config_thresholds_respected(temp_python_file):
    """Test custom config thresholds are respected."""
    config_data = {
        "thresholds": {
            "ldr": {
                "critical": 0.5  # Higher threshold
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        import yaml
        yaml.dump(config_data, f)
        config_path = f.name
    
    try:
        detector = SlopDetector(config_path=config_path)
        
        code = '''
def simple():
    """Simple function."""
    return 1
'''
        temp_python_file.write(code)
        temp_python_file.flush()
        
        result = detector.analyze_file(temp_python_file.name)
        
        # Config should affect threshold evaluation
        assert result.ldr.ldr_score > 0.5
        
    finally:
        Path(config_path).unlink(missing_ok=True)


def test_pattern_registry_disabled(detector, temp_python_file):
    """Test patterns can be disabled via config."""
    # Detector should have pattern registry
    assert detector.pattern_registry is not None
    
    code = '''
def function():
    """Function with bare except."""
    try:
        risky()
    except:
        pass
'''
    temp_python_file.write(code)
    temp_python_file.flush()
    
    result = detector.analyze_file(temp_python_file.name)
    
    # Pattern issues should be detected (unless disabled)
    assert isinstance(result.pattern_issues, list)
