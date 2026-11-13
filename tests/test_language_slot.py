"""The language slot: a language added to the registry reaches every surface.

3.15.1 and 3.15.2 fixed the same defect twice: a language analyzer was
added, and a report (report.md, --details) or the CI gate did not know it.
These controls make that defect fail a test before it ships:

- a language registered only here ("toy") must appear in scan coverage, the
  project score, the finding summary, the report view and every report, the
  AI report and work order, the CI gate, history counts and the JSON;
- every registered language must have its schema fields (ProjectAnalysis,
  REST model, npm types, VS Code extension) and no other code may read a
  language result by its key.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import slop_detector
from slop_detector import language_registry as registry

ROOT = Path(__file__).resolve().parents[1]
# The package as imported (the source under test), not a path in the checkout.
SRC = Path(slop_detector.__file__).resolve().parent


@dataclass
class ToyIssue:
    pattern_id: str
    severity: str
    line: int
    message: str
    suggestion: Optional[str] = None
    fingerprint: Optional[str] = None
    locator: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ToyResult:
    file_path: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    ldr_equivalent: float
    issues: List[ToyIssue] = field(default_factory=list)
    slop_score: float = 0.0
    status: str = "clean"
    ast_mode: bool = True
    source_sha256: str = ""
    content_origin: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items() if k != "issues"}
        out["issues"] = [i.to_dict() for i in self.issues]
        return out


class ToyAnalyzer:
    """One critical finding per line that says `stub`."""

    def analyze(self, file_path: str) -> ToyResult:
        from slop_detector.finding_identity import bind_lines, read_source

        content, digest = read_source(file_path)
        lines = content.splitlines()
        issues = [
            ToyIssue("toy_stub", "critical", n, "stub left in toy code", "Write the toy code")
            for n, text in enumerate(lines, 1)
            if "stub" in text
        ]
        result = ToyResult(
            file_path=file_path,
            total_lines=len(lines),
            code_lines=len(lines),
            comment_lines=0,
            blank_lines=0,
            ldr_equivalent=1.0,
            issues=issues,
            slop_score=90.0 if issues else 0.0,
            status="critical_deficit" if issues else "clean",
        )
        return bind_lines(result, content, digest)


TOY = registry.LanguageSpec(
    name="toy",
    label="Toy",
    result_key="toy_file_results",
    extensions=frozenset({".toy"}),
    analyzer=ToyAnalyzer,
    fallback_mode="regex",
    ast_available=lambda: True,
    fallback_not_measured=lambda: (),
)

TOY_SOURCE = "a = 1\nstub here\nb = 2\nstub again\nstub three\n"


@pytest.fixture
def toy(monkeypatch):
    monkeypatch.setattr(registry, "LANGUAGES", registry.LANGUAGES + (TOY,))
    return TOY


@pytest.fixture
def scanned(toy, tmp_path):
    from slop_detector.core import SlopDetector

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\n', encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "ok.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "a.toy").write_text(TOY_SOURCE, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def test_the_toy_language_is_discovered_and_counted(scanned):
    coverage = scanned.scan_coverage
    assert coverage["analyzed"].get("toy") == 1, coverage["analyzed"]
    assert coverage["analyzed"]["total"] == 2, coverage["analyzed"]
    assert all(f["extension"] != ".toy" for f in coverage["unsupported"]["files"])
    assert "toy" in coverage.get("analysis_modes", {}), coverage.get("analysis_modes")
    assert len(getattr(scanned, "toy_file_results", [])) == 1


def test_the_toy_language_counts_in_the_score_and_the_summary(scanned):
    assert scanned.total_files == 2 and scanned.deficit_files == 1
    assert scanned.finding_summary["severity"]["critical"] == 3, scanned.finding_summary
    from slop_detector.finding_summary import get_finding_summary

    scanned.finding_summary = {}
    assert get_finding_summary(scanned)["severity"]["critical"] == 3


def test_the_toy_language_reaches_every_report(scanned):
    from slop_detector.renderer_html import generate_html_report
    from slop_detector.renderer_markdown import generate_markdown_report
    from slop_detector.renderer_text import generate_text_report
    from slop_detector.report_view import build_report_view

    view = build_report_view(scanned)
    assert [i.rule for i in view.findings].count("toy_stub") == 3
    assert any(row[0].endswith("a.toy") for row in view.file_rows)
    for render in (generate_markdown_report, generate_html_report, generate_text_report):
        assert render(scanned).count("toy_stub") >= 3, render.__module__
    assert "toy_file_results" in scanned.to_dict()


def test_the_toy_language_reaches_the_ai_report_and_work_order(scanned, tmp_path):
    from slop_detector.ai_report import build_records
    from slop_detector.ai_report_md import render_ai_report_md
    from slop_detector.report_view import build_report_view

    records = build_records(build_report_view(scanned))[1:]
    toy = [r for r in records if r["rule"] == "toy_stub"]
    assert len(toy) == 3 and len({r["id"] for r in toy}) == 3
    digest = hashlib.sha256((tmp_path / "pkg" / "a.toy").read_bytes()).hexdigest()
    assert {r["source_sha256"] for r in toy} == {digest}
    assert render_ai_report_md(scanned).count("toy_stub") >= 3  # passes the read-back check


def test_the_toy_language_is_judged_by_the_gate(scanned):
    from slop_detector.service.policy import evaluate_gate, gate_exit_code

    gate = evaluate_gate(scanned, mode="hard", claims_strict=False, read_only=False)
    assert gate_exit_code(gate) == 1 and any(p.endswith("a.toy") for p in gate.failed_files)


def test_the_toy_language_counts_in_history_and_telemetry(scanned):
    from slop_detector import impact, telemetry

    assert impact._issue_count_from_result(scanned) == 3
    assert telemetry._issue_count_from_result(scanned) == 3


def test_every_registered_language_has_its_schema_fields():
    from slop_detector.api.models import AgentProjectResponse
    from slop_detector.languages import LANGUAGE_ANALYZERS
    from slop_detector.models import ProjectAnalysis

    project_fields = set(ProjectAnalysis.__dataclass_fields__)
    api_fields = set(getattr(AgentProjectResponse, "model_fields", {}) or {})
    npm_types = (ROOT / "npm-wrapper" / "types.d.ts").read_text(encoding="utf-8")
    for item in registry.LANGUAGES:
        assert item.result_key in project_fields, item.name
        assert item.result_key in api_fields, item.name
        assert f"{item.result_key}:" in npm_types, item.name
    extensions = {e for item in registry.LANGUAGES for e in item.extensions}
    assert set(LANGUAGE_ANALYZERS) == {".py"} | extensions
    from slop_detector import cli_init, core_project

    assert not extensions & core_project._UNSUPPORTED_SOURCE_EXTENSIONS
    assert extensions <= set(cli_init._source_suffixes())  # --init counts the language


def test_the_vscode_extension_reads_every_language_result_generically():
    findings = (ROOT / "vscode-extension" / "src" / "findings.ts").read_text(encoding="utf-8")
    # one rule for every language result, not a list of language keys
    assert "_file_results" in findings
    for item in registry.LANGUAGES:
        assert item.result_key not in findings, item.result_key


ALLOWED = {
    "language_registry.py",  # the list itself
    "models.py",  # the ProjectAnalysis fields
    "api/models.py",  # the REST schema fields
}


def test_no_code_reads_a_language_result_by_its_key():
    keys = [re.escape(item.result_key) for item in registry.LANGUAGES]
    pattern = re.compile("|".join(keys))
    offenders = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in ALLOWED:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert not offenders, "read language results through language_registry:\n" + "\n".join(
        offenders
    )


def test_a_single_toy_file_is_scanned_as_its_own_language(toy, tmp_path):
    from slop_detector.core import SlopDetector
    from slop_detector.service.targets import analyze_single_source_file, target_kind

    path = tmp_path / "a.toy"
    path.write_text(TOY_SOURCE, encoding="utf-8")
    assert target_kind(path, project=False) == "source_file"
    result = analyze_single_source_file(SlopDetector(read_only=True), path)
    assert len(getattr(result, "toy_file_results", [])) == 1
    assert result.scan_coverage["analyzed"]["toy"] == 1
    import pytest as _pytest

    with _pytest.raises(Exception, match="not Python source"):
        SlopDetector(read_only=True).analyze_file(str(path))


def test_the_toy_language_reaches_the_rest_response(scanned):
    # FH-G1-01: the REST snapshot keeps every registered language's results
    from slop_detector.api.models import AgentProjectResponse

    dumped = AgentProjectResponse.from_result(scanned).model_dump()
    toy = dumped.get("toy_file_results") or []
    assert len(toy) == 1 and len(toy[0]["issues"]) == 3, sorted(dumped)


def test_the_analyzer_for_a_toy_file_comes_from_the_registry(toy, tmp_path):
    # FH-G0-01: the public extension -> analyzer lookup follows the registry
    from slop_detector.languages import get_analyzer_for_file

    assert isinstance(get_analyzer_for_file(str(tmp_path / "a.toy")), ToyAnalyzer)


def test_the_toy_language_reaches_the_cli_details_output(scanned, capsys):
    from slop_detector.cli import main

    main(["--project", scanned.project_path, "--details", "--no-color", "--no-history"])
    out = capsys.readouterr().out
    assert out.count("toy_stub") >= 3, out[-2000:]


def test_the_quarantine_records_a_toy_file_with_its_score(scanned, tmp_path):
    from slop_detector.ci_gate import CIGate
    from slop_detector.gate.models import GateMode, GateVerdict

    gate = CIGate(mode=GateMode.QUARANTINE, quarantine_db_path=str(tmp_path / "q.json"))
    result = gate.evaluate(scanned)
    assert result.verdict == GateVerdict.QUARANTINE
    (toy_path,) = [p for p in gate.quarantine_records if p.endswith("a.toy")]
    assert gate.quarantine_records[toy_path].last_deficit_score == 90.0


def test_init_counts_the_toy_language(toy, tmp_path):
    from slop_detector import cli_init

    (tmp_path / "a.toy").write_text(TOY_SOURCE, encoding="utf-8")
    assert cli_init._count_repo_languages(tmp_path).get("toy") == 1
