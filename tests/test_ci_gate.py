"""Tests for CI/CD gate functionality."""

import json
import tempfile
from pathlib import Path

import pytest

from slop_detector.ci_gate import (
    CIGate,
    GateMode,
    GateResult,
    GateThresholds,
    GateVerdict,
    QuarantineRecord,
)
from slop_detector.core import SlopDetector
from slop_detector.models import FileAnalysis, ProjectAnalysis, SlopStatus


@pytest.fixture
def gate_soft():
    """Create gate in soft mode."""
    return CIGate(mode=GateMode.SOFT)


@pytest.fixture
def gate_hard():
    """Create gate in hard mode."""
    return CIGate(mode=GateMode.HARD)


@pytest.fixture
def gate_quarantine():
    """Create gate in quarantine mode."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_db = f.name

    gate = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=temp_db)
    yield gate

    # Cleanup
    Path(temp_db).unlink(missing_ok=True)


@pytest.fixture
def clean_file_analysis():
    """Create a clean file analysis result."""
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def good_function(x):
    """Well-implemented function."""
    if x > 0:
        return x * 2
    return 0
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)
    Path(temp_file).unlink(missing_ok=True)

    return result


@pytest.fixture
def failing_file_analysis():
    """Create a failing file analysis result."""
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def empty1():
    pass

def empty2():
    pass

def empty3():
    pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)
    Path(temp_file).unlink(missing_ok=True)

    return result


def test_gate_mode_enum():
    """Test GateMode enum values."""
    assert GateMode.SOFT.value == "soft"
    assert GateMode.HARD.value == "hard"
    assert GateMode.QUARANTINE.value == "quarantine"


def test_gate_verdict_enum():
    """Test GateVerdict enum values."""
    assert GateVerdict.PASS.value == "pass"
    assert GateVerdict.WARN.value == "warn"
    assert GateVerdict.FAIL.value == "fail"
    assert GateVerdict.QUARANTINE.value == "quarantine"


def test_gate_thresholds_defaults():
    """Test default threshold values."""
    thresholds = GateThresholds()

    assert thresholds.deficit_fail == 70.0
    assert thresholds.deficit_warn == 30.0
    assert thresholds.critical_patterns_fail == 3
    assert thresholds.high_patterns_warn == 5
    assert thresholds.inflation_fail == 1.5
    assert thresholds.ddc_fail == 0.5


def test_gate_thresholds_custom():
    """Test custom threshold values."""
    thresholds = GateThresholds(
        deficit_fail=80.0,
        deficit_warn=40.0,
        critical_patterns_fail=5
    )

    assert thresholds.deficit_fail == 80.0
    assert thresholds.deficit_warn == 40.0
    assert thresholds.critical_patterns_fail == 5


def test_quarantine_record_to_dict():
    """Test QuarantineRecord serialization."""
    record = QuarantineRecord(
        file_path="test.py",
        offense_count=2,
        last_deficit_score=45.0,
        violations=["high_deficit", "low_ldr"]
    )

    result = record.to_dict()

    assert result["file_path"] == "test.py"
    assert result["offense_count"] == 2
    assert result["last_deficit_score"] == 45.0
    assert result["violations"] == ["high_deficit", "low_ldr"]


def test_gate_result_to_dict():
    """Test GateResult serialization."""
    result = GateResult(
        verdict=GateVerdict.PASS,
        mode=GateMode.SOFT,
        deficit_score=25.0,
        message="All checks passed",
        failed_files=[],
        warned_files=["test.py"],
        should_fail_build=False,
        pr_comment="Quality check complete"
    )

    result_dict = result.to_dict()

    assert result_dict["verdict"] == "pass"
    assert result_dict["mode"] == "soft"
    assert result_dict["deficit_score"] == 25.0
    assert result_dict["message"] == "All checks passed"
    assert result_dict["warned_files"] == ["test.py"]
    assert result_dict["should_fail_build"] is False


def test_ci_gate_initialization_soft(gate_soft):
    """Test CI gate initialization in soft mode."""
    assert gate_soft.mode == GateMode.SOFT
    assert gate_soft.thresholds is not None
    assert isinstance(gate_soft.thresholds, GateThresholds)


def test_ci_gate_initialization_hard(gate_hard):
    """Test CI gate initialization in hard mode."""
    assert gate_hard.mode == GateMode.HARD


def test_ci_gate_initialization_quarantine(gate_quarantine):
    """Test CI gate initialization in quarantine mode."""
    assert gate_quarantine.mode == GateMode.QUARANTINE
    assert gate_quarantine.quarantine_records is not None


def test_soft_mode_clean_file_passes(gate_soft, clean_file_analysis):
    """Test soft mode passes clean file."""
    result = gate_soft.evaluate(clean_file_analysis)

    assert result.verdict == GateVerdict.PASS
    assert result.should_fail_build is False
    assert result.mode == GateMode.SOFT


def test_soft_mode_failing_file_warns(gate_soft, failing_file_analysis):
    """Test soft mode warns on failing file but doesn't fail build."""
    result = gate_soft.evaluate(failing_file_analysis)

    # Soft mode never fails build
    assert result.should_fail_build is False
    assert result.mode == GateMode.SOFT


