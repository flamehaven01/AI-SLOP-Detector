"""Output helpers for CLI commands and analysis results."""

from __future__ import annotations

import json
import math
from typing import Any


def _write_file(path: str, content: str, label: str = "") -> None:
    """Write content to a file, with optional console confirmation."""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    if label:
        print(f"[+] {label} saved to {path}")


def _emit_command_payload(args, payload: dict) -> int:
    """Emit a command payload in JSON, markdown, or text form."""
    if getattr(args, "json", False):
        output = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        from slop_detector.operations import render_payload_markdown, render_payload_text

        out = str(getattr(args, "output", "") or "")
        if out.endswith(".md"):
            output = render_payload_markdown(payload)
        else:
            output = render_payload_text(payload)
    if getattr(args, "output", None):
        _write_file(str(args.output), output)
    else:
        print(output)
    return 0


def _emit_simple_payload(payload: dict, as_json: bool = False) -> int:
    """Emit a simple payload as JSON or indented text."""
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    for key, value in payload.items():
        print(f"{key}: {value}")
    return 0


def _sanitize_for_json(obj: Any):
    """Recursively replace non-finite floats with None for RFC 8259 compliance."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _write_json_output(args, result) -> None:
    """Serialize result to JSON and write to file or stdout."""
    output = json.dumps(_sanitize_for_json(result.to_dict()), indent=2, allow_nan=False)
    if args.output:
        _write_file(args.output, output)
    else:
        print(output)


def _route_file_output(out: str, result, rich_ok: bool) -> None:
    """Write result to file or console based on output extension and flags."""
    from slop_detector.cli_renderer import (
        generate_html_report,
        generate_markdown_report,
        generate_text_report,
        print_rich_report,
    )

    if out.endswith(".html"):
        _write_file(out, generate_html_report(result), "HTML report")
        return
    if out.endswith(".md"):
        _write_file(out, generate_markdown_report(result), "Markdown report")
        return
    if out:
        _write_file(out, generate_text_report(result))
        return
    if rich_ok:
        print_rich_report(result)
        return
    print(generate_text_report(result))


def _handle_output(args, result) -> None:
    """Route analysis result to the appropriate output format."""
    from slop_detector.cli_renderer import RICH_AVAILABLE

    if args.json:
        _write_json_output(args, result)
        return
    out = str(args.output) if args.output else ""
    _route_file_output(out, result, RICH_AVAILABLE and not args.no_color)
