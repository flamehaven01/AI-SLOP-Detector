"""The default terminal screen: what matters in one screen (docs/REPORTS.md 3).

Formats a `ReportView`; computes nothing of its own. The full tables of
earlier releases stay available with `--details`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, List, Optional

from slop_detector import __version__
from slop_detector.report_view import TERMINAL_LIMITS, Item, ReportView, short_path, top

_SEVERITY_STYLE = {"critical": "bold red", "high": "red", "medium": "yellow", "low": "dim"}


def _root(view: ReportView) -> str:
    return view.target if view.is_project else str(Path(view.target).parent)


def _score_line(view: ReportView) -> str:
    if view.score is None:
        return "N/A  NOT EVALUATED (nothing was measured)"
    return f"{view.score:.1f}/100  {view.status} (score band)"


def _findings_line(view: ReportView) -> str:
    counts = " / ".join(f"{name} {n}" for name, n in view.severity.items())
    return f"{len(view.findings)}  ({counts})"


def hollow_line(view: ReportView) -> str:
    """The hollow channel with its denominator; never "0" when not measured."""
    sem = view.semantic
    if sem.state == "NOT_APPLICABLE":
        return "not applicable (no Python file)"
    if sem.state == "SKIPPED":
        return "skipped"
    if sem.state == "UNMEASURED":
        return "not measured (analysis failed)"
    line = (
        f"{len(view.candidates)} review candidate(s), not scored  -  "
        f"{sem.functions} functions, {sem.unknown} not decidable"
    )
    if sem.state != "MEASURED":
        parts = ", ".join(f"{n} {state}" for state, n in sorted(sem.files.items()))
        line += f"  [partial: {parts} files]"
    return line


def quiet_line(view: ReportView) -> str:
    """One line for CI logs."""
    score = "N/A" if view.score is None else f"{view.score:.1f}"
    sev = view.severity
    return (
        f"slop-detector {__version__}: score {score} {view.status}; findings {len(view.findings)} "
        f"(critical {sev['critical']}, high {sev['high']}); hollow {_quiet_hollow(view)}; "
        f"measurement {view.measurement}"
    )


def _quiet_hollow(view: ReportView) -> str:
    if view.semantic.state in ("MEASURED", "PARTIAL"):
        return f"{len(view.candidates)} candidate(s) {view.semantic.state}"
    return view.semantic.state


def _item_rows(items: List[Item], root: str, candidates: bool) -> List[tuple]:
    rows = []
    for item in items:
        where = f"{short_path(item.file, root)}:{item.line}"
        label = "" if candidates else item.severity.upper()
        rows.append((label, where, item.rule, item.message))
    return rows


def _steps(view: ReportView) -> List[str]:
    if view.next_steps:
        return view.next_steps
    urgent = view.severity["critical"] + view.severity["high"]
    if urgent:
        return [f"Review the {urgent} critical or high finding(s) before accepting this scan."]
    if view.findings:
        return [f"{len(view.findings)} lower-severity finding(s) are open for review."]
    return []


def print_summary(view: ReportView, elapsed: Optional[float] = None, console: Any = None) -> None:
    """Print the one-screen summary with rich."""
    from rich.console import Console
    from rich.table import Table

    console = console or Console()
    timing = f", {elapsed:.1f} s" if elapsed is not None else ""
    unit = "files" if view.files != 1 else "file"
    console.print(
        f"[bold]AI SLOP Detector {__version__}[/bold] - {view.target} ({view.files} {unit}{timing})"
        f"    [dim]measurement: {view.measurement}[/dim]"
    )
    head = Table.grid(padding=(0, 2))
    head.add_column(style="bold")
    head.add_column()
    head.add_row("Score", _score_line(view))
    head.add_row("Findings", _findings_line(view))
    head.add_row("Hollow", hollow_line(view))
    console.print(head)
    root = _root(view)
    _print_items(console, "Findings", view.findings, TERMINAL_LIMITS["findings"], root, False)
    _print_items(
        console, "Hollow review candidates (not scored)", view.candidates,
        TERMINAL_LIMITS["candidates"], root, True,
    )
    steps = _steps(view)
    if steps:
        console.print("\n[bold]Next[/bold]")
        for i, step in enumerate(steps, 1):
            console.print(f"  {i}. {step}")
    console.print("\n[dim]Full tables: --details   Report file: -o report.md[/dim]")


def _print_items(console: Any, title: str, items: List[Item], limit: int, root: str, candidates: bool) -> None:
    from rich.table import Table

    if not items:
        return
    shown, rest = top(items, limit)
    console.print(f"\n[bold]{title}[/bold]  [dim]top {len(shown)} of {len(items)}[/dim]")
    table = Table.grid(padding=(0, 2))
    for _ in range(4):
        table.add_column(overflow="fold")
    for label, where, rule, message in _item_rows(shown, root, candidates):
        style = _SEVERITY_STYLE.get(label.lower(), "")
        table.add_row(f"[{style}]{label}[/{style}]" if style else label, where, rule, message)
    console.print(table)
    if rest:
        console.print(f"  [dim]+{rest} more (--details or -o report.md)[/dim]")


class Progress:
    """One updating line on a terminal (`[37/120] path`); nothing otherwise.
    A failure here never ends the scan."""

    def __init__(self, stream: Any = None) -> None:
        self._stream = stream or sys.stderr
        self._on = bool(getattr(self._stream, "isatty", lambda: False)())
        self._width = 0

    def __call__(self, event: Any) -> None:
        if not self._on:
            return
        try:
            if event.kind == "file_done" and event.total:
                text = f"[{event.index}/{event.total}] {Path(event.path or '').name}"
                self._write(text)
            elif event.kind in ("aggregating", "completed", "failed", "cancelled"):
                self._write("")
        except (OSError, ValueError):  # a closed or broken stream: stop drawing, keep scanning
            self._on = False

    def _write(self, text: str) -> None:
        pad = max(0, self._width - len(text))
        self._stream.write("\r" + text + " " * pad + ("\r" if not text else ""))
        self._stream.flush()
        self._width = len(text)