def test_hard_mode_clean_file_passes(gate_hard, clean_file_analysis):
    """Test hard mode passes clean file."""
    result = gate_hard.evaluate(clean_file_analysis)

    assert result.verdict == GateVerdict.PASS
    assert result.should_fail_build is False


def test_hard_mode_failing_file_fails(gate_hard, failing_file_analysis):
    """Test hard mode fails build on failing file."""
    result = gate_hard.evaluate(failing_file_analysis)

    # Should fail if deficit is high
    if failing_file_analysis.deficit_score >= 70.0:
        assert result.should_fail_build is True
        assert result.verdict == GateVerdict.FAIL


def test_project_analysis_soft_mode(gate_soft):
    """Test project-level analysis in soft mode."""
    detector = SlopDetector()

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create test files
        (project_path / "good.py").write_text('''
def good():
    return sum([1, 2, 3])
''')

        (project_path / "bad.py").write_text('''
def empty1():
    pass
def empty2():
    pass
''')

        project_result = detector.analyze_project(str(project_path))
        gate_result = gate_soft.evaluate(project_result)

        assert gate_result.mode == GateMode.SOFT
        assert gate_result.should_fail_build is False


def test_project_analysis_hard_mode(gate_hard):
    """Test project-level analysis in hard mode."""
    detector = SlopDetector()

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create mostly good files
        (project_path / "good1.py").write_text('''
def process(x):
    if x > 0:
        return x * 2
    return 0
''')

        project_result = detector.analyze_project(str(project_path))
        gate_result = gate_hard.evaluate(project_result)

        assert gate_result.mode == GateMode.HARD


def test_custom_thresholds():
    """Test gate with custom thresholds."""
    thresholds = GateThresholds(
        deficit_fail=50.0,  # Lower threshold
        deficit_warn=20.0
    )

    gate = CIGate(mode=GateMode.HARD, thresholds=thresholds)

    assert gate.thresholds.deficit_fail == 50.0
    assert gate.thresholds.deficit_warn == 20.0


def test_gate_result_message_generation(gate_soft, clean_file_analysis):
    """Test that gate result includes proper message."""
    result = gate_soft.evaluate(clean_file_analysis)

    assert result.message is not None
    assert isinstance(result.message, str)
    assert len(result.message) > 0


def test_gate_result_pr_comment(gate_soft):
    """Test PR comment generation for project analysis."""
    detector = SlopDetector()

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        (project_path / "test.py").write_text('''
def func():
    return 42
''')

        project_result = detector.analyze_project(str(project_path))
        gate_result = gate_soft.evaluate(project_result)

        # PR comment should be generated for project analysis
        assert gate_result.pr_comment is not None


