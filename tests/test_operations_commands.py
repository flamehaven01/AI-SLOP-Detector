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


def _make_analysis(project, *, churn_count=0, churn_score=0.0, coverage_ratio=None, reasons=None):
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
                churn_count=churn_count,
                churn_score=churn_score,
                coverage_ratio=coverage_ratio,
                reasons=reasons or ["critical deficit"],
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
    analysis = _make_analysis(
        project,
        churn_count=0,
        churn_score=0.0,
        coverage_ratio=0.0,
        reasons=["critical deficit", "low coverage"],
    )
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
    issue = payload["issues"][0]
    assert issue["action_class"] == "safe_review"
    assert 0.0 <= issue["confidence"] <= 1.0
    assert issue["evidence"]["coverage_ratio"] == 0.0
    assert issue["evidence"]["churn_score"] == 0.0


def test_dead_code_high_churn_lowers_confidence(tmp_path):
    project = _make_project(tmp_path)
    analysis = _make_analysis(
        project,
        churn_count=9,
        churn_score=1.0,
        coverage_ratio=0.0,
        reasons=["critical deficit", "high churn", "low coverage"],
    )
    output_file = tmp_path / "dead_code_churn.json"

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        with patch.object(
            sys,
            "argv",
            ["slop-detector", "dead-code", str(project), "--json", "-o", str(output_file)],
        ):
            assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    issue = payload["issues"][0]
    assert issue["action_class"] in {"needs_review", "unsafe_auto_remove"}
    assert issue["confidence"] < 0.75
    assert issue["evidence"]["churn_score"] == 1.0


def test_dead_code_excludes_high_deficit_non_dead_file():
    from slop_detector.operations import _should_include_dead_code_candidate

    class _P:
        def __init__(self, pid):
            self.pattern_id = pid

    class _FR:
        def __init__(self, deficit, patterns):
            self.deficit_score = deficit
            self.pattern_issues = patterns

    # High deficit (low LDR / inflation) with no placeholder and no dead-code
    # patterns must NOT be classified as dead code.
    non_dead = _FR(72.0, [_P("god_function"), _P("deep_nesting")])
    assert _should_include_dead_code_candidate(non_dead, placeholder=False) is False

    # A real dead-code pattern qualifies even at low deficit.
    dead = _FR(12.0, [_P("pass_placeholder")])
    assert _should_include_dead_code_candidate(dead, placeholder=False) is True

    # Placeholder-only files always qualify.
    assert _should_include_dead_code_candidate(_FR(0.0, []), placeholder=True) is True


def test_unused_deps_includes_python_manifest_hygiene(tmp_path):
    project = tmp_path / "pyproj"
    project.mkdir()
    (project / "module.py").write_text(
        "import yaml\nimport rich\n\n\ndef run():\n    return yaml.__name__, rich.__name__\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\ndependencies=['pyyaml>=6.0','jinja2>=3.1']\n",
        encoding="utf-8",
    )
    detector = SlopDetector()
    file_result = detector.analyze_file(str(project / "module.py"))
    analysis = ProjectAnalysis(
        project_path=str(project),
        total_files=1,
        deficit_files=1 if file_result.deficit_score > 0 else 0,
        clean_files=0 if file_result.deficit_score > 0 else 1,
        avg_deficit_score=file_result.deficit_score,
        weighted_deficit_score=file_result.deficit_score,
        avg_ldr=file_result.ldr.ldr_score,
        avg_inflation=file_result.inflation.inflation_score,
        avg_ddc=file_result.ddc.usage_ratio,
        overall_status=file_result.status,
        file_results=[file_result],
    )
    output_file = tmp_path / "python_manifest_unused.json"

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        with patch.object(
            sys,
            "argv",
            ["slop-detector", "unused-deps", str(project), "--json", "-o", str(output_file)],
        ):
            assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    issue_types = {(item.get("issue_type"), item.get("dependency")) for item in payload["issues"]}
    assert ("manifest_unused_dependency", "jinja2>=3.1") in issue_types
    assert ("undeclared_import", "rich") in issue_types


def test_unused_deps_excludes_stdlib_and_dev_extras(tmp_path):
    project = tmp_path / "pyproj_fp"
    project.mkdir()
    (project / "module.py").write_text(
        "import collections\nimport yaml\n\n\n"
        "def run():\n    return collections.OrderedDict(), yaml.__name__\n",
        encoding="utf-8",
    )
    (project / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.1.0'\ndependencies=['pyyaml>=6.0']\n"
        "[project.optional-dependencies]\ndev=['black>=24.0','pytest>=8.0']\n",
        encoding="utf-8",
    )
    detector = SlopDetector()
    file_result = detector.analyze_file(str(project / "module.py"))
    analysis = ProjectAnalysis(
        project_path=str(project),
        total_files=1,
        deficit_files=0,
        clean_files=1,
        avg_deficit_score=file_result.deficit_score,
        weighted_deficit_score=file_result.deficit_score,
        avg_ldr=file_result.ldr.ldr_score,
        avg_inflation=file_result.inflation.inflation_score,
        avg_ddc=file_result.ddc.usage_ratio,
        overall_status=file_result.status,
        file_results=[file_result],
    )
    output_file = tmp_path / "fp_check.json"

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        with patch.object(
            sys,
            "argv",
            ["slop-detector", "unused-deps", str(project), "--json", "-o", str(output_file)],
        ):
            assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    deps = [(i.get("issue_type"), i.get("dependency")) for i in payload["issues"]]
    # stdlib import must NOT be flagged as undeclared
    assert not any(t == "undeclared_import" and d == "collections" for t, d in deps)
    # dev/optional extras must NOT be flagged as unused
    assert not any(t == "manifest_unused_dependency" and "black" in (d or "") for t, d in deps)
    assert not any(t == "manifest_unused_dependency" and "pytest" in (d or "") for t, d in deps)


