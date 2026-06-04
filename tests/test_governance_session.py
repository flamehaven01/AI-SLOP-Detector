"""Tests for CR-EP governance session artifacts."""

import json

from slop_detector.governance.session import AnalysisSession


def test_finalize_writes_governance_record_with_stable_hash(tmp_path):
    session = AnalysisSession(project_path=tmp_path)

    output_dir = session.finalize(
        files_planned=["a.py", "b.py"],
        files_actual=["a.py"],
        total_issues=3,
        halt_count=1,
    )

    record_path = output_dir / "governance_record.json"
    assert record_path.exists()

    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["kind"] == "governance_record"
    assert record["counts"]["planned_files"] == 2
    assert record["counts"]["actual_files"] == 1
    assert record["counts"]["total_issues"] == 3
    assert record["counts"]["halt_count"] == 1
    assert record["record_hash"]

    rebuilt = session._build_governance_record(
        files_planned=["a.py", "b.py"],
        files_actual=["a.py"],
        total_issues=3,
        halt_count=1,
    )
    assert rebuilt["record_hash"] == record["record_hash"]


def test_governance_record_hash_changes_with_session_identity(tmp_path):
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    session_a = AnalysisSession(project_path=tmp_path / "one")
    session_b = AnalysisSession(project_path=tmp_path / "two")

    record_a = session_a._build_governance_record(["a.py"], ["a.py"], 1, 0)
    record_b = session_b._build_governance_record(["a.py"], ["a.py"], 1, 0)

    assert record_a["record_hash"] != record_b["record_hash"]