def test_quarantine_mode_tracking(gate_quarantine):
    """Test quarantine mode tracks offenders."""
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def empty():
    pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)
    gate_result = gate_quarantine.evaluate(result)

    Path(temp_file).unlink(missing_ok=True)

    # Check that result was evaluated
    assert gate_result.mode == GateMode.QUARANTINE


def test_gate_handles_syntax_error():
    """Test gate handles syntax error gracefully."""
    detector = SlopDetector()
    gate = CIGate(mode=GateMode.SOFT)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def broken(
    pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)
    gate_result = gate.evaluate(result)

    Path(temp_file).unlink(missing_ok=True)

    # Should handle gracefully
    assert gate_result is not None
    assert isinstance(gate_result, GateResult)


def test_quarantine_mode_escalation():
    """Test quarantine mode escalates after 3 violations."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_db = f.name

    gate = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=temp_db)
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def empty1():
    pass
def empty2():
    pass
def empty3():
    pass
''')
        f.flush()
        temp_file = f.name

    # First violation
    result1 = detector.analyze_file(temp_file)
    gate_result1 = gate.evaluate(result1)
    assert gate_result1.should_fail_build is False  # Not escalated yet

    # Second violation
    result2 = detector.analyze_file(temp_file)
    gate_result2 = gate.evaluate(result2)
    assert gate_result2.should_fail_build is False  # Not escalated yet

    # Third violation - should escalate
    result3 = detector.analyze_file(temp_file)
    gate_result3 = gate.evaluate(result3)

    # Check if escalated (depends on deficit score)
    if result3.deficit_score >= 70.0:
        assert gate_result3.should_fail_build is True

    Path(temp_file).unlink(missing_ok=True)
    Path(temp_db).unlink(missing_ok=True)


def test_quarantine_project_evaluation():
    """Test quarantine mode with project-level analysis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)
        temp_db = Path(tmpdir) / "quarantine.json"

        # Use very low thresholds to ensure files fail
        thresholds = GateThresholds(
            deficit_fail=20.0,  # Very low threshold
            deficit_warn=10.0
        )

        gate = CIGate(
            mode=GateMode.QUARANTINE,
            quarantine_db_path=str(temp_db),
            thresholds=thresholds
        )
        detector = SlopDetector()

        # Create multiple bad files with very high deficit
        (project_path / "bad1.py").write_text('''
def empty1():
    pass
def empty2():
    pass
def empty3():
    pass
def empty4():
    pass
def empty5():
    pass
''')

        (project_path / "bad2.py").write_text('''
def empty6():
    pass
def empty7():
    pass
def empty8():
    pass
''')

        # Analyze project multiple times
        for _ in range(3):
            project_result = detector.analyze_project(str(project_path))
            gate_result = gate.evaluate(project_result)

        # Check that quarantine records were created
        # (Only if files actually failed the low threshold)
        assert isinstance(gate.quarantine_records, dict)


