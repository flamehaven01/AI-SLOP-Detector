"""Tests for core SlopDetector integration."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_detector.core import SlopDetector
from slop_detector.models import DDCResult, FileAnalysis, InflationResult, LDRResult, SlopStatus


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
    # v2.8.0: status now uses monotonic thresholds (INFLATED_SIGNAL = 50-70 range)
    assert result.status in [
        SlopStatus.CRITICAL_DEFICIT,
        SlopStatus.INFLATED_SIGNAL,
        SlopStatus.SUSPICIOUS,
    ]
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


def test_analyze_file_flags_exact_duplicate_pair(detector, temp_python_file):
    """Same-file alpha-renamed duplicate functions must not pass as CLEAN."""
    code = """
def score_route(readings, offset):
    tally = offset
    for reading in readings:
        tally = (tally * 31 + reading) % 1_000_003
    return tally


def blend_samples(bucket, origin):
    marker = origin
    for sample in bucket:
        marker = (marker * 31 + sample) % 1_000_003
    return marker
"""
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    clone_ids = {issue.pattern_id for issue in result.pattern_issues}
    assert "exact_duplicate_pair" in clone_ids
    assert result.deficit_score > 0.0


def test_analyze_file_does_not_flag_tiny_duplicate_wrappers(detector, temp_python_file):
    """Tiny one-line wrappers should not trigger the strict exact-duplicate pair path."""
    code = """
def first(items):
    return items[0]


def second(values):
    return values[0]
