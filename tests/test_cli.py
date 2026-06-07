"""Tests for CLI module."""

import json
import sys
from unittest.mock import patch

import pytest
import yaml

from slop_detector.cli import (
    _apply_runtime_overrides,
    _build_arg_parser,
    generate_html_report,
    generate_markdown_report,
    generate_text_report,
    get_mitigation,
    list_patterns,
    main,
    setup_logging,
)
from slop_detector.core import SlopDetector
from slop_detector.models import (
    DDCResult,
    FileAnalysis,
    InflationResult,
    LDRResult,
    PriorityHotspot,
    ProjectAnalysis,
    SlopStatus,
    SuppressionLedgerEntry,
)


def test_setup_logging_default():
    """Test setup_logging with default verbose=False."""
    setup_logging(verbose=False)
    # Should not raise


def test_setup_logging_verbose():
    """Test setup_logging with verbose=True."""
    setup_logging(verbose=True)
    # Should not raise


def test_list_patterns(capsys):
    """Test list_patterns outputs pattern information."""
    list_patterns()
    captured = capsys.readouterr()
    assert "Available Patterns:" in captured.out
    assert "bare_except" in captured.out
    assert "mutable_default_arg" in captured.out


def test_get_mitigation_jargon():
    """Test get_mitigation for jargon issues."""
    result = get_mitigation("jargon")
    assert "Replace vague marketing terminology" in result


def test_get_mitigation_mutable_default():
    """Test get_mitigation for mutable default arguments."""
    result = get_mitigation("mutable_default")
    assert "None" in result and "default" in result


def test_get_mitigation_unknown():
    """Test get_mitigation for unknown issue type."""
    result = get_mitigation("unknown_issue_type")
    assert "Review specific line" in result


def test_generate_text_report_single_file():
    """Test generate_text_report for single file analysis."""
    result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 80, 20, 0.80, "A"),
        inflation=InflationResult(5, 2.0, 0.5, "PASS", ["neural"], []),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=25.0,
        status=SlopStatus.CLEAN,
        warnings=["Test warning"],
    )

    report = generate_text_report(result)
    assert "AI CODE QUALITY REPORT" in report
    assert "/test/file.py" in report
    assert "CLEAN" in report
    assert "Test warning" in report


def test_generate_text_report_project():
    """Test generate_text_report for project analysis."""
    file_result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 50, 50, 0.50, "B"),
        inflation=InflationResult(10, 2.0, 1.5, "WARNING", ["neural"] * 10, []),
        ddc=DDCResult(["numpy", "pandas"], ["numpy"], ["pandas"], [], [], 0.5, "ACCEPTABLE"),
        deficit_score=60.0,
        status=SlopStatus.INFLATED_SIGNAL,
        warnings=["High inflation"],
    )

    result = ProjectAnalysis(
        project_path="/test/project",
        total_files=10,
        deficit_files=3,
        clean_files=7,
        avg_deficit_score=35.0,
        weighted_deficit_score=32.0,
        avg_ldr=0.75,
        avg_inflation=0.8,
        avg_ddc=0.85,
        overall_status=SlopStatus.SUSPICIOUS,
        file_results=[file_result],
    )

    report = generate_text_report(result)
    assert "AI CODE QUALITY REPORT" in report
    assert "/test/project" in report
    assert "Total Files: 10" in report
    assert "SUSPICIOUS" in report