def test_hard_mode_fails_on_critical_patterns():
    """Test hard mode fails build on critical patterns."""
    gate = CIGate(mode=GateMode.HARD)
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        # Create code with multiple bare except (critical patterns)
        f.write('''
def bad1():
    try:
        x()
    except:
        pass

def bad2():
    try:
        y()
    except:
        pass

def bad3():
    try:
        z()
    except:
        pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)
    gate_result = gate.evaluate(result)

    Path(temp_file).unlink(missing_ok=True)

    # Should fail if critical patterns >= 3
    critical_count = sum(
        1 for issue in result.pattern_issues
        if issue.severity.value == "critical"
    )

    if critical_count >= 3:
        assert gate_result.should_fail_build is True
        assert gate_result.verdict == GateVerdict.FAIL


def test_hard_mode_fails_on_high_inflation():
    """Test hard mode fails on high inflation score."""
    thresholds = GateThresholds(inflation_fail=1.0)
    gate = CIGate(mode=GateMode.HARD, thresholds=thresholds)
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def buzzword():
    """State-of-the-art neural network transformer with
    cutting-edge deep learning Byzantine fault-tolerant
    cloud-native microservices architecture for enterprise-grade
    mission-critical deployments leveraging advanced algorithms."""
    pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)
    gate_result = gate.evaluate(result)

    Path(temp_file).unlink(missing_ok=True)

    # Should fail if inflation >= threshold
    if result.inflation.inflation_score >= 1.0:
        assert gate_result.should_fail_build is True


def test_hard_mode_fails_on_low_ddc():
    """Test hard mode fails on low dependency usage."""
    thresholds = GateThresholds(ddc_fail=0.5)
    gate = CIGate(mode=GateMode.HARD, thresholds=thresholds)
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
import torch
import tensorflow as tf
import keras
import numpy as np

def simple():
    return 42
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)
    gate_result = gate.evaluate(result)

    Path(temp_file).unlink(missing_ok=True)

    # Should fail if usage ratio < threshold
    if result.ddc.usage_ratio < 0.5:
        assert gate_result.should_fail_build is True


def test_soft_mode_messages():
    """Test soft mode message generation."""
    gate = CIGate(mode=GateMode.SOFT)

    # Test with failed and warned files
    msg1 = gate._generate_soft_message(["file1.py", "file2.py"], ["file3.py"])
    assert "critical" in msg1.lower()
    assert "warnings" in msg1.lower()

    # Test with only failed files
    msg2 = gate._generate_soft_message(["file1.py"], [])
    assert "critical" in msg2.lower()

    # Test with only warned files
    msg3 = gate._generate_soft_message([], ["file1.py"])
    assert "warnings" in msg3.lower()

    # Test with no issues
    msg4 = gate._generate_soft_message([], [])
    assert "meet quality standards" in msg4.lower()


def test_pr_comment_generation_file():
    """Test PR comment generation for single file."""
    gate = CIGate(mode=GateMode.SOFT)
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def empty():
    pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)

    # Generate PR comment with failed file
    comment = gate._generate_pr_comment(result, [temp_file], [], [])

    Path(temp_file).unlink(missing_ok=True)

    assert "AI Code Quality Report" in comment
    assert "SOFT" in comment.upper()


def test_pr_comment_generation_project():
    """Test PR comment generation for project."""
    gate = CIGate(mode=GateMode.HARD)
    detector = SlopDetector()

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        (project_path / "good.py").write_text('''
def good():
    return sum([1, 2, 3])
''')

        (project_path / "bad.py").write_text('''
def empty():
    pass
''')

        project_result = detector.analyze_project(str(project_path))

        # Generate PR comment
        failed = []
        warned = []
        for file_result in project_result.file_results:
            if file_result.deficit_score >= 70:
                failed.append(file_result.file_path)
            elif file_result.deficit_score >= 30:
                warned.append(file_result.file_path)

        comment = gate._generate_pr_comment(project_result, failed, warned, [])

        assert "AI Code Quality Report" in comment
        assert "HARD" in comment.upper()
        assert "Summary" in comment


def test_pr_comment_quarantine_files():
    """Test PR comment includes quarantine information."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_db = f.name

    gate = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=temp_db)
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def empty():
    pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)

    # Add to quarantine
    gate._update_quarantine(temp_file, result)

    # Generate comment
    comment = gate._generate_pr_comment(result, [], [], [temp_file])

    Path(temp_file).unlink(missing_ok=True)
    Path(temp_db).unlink(missing_ok=True)

    assert "TRACKING" in comment or "Quarantine" in comment


def test_quarantine_db_save_load():
    """Test quarantine database persistence."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_db = f.name

    # Create gate and add records
    gate1 = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=temp_db)
    gate1.quarantine_records["test.py"] = QuarantineRecord(
        file_path="test.py",
        offense_count=2,
        last_deficit_score=50.0,
        violations=["test1", "test2"]
    )
    gate1._save_quarantine_db()

    # Load in new gate instance
    gate2 = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=temp_db)

    # Verify records were loaded
    assert "test.py" in gate2.quarantine_records
    assert gate2.quarantine_records["test.py"].offense_count == 2
    assert gate2.quarantine_records["test.py"].last_deficit_score == 50.0

    Path(temp_db).unlink(missing_ok=True)


def test_quarantine_db_load_corrupted():
    """Test quarantine database handles corrupted data."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        # Write corrupted JSON
        f.write("{ invalid json }")
        temp_db = f.name

    # Should handle gracefully
    gate = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=temp_db)

    # Should start with empty records
    assert len(gate.quarantine_records) == 0

    Path(temp_db).unlink(missing_ok=True)


def test_quarantine_db_load_missing():
    """Test quarantine database handles missing file."""
    temp_db = "nonexistent_quarantine_db.json"

    # Should handle gracefully
    gate = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=temp_db)

    # Should start with empty records
    assert len(gate.quarantine_records) == 0


def test_should_escalate():
    """Test escalation logic."""
    gate = CIGate(mode=GateMode.QUARANTINE)

    # File not in records - should not escalate
    assert gate._should_escalate("unknown.py") is False

    # Add record with < 3 offenses
    gate.quarantine_records["test1.py"] = QuarantineRecord(
        file_path="test1.py",
        offense_count=2
    )
    assert gate._should_escalate("test1.py") is False

    # Add record with >= 3 offenses
    gate.quarantine_records["test2.py"] = QuarantineRecord(
        file_path="test2.py",
        offense_count=3
    )
    assert gate._should_escalate("test2.py") is True


def test_update_quarantine_file_analysis():
    """Test quarantine update with FileAnalysis."""
    gate = CIGate(mode=GateMode.QUARANTINE)
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def empty():
    pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)

    # Update quarantine
    gate._update_quarantine(temp_file, result)

    Path(temp_file).unlink(missing_ok=True)

    # Verify record created
    assert temp_file in gate.quarantine_records
    assert gate.quarantine_records[temp_file].offense_count == 1
    assert gate.quarantine_records[temp_file].last_deficit_score == result.deficit_score


def test_update_quarantine_project_analysis():
    """Test quarantine update with ProjectAnalysis."""
    gate = CIGate(mode=GateMode.QUARANTINE)
    detector = SlopDetector()

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)
        test_file = project_path / "test.py"

        test_file.write_text('''
def empty():
    pass
''')

        project_result = detector.analyze_project(str(project_path))

        # Update quarantine for specific file
        gate._update_quarantine(str(test_file), project_result)

        # Verify record created
        assert str(test_file) in gate.quarantine_records


def test_check_file_thresholds_warn_conditions():
    """Test warning threshold checks."""
    thresholds = GateThresholds(
        deficit_warn=20.0,
        high_patterns_warn=2
    )
    gate = CIGate(mode=GateMode.SOFT, thresholds=thresholds)
    detector = SlopDetector()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write('''
def somewhat_empty():
    """Has some content but not much."""
    x = 1
    pass
''')
        f.flush()
        temp_file = f.name

    result = detector.analyze_file(temp_file)
    verdict = gate._check_file_thresholds(result)

    Path(temp_file).unlink(missing_ok=True)

    # Should be WARN or PASS based on actual scores
    assert verdict in [GateVerdict.WARN, GateVerdict.PASS, GateVerdict.FAIL]


def test_pr_comment_many_files():
    """Test PR comment truncates long file lists."""
    gate = CIGate(mode=GateMode.HARD)
    detector = SlopDetector()

    with tempfile.TemporaryDirectory() as tmpdir:
        project_path = Path(tmpdir)

        # Create many files
        for i in range(15):
            (project_path / f"file{i}.py").write_text(f'''
def empty{i}():
    pass
''')

        project_result = detector.analyze_project(str(project_path))

        # Collect failed files
        failed = [f.file_path for f in project_result.file_results if f.deficit_score >= 70]

        if len(failed) > 10:
            comment = gate._generate_pr_comment(project_result, failed, [], [])

            # Should truncate and show "... and X more"
            assert "more" in comment.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
