"""The AI report ai-slop-report/1 and the report bundle (docs/REPORTS.md 4, 7; O4)."""

import hashlib
import json

import pytest

import slop_detector.ai_report as ai_report
from slop_detector.ai_report import (
    AiReportInvalidError,
    build_records,
    render_ai_report,
    schema,
    validate,
)
from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.mcp.server import MCPServer
from slop_detector.report_bundle import BUNDLE_FILES, write_bundle
from slop_detector.report_pdf import BROWSER_ENV
from slop_detector.report_view import build_report_view

HOLLOW = """
def persist(record):
    return None


def save_record(record):
    persist(record)
    return True
"""


def _project(tmp_path):
    (tmp_path / "pkg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pkg" / "store.py").write_text(HOLLOW, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _lines(text):
    return [json.loads(line) for line in text.splitlines()]


def test_the_header_comes_first_and_every_item_is_bound_to_its_source(tmp_path):
    result = _project(tmp_path)
    records = _lines(render_ai_report(result))
    header, items = records[0], records[1:]
    assert header["schema"] == "ai-slop-report/1" and header["record"] == "header"
    assert (
        header["findings"] + header["candidates"]
        == header["emitted"] + header["truncated"]
        == len(items)
    )
    assert {"FINDING", "REVIEW_CANDIDATE"} == {i["kind"] for i in items}
    digest = hashlib.sha256((tmp_path / "pkg" / "store.py").read_bytes()).hexdigest()
    assert {i["source_sha256"] for i in items} == {digest}
    assert {i["file"] for i in items} == {"pkg/store.py"}
    # rules shared by every item are stated once, in the header
    assert header["forbid"] and header["verify"] and header["prove"]["suggestion"]
    assert not any("forbid" in i or "prove" in i for i in items)
    candidates = [i for i in items if i["kind"] == "REVIEW_CANDIDATE"]
    assert all(i["severity"] is None and i["channel_state"] == "MEASURED" for i in candidates)


def test_ids_are_stable_across_runs_and_distinct(tmp_path):
    first = [r["id"] for r in _lines(render_ai_report(_project(tmp_path)))[1:]]
    second = [r["id"] for r in _lines(render_ai_report(_project(tmp_path)))[1:]]
    assert first == second and len(set(first)) == len(first)
    # the same rule at two places is two items
    twice = ["def a(x):", "    return None", "", "", "def b(y):", "    return None", ""]
    (tmp_path / "pkg" / "twice.py").write_text(chr(10).join(twice), encoding="utf-8")
    items = _lines(render_ai_report(SlopDetector(read_only=True).analyze_project(str(tmp_path))))[
        1:
    ]
    same_rule = [
        i["id"]
        for i in items
        if i["file"] == "pkg/twice.py" and i["rule"] == "return_none_placeholder"
    ]
    assert len(same_rule) == 2 and len(set(same_rule)) == 2


def test_a_limit_keeps_the_count_of_what_was_left_out(tmp_path):
    records = _lines(render_ai_report(_project(tmp_path), limit=1))
    assert records[0]["emitted"] == 1 and len(records) == 2
    assert records[0]["truncated"] == records[0]["findings"] + records[0]["candidates"] - 1


def test_an_unmeasured_hollow_channel_is_stated_not_zeroed(tmp_path):
    result = _project(tmp_path)
    for f in result.file_results:
        f.semantic_coverage, f.semantic_findings = {"state": "UNMEASURED"}, []
    header = _lines(render_ai_report(result))[0]
    assert header["measurement"]["hollow"] == "UNMEASURED"


def test_a_record_that_breaks_the_schema_is_never_emitted(tmp_path, monkeypatch, capsys):
    records = build_records(build_report_view(_project(tmp_path)))
    broken = [dict(records[0])] + [dict(records[1], line="three")]
    with pytest.raises(AiReportInvalidError):
        validate(broken)
    with pytest.raises(AiReportInvalidError):
        validate([dict(records[0], surprise=True)])  # no field outside the schema
    with pytest.raises(AiReportInvalidError):
        validate([])

    monkeypatch.setattr(ai_report, "build_records", lambda view, limit=None: broken)
    with pytest.raises(SystemExit) as stop:
        main([str(tmp_path / "pkg"), "--format", "ai", "--no-history"])
    assert stop.value.code == 2
    out = capsys.readouterr()
    assert out.out == "" and "failed its schema" in out.err


def test_the_schema_describes_both_record_kinds():
    described = schema()
    assert described["$id"] == "ai-slop-report/1"
    assert "source_sha256" in described["item"]["properties"]
    assert "hold_if" in described["header"]["properties"]


def test_the_cli_prints_json_lines(tmp_path, capsys):
    _project(tmp_path)
    assert main([str(tmp_path / "pkg"), "--format", "ai", "--no-history"]) == 0
    records = _lines(capsys.readouterr().out)
    assert records[0]["record"] == "header" and len(records) > 1


def test_the_bundle_lists_what_it_could_not_write_and_removes_a_stale_copy(tmp_path, monkeypatch):
    result = _project(tmp_path / "src")
    out = tmp_path / "reports"
    out.mkdir()
    (out / "report.pdf").write_bytes(b"%PDF- from an earlier run")
    monkeypatch.setenv(BROWSER_ENV, str(tmp_path / "missing-browser"))
    written, failed = write_bundle(result, str(out))
    assert written == ["report.md", "report.html", "ai-report.jsonl", "ai-report.md", "scan.json"]
    assert [name for name, _ in failed] == ["report.pdf"]
    assert "ENV_BLOCKED" in failed[0][1] and "earlier run was removed" in failed[0][1]
    assert not (out / "report.pdf").exists()
    assert set(BUNDLE_FILES) - {"report.pdf"} == {p.name for p in out.iterdir()}


def test_the_cli_exits_2_on_an_incomplete_bundle_and_read_only_refuses_it(
    tmp_path, monkeypatch, capsys
):
    _project(tmp_path)
    monkeypatch.setenv(BROWSER_ENV, str(tmp_path / "missing-browser"))
    with pytest.raises(SystemExit) as stop:
        main(
            [str(tmp_path / "pkg"), "--report-dir", str(tmp_path / "r"), "--quiet", "--no-history"]
        )
    assert stop.value.code == 2
    assert "not written: report.pdf" in capsys.readouterr().err
    code = main([str(tmp_path / "pkg"), "--report-dir", str(tmp_path / "r2"), "--read-only"])
    assert code != 0 and not (tmp_path / "r2").exists()


def test_the_mcp_tool_returns_the_same_report(tmp_path):
    _project(tmp_path)
    response = MCPServer().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "slop_ai_report",
                "arguments": {"target": str(tmp_path / "pkg"), "limit": 2},
            },
        }
    )
    result = response["result"]
    assert result["isError"] is False
    records = result["structuredContent"]["records"]
    assert records[0]["emitted"] == 2 and _lines(result["content"][0]["text"]) == records
    missing = MCPServer().handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "slop_ai_report", "arguments": {"target": str(tmp_path / "nope")}},
        }
    )
    assert missing["result"]["isError"] is True