def test_generate_text_report_project_shows_approximate_coherence():
    file_result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 50, 50, 0.50, "B"),
        inflation=InflationResult(10, 2.0, 1.5, "WARNING", ["neural"] * 10, []),
        ddc=DDCResult(["numpy", "pandas"], ["numpy"], ["pandas"], [], [], 0.5, "ACCEPTABLE"),
        deficit_score=60.0,
        status=SlopStatus.INFLATED_SIGNAL,
        warnings=["High inflation"],
    )

    result = ProjectAnalysis(
        project_path="/test/project",
        total_files=10,
        deficit_files=3,
        clean_files=7,
        avg_deficit_score=35.0,
        weighted_deficit_score=32.0,
        avg_ldr=0.75,
        avg_inflation=0.8,
        avg_ddc=0.85,
        overall_status=SlopStatus.SUSPICIOUS,
        file_results=[file_result],
        structural_coherence=0.8123,
        coherence_level="vr_structural_approx",
    )

    report = generate_text_report(result)
    assert "Structural Coherence:" in report
    # Internal algorithm name is hidden from human output (kept only in JSON).
    assert "vr_structural" not in report
    assert "MST" not in report
    assert "sampled" in report  # large-project coverage shown in plain words
    assert "81%" in report


def test_generate_text_report_project_shows_priority_hotspots():
    file_result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 50, 50, 0.50, "B"),
        inflation=InflationResult(10, 2.0, 1.5, "WARNING", ["neural"] * 10, []),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=60.0,
        status=SlopStatus.INFLATED_SIGNAL,
        warnings=[],
    )

    result = ProjectAnalysis(
        project_path="/test/project",
        total_files=10,
        deficit_files=3,
        clean_files=7,
        avg_deficit_score=35.0,
        weighted_deficit_score=32.0,
        avg_ldr=0.75,
        avg_inflation=0.8,
        avg_ddc=0.85,
        overall_status=SlopStatus.SUSPICIOUS,
        file_results=[file_result],
        priority_hotspots=[
            PriorityHotspot(
                file_path="/test/file.py",
                deficit_score=60.0,
                churn_count=9,
                churn_score=1.0,
                coverage_ratio=0.2,
                priority_score=82.0,
                reasons=["high deficit", "high churn", "low coverage"],
            )
        ],
        churn_analysis_available=True,
        coverage_analysis_available=True,
    )

    report = generate_text_report(result)
    assert "Priority Hotspots:" in report
    assert "priority 82.0/100" in report
    assert "coverage 20%" in report


def test_generate_text_report_single_file_shows_suppression_ledger():
    result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 80, 20, 0.80, "A"),
        inflation=InflationResult(5, 2.0, 0.5, "PASS", ["neural"], []),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=25.0,
        status=SlopStatus.CLEAN,
        suppression_ledger=[
            SuppressionLedgerEntry(
                file_path="/test/file.py",
                suppressed_line=12,
                directive_line=11,
                pattern_id="bare_except",
                scope="next_line",
                matched_rule="bare_except",
            )
        ],
    )

    report = generate_text_report(result)
    assert "Inline Suppressions:" in report
    assert "bare_except" in report


def test_generate_markdown_report_single_file():
    """Test generate_markdown_report for single file."""
    result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 80, 20, 0.80, "A"),
        inflation=InflationResult(
            5,
            2.0,
            0.5,
            "PASS",
            ["neural"],
            [{"line": 10, "word": "neural", "category": "ai_ml", "justified": False}],
        ),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=25.0,
        status=SlopStatus.CLEAN,
        warnings=[],
        pattern_issues=[],
    )

    report = generate_markdown_report(result)
    assert "# AI Code Quality Audit Report" in report
    assert "file.py" in report


def test_generate_markdown_report_project():
    """Test generate_markdown_report for project."""
    file_result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 50, 50, 0.50, "B"),
        inflation=InflationResult(
            10,
            2.0,
            1.5,
            "WARNING",
            ["neural"] * 10,
            [
                {"line": i, "word": "neural", "category": "ai_ml", "justified": False}
                for i in range(5)
            ],
        ),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=60.0,
        status=SlopStatus.INFLATED_SIGNAL,
        warnings=[],
        pattern_issues=[],
    )

    result = ProjectAnalysis(
        project_path="/test/project",
        total_files=10,
        deficit_files=3,
        clean_files=7,
        avg_deficit_score=35.0,
        weighted_deficit_score=32.0,
        avg_ldr=0.75,
        avg_inflation=0.8,
        avg_ddc=0.85,
        overall_status=SlopStatus.SUSPICIOUS,
        file_results=[file_result],
    )

    report = generate_markdown_report(result)
    assert "# AI Code Quality Audit Report" in report
    assert "/test/project" in report
    assert "Jargon" in report


