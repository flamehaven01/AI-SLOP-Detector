"""S0-P1: the work-order contract comes from a versioned JSON ruleset, checked
against its schema and bound by a canonical SHA-256; a missing or invalid
ruleset fails the report closed, with no default text to fall back on.
"""

import hashlib
import json
import shutil

import pytest

import slop_detector.work_order_rules as rules
from slop_detector.ai_report import AiReportInvalidError, build_records, render_ai_report
from slop_detector.ai_report_md import render_ai_report_md
from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.report_view import build_report_view

SOURCE = "def f(x):\n    # TODO: validate x\n    return x\n\n\ndef g(a, b):\n    return a\n"


def _result(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "m.py").write_text(SOURCE, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _copy(tmp_path, monkeypatch, change=None, raw=None):
    """A copy of the packaged ruleset, edited, used for the report."""
    target = tmp_path / "rules.json"
    if raw is not None:
        target.write_text(raw, encoding="utf-8")
    else:
        data = json.loads(rules.RULESET_PATH.read_text(encoding="utf-8"))
        if change:
            change(data)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    monkeypatch.setattr(rules, "RULESET_PATH", target)
    return target


def _canonical(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def test_the_header_names_the_ruleset_and_its_canonical_digest(tmp_path):
    header = build_records(build_report_view(_result(tmp_path)))[0]
    assert header["ruleset"]["schema"] == "ai-slop-work-order-rules/2"
    assert header["ruleset"]["sha256"] == _canonical(rules.RULESET_PATH)
    data = json.loads(rules.RULESET_PATH.read_text(encoding="utf-8"))
    # the contract text in the header is the ruleset's, not code defaults
    assert header["forbid"] == data["forbid"] and header["hold_if"] == data["hold_if"]
    assert header["prove"] == data["prove"] and header["loop"] == data["loop"]
    assert header["verify"] == data["verify"]
    text = render_ai_report_md(_result(tmp_path))
    assert (
        f"ruleset: {data['schema']} {data['version']} sha256:{header['ruleset']['sha256']}" in text
    )


def test_a_changed_rule_changes_the_digest_and_the_text_a_reformat_does_not(tmp_path, monkeypatch):
    before = build_records(build_report_view(_result(tmp_path)))[0]["ruleset"]["sha256"]
    _copy(tmp_path, monkeypatch)  # the same content, indented differently
    assert build_records(build_report_view(_result(tmp_path)))[0]["ruleset"]["sha256"] == before

    def ask(data):
        data["families"]["placeholder"]["question"] = "A changed question?"

    _copy(tmp_path, monkeypatch, ask)
    result = _result(tmp_path)
    assert build_records(build_report_view(result))[0]["ruleset"]["sha256"] != before
    assert "- todo_comment: A changed question?" in render_ai_report_md(result)


@pytest.mark.parametrize(
    "name, change, raw",
    [
        ("missing", None, None),
        ("not_json", None, "{ not json"),
        ("unknown_key", lambda d: d.update(extra=1), None),
        ("empty_text", lambda d: d["forbid"].__setitem__(0, ""), None),
        (
            "rule_in_two_families",
            lambda d: d["families"]["size"]["rules"].append("todo_comment"),
            None,
        ),
        ("missing_field", lambda d: d.pop("prove"), None),
        ("wrong_schema", lambda d: d.update(schema="ai-slop-work-order-rules/1"), None),
    ],
)
def test_a_missing_or_invalid_ruleset_fails_every_report_closed(
    tmp_path, monkeypatch, name, change, raw
):
    result = _result(tmp_path)
    if name == "missing":
        monkeypatch.setattr(rules, "RULESET_PATH", tmp_path / "absent.json")
    else:
        _copy(tmp_path, monkeypatch, change, raw)
    with pytest.raises(AiReportInvalidError):
        render_ai_report(result)
    with pytest.raises(AiReportInvalidError):
        render_ai_report_md(result)
    out = tmp_path / "wo.md"
    with pytest.raises(SystemExit) as stop:
        main([str(tmp_path), "--project", "--format", "ai-md", "--no-history", "-o", str(out)])
    assert stop.value.code == 2 and not out.exists()


def test_the_packaged_ruleset_ships_with_the_package(tmp_path):
    # the file sits in the package tree that MANIFEST.in includes (*.json)
    assert rules.RULESET_PATH.is_file()
    assert rules.RULESET_PATH.parent.name == "config"
    shutil.copy(rules.RULESET_PATH, tmp_path / "copy.json")
    loaded, digest = rules.load_ruleset(tmp_path / "copy.json")
    assert digest == _canonical(rules.RULESET_PATH) and loaded.version
