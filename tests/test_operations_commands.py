"""Isolated tests for audit / health / cleanup command surfaces."""

import json
import sys
from unittest.mock import patch

from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.models import PriorityHotspot, ProjectAnalysis, SlopStatus


def _make_project(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "good.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (project / "bad.py").write_text("def bad():\n    pass\n", encoding="utf-8")
    return project


def _make_analysis(project):
    detector = SlopDetector()
    bad_result = detector.analyze_file(str(project / "bad.py"))
    good_result = detector.analyze_file(str(project / "good.py"))
    file_results = [bad_result, good_result]
    avg_deficit_score = sum(r.deficit_score for r in file_results) / len(file_results)
    avg_ldr = 0.6 * min(r.ldr.ldr_score for r in file_results) + 0.4 * (
        sum(r.ldr.ldr_score for r in file_results) / len(file_results)
    )
    avg_inflation = sum(r.inflation.inflation_score for r in file_results) / len(file_results)
    avg_ddc = sum(r.ddc.usage_ratio for r in file_results) / len(file_results)
    weighted_deficit_score = avg_deficit_score
    return ProjectAnalysis(
        project_path=str(project),
        total_files=len(file_results),
        deficit_files=1,
        clean_files=1,
        avg_deficit_score=avg_deficit_score,
        weighted_deficit_score=weighted_deficit_score,
        avg_ldr=avg_ldr,
        avg_inflation=avg_inflation,
        avg_ddc=avg_ddc,
        overall_status=SlopStatus.CRITICAL_DEFICIT,
        file_results=file_results,
        priority_hotspots=[
            PriorityHotspot(
                file_path=str(project / "bad.py"),
                deficit_score=bad_result.deficit_score,
                priority_score=100.0,
                reasons=["critical deficit"],
            )
        ],
    )


def test_audit_command_json_contract(tmp_path):
    project = _make_project(tmp_path)
    analysis = _make_analysis(project)
    output_file = tmp_path / "audit.json"

    with patch(
        "slop_detector.operations.get_changed_files",
        return_value=[str(project / "bad.py")],
    ):
        with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
            with patch.object(
                sys,
                "argv",
                ["slop-detector", "audit", str(project), "--json", "-o", str(output_file)],
            ):
                assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["command"] == "audit"
    assert payload["verdict"] in {"pass", "warn", "fail"}
    assert payload["attribution"]["introduced_count"] == 1
    assert payload["actions"]
    assert payload["targets"]


def test_health_command_json_contract(tmp_path):
    project = _make_project(tmp_path)
    analysis = _make_analysis(project)
    output_file = tmp_path / "health.json"

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        with patch.object(
            sys,
            "argv",
            ["slop-detector", "health", str(project), "--json", "-o", str(output_file)],
        ):
            assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["command"] == "health"
    assert payload["targets"]
    assert "summary" in payload


def test_dead_code_command_reports_issues(tmp_path):
    project = _make_project(tmp_path)
    analysis = _make_analysis(project)
    output_file = tmp_path / "dead_code.json"

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        with patch.object(
            sys,
            "argv",
            ["slop-detector", "dead-code", str(project), "--json", "-o", str(output_file)],
        ):
            assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["command"] == "dead-code"
    assert payload["verdict"] == "fail"
    assert payload["issues"]


def test_explain_command_outputs_mitigation(tmp_path):
    output_file = tmp_path / "explain.md"

    with patch.object(
        sys,
        "argv",
        ["slop-detector", "explain", "dead-code", "-o", str(output_file)],
    ):
        assert main() == 0

    report = output_file.read_text(encoding="utf-8")
    assert "Explain" in report or "EXPLAIN" in report or "command" in report.lower()
    assert "dead code" in report.lower()
