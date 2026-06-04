"""Minimal MCP stdio server exposing the agent-native analysis surface."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from slop_detector import __version__
from slop_detector.api.models import AgentFileResponse, AgentProjectResponse, AgentSurfaceManifest
from slop_detector.core import SlopDetector

JSONRPC_VERSION = "2.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"


class MCPError(Exception):
    """JSON-RPC / MCP protocol error."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "slop_schema",
            "description": "Return the structured AI-SLOP Detector agent surface manifest.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "slop_analyze_file",
            "description": "Analyze a single file and return the structured agent snapshot.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "config_path": {"type": "string"},
                },
                "required": ["file_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "slop_analyze_project",
            "description": "Analyze a project and return the structured agent project snapshot.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "config_path": {"type": "string"},
                },
                "required": ["project_path"],
                "additionalProperties": False,
            },
        },
    ]


def _surface_manifest() -> AgentSurfaceManifest:
    return AgentSurfaceManifest(
        capabilities=[
            "structured project snapshots",
            "structured file snapshots",
            "priority hotspots",
            "suppression ledger",
            "structural coherence mode",
        ],
        endpoints=[
            {
                "path": "tool:slop_schema",
                "method": "CALL",
                "description": "Describe the MCP tool contract for agent-native use",
            },
            {
                "path": "tool:slop_analyze_file",
                "method": "CALL",
                "description": "Return a structured snapshot for a single file analysis",
            },
            {
                "path": "tool:slop_analyze_project",
                "method": "CALL",
                "description": "Return a structured snapshot for a full project analysis",
            },
        ],
        notes=[
            "MCP wraps the same structured agent-native contract exposed by the REST API.",
            "Tool responses return JSON text plus structuredContent for downstream agents.",
        ],
    )


def _tool_result(payload: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "structuredContent": payload,
        "isError": is_error,
    }


def _analyze_file(arguments: Dict[str, Any]) -> Dict[str, Any]:
    file_path = Path(arguments["file_path"])
    if not file_path.exists():
        return _tool_result({"error": "file_not_found", "file_path": str(file_path)}, is_error=True)
    detector = SlopDetector(config_path=arguments.get("config_path"))
    result = detector.analyze_file(str(file_path))
    return _tool_result(AgentFileResponse.from_result(result).model_dump())


def _analyze_project(arguments: Dict[str, Any]) -> Dict[str, Any]:
    project_path = Path(arguments["project_path"])
    if not project_path.exists():
        return _tool_result(
            {"error": "project_not_found", "project_path": str(project_path)},
            is_error=True,
        )
    detector = SlopDetector(config_path=arguments.get("config_path"))
    result = detector.analyze_project(str(project_path))
    return _tool_result(AgentProjectResponse.from_result(result).model_dump())


def _call_tool(name: str, arguments: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    arguments = arguments or {}
    if name == "slop_schema":
        return _tool_result(_surface_manifest().model_dump())
    if name == "slop_analyze_file":
        if "file_path" not in arguments:
            return _tool_result({"error": "missing_file_path"}, is_error=True)
        return _analyze_file(arguments)
    if name == "slop_analyze_project":
        if "project_path" not in arguments:
            return _tool_result({"error": "missing_project_path"}, is_error=True)
        return _analyze_project(arguments)
    return _tool_result({"error": "unknown_tool", "tool_name": name}, is_error=True)


class MCPServer:
    """Very small MCP JSON-RPC server for stdio transport."""

    def __init__(self) -> None:
        self.protocol_version = DEFAULT_PROTOCOL_VERSION

    def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        method = message.get("method")
        if method is None:
            raise MCPError(-32600, "Invalid Request")
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return self._success(message, {})
        if method == "initialize":
            params = message.get("params", {})
            self.protocol_version = params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION)
            return self._success(
                message,
                {
                    "protocolVersion": self.protocol_version,
                    "serverInfo": {
                        "name": "ai-slop-detector",
                        "version": __version__,
                    },
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        }
                    },
                },
            )
        if method == "tools/list":
            return self._success(message, {"tools": _tool_definitions()})
        if method == "tools/call":
            params = message.get("params", {})
            name = params.get("name")
            if not name:
                raise MCPError(-32602, "Missing tool name")
            return self._success(message, _call_tool(name, params.get("arguments")))
        raise MCPError(-32601, f"Method not found: {method}")

    @staticmethod
    def _success(message: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": message.get("id"),
            "result": result,
        }

    @staticmethod
    def error_response(message_id: Any, code: int, error_message: str) -> Dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": message_id,
            "error": {
                "code": code,
                "message": error_message,
            },
        }


def _read_message(stdin) -> Optional[Dict[str, Any]]:
    content_length: Optional[int] = None
    while True:
        header_line = stdin.buffer.readline()
        if not header_line:
            return None
        line = header_line.decode("utf-8").strip()
        if not line:
            break
        name, _, value = line.partition(":")
        if name.lower() == "content-length":
            content_length = int(value.strip())
    if content_length is None:
        raise MCPError(-32700, "Missing Content-Length header")
    body = stdin.buffer.read(content_length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(stdout, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stdout.buffer.write(body)
    stdout.buffer.flush()


def run_stdio_server() -> int:
    server = MCPServer()
    while True:
        try:
            message = _read_message(sys.stdin)
            if message is None:
                return 0
            response = server.handle_message(message)
            if response is not None:
                _write_message(sys.stdout, response)
        except MCPError as exc:
            response = server.error_response(None, exc.code, exc.message)
            _write_message(sys.stdout, response)
        except Exception as exc:  # pragma: no cover - defensive protocol boundary
            response = server.error_response(None, -32603, str(exc))
            _write_message(sys.stdout, response)


def main() -> int:
    """Script entry point for MCP stdio mode."""
    return run_stdio_server()
