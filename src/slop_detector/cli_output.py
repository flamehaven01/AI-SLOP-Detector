"""Output helpers for CLI commands and analysis results."""

from __future__ import annotations

import json
import math
import sys
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


def render_json(result) -> str:
    """The JSON document for an analysis result (the CLI's --json output)."""
    return json.dumps(_sanitize_for_json(result.to_dict()), indent=2, allow_nan=False)


def _write_json_output(args, result) -> None:
    """Serialize result to JSON and write to file or stdout."""
    output = render_json(result)
    if args.output:
        _write_file(args.output, output)
    else:
        print(output)


def _write_pdf(out: str, page_html: str) -> None:
    """The PDF report, or a clear failure (exit 2) with nothing written."""
    from slop_detector.report_pdf import PdfFailed, PdfUnavailable, write_pdf

    try:
        write_pdf(page_html, out)
    except (PdfUnavailable, PdfFailed) as exc:
        print(f"[!] {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(f"[+] PDF report saved to {out}")


def _route_file_output(out: str, result, rich_ok: bool, details: bool = True, elapsed=None) -> None:
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
    if out.endswith(".pdf"):
        _write_pdf(out, generate_html_report(result))
        return
    if out.endswith(".md"):
        _write_file(out, generate_markdown_report(result), "Markdown report")
        return
    if out:
        _write_file(out, generate_text_report(result))
        return
    if rich_ok and details:
        print_rich_report(result)
        return
    if rich_ok:
        from slop_detector.renderer_terminal import print_summary
        from slop_detector.report_view import build_report_view

        print_summary(build_report_view(result), elapsed=elapsed)
        return
    print(generate_text_report(result))


def _write_ai_report(args, result) -> None:
    """The AI report (JSON Lines) to stdout or --output; never an invalid one."""
    from slop_detector.ai_report import AiReportInvalid, render_ai_report

    try:
        text = render_ai_report(result, getattr(args, "ai_limit", None))
    except AiReportInvalid as exc:
        print(f"[!] {exc}; nothing was written", file=sys.stderr)
        raise SystemExit(2) from exc
    if args.output:
        _write_file(str(args.output), text, "AI report")
    else:
        sys.stdout.write(text)


def _report_bundle(args, result) -> None:
    """--report-dir: list what was written and what was not; exit 2 when the
    bundle is incomplete."""
    from slop_detector.report_bundle import write_bundle

    written, failed = write_bundle(result, args.report_dir, getattr(args, "ai_limit", None))
    print(f"[+] Reports in {args.report_dir}: {', '.join(written) or 'none'}")
    for name, why in failed:
        print(f"[!] not written: {name} - {why}", file=sys.stderr)
    if failed:
        raise SystemExit(2)


def _handle_output(args, result) -> None:
    """Route analysis result to the appropriate output format."""
    from slop_detector.cli_renderer import RICH_AVAILABLE

    _handle_screen_output(args, result, RICH_AVAILABLE)
    if getattr(args, "report_dir", None):
        _report_bundle(args, result)


def _handle_screen_output(args, result, rich_available: bool) -> None:
    if getattr(args, "ai", False):
        _write_ai_report(args, result)
        return
    if args.json:
        _write_json_output(args, result)
        return
    out = str(args.output) if args.output else ""
    if getattr(args, "quiet", False) and not out:
        from slop_detector.renderer_terminal import quiet_line
        from slop_detector.report_view import build_report_view

        print(quiet_line(build_report_view(result)))
        return
    _route_file_output(
        out, result, rich_available and not args.no_color,
        details=bool(getattr(args, "details", False)), elapsed=getattr(args, "elapsed", None),
    )
