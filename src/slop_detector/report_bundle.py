"""`--report-dir`: every report of one scan in one folder (docs/REPORTS.md 4).

Files of the same name are replaced. A file that could not be made is listed
with the reason, and a file of that name left from an earlier run is removed
(it would read as this scan's). The bundle is complete only when every file
was written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Tuple

BUNDLE_FILES = (
    "report.md",
    "report.html",
    "report.pdf",
    "ai-report.jsonl",
    "ai-report.md",
    "scan.json",
)


def write_bundle(
    result: Any,
    directory: str,
    ai_limit: Optional[int] = None,
    only: Optional[Sequence[str]] = None,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Write the bundle; return (files written, (file, why) not written).
    `only`: the bundle files to write (`--interactive`); None writes them all.
    """
    from slop_detector.ai_report import AiReportInvalidError, render_ai_report
    from slop_detector.ai_report_md import render_ai_report_md
    from slop_detector.cli_output import render_json
    from slop_detector.renderer_html import generate_html_report
    from slop_detector.renderer_markdown import generate_markdown_report
    from slop_detector.report_pdf import PdfFailedError, PdfUnavailableError, write_pdf

    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    pages: List[str] = []

    def html() -> str:
        # One page for report.html and report.pdf, made when the first of them is.
        if not pages:
            pages.append(generate_html_report(result))
        return pages[0]

    producers: List[Tuple[str, Callable[[], Optional[str]]]] = [
        ("report.md", lambda: generate_markdown_report(result)),
        ("report.html", html),
        ("report.pdf", lambda: write_pdf(html(), str(folder / "report.pdf"))),
        ("ai-report.jsonl", lambda: render_ai_report(result, ai_limit)),
        ("ai-report.md", lambda: render_ai_report_md(result, ai_limit, mode="auditor")),
        ("scan.json", lambda: render_json(result)),
    ]
    written: List[str] = []
    failed: List[Tuple[str, str]] = []
    for name, make in producers:
        if only is not None and name not in only:
            continue
        target = folder / name
        try:
            text = make()
            if text is not None:
                target.write_text(text, encoding="utf-8")
            written.append(name)
        except (
            AiReportInvalidError,
            PdfUnavailableError,
            PdfFailedError,
            OSError,
            ValueError,
        ) as exc:
            reason = str(exc)
            if target.exists():
                target.unlink()
                reason += f" (the {name} of an earlier run was removed)"
            failed.append((name, reason))
    return written, failed
