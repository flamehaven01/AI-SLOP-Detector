"""The CI gate judges JS/TS and Go files as it judges Python files.

Up to 3.15.1 the gate read Python file results only: a project of one Go file
with five panic() calls (three critical go_panic findings, project score 100,
CRITICAL_DEFICIT) passed --ci-mode hard with exit 0. JS/TS and Go results
carry a score and severities, so the same thresholds apply to them; the
metrics they do not have (inflation, DDC) are never judged.
"""

import pytest

from slop_detector.ci_gate import CIGate
from slop_detector.core import SlopDetector
from slop_detector.gate.models import GateMode, GateVerdict
from slop_detector.languages.go_analyzer import GoFileAnalysis, GoIssue
from slop_detector.languages.js_analyzer import JSFileAnalysis, JSIssue
from slop_detector.models import ProjectAnalysis, SlopStatus
from slop_detector.service.policy import evaluate_gate, gate_exit_code

GO_PANICS = (
    "package main\n\nfunc main() {\n" + "".join(f'\tpanic("{c}")\n' for c in "abcde") + "}\n"
)


def _scan(tmp_path, files):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "g"\n', encoding="utf-8")
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def test_a_go_only_project_in_the_critical_band_fails_the_hard_gate(tmp_path):
    result = _scan(tmp_path, {"main.go": GO_PANICS})
    # the case this control is about, as measured on 3.15.1
    assert result.weighted_deficit_score >= 70.0
    assert result.finding_summary["severity"]["critical"] >= 3
    gate = evaluate_gate(result, mode="hard", claims_strict=False, read_only=False)
    assert gate_exit_code(gate) == 1, gate.message
    assert [p for p in gate.failed_files if p.endswith("main.go")], gate.failed_files


def _go(score, severities=()):
    return GoFileAnalysis(
        file_path="pkg/main.go",
        total_lines=40,
        code_lines=30,
        comment_lines=5,
        blank_lines=5,
        ldr_equivalent=0.75,
        issues=[GoIssue("go_panic", s, n + 1, "panic") for n, s in enumerate(severities)],
        slop_score=score,
    )


def _js(score, severities=()):
    return JSFileAnalysis(
        file_path="web/app.ts",
        language="typescript",
        total_lines=40,
        code_lines=30,
        comment_lines=5,
        blank_lines=5,
        ldr_equivalent=0.75,
        issues=[JSIssue("js_any_type", s, n + 1, 0, "any") for n, s in enumerate(severities)],
        slop_score=score,
    )


def _project(go=(), js=()):
    return ProjectAnalysis(
        project_path="proj",
        total_files=len(go) + len(js),
        deficit_files=0,
        clean_files=len(go) + len(js),
        avg_deficit_score=0.0,
        weighted_deficit_score=0.0,
        avg_ldr=0.75,
        avg_inflation=0.0,
        avg_ddc=1.0,
        overall_status=SlopStatus.CLEAN,
        file_results=[],
        js_file_results=list(js),
        go_file_results=list(go),
    )


@pytest.mark.parametrize(
    "make, score, severities, verdict",
    [
        (_go, 80.0, (), GateVerdict.FAIL),  # deficit band: critical
        (_js, 80.0, (), GateVerdict.FAIL),
        (_go, 40.0, (), GateVerdict.WARN),  # deficit band: suspicious
        (_js, 40.0, (), GateVerdict.WARN),
        (_go, 10.0, ("critical",) * 3, GateVerdict.FAIL),  # critical findings
        (_go, 10.0, ("critical",) * 2, GateVerdict.PASS),
        (_js, 10.0, ("high",) * 5, GateVerdict.WARN),  # high findings
        (_js, 10.0, ("high",) * 4, GateVerdict.PASS),
        (_go, 10.0, (), GateVerdict.PASS),
    ],
)
def test_language_files_meet_the_python_thresholds(make, score, severities, verdict):
    file_result = make(score, severities)
    project = _project(**({"go": [file_result]} if make is _go else {"js": [file_result]}))
    gate = CIGate(mode=GateMode.HARD).evaluate(project)
    assert gate.verdict == verdict, (score, severities, gate.message)
    assert (file_result.file_path in gate.failed_files) == (verdict == GateVerdict.FAIL)
    assert (file_result.file_path in gate.warned_files) == (verdict == GateVerdict.WARN)


def test_soft_mode_reports_a_failing_language_file_without_failing_the_build():
    gate = CIGate(mode=GateMode.SOFT).evaluate(_project(go=[_go(80.0)]))
    assert gate.verdict == GateVerdict.WARN and not gate.should_fail_build
    assert gate.failed_files == ["pkg/main.go"]


def test_quarantine_records_a_language_file_with_its_score(tmp_path):
    gate = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=str(tmp_path / "q.json"))
    result = gate.evaluate(_project(js=[_js(80.0)]))
    assert result.verdict == GateVerdict.QUARANTINE and result.failed_files == ["web/app.ts"]
    record = gate.quarantine_records["web/app.ts"]
    assert record.offense_count == 1 and record.last_deficit_score == 80.0, record
