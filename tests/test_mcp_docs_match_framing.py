"""The docs say what the MCP server actually does on the specification's stdio framing.

The MCP specification's stdio transport is newline-delimited JSON. The server
started by `slop-detector mcp` frames messages with a Content-Length header, so
a client that follows the specification gets no reply. This test starts the
real server as its own process, sends one newline-delimited `initialize`, and
holds the docs to the measured result: no reply -> the docs warn and nothing
recommends the server; a reply (a server that speaks the specification) -> the
warning must be removed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WARNING = "a client that follows the specification gets no reply"
DOCS = [
    "README.md",
    "claude-skills/slop-detector/SKILL.md",
    "docs/GUIDE.md",
    "docs/CLAUDE_CODE_SKILL.md",
    "docs/CLI_USAGE.md",
    "docs/AGENT_WORKFLOW.md",
    "npm-wrapper/README.md",
]
RECOMMENDATIONS = [
    "for Claude Code and other MCP clients",
    "use when the host tool already speaks MCP",
    "Use MCP when the host tool already expects a stdio tool surface",
    "Agent tooling can use the same semantics over MCP stdio",
]


def _replies_to_newline_framing(tmp_path) -> bool:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "spec-client", "version": "0"},
        },
    }
    env = dict(os.environ, HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    env["PYTHONPATH"] = str(REPO / "src")
    done = subprocess.run(
        [sys.executable, "-m", "slop_detector.cli", "mcp"],
        input=(json.dumps(request) + "\n").encode("utf-8"),
        capture_output=True,
        env=env,
        timeout=120,
    )
    return bool(done.stdout.strip())


def _flat(rel: str) -> str:
    return " ".join((REPO / rel).read_text(encoding="utf-8").split())


def test_the_docs_match_the_server_on_newline_framing(tmp_path):
    replied = _replies_to_newline_framing(tmp_path)
    for rel in DOCS:
        text = _flat(rel)
        if replied:
            assert WARNING not in text, f"{rel}: the server now replies; remove the warning"
        else:
            assert WARNING in text, f"{rel}: the server gives no reply; say so"
            for phrase in RECOMMENDATIONS:
                assert phrase.lower() not in text.lower(), f"{rel} still recommends it: {phrase!r}"
