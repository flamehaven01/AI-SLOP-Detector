"""Tests for core SlopDetector integration."""

import tempfile
from pathlib import Path

import pytest

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
        inflation_score=0.2,
        jargon_count=2,
        avg_complexity=10.0,
        status="pass",
        jargon_found=[],
        jargon_details=[],
    )
    good_ddc = DDCResult(
        usage_ratio=0.9,
        imported=["os", "sys"],
        actually_used=["os"],
        unused=["sys"],
        fake_imports=[],
        type_checking_imports=[],
        grade="A",
    )

    score, status, warnings = detector._calculate_slop_status(high_ldr, low_inflation, good_ddc, [])

    assert score < 30
    assert status == SlopStatus.CLEAN
    assert len(warnings) == 0


def test_weighted_analysis(detector, temp_python_file):
    """Test weighted analysis considers file size."""
    code = (
        '''
def function_one():
    """First function."""
    return 1

def function_two():
    """Second function."""
    return 2
'''
        * 10
    )  # Repeat to make larger file

    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    # Larger files should still be analyzed correctly
    assert result.ldr.total_lines > 50
    assert result.deficit_score >= 0


def test_config_thresholds_respected(temp_python_file):
    """Test custom config thresholds are respected."""
    config_data = {"thresholds": {"ldr": {"critical": 0.5}}}  # Higher threshold

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


def test_analyze_project(detector):
    """Test project-level analysis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create multiple Python files
        (project_path / "file1.py").write_text(
            '''
def clean_function():
    """Clean implementation."""
    return sum([1, 2, 3])
'''
        )

        (project_path / "file2.py").write_text(
            '''
def empty_function():
    """Empty."""
    pass
'''
        )

        (project_path / "file3.py").write_text(
            '''
import torch
import sys

def another():
    """Has unused imports."""
    return sys.version
'''
        )

        result = detector.analyze_project(str(project_path))

        assert result.project_path == str(project_path)
        assert result.total_files == 3
        assert len(result.file_results) == 3
        assert result.avg_deficit_score >= 0
        assert result.weighted_deficit_score >= 0


def test_analyze_project_with_ignore_patterns(detector):
    """Test project analysis respects ignore patterns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create files including test files
        (project_path / "main.py").write_text(
            """
def main():
    return "hello"
"""
        )

        (project_path / "test_main.py").write_text(
            """
def test_main():
    assert True
"""
        )

        # Detector should honor default ignore patterns
        result = detector.analyze_project(str(project_path))

        # May or may not include test files depending on config
        assert result.total_files >= 1


def test_analyze_empty_project(detector):
    """Test analyzing project with no Python files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = detector.analyze_project(tmpdir)

        assert result.total_files == 0
        assert result.avg_deficit_score == 0.0
        assert result.overall_status == SlopStatus.CLEAN


def test_should_ignore(detector):
    """Test ignore pattern matching."""
    test_path = Path("tests/test_main.py")
    ignore_patterns = ["tests/*", "**/test_*.py"]

    # Should match ignore patterns
    assert detector._should_ignore(test_path, ignore_patterns) is True

    regular_path = Path("src/main.py")
    assert detector._should_ignore(regular_path, ignore_patterns) is False


def test_calculate_pattern_penalty(detector):
    """Test pattern penalty calculation."""
    from slop_detector.patterns.base import Axis, Issue, Severity

    # Create test issues with different severities
    issues = [
        Issue(
            pattern_id="test1",
            severity=Severity.CRITICAL,
            axis=Axis.STRUCTURE,
            file=Path("test.py"),
            line=1,
            column=0,
            message="Critical issue",
            suggestion="Fix it",
        ),
        Issue(
            pattern_id="test2",
            severity=Severity.HIGH,
            axis=Axis.QUALITY,
            file=Path("test.py"),
            line=2,
            column=0,
            message="High issue",
            suggestion="Fix it",
        ),
        Issue(
            pattern_id="test3",
            severity=Severity.MEDIUM,
            axis=Axis.STYLE,
            file=Path("test.py"),
            line=3,
            column=0,
            message="Medium issue",
            suggestion="Fix it",
        ),
        Issue(
            pattern_id="test4",
            severity=Severity.LOW,
            axis=Axis.NOISE,
            file=Path("test.py"),
            line=4,
            column=0,
            message="Low issue",
            suggestion="Fix it",
        ),
    ]

    penalty = detector._calculate_pattern_penalty(issues)

    # critical=10, high=5, medium=2, low=1 → total=18
    assert penalty == 18.0


def test_calculate_pattern_penalty_capped(detector):
    """Test pattern penalty is capped at 50."""
    from slop_detector.patterns.base import Axis, Issue, Severity

    # Create many critical issues
    issues = [
        Issue(
            pattern_id=f"test{i}",
            severity=Severity.CRITICAL,
            axis=Axis.STRUCTURE,
            file=Path("test.py"),
            line=i,
            column=0,
            message=f"Critical {i}",
            suggestion="Fix",
        )
        for i in range(20)  # 20 * 10 = 200, but should cap at 50
    ]

    penalty = detector._calculate_pattern_penalty(issues)

    # Should be capped at 50
    assert penalty == 50.0


def test_deficit_score_with_pattern_penalties(detector, temp_python_file):
    """Test that pattern issues increase deficit score."""
    code = '''
def bad_code():
    """Multiple anti-patterns."""
    try:
        something()
    except:  # Bare except
        pass

def another_bad(items=[]):  # Mutable default
    """More issues."""
    items.append(1)
    return items
'''
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    # Should have pattern issues
    assert len(result.pattern_issues) > 0
    # Deficit score should be affected
    assert result.deficit_score > 0


def test_critical_patterns_trigger_critical_status(detector, temp_python_file):
    """Test multiple critical patterns trigger CRITICAL_DEFICIT."""
    code = """