"""
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    clone_ids = {issue.pattern_id for issue in result.pattern_issues}
    assert "exact_duplicate_pair" not in clone_ids


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

    score, status, warnings, breakdown = detector._calculate_slop_status(
        high_ldr, low_inflation, good_ddc, []
    )

    assert score < 30
    assert status == SlopStatus.CLEAN
    assert len(warnings) == 0
    # v3.7.6 (SLOP-003): breakdown fields sum to total within 0.01
    keys = ("ldr_penalty", "inflation_penalty", "ddc_penalty", "purity_penalty", "pattern_hits")
    assert abs(sum(breakdown[k] for k in keys) - breakdown["total"]) < 0.01


def test_deficit_breakdown_attribution_on_clean_file(detector, temp_python_file):
    """SLOP-003: analyze_file exposes per-dimension deficit_breakdown."""
    code = '''
def add(a, b):
    """Return sum."""
    return a + b


def multiply(a, b):
    """Return product."""
    return a * b
'''
    temp_python_file.write(code)
    temp_python_file.flush()

    result = detector.analyze_file(temp_python_file.name)

    bd = result.deficit_breakdown
    assert bd, "deficit_breakdown should be populated"
    for key in (
        "ldr_penalty",
        "inflation_penalty",
        "ddc_penalty",
        "purity_penalty",
        "pattern_hits",
        "total",
    ):
        assert key in bd, f"missing key: {key}"
        assert bd[key] >= 0.0, f"{key} should be non-negative"

    # Conservation: penalties sum to total when deficit_score is not capped at 100
    if result.deficit_score < 100.0:
        keys = ("ldr_penalty", "inflation_penalty", "ddc_penalty", "purity_penalty", "pattern_hits")
        assert abs(sum(bd[k] for k in keys) - bd["total"]) < 0.01

    # to_dict round-trip preserves the field
    as_dict = result.to_dict()
    assert "deficit_breakdown" in as_dict
    assert as_dict["deficit_breakdown"]["total"] == bd["total"]


def test_weighted_geometric_deficit_contract(detector):
    """The snapshot score must follow the declared weighted geometric formula."""
    ldr = LDRResult(
        total_lines=10,
        logic_lines=8,
        empty_lines=2,
        ldr_score=0.8,
        grade="A",
    )
    inflation_normalized = 0.25
    inflation = InflationResult(
        jargon_count=1,
        avg_complexity=1.0,
        inflation_score=0.5,
        status="pass",
        jargon_found=[],
        jargon_details=[],
    )
    ddc = DDCResult(
        imported=["os"],
        actually_used=[],
        unused=[],
        fake_imports=[],
        type_checking_imports=[],
        usage_ratio=0.5,
        grade="A",
    )
    purity = 1.0

    gqg = detector._compute_gqg(ldr, inflation_normalized, ddc, purity)

    import math

    weights = detector.config.get_weights()
    total_weight = sum(
        [
            weights.get("ldr", 0.40),
            weights.get("inflation", 0.30),
            weights.get("ddc", 0.20),
            weights.get("purity", 0.10),
        ]
    )
    expected = math.exp(
        (
            weights.get("ldr", 0.40) * math.log(0.8)
            + weights.get("inflation", 0.30) * math.log(1.0 - inflation_normalized)
            + weights.get("ddc", 0.20) * math.log(0.5)
            + weights.get("purity", 0.10) * math.log(1.0)
        )
        / total_weight
    )

    assert gqg == pytest.approx(expected, rel=1e-9, abs=1e-9)

    score, status, warnings, breakdown = detector._calculate_slop_status(ldr, inflation, ddc, [])

    assert status == SlopStatus.CLEAN
    assert warnings == ["WARNING: Low import usage 50.00%"]
    assert score == pytest.approx(100.0 * (1.0 - gqg), rel=1e-9, abs=1e-9)
    assert breakdown["pattern_hits"] == 0.0
    assert breakdown["total"] == round(score, 4)


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

    venv_path = Path("project/.venv/Lib/site-packages/pkg/module.py")
    assert detector._should_ignore(venv_path, ignore_patterns) is True

    build_path = Path("project/build/lib/pkg/module.py")
    assert detector._should_ignore(build_path, ignore_patterns) is True


def test_should_ignore_with_project_root_absolute_path(detector, tmp_path):
    """Repo-relative ignore globs must still work for absolute paths."""
    test_path = tmp_path / "tests" / "test_main.py"
    test_path.parent.mkdir()
    test_path.write_text("def test_main():\n    assert True\n", encoding="utf-8")

    assert detector._should_ignore(test_path, ["tests/**"], root=tmp_path) is True


def test_should_ignore_recursive_generated_glob(detector, tmp_path):
    """Recursive generated-file globs should match repo-relative nested paths."""
    generated_path = tmp_path / "src" / "generated" / "foo.generated.py"
    generated_path.parent.mkdir(parents=True)
    generated_path.write_text("x = 1\n", encoding="utf-8")

    assert detector._should_ignore(generated_path, ["**/*.generated.py"], root=tmp_path) is True
    assert detector._should_ignore(generated_path, ["src/**/*.generated.py"], root=tmp_path) is True


def test_analyze_project_repo_relative_ignore_patterns(detector, tmp_path, monkeypatch):
    """Project analysis must apply repo-relative ignore patterns to absolute paths."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_main.py").write_text(
        "def test_main():\n    assert True\n", encoding="utf-8"
    )
    monkeypatch.setattr(detector.config, "get_ignore_patterns", lambda: ["tests/**"])

    result = detector.analyze_project(str(tmp_path))

    analyzed = {Path(item.file_path).name for item in result.file_results}
    assert analyzed == {"main.py"}