def test_unused_deps_includes_package_json_hygiene(tmp_path):
    project = tmp_path / "jsproj"
    project.mkdir()
    (project / "app.js").write_text(
        "import _ from 'lodash';\nimport React from 'react';\nconsole.log(_, React);\n",
        encoding="utf-8",
    )
    (project / "package.json").write_text(
        json.dumps(
            {
                "name": "demo-js",
                "version": "0.1.0",
                "dependencies": {"lodash": "^4.17.0", "axios": "^1.0.0"},
            }
        ),
        encoding="utf-8",
    )
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
    output_file = tmp_path / "js_manifest_unused.json"

    with patch("slop_detector.cli.SlopDetector.analyze_project", return_value=analysis):
        with patch.object(
            sys,
            "argv",
            ["slop-detector", "unused-deps", str(project), "--json", "-o", str(output_file)],
        ):
            assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    issue_types = {(item.get("issue_type"), item.get("dependency")) for item in payload["issues"]}
    assert ("manifest_unused_dependency", "axios") in issue_types
    assert ("undeclared_import", "react") in issue_types


def test_boundary_violations_respects_opt_in_layered_architecture(tmp_path, monkeypatch):
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    project = tmp_path / "archproj"
    (project / "src" / "api").mkdir(parents=True)
    (project / "src" / "domain").mkdir(parents=True)
    (project / "src" / "data").mkdir(parents=True)
    (project / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "api" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "domain" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "data" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "api" / "controller.py").write_text(
        "from src.domain import model\n", encoding="utf-8"
    )
    (project / "src" / "domain" / "model.py").write_text(
        "from src.data import repo\n", encoding="utf-8"
    )
    (project / "src" / "data" / "repo.py").write_text("VALUE = 1\n", encoding="utf-8")
    config_file = tmp_path / "arch.slopconfig.yaml"
    config_file.write_text(
        "architecture:\n  enabled: true\n  preset: layered\n",
        encoding="utf-8",
    )
    output_file = tmp_path / "boundary.json"

    with patch.object(
        sys,
        "argv",
        [
            "slop-detector",
            "boundary-violations",
            str(project),
            "--config",
            str(config_file),
            "--json",
            "-o",
            str(output_file),
        ],
    ):
        assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    issue_types = {item.get("issue_type") for item in payload["issues"]}
    assert "layer_boundary_violation" in issue_types
    assert any(item.get("importer_layer") == "domain" for item in payload["issues"])
    violating_issue = next(
        item for item in payload["issues"] if item.get("importer_layer") == "domain"
    )
    assert violating_issue["evidence"]["matched_importer_pattern"]
    assert violating_issue["evidence"]["matched_importee_pattern"]


def test_boundary_violations_allows_api_to_domain_in_layered_preset(tmp_path, monkeypatch):
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    project = tmp_path / "archproj_allowed"
    (project / "src" / "api").mkdir(parents=True)
    (project / "src" / "domain").mkdir(parents=True)
    (project / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "api" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "domain" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "api" / "controller.py").write_text(
        "from src.domain import model\n", encoding="utf-8"
    )
    (project / "src" / "domain" / "model.py").write_text("VALUE = 1\n", encoding="utf-8")
    config_file = tmp_path / "arch_allowed.slopconfig.yaml"
    config_file.write_text(
        "architecture:\n  enabled: true\n  preset: layered\n",
        encoding="utf-8",
    )
    output_file = tmp_path / "boundary_allowed.json"

    with patch.object(
        sys,
        "argv",
        [
            "slop-detector",
            "boundary-violations",
            str(project),
            "--config",
            str(config_file),
            "--json",
            "-o",
            str(output_file),
        ],
    ):
        assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    issue_types = {item.get("issue_type") for item in payload["issues"]}
    assert "layer_boundary_violation" not in issue_types


def test_boundary_violations_stays_cycle_only_without_architecture_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    project = tmp_path / "archproj_default"
    (project / "src" / "domain").mkdir(parents=True)
    (project / "src" / "data").mkdir(parents=True)
    (project / "src" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "domain" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "data" / "__init__.py").write_text("", encoding="utf-8")
    (project / "src" / "domain" / "model.py").write_text(
        "from src.data import repo\n", encoding="utf-8"
    )
    (project / "src" / "data" / "repo.py").write_text("VALUE = 1\n", encoding="utf-8")
    config_file = tmp_path / "arch_disabled.slopconfig.yaml"
    config_file.write_text(
        "architecture:\n  enabled: false\n  preset: none\n",
        encoding="utf-8",
    )
    output_file = tmp_path / "boundary_default.json"

    with patch.object(
        sys,
        "argv",
        [
            "slop-detector",
            "boundary-violations",
            str(project),
            "--config",
            str(config_file),
            "--json",
            "-o",
            str(output_file),
        ],
    ):
        assert main() == 0

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    issue_types = {item.get("issue_type") for item in payload["issues"]}
    assert "layer_boundary_violation" not in issue_types


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