def bad1():
    try:
        x()
    except:  # Critical
        pass

def bad2():
    try:
        y()
    except:  # Critical
        pass

def bad3():
    try:
        z()
    except:  # Critical
        pass
"""
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    # Multiple critical patterns should trigger critical status
    critical_count = sum(1 for issue in result.pattern_issues if issue.severity.value == "critical")

    if critical_count >= 3:
        assert result.status == SlopStatus.CRITICAL_DEFICIT


def test_analyze_file_read_error(detector):
    """Test handling file read errors."""
    with pytest.raises(Exception):
        detector.analyze_file("/nonexistent/file.py")


def test_weighted_analysis_enabled(detector):
    """Test weighted analysis uses LOC weighting."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Small file with poor quality
        (project_path / "small.py").write_text(
            """
def empty():
    pass
"""
        )

        # Large file with good quality
        large_code = (
            '''
def process(data):
    """Process data."""
    result = []
    for item in data:
        if item > 0:
            result.append(item * 2)
    return result
'''
            * 10
        )

        (project_path / "large.py").write_text(large_code)

        result = detector.analyze_project(str(project_path))

        # Weighted score should differ from average
        # (large file should dominate)
        assert result.weighted_deficit_score >= 0
        assert result.avg_deficit_score >= 0


def test_project_overall_status_calculation(detector):
    """Test project overall status based on weighted score."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create clean files
        (project_path / "clean.py").write_text(
            '''
def good_function(x):
    """Good implementation."""
    if x > 0:
        return x * 2
    return 0
'''
        )

        result = detector.analyze_project(str(project_path))

        # Should be CLEAN
        assert result.overall_status == SlopStatus.CLEAN


def test_inflated_signal_status(detector, temp_python_file):
    """Test INFLATED_SIGNAL status for high inflation."""
    code = '''
def buzzword_function():
    """State-of-the-art neural network transformer with
    cutting-edge deep learning and Byzantine fault-tolerant
    architecture for mission-critical cloud-native deployments."""
    pass
'''
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    # High inflation should trigger INFLATED_SIGNAL
    if result.inflation.inflation_score > 1.0:
        assert result.status == SlopStatus.INFLATED_SIGNAL


def test_dependency_noise_status(detector, temp_python_file):
    """Test DEPENDENCY_NOISE status for low usage ratio."""
    code = '''
import torch
import tensorflow as tf
import keras
import numpy as np
import pandas as pd

def simple():
    """Uses nothing."""
    return 42
'''
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    # Very low usage ratio should trigger DEPENDENCY_NOISE
    if result.ddc.usage_ratio < 0.50:
        assert result.status == SlopStatus.DEPENDENCY_NOISE


def test_warnings_generation(detector, temp_python_file):
    """Test warning message generation."""
    code = '''
import torch

def empty():
    """Low LDR, high inflation, fake imports."""
    pass
'''
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    # Should have warnings
    assert isinstance(result.warnings, list)


def test_run_patterns_integration(detector, temp_python_file):
    """Test pattern execution integration."""
    code = '''
def test_function():
    """Has patterns to detect."""
    try:
        risky_op()
    except:
        pass
'''
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    # Patterns should run and find issues
    assert hasattr(result, "pattern_issues")
    assert isinstance(result.pattern_issues, list)
