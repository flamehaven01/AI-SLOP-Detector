"""Tests for the MCP stdio server surface."""

from __future__ import annotations

import io
import json

from slop_detector.mcp.server import MCPServer, _read_message, _write_message


def test_initialize_returns_server_info():
    server = MCPServer()

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )

    assert response is not None
    assert response["result"]["protocolVersion"] == "2024-11-05"
    assert response["result"]["serverInfo"]["name"] == "ai-slop-detector"
    assert "tools" in response["result"]["capabilities"]


def test_tools_list_exposes_agent_surface_tools():
    server = MCPServer()

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        }
    )

    assert response is not None
    tools = response["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "slop_schema",
        "slop_analyze_file",
        "slop_analyze_project",
    }


def test_tools_call_analyze_file_returns_structured_content(tmp_path):
    server = MCPServer()
    file_path = tmp_path / "sample.py"
    file_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "slop_analyze_file",
                "arguments": {"file_path": str(file_path)},
            },
        }
    )

    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["kind"] == "agent_file_analysis"
    assert result["structuredContent"]["file_path"].endswith("sample.py")


def test_tools_call_analyze_project_returns_structured_content(tmp_path):
    server = MCPServer()
    project_path = tmp_path / "proj"
    project_path.mkdir()
    (project_path / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "slop_analyze_project",
                "arguments": {"project_path": str(project_path)},
            },
        }
    )

    assert response is not None
    result = response["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["kind"] == "agent_project_analysis"
    assert result["structuredContent"]["project_path"].endswith("proj")


def test_tools_call_unknown_tool_returns_error_result():
    server = MCPServer()

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "unknown_tool", "arguments": {}},
        }
    )

    assert response is not None
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["error"] == "unknown_tool"


def test_stdio_message_round_trip():
    payload = {"jsonrpc": "2.0", "id": 7, "method": "ping"}
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="utf-8")
    _write_message(stdout, payload)
    raw.seek(0)
    stdin = io.TextIOWrapper(raw, encoding="utf-8")

    message = _read_message(stdin)

    assert message == payload
    raw.seek(0)
    written = raw.read().decode("utf-8")
    assert "Content-Length:" in written
    assert json.dumps(payload, ensure_ascii=False) in written