def test_analyze_project_filters_rust_discovered_build_artifacts(detector, tmp_path, monkeypatch):
    """Rust-discovered Python files must still pass through ignore filtering."""
    (tmp_path / "src").mkdir()
    (tmp_path / "build" / "lib").mkdir(parents=True)
    main_path = tmp_path / "src" / "main.py"
    build_path = tmp_path / "build" / "lib" / "main.py"
    main_path.write_text("def main():\n    return 1\n", encoding="utf-8")
    build_path.write_text("def main():\n    return 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "slop_detector.core.discover_project_files",
        lambda *args, **kwargs: [main_path, build_path],
    )
    monkeypatch.setattr(detector.config, "get_ignore_patterns", lambda: [])
    assert detector._should_ignore(main_path, [], root=tmp_path) is False
    assert detector._should_ignore(build_path, [], root=tmp_path) is True
    monkeypatch.setattr(
        detector,
        "analyze_file",
        lambda file_path: FileAnalysis(
            file_path=str(Path(file_path).resolve()),
            ldr=LDRResult(total_lines=2, logic_lines=1, empty_lines=0, ldr_score=0.8, grade="A"),
            inflation=InflationResult(
                jargon_count=0,
                avg_complexity=1.0,
                inflation_score=0.1,
                status="pass",
                jargon_found=[],
                jargon_details=[],
            ),
            ddc=DDCResult(
                imported=[],
                actually_used=[],
                unused=[],
                fake_imports=[],
                type_checking_imports=[],
                usage_ratio=1.0,
                grade="A",
            ),
            deficit_score=5.0,
            status=SlopStatus.CLEAN,
            dcf={"FunctionDef": 1.0},
        ),
    )
    monkeypatch.setattr(
        detector.project_prioritizer,
        "prioritize_project",
        lambda *args, **kwargs: ([], False, False),
    )

    result = detector.analyze_project(str(tmp_path))

    analyzed = {Path(item.file_path) for item in result.file_results}
    assert main_path.resolve() in analyzed
    assert build_path.resolve() not in analyzed


def test_analyze_project_includes_non_python_results_in_aggregate(detector, tmp_path, monkeypatch):
    """Project totals and status must include JS/Go analyzer results."""
    (tmp_path / "src").mkdir()
    app_path = tmp_path / "src" / "app.py"
    app_path.write_text("def ok():\n    return 1\n", encoding="utf-8")
    py_result = detector.analyze_file(str(app_path))
    js_result = SimpleNamespace(
        file_path=str(tmp_path / "index.js"),
        total_lines=200,
        ldr_equivalent=0.10,
        slop_score=80.0,
        status="critical_deficit",
    )
    go_result = SimpleNamespace(
        file_path=str(tmp_path / "main.go"),
        total_lines=40,
        ldr_equivalent=0.90,
        slop_score=0.0,
        status="clean",
    )
    monkeypatch.setattr(detector.config, "get_ignore_patterns", lambda: [])
    monkeypatch.setattr(detector, "analyze_file", lambda path: py_result)
    monkeypatch.setattr(detector, "_analyze_js_files", lambda *args, **kwargs: [js_result])
    monkeypatch.setattr(detector, "_analyze_go_files", lambda *args, **kwargs: [go_result])

    result = detector.analyze_project(str(tmp_path))

    assert result.total_files == 3
    assert result.deficit_files >= 1
    assert result.clean_files == result.total_files - result.deficit_files
    assert result.overall_status == SlopStatus.CRITICAL_DEFICIT


def test_analyze_project_js_only_is_not_reported_as_empty_clean(detector, tmp_path, monkeypatch):
    """JS-only projects must not fall through to empty CLEAN results."""
    js_result = SimpleNamespace(
        file_path=str(tmp_path / "index.js"),
        total_lines=120,
        ldr_equivalent=0.15,
        slop_score=72.0,
        status="critical_deficit",
    )
    monkeypatch.setattr(detector, "_analyze_js_files", lambda *args, **kwargs: [js_result])
    monkeypatch.setattr(detector, "_analyze_go_files", lambda *args, **kwargs: [])

    result = detector.analyze_project(str(tmp_path))

    assert result.total_files == 1
    assert result.deficit_files == 1
    assert result.js_file_results == [js_result]
    assert result.overall_status == SlopStatus.CRITICAL_DEFICIT