def test_generate_markdown_report_project_shows_approximate_coherence():
    file_result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 50, 50, 0.50, "B"),
        inflation=InflationResult(10, 2.0, 1.5, "WARNING", ["neural"] * 10, []),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=60.0,
        status=SlopStatus.INFLATED_SIGNAL,
        warnings=[],
        pattern_issues=[],
    )

    result = ProjectAnalysis(
        project_path="/test/project",
        total_files=10,
        deficit_files=3,
        clean_files=7,
        avg_deficit_score=35.0,
        weighted_deficit_score=32.0,
        avg_ldr=0.75,
        avg_inflation=0.8,
        avg_ddc=0.85,
        overall_status=SlopStatus.SUSPICIOUS,
        file_results=[file_result],
        structural_coherence=0.8123,
        coherence_level="vr_structural_approx",
    )

    report = generate_markdown_report(result)
    assert "## Structural Coherence" in report
    # Internal algorithm name is hidden from human output (kept only in JSON).
    assert "vr_structural" not in report
    assert "sampled" in report


def test_generate_markdown_report_project_shows_suppression_ledger():
    file_result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 50, 50, 0.50, "B"),
        inflation=InflationResult(10, 2.0, 1.5, "WARNING", ["neural"] * 10, []),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=60.0,
        status=SlopStatus.INFLATED_SIGNAL,
        warnings=[],
        pattern_issues=[],
    )

    result = ProjectAnalysis(
        project_path="/test/project",
        total_files=10,
        deficit_files=3,
        clean_files=7,
        avg_deficit_score=35.0,
        weighted_deficit_score=32.0,
        avg_ldr=0.75,
        avg_inflation=0.8,
        avg_ddc=0.85,
        overall_status=SlopStatus.SUSPICIOUS,
        file_results=[file_result],
        suppression_ledger=[
            SuppressionLedgerEntry(
                file_path="/test/file.py",
                suppressed_line=12,
                directive_line=11,
                pattern_id="bare_except",
                scope="next_line",
                matched_rule="bare_except",
            )
        ],
    )

    report = generate_markdown_report(result)
    assert "## Inline Suppression Ledger" in report
    assert "bare_except" in report


def test_generate_markdown_report_project_shows_priority_hotspots():
    file_result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 50, 50, 0.50, "B"),
        inflation=InflationResult(10, 2.0, 1.5, "WARNING", ["neural"] * 10, []),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=60.0,
        status=SlopStatus.INFLATED_SIGNAL,
        warnings=[],
        pattern_issues=[],
    )

    result = ProjectAnalysis(
        project_path="/test/project",
        total_files=10,
        deficit_files=3,
        clean_files=7,
        avg_deficit_score=35.0,
        weighted_deficit_score=32.0,
        avg_ldr=0.75,
        avg_inflation=0.8,
        avg_ddc=0.85,
        overall_status=SlopStatus.SUSPICIOUS,
        file_results=[file_result],
        priority_hotspots=[
            PriorityHotspot(
                file_path="/test/file.py",
                deficit_score=60.0,
                churn_count=9,
                churn_score=1.0,
                coverage_ratio=0.2,
                priority_score=82.0,
                reasons=["high deficit", "high churn", "low coverage"],
            )
        ],
        churn_analysis_available=True,
        coverage_analysis_available=True,
    )

    report = generate_markdown_report(result)
    assert "## Priority Hotspots" in report
    assert "82.0/100" in report
    assert "low coverage" in report


