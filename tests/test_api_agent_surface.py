import pytest

pytest.importorskip("fastapi", reason="requires api extra: pip install ai-slop-detector[api]")

from fastapi.testclient import TestClient  # noqa: E402

from slop_detector.api.server import create_app  # noqa: E402


def test_agent_schema_exposes_structured_surface():
    client = TestClient(create_app())

    response = client.get("/agent/schema")

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "agent_surface_manifest"
    assert any(item["path"] == "/agent/project" for item in data["endpoints"])
    assert "priority hotspots" in " ".join(data["capabilities"])


def test_agent_file_endpoint_returns_structured_snapshot(tmp_path):
    client = TestClient(create_app())
    file_path = tmp_path / "sample.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    response = client.post("/agent/file", json={"file_path": str(file_path)})

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "agent_file_analysis"
    assert data["file_path"].endswith("sample.py")
    assert "analysis" in data
    assert "signals" in data


def test_agent_project_endpoint_returns_hotspots_and_signals(tmp_path):
    client = TestClient(create_app())
    project_path = tmp_path / "proj"
    project_path.mkdir()
    (project_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")

    response = client.post("/agent/project", json={"project_path": str(project_path)})

    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "agent_project_analysis"
    assert data["project_path"].endswith("proj")
    assert "summary" in data
    assert "signals" in data
    assert "file_results" in data
