"""The AI work order (`--format ai-md`): the AI report as one Markdown document
an agent acts on (docs/REPORTS.md 7)."""

import re

import pytest

import slop_detector.ai_report as ai_report
from slop_detector.ai_report import AiReportInvalid, build_records
from slop_detector.ai_report_md import render_ai_report_md
from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.report_view import build_report_view
from slop_detector.semantic import SemanticFinding

SOURCE = '''
def persist(record):
    return None


def save_record(record):
    persist(record)
    return True


def fetch_exchange_rates(base="USD"):
    """Fetch live exchange rates for the base currency."""
    return {"EUR": 0.92}
'''


def _project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "store.py").write_text(SOURCE, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _ids(text, section):
    part = text.split(f"## {section}")[1].split("\n## ")[0]
    return re.findall(r"\b[FC][0-9a-f]{12}\b", part)


def test_every_item_is_worked_or_listed_exactly_once_in_priority_order(tmp_path):
    result = _project(tmp_path)
    records = build_records(build_report_view(result))[1:]
    full = render_ai_report_md(result)
    assert sorted(_ids(full, "WORK-ORDER")) == sorted(r["id"] for r in records)
    assert "NOT-APPLICABLE: every item is in the work order" in full
    limited = render_ai_report_md(result, limit=2)
    worked, listed = _ids(limited, "WORK-ORDER"), _ids(limited, "BACKLOG")
    assert len(worked) == 2 and sorted(worked + listed) == sorted(r["id"] for r in records)
    assert f"work order 2 | backlog {len(records) - 2}" in limited
    severities = re.findall(r"^### W\d+ \S+ \S+ \S+ (\S+)$", full, re.M)
    rank = {"critical": 0, "high": 1, "review": 2, "medium": 3, "low": 4}
    assert [rank[s] for s in severities] == sorted(rank[s] for s in severities)


def test_each_block_binds_the_source_and_shows_its_code(tmp_path, monkeypatch):
    result = _project(tmp_path)
    text = render_ai_report_md(result)
    assert text.count("(code below read from this content)") == len(_ids(text, "WORK-ORDER"))
    assert "span [FACT]: pkg/store.py:6-8 `save_record`" in text
    assert "7|     persist(record)" in text
    # an unused input is named, so the item can be acted on
    result.file_results[0].semantic_findings.append(SemanticFinding("scale", "input_never_used", 2, ["factor"], "e"))
    assert "scale [factor]: e" in render_ai_report_md(result)
    # the bound content differs from the file: every block is VOID, not repaired from the document
    monkeypatch.setattr(ai_report, "_sha256", lambda path: "0" * 64)
    stale = render_ai_report_md(result)
    assert "read from this content" not in stale and stale.count("(VOID: now ") == len(_ids(stale, "WORK-ORDER"))


def test_a_broken_promise_carries_its_own_question(tmp_path):
    text = render_ai_report_md(_project(tmp_path))
    block = text.split("claim_without_mechanism review")[1].split("\n### ")[0]
    assert 'promise [FACT]: "Fetch live exchange rates for the base currency."' in block
    assert "verify [NORM]: the body needs an I/O call" in block and "found: every return is a literal" in block
    assert "fix [DERIVED]: implement the mechanism, or change the docstring" in block


def test_the_contract_comes_first_and_no_local_path_leaks(tmp_path):
    text = render_ai_report_md(_project(tmp_path))
    order = ["## CONTRACT", "## HARD-STOP", "## FORBID", "## INVARIANTS", "## ALLOWED", "## MEASUREMENT",
             "## RULES", "## WORK-ORDER", "## BACKLOG", "## RESPONSE-FORM"]
    assert [text.index(s) for s in order] == sorted(text.index(s) for s in order)
    assert str(tmp_path) not in text and str(tmp_path.as_posix()) not in text
    assert "- success_without_effect: Does the reported success reflect work that happened?" in text


def test_an_invalid_report_is_never_written(tmp_path, monkeypatch, capsys):
    result = _project(tmp_path)
    monkeypatch.setattr(ai_report, "_record", lambda *a: {"record": "item"})
    with pytest.raises(AiReportInvalid):
        render_ai_report_md(result)
    out = tmp_path / "work.md"
    with pytest.raises(SystemExit) as stop:
        main([str(tmp_path), "--project", "--format", "ai-md", "-o", str(out)])
    assert stop.value.code == 2 and not out.exists()


def test_the_cli_and_the_bundle_write_the_work_order(tmp_path, capsys):
    _project(tmp_path)
    main([str(tmp_path), "--project", "--format", "ai-md", "--ai-limit", "1"])
    out = capsys.readouterr().out
    assert out.startswith("# AI-SLOP WORK ORDER") and "work order 1 |" in out