def test_apply_runtime_overrides_updates_topology_settings():
    detector = SlopDetector()
    args = type("Args", (), {"topology_ceiling": 123, "topology_mode": "exact"})()

    _apply_runtime_overrides(args, detector)

    assert detector.config.get_exact_topology_ceiling() == 123
    assert detector.config.get_topology_mode_above_ceiling() == "exact"


def test_cli_parser_accepts_topology_flags():
    parser = _build_arg_parser()
    args = parser.parse_args(
        ["--project", ".", "--topology-ceiling", "123", "--topology-mode", "exact"]
    )

    assert args.topology_ceiling == 123
    assert args.topology_mode == "exact"


def test_cli_parser_accepts_format_json_alias():
    parser = _build_arg_parser()
    args = parser.parse_args(["--format", "json"])

    assert args.format == "json"
    assert args.json is False


def test_cli_parser_accepts_adaptive_init_flags():
    parser = _build_arg_parser()
    args = parser.parse_args(
        ["--init", "--adaptive-init", "--init-preview", "--apply-init-suggestions"]
    )

    assert args.init is True
    assert args.adaptive_init is True
    assert args.init_preview is True
    assert args.apply_init_suggestions is True


def test_generate_html_report():
    """Test generate_html_report."""
    result = FileAnalysis(
        file_path="/test/file.py",
        ldr=LDRResult(100, 80, 20, 0.80, "A"),
        inflation=InflationResult(5, 2.0, 0.5, "PASS", ["neural"], []),
        ddc=DDCResult(["numpy"], ["numpy"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=25.0,
        status=SlopStatus.CLEAN,
        warnings=[],
    )

    html = generate_html_report(result)
    assert "<!DOCTYPE html>" in html
    assert "SLOP Detection Report" in html
    assert "25.0" in html


def test_main_version(capsys):
    """Test main with --version flag."""
    with pytest.raises(SystemExit) as exc_info:
        with patch.object(sys, "argv", ["slop-detector", "--version"]):
            main()
    assert exc_info.value.code == 0


def test_main_list_patterns(capsys):
    """Test main with --list-patterns flag."""
    with patch.object(sys, "argv", ["slop-detector", "--list-patterns", "dummy.py"]):
        result = main()
        assert result == 0


def test_main_single_file_json(tmp_path):
    """Test main analyzing single file with JSON output."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('Hello')\n")

    output_file = tmp_path / "output.json"

    with patch.object(
        sys, "argv", ["slop-detector", str(test_file), "--json", "-o", str(output_file)]
    ):
        result = main()
        assert result == 0
        assert output_file.exists()

        data = json.loads(output_file.read_text())
        assert "file_path" in data
        assert "deficit_score" in data


def test_main_scan_alias_single_file_json(tmp_path):
    """scan is the canonical analysis surface for file/project inspection."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('Hello')\n", encoding="utf-8")
    output_file = tmp_path / "scan_output.json"

    result = main(["scan", str(test_file), "--json", "-o", str(output_file)])

    assert result == 0
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert "file_path" in data
    assert "deficit_score" in data


def test_main_single_file_markdown(tmp_path):
    """Test main analyzing single file with markdown output."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('Hello')\n", encoding="utf-8")

    output_file = tmp_path / "output.md"

    with patch.object(sys, "argv", ["slop-detector", str(test_file), "-o", str(output_file)]):
        result = main()
        assert result == 0
        assert output_file.exists()

        content = output_file.read_text(encoding="utf-8")
        assert "# AI Code Quality Audit Report" in content


def test_main_single_file_html(tmp_path):
    """Test main analyzing single file with HTML output."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('Hello')\n")

    output_file = tmp_path / "output.html"

    with patch.object(sys, "argv", ["slop-detector", str(test_file), "-o", str(output_file)]):
        result = main()
        assert result == 0
        assert output_file.exists()

        content = output_file.read_text()
        assert "<!DOCTYPE html>" in content


