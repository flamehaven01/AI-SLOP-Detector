"""A project result says whether its score measures anything.

overall_status is a score band, so a scan that analyzed nothing reported
"clean / 0.0" like a clean project. scan_coverage now carries
measurement_state (COMPLETE / PARTIAL / NO_MEASUREMENT), score_valid and
reason; overall_status and the scores keep their types and meaning.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from slop_detector.ci_gate import CIGate
from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.gate.models import GateMode, GateVerdict
from slop_detector.patterns.python_complexity import GodFunctionPattern
from slop_detector.renderer_markdown import generate_markdown_report
from slop_detector.renderer_rich import _render_rich_project
from slop_detector.renderer_text import generate_text_report

CODE = "def f(x):\n    return x + 1\n"


def _state(result) -> tuple:
    cov = result.scan_coverage
    return cov["measurement_state"], cov["score_valid"], cov["reason"]


def _scan(path: Path):
    return SlopDetector(read_only=True).analyze_project(str(path))


def _fail_analysis_of(monkeypatch, name: str) -> None:
    original = SlopDetector._build_file_analysis

    def build(self, file_path, *args, **kwargs):
        if Path(file_path).name == name:
            raise AttributeError("analysis raised")
        return original(self, file_path, *args, **kwargs)

    monkeypatch.setattr(SlopDetector, "_build_file_analysis", build)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text(CODE, encoding="utf-8")
    (tmp_path / "b.py").write_text(CODE, encoding="utf-8")
    return tmp_path


def test_complete_scan(project):
    assert _state(_scan(project)) == ("COMPLETE", True, None)


def test_a_failed_file_makes_it_partial(project, monkeypatch):
    _fail_analysis_of(monkeypatch, "b.py")
    assert _state(_scan(project)) == ("PARTIAL", True, "analysis_failed")


def test_an_unmeasured_check_makes_it_partial(project, monkeypatch):
    def broken(self, tree, file, content):
        raise RuntimeError("pattern raised")

    monkeypatch.setattr(GodFunctionPattern, "check", broken)
    assert _state(_scan(project)) == ("PARTIAL", True, "checks_unmeasured")


def _fail_all_analysis(monkeypatch) -> None:
    def build(*args, **kwargs):
        raise AttributeError("analysis raised")

    monkeypatch.setattr(SlopDetector, "_build_file_analysis", build)


def test_every_file_failed_is_no_measurement(project, monkeypatch):
    _fail_all_analysis(monkeypatch)
    assert _state(_scan(project)) == ("NO_MEASUREMENT", False, "all_analysis_failed")


def test_no_supported_files_is_no_measurement(tmp_path):
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    assert _state(_scan(tmp_path)) == ("NO_MEASUREMENT", False, "no_eligible_files")


def test_only_excluded_files_is_no_measurement(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(CODE, encoding="utf-8")
    assert _state(_scan(tmp_path)) == ("NO_MEASUREMENT", False, "all_excluded")


def test_existing_fields_keep_type_and_meaning(tmp_path):
    """Preservation: an empty scan is still overall_status clean, score 0.0."""
    data = _scan(tmp_path).to_dict()
    assert data["overall_status"] == "clean" and data["weighted_deficit_score"] == 0.0
    assert data["scan_coverage"]["score_valid"] is False


def test_hard_gate_without_eligible_files_warns_not_passes(tmp_path):
    gate = CIGate(mode=GateMode.HARD).evaluate(_scan(tmp_path))
    assert gate.verdict == GateVerdict.WARN and gate.should_fail_build is False


def test_hard_gate_with_all_analysis_failed_fails(project, monkeypatch):
    _fail_all_analysis(monkeypatch)
    gate = CIGate(mode=GateMode.HARD).evaluate(_scan(project))
    assert gate.verdict == GateVerdict.FAIL and gate.should_fail_build is True


def test_cli_hard_exit_codes(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["--project", str(empty), "--ci-mode", "hard", "--json"]) == 0
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "a.py").write_text(CODE, encoding="utf-8")
    _fail_all_analysis(monkeypatch)
    assert main(["--project", str(broken), "--ci-mode", "hard", "--json"]) == 1


def test_human_reports_say_not_evaluated(tmp_path):
    result = _scan(tmp_path)
    buffer = io.StringIO()
    _render_rich_project(Console(file=buffer, width=200), result)
    for text in (buffer.getvalue(), generate_text_report(result), generate_markdown_report(result)):
        assert "NOT EVALUATED" in text and "N/A" in text
        status_lines = [line for line in text.splitlines() if "status" in line.lower()]
        assert status_lines and not any("clean" in line.lower() for line in status_lines)
    markdown = generate_markdown_report(result)
    assert "| **Weighted Deficit Score** | N/A | NOT EVALUATED |" in markdown


def _agent_summary(result) -> tuple:
    from slop_detector.api.models import AgentProjectResponse

    summary = AgentProjectResponse.from_result(result).summary
    return summary["measurement_state"], summary["score_valid"], summary["reason"]


def test_agent_response_complete(project):
    assert _agent_summary(_scan(project)) == ("COMPLETE", True, None)


def test_agent_response_partial(project, monkeypatch):
    _fail_analysis_of(monkeypatch, "b.py")
    assert _agent_summary(_scan(project)) == ("PARTIAL", True, "analysis_failed")


def test_agent_response_all_analysis_failed(project, monkeypatch):
    _fail_all_analysis(monkeypatch)
    assert _agent_summary(_scan(project)) == ("NO_MEASUREMENT", False, "all_analysis_failed")


def test_agent_response_no_eligible_files(tmp_path):
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    assert _agent_summary(_scan(tmp_path)) == ("NO_MEASUREMENT", False, "no_eligible_files")
