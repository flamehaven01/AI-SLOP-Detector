"""Controls for API routes that have no implementation.

They answer 501 Not Implemented and do nothing. Before, the push webhook
answered {"status": "accepted"} and scheduled a background task whose body was
`pass`, and the project status route returned nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="requires api extra: pip install ai-slop-detector[api]")

from fastapi import BackgroundTasks  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from slop_detector.api import server  # noqa: E402
from slop_detector.core import SlopDetector  # noqa: E402

PUSH = {
    "ref": "refs/heads/main",
    "before": "0" * 40,
    "after": "a" * 40,
    "repository": {"full_name": "owner/repo"},
    "commits": [],
}


def test_project_status_answers_501():
    client = TestClient(server.create_app(), raise_server_exceptions=False)
    response = client.get("/status/project/abc")  # before: 500, None fails ProjectStatus
    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"].lower()


def test_push_webhook_answers_501_and_schedules_nothing(monkeypatch):
    scheduled = []
    monkeypatch.setattr(
        BackgroundTasks, "add_task", lambda self, func, *a, **k: scheduled.append(func)
    )
    response = TestClient(server.create_app()).post("/webhook/github", json=PUSH)
    assert response.status_code == 501
    assert "not implemented" in response.json()["detail"].lower()
    assert scheduled == [], f"background work was scheduled: {scheduled}"


def test_push_webhook_never_reports_acceptance():
    response = TestClient(server.create_app()).post("/webhook/github", json=PUSH)
    assert response.json().get("status") != "accepted"


def test_no_placeholder_helper_or_finding_remains():
    assert not hasattr(server, "_analyze_github_push")
    path = Path(server.__file__)
    findings = SlopDetector(read_only=True).analyze_file(str(path)).pattern_issues
    stubs = [(i.pattern_id, i.line) for i in findings if i.pattern_id == "pass_placeholder"]
    assert stubs == [], f"api/server.py still has placeholder stubs: {stubs}"


def test_preservation_supported_routes_still_answer(tmp_path):
    """PRESERVATION: the documented agent route is unaffected."""
    response = TestClient(server.create_app()).get("/agent/schema")
    assert response.status_code == 200