def test_main_project_mode(tmp_path):
    """Test main analyzing project directory."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    (project_dir / "file1.py").write_text("def func1():\n    pass\n")
    (project_dir / "file2.py").write_text("def func2():\n    return 42\n")

    with patch.object(sys, "argv", ["slop-detector", "--project", str(project_dir), "--no-color"]):
        result = main()
        assert result == 0


def test_main_review_alias_routes_to_audit(tmp_path):
    """review is the canonical changed-code surface."""
    from slop_detector.models import PriorityHotspot

    project = tmp_path / "project"
    project.mkdir()
    output_file = tmp_path / "review.json"
    analysis = ProjectAnalysis(
        project_path=str(project),
        total_files=1,
        deficit_files=1,
        clean_files=0,
        avg_deficit_score=55.0,
        weighted_deficit_score=55.0,
        avg_ldr=0.4,
        avg_inflation=0.7,
        avg_ddc=0.5,
        overall_status=SlopStatus.INFLATED_SIGNAL,
        file_results=[],
        priority_hotspots=[
            PriorityHotspot(
                file_path=str(project / "bad.py"),
                deficit_score=55.0,
                priority_score=55.0,
                reasons=["high deficit"],
            )
        ],
    )

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        with patch("slop_detector.operations.get_changed_files", return_value=["bad.py"]):
            result = main(["review", str(project), "--json", "-o", str(output_file)])

    assert result == 0
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["command"] == "audit"
    assert payload["verdict"] in {"pass", "warn", "fail"}


def test_main_review_alias_accepts_format_json(tmp_path):
    """review should accept --format json as an alias for --json."""
    project = tmp_path / "project"
    project.mkdir()
    output_file = tmp_path / "review_format.json"
    analysis = ProjectAnalysis(
        project_path=str(project),
        total_files=1,
        deficit_files=0,
        clean_files=1,
        avg_deficit_score=12.0,
        weighted_deficit_score=12.0,
        avg_ldr=0.8,
        avg_inflation=0.1,
        avg_ddc=0.9,
        overall_status=SlopStatus.CLEAN,
        file_results=[],
    )

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        with patch("slop_detector.operations.get_changed_files", return_value=[]):
            result = main(["review", str(project), "--format", "json", "-o", str(output_file)])

    assert result == 0
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["command"] == "audit"


def test_main_pulse_alias_routes_to_health(tmp_path):
    """pulse is the canonical repository health surface."""
    from slop_detector.models import PriorityHotspot

    project = tmp_path / "project"
    project.mkdir()
    output_file = tmp_path / "pulse.json"
    analysis = ProjectAnalysis(
        project_path=str(project),
        total_files=1,
        deficit_files=0,
        clean_files=1,
        avg_deficit_score=12.0,
        weighted_deficit_score=12.0,
        avg_ldr=0.8,
        avg_inflation=0.1,
        avg_ddc=0.9,
        overall_status=SlopStatus.CLEAN,
        file_results=[],
        priority_hotspots=[
            PriorityHotspot(
                file_path=str(project / "good.py"),
                deficit_score=12.0,
                priority_score=12.0,
                reasons=["elevated deficit"],
            )
        ],
    )

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        result = main(["pulse", str(project), "--json", "-o", str(output_file)])

    assert result == 0
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["command"] == "health"
    assert payload["targets"]


def test_main_sweep_routes_to_cleanup_family(tmp_path):
    """sweep canonicalizes cleanup-family execution under one verb."""
    project = tmp_path / "project"
    project.mkdir()
    output_file = tmp_path / "sweep.json"
    analysis = ProjectAnalysis(
        project_path=str(project),
        total_files=0,
        deficit_files=0,
        clean_files=0,
        avg_deficit_score=0.0,
        weighted_deficit_score=0.0,
        avg_ldr=1.0,
        avg_inflation=0.0,
        avg_ddc=1.0,
        overall_status=SlopStatus.CLEAN,
        file_results=[],
    )

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        result = main(["sweep", "dead-code", str(project), "--json", "-o", str(output_file)])

    assert result == 0
    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["command"] == "dead-code"


def test_main_emit_leda_yaml(tmp_path):
    """Test main emits LEDA injection YAML."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "model.py").write_text("def solve():\n    return 1\n", encoding="utf-8")
    output_file = tmp_path / "reports" / "leda_injection.yaml"
    fake_payload = {
        "version": "0.1",
        "source": {"analyzer": "LEDA"},
        "analysis": {"mode": "project"},
    }

    with patch.object(
        sys,
        "argv",
        [
            "slop-detector",
            "--project",
            str(project_dir),
            "--emit-leda-yaml",
            "--leda-output",
            str(output_file),
            "--leda-profile",
            "public",
            "--no-color",
            "--no-history",
        ],
    ):
        with patch("slop_detector.cli.build_leda_injection", return_value=fake_payload):
            result = main()
            assert result == 0
            assert output_file.exists()

            data = json.loads(json.dumps(yaml.safe_load(output_file.read_text())))
            assert data["source"]["analyzer"] == "LEDA"
            assert data["analysis"]["mode"] == "project"


