"""The MCP tools and REST routes are read-only by default.

MCP writes neither the analysis cache nor history. REST scans read-only and
records history only when a request sets save_history=true; even then the
analysis cache is not written. The REST server binds 127.0.0.1 unless a host
is given. State paths bind at import, so each scan runs in a child process
whose HOME is a fresh directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tests.test_read_only import REPO_SRC, _diff, _state

RUNNER = """
import sys
from pathlib import Path
surface, target, route, save = sys.argv[1:5]
key = "project_path" if Path(target).is_dir() else "file_path"
if surface == "mcp":
    from slop_detector.mcp.server import _call_tool
    tool = "slop_analyze_project" if key == "project_path" else "slop_analyze_file"
    answer = _call_tool(tool, {key: target})
    assert not answer["isError"], answer
else:
    from fastapi.testclient import TestClient
    from slop_detector.api.server import create_app
    body = {key: target}
    if save != "default":
        body["save_history"] = save == "true"
    answer = TestClient(create_app()).post(route, json=body)
    assert answer.status_code == 200, answer.text
print("OK")
"""

FILE_ROUTES = ["/analyze/file", "/agent/file"]
PROJECT_ROUTES = ["/analyze/project", "/agent/project"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    (root / "b.py").write_text("def g():\n    pass\n", encoding="utf-8")
    return root


def _scan(tmp_path: Path, surface: str, target: Path, route: str = "", save: str = "default"):
    """Run one scan with a fresh HOME; return (home, files written or changed)."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    runner = tmp_path / "runner.py"
    runner.write_text(RUNNER, encoding="utf-8")
    watched = target if target.is_dir() else target.parent
    before = _state(home, watched)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONPATH=REPO_SRC)
    env.pop("SLOP_CONFIG", None)
    result = subprocess.run(
        [sys.executable, str(runner), surface, str(target), route, save],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=180,
    )
    assert result.stdout.strip() == "OK", result.stderr[-600:]
    return home, _diff(before, _state(home, watched))


@pytest.mark.parametrize("target", ["file", "project"])
def test_mcp_scans_write_nothing(tmp_path, project, target):
    path = project / "a.py" if target == "file" else project
    _, written = _scan(tmp_path, "mcp", path)
    assert written == []


def _needs_api():
    pytest.importorskip("fastapi", reason="requires api extra")


@pytest.mark.parametrize("route", FILE_ROUTES + PROJECT_ROUTES)
def test_rest_scans_write_nothing_by_default(tmp_path, project, route):
    _needs_api()
    target = project / "a.py" if route in FILE_ROUTES else project
    _, written = _scan(tmp_path, "api", target, route)
    assert written == []


@pytest.mark.parametrize("route", ["/analyze/file", "/analyze/project"])
def test_rest_history_is_an_explicit_opt_in_without_the_cache(tmp_path, project, route):
    _needs_api()
    target = project / "a.py" if route == "/analyze/file" else project
    home, written = _scan(tmp_path, "api", target, route, save="true")
    assert written == ["created home/.slop-detector/history.db"]
    assert not (home / ".slop-detector" / "analysis_cache.db").exists()


def test_rest_save_history_false_writes_nothing(tmp_path, project):
    _needs_api()
    _, written = _scan(tmp_path, "api", project, "/analyze/project", save="false")
    assert written == []


def test_rest_request_does_not_record_history_unless_asked():
    from slop_detector.api.models import AnalysisRequest

    assert AnalysisRequest(project_path=".").save_history is False
    example = AnalysisRequest.model_json_schema()["example"]
    assert example["save_history"] is False


def _captured_uvicorn(monkeypatch) -> dict:
    seen: dict = {}
    fake = types.ModuleType("uvicorn")
    fake.run = lambda app, host, port: seen.update(host=host, port=port)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", fake)
    return seen


def test_rest_server_binds_localhost_by_default(monkeypatch):
    _needs_api()
    from slop_detector.api.server import run_server

    seen = _captured_uvicorn(monkeypatch)
    run_server()
    assert seen == {"host": "127.0.0.1", "port": 8000}


def test_rest_server_binds_an_explicit_host(monkeypatch):
    _needs_api()
    from slop_detector.api.server import run_server

    seen = _captured_uvicorn(monkeypatch)
    run_server(host="0.0.0.0", port=9001)
    assert seen == {"host": "0.0.0.0", "port": 9001}
