"""Isolated tests for the verify-governance CLI command."""

import json
import sys

from slop_detector.cli import main
from slop_detector.governance.session import AnalysisSession


def test_verify_governance_passes_on_clean_record(tmp_path, monkeypatch):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    session = AnalysisSession(project_path=project_root, trust_tier="PEER")
    session.finalize(["a.py"], ["a.py"], total_issues=0, halt_count=0)

    monkeypatch.setattr(sys, "argv", ["slop-detector", "verify-governance", str(project_root)])
    assert main() == 0


def test_verify_governance_fails_on_tampered_hash(tmp_path, monkeypatch):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    session = AnalysisSession(project_path=project_root, trust_tier="PEER")
    session.finalize(["a.py"], ["a.py"], total_issues=0, halt_count=0)

    record_path = project_root / ".cr-ep" / "governance_record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["record_hash"] = "deadbeef"
    record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        ["slop-detector", "verify-governance", str(project_root)],
    )
    assert main() == 1


def test_verify_governance_fails_on_policy_violation_halt_count(tmp_path, monkeypatch):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    session = AnalysisSession(project_path=project_root, trust_tier="PEER")
    session.finalize(["a.py"], ["a.py"], total_issues=0, halt_count=1)

    monkeypatch.setattr(
        sys,
        "argv",
        ["slop-detector", "verify-governance", str(project_root)],
    )
    assert main() == 1


def test_verify_governance_fails_on_policy_violation_untrusted(tmp_path, monkeypatch):
    project_root = tmp_path / "proj"
    project_root.mkdir()
    session = AnalysisSession(project_path=project_root, trust_tier="UNTRUSTED")
    session.finalize(["a.py"], ["a.py"], total_issues=0, halt_count=0)

    monkeypatch.setattr(
        sys,
        "argv",
        ["slop-detector", "verify-governance", str(project_root)],
    )
    assert main() == 1