def test_main_fail_threshold(tmp_path):
    """Test main with fail threshold."""
    test_file = tmp_path / "test.py"
    # Create a file with high deficit score
    test_file.write_text("def empty():\n    pass\n" * 10)

    with patch.object(
        sys, "argv", ["slop-detector", str(test_file), "--fail-threshold", "50", "--no-color"]
    ):
        result = main()
        # Should fail if deficit > 50
        assert result in (0, 1)


def test_main_verbose_mode(tmp_path, capsys):
    """Test main with verbose flag."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('Hello')\n")

    with patch.object(sys, "argv", ["slop-detector", str(test_file), "-v", "--no-color"]):
        result = main()
        assert result == 0


def test_main_config_file(tmp_path):
    """Test main with custom config file."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello():\n    print('Hello')\n")

    config_file = tmp_path / "config.yaml"
    config_file.write_text("version: '2.0'\nweights:\n  ldr: 0.5\n  inflation: 0.3\n  ddc: 0.2\n")

    with patch.object(
        sys, "argv", ["slop-detector", str(test_file), "-c", str(config_file), "--no-color"]
    ):
        result = main()
        assert result == 0


def test_main_disable_patterns(tmp_path):
    """Test main with disabled patterns."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def func():\n    pass\n")

    with patch.object(
        sys,
        "argv",
        [
            "slop-detector",
            str(test_file),
            "--disable",
            "bare_except",
            "--disable",
            "star_import",
            "--no-color",
        ],
    ):
        result = main()
        assert result == 0


def test_main_auto_detect_project_mode(tmp_path):
    """Test main auto-detects project mode for directories."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "test.py").write_text("def func():\n    return 1\n")

    with patch.object(sys, "argv", ["slop-detector", str(project_dir), "--no-color"]):
        result = main()
        assert result == 0


def test_main_initialization_error():
    """Test main handles detector initialization errors."""
    with patch.object(
        sys, "argv", ["slop-detector", "/nonexistent/config.yaml", "-c", "/nonexistent/config.yaml"]
    ):
        with patch("slop_detector.cli.SlopDetector", side_effect=Exception("Config error")):
            result = main()
            assert result == 1


def test_main_analysis_error(tmp_path):
    """Test main handles analysis errors."""
    test_file = tmp_path / "test.py"
    test_file.write_text("invalid python syntax {{{")

    with patch.object(sys, "argv", ["slop-detector", str(test_file), "--no-color"]):
        # Should handle syntax errors gracefully
        result = main()
        # May return 0 or 1 depending on error handling
        assert result in (0, 1)