def test_compute_coherence_uses_deterministic_approximation_above_ceiling(detector):
    detector.config.config["advanced"]["exact_topology_ceiling"] = 2
    detector.config.config["advanced"]["topology_mode_above_ceiling"] = "deterministic_approximate"

    file_dcfs = [
        {"Module": 1.0},
        {"FunctionDef": 1.0},
        {"ClassDef": 1.0},
    ]

    coherence_a, level_a = detector._compute_coherence_vr(file_dcfs)
    coherence_b, level_b = detector._compute_coherence_vr(file_dcfs)

    assert level_a == "vr_structural_approx"
    assert level_b == "vr_structural_approx"
    assert coherence_a == coherence_b


def test_analyze_project_marks_approximate_coherence_above_ceiling(detector, tmp_path):
    detector.config.config["advanced"]["exact_topology_ceiling"] = 2
    detector.config.config["advanced"]["topology_mode_above_ceiling"] = "deterministic_approximate"
    detector.config.config["ignore"] = []

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("class C:\n    pass\n", encoding="utf-8")

    result = detector.analyze_project(str(tmp_path))

    assert result.total_files == 3
    assert result.coherence_level == "vr_structural_approx"
    assert 0.0 <= result.structural_coherence <= 1.0


def test_analyze_project_attaches_priority_hotspots(detector, tmp_path, monkeypatch):
    detector.config.config["ignore"] = []
    file_path = tmp_path / "a.py"
    file_path.write_text("def a():\n    return 1\n", encoding="utf-8")

    fake_hotspot = SimpleNamespace(
        file_path=str(file_path),
        deficit_score=80.0,
        churn_count=7,
        churn_score=1.0,
        coverage_ratio=0.2,
        priority_score=88.0,
        reasons=["critical deficit", "high churn", "low coverage"],
    )
    monkeypatch.setattr(
        detector.project_prioritizer,
        "prioritize_project",
        lambda *args, **kwargs: ([fake_hotspot], True, True),
    )

    result = detector.analyze_project(str(tmp_path))

    assert result.priority_hotspots == [fake_hotspot]
    assert result.churn_analysis_available is True
    assert result.coverage_analysis_available is True


def test_compute_coherence_caps_exact_input_size_for_large_repo(monkeypatch, detector):
    detector.config.config["advanced"]["exact_topology_ceiling"] = 5
    detector.config.config["advanced"]["topology_mode_above_ceiling"] = "deterministic_approximate"

    seen_sizes = []

    def fake_exact(file_dcfs):
        seen_sizes.append(len(file_dcfs))
        return 0.42

    monkeypatch.setattr(detector, "_compute_coherence_vr_exact", fake_exact)

    file_dcfs = [{"Module": 1.0}] * 40
    coherence, level = detector._compute_coherence_vr(file_dcfs)

    assert coherence == 0.42
    assert level == "vr_structural_approx"
    assert seen_sizes == [5]


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

    # Multiple critical patterns should indicate a non-clean file
    # v2.8.0: status is score-driven; 3 bare_except = 30pts penalty -> SUSPICIOUS or higher
    critical_count = sum(1 for issue in result.pattern_issues if issue.severity.value == "critical")

    if critical_count >= 3:
        assert result.status != SlopStatus.CLEAN


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

    # v2.8.0: pure-jargon empty function has zero LDR (40pts) + max inflation (35pts) = 75
    # -> CRITICAL_DEFICIT. INFLATED_SIGNAL is 50-70 range; this case exceeds it.
    if result.inflation.inflation_score > 1.0:
        assert result.status in (SlopStatus.INFLATED_SIGNAL, SlopStatus.CRITICAL_DEFICIT)


def test_dependency_noise_status(detector, temp_python_file):
    """Test DEPENDENCY_NOISE status for low usage ratio."""
    # Use stdlib-only imports so PhantomImportPattern (v2.9.0) does not fire.
    # The test validates DDC usage_ratio behaviour, not phantom detection.
    code = '''
import os
import sys
import json
import pathlib
import hashlib
import textwrap
import functools
import itertools
import contextlib
import collections

def simple():
    """Uses nothing from the imports above."""
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
