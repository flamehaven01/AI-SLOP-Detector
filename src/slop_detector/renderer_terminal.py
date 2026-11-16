"""The default terminal screen: what matters in one screen (docs/REPORTS.md 3).

Formats a `ReportView`; computes nothing of its own. The full tables of
earlier releases stay available with `--details`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, List, Optional

from slop_detector import __version__
from slop_detector.diagnostic_bands import CRITICAL_AT, INFLATED_AT, SUSPICIOUS_AT
from slop_detector.report_view import TERMINAL_LIMITS, Item, ReportView, top, where

_SEVERITY_STYLE = {"critical": "bold red", "high": "red", "medium": "yellow", "low": "dim"}


def _root(view: ReportView) -> str:
    return view.target if view.is_project else str(Path(view.target).parent)


def _headline_target(view: ReportView) -> str:
    """The target as the headline names it: a scan of "." is named by its folder."""
    if view.target in (".", "./", ".\\"):
        return Path(view.target).resolve().name or view.target
    return view.target


def _score_line(view: ReportView) -> str:
    if view.score is None:
        return "N/A  NOT EVALUATED (nothing was measured)"
    basis = "weighted by lines of code, " if view.is_project else ""
    return f"{view.score:.1f}/100  {view.status} ({basis}score band)"


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


def claim_line(view: ReportView) -> str:
    """Docstring promises by state; never "0" when not measured."""
    claims = view.claims
    if claims.state == "NOT_APPLICABLE":
        return "not applicable (no Python file)"
    if claims.state == "SKIPPED":
        return "skipped"
    if claims.state == "UNMEASURED":
        return "not measured (analysis failed)"
    c = claims.counts
    line = (
        f"{c['extracted_claims']} docstring promise(s): {c['contradicted']} contradicted "
        f"({c['candidates']} candidate(s), {c['merged']} merged into a finding), {c['undecided']} undecided, "
        f"{c['supported']} with the structure, {c['delegated_in_module']} delegated, "
        f"{c['not_evaluated']} not evaluated"
    )
    if c["unmeasured"]:
        line += f", {c['unmeasured']} not measured"
    if claims.state != "MEASURED":
        parts = ", ".join(f"{n} {state}" for state, n in sorted(claims.files.items()))
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
        label = "" if candidates else item.severity.upper()
        rows.append((label, where(item, root), item.rule, item.message))
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


# The meter of the score: this many cells for 0-100.
METER_WIDTH = 40
_BANDS = ((SUSPICIOUS_AT, "green"), (INFLATED_AT, "yellow"), (CRITICAL_AT, "dark_orange"))
# The screen's glyphs, and what it draws on a console that cannot encode them
# (cp1252 has no box-drawing characters; a redirected ASCII stream has none).
_GLYPHS = {
    "filled": "\u2501",
    "rest": "\u2500",
    "dot": "\u25cf",
    "sep": "\u00b7",
}
_ASCII_GLYPHS = {"filled": "#", "rest": "-", "dot": "*", "sep": "-"}
# The panel's rounded corners and the cut mark of a line that does not fit.
_BOX_AND_CUT = "\u256d\u2570\u2026"


def _glyphs(console: Any) -> dict:
    """The glyph set this console can print (its encoding decides, not the platform)."""
    encoding = getattr(console, "encoding", None) or "utf-8"
    try:
        ("".join(_GLYPHS.values()) + _BOX_AND_CUT).encode(encoding)
    except (UnicodeError, LookupError):
        return _ASCII_GLYPHS
    return _GLYPHS


def _band_style(score: float) -> str:
    return next((style for limit, style in _BANDS if score < limit), "red")


def _meter(score: float, glyphs: dict) -> tuple:
    """The meter line and the line of band limits under it."""
    from rich.text import Text

    filled = round(score / 100 * METER_WIDTH)
    bar = Text(glyphs["filled"] * filled, style=_band_style(score))
    bar.append(glyphs["rest"] * (METER_WIDTH - filled), style="bright_black")
    ticks = [" "] * METER_WIDTH
    for limit, _ in _BANDS:
        label = f"{limit:g}"
        start = round(limit / 100 * METER_WIDTH) - 1
        ticks[start : start + len(label)] = label
    return bar, Text("".join(ticks), style="bright_black")


def _first_clause(message: str) -> str:
    """What an item says before its explanation: the screen shows one line per
    item; the whole message is in --details and in every report."""
    return message.split(" - ")[0].split("; ")[0]


def _review_line(view: ReportView) -> str:
    """The review-candidate channel in a few words; nothing for a project with
    no Python file, and never a count when the channel did not measure."""
    state = view.semantic.state
    if state == "NOT_APPLICABLE":
        return ""
    if state == "SKIPPED":
        line = "review candidates: skipped"
    elif state == "UNMEASURED":
        line = "review candidates: not measured (analysis failed)"
    else:
        line = f"{len(view.candidates)} to review (not scored)"
        if state != "MEASURED":
            line += ", partly measured"
    # Contradicted docstring promises are among the candidates; the channel is
    # named only when it did not measure.
    promises = {"SKIPPED": "skipped", "UNMEASURED": "not measured", "PARTIAL": "partly measured"}
    if view.claims.state in promises:
        line += f"   docstring promises: {promises[view.claims.state]}"
    return line


def _verdict(view: ReportView, glyphs: dict, elapsed: Optional[float]) -> Any:
    """The panel: score, band, meter, counts, what was read."""
    from rich.console import Group
    from rich.table import Table
    from rich.text import Text

    parts: List[Any] = []
    if view.score is None:
        parts.append(Text("N/A  NOT EVALUATED (nothing was measured)", style="bold"))
    else:
        style = _band_style(view.score)
        bar, ticks = _meter(view.score, glyphs)
        basis = "weighted by lines of code" if view.is_project else "this file"
        grid = Table.grid(padding=(0, 3))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_row(
            Text.assemble(
                (f"{view.score:.1f}", f"bold {style}"), " / 100  ", (view.status, f"bold {style}")
            ),
            bar,
        )
        grid.add_row(Text("higher = more warning signs", style="bright_black"), ticks)
        parts += [grid, Text(basis, style="bright_black")]
    counts = Text()
    for name, n in view.severity.items():
        counts.append(glyphs["dot"] + " ", style=_SEVERITY_STYLE[name] if n else "bright_black")
        counts.append(f"{n} {name}   ", style="bold" if n else "bright_black")
    review = _review_line(view)
    if review:
        counts.append(review, style="magenta")
    parts += [Text(""), counts]
    unit = "files" if view.files != 1 else "file"
    read = [f"{view.files} {unit}"] + [f"{label} {n}" for label, n in view.languages]
    if elapsed is not None:
        read.append(f"{elapsed:.1f} s")
    line = Text(f" {glyphs['sep']} ".join(read), style="bright_black")
    if view.measurement != "COMPLETE":
        line.append(f"   measurement: {view.measurement}", style="bold yellow")
    parts.append(line)
    for note in view.coverage_notes:  # an install hint, or what could not be analyzed
        parts.append(Text(note, style="yellow"))
    return Group(*parts)


def print_summary(view: ReportView, elapsed: Optional[float] = None, console: Any = None) -> None:
    """Print the one-screen summary with rich: the verdict in a panel, then at
    most 5 findings and 3 review candidates (one line each), then what to do.

    Everything that comes from the scan (paths, messages, docstring text,
    notes) is printed as `Text`, never as rich markup: `[id]` in a path is a
    folder name, and `[/x]` in a docstring is not a closing tag."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = console or Console()
    glyphs = _glyphs(console)
    console.print(
        Panel(
            _verdict(view, glyphs, elapsed),
            title=Text.assemble(("AI SLOP Detector ", "bold"), (__version__, "bright_black")),
            title_align="left",
            subtitle=Text(_headline_target(view), style="bright_black"),
            subtitle_align="right",
            box=box.ROUNDED if glyphs is _GLYPHS else box.ASCII,
            border_style="bright_black",
            padding=(1, 2),
        )
    )
    root = _root(view)
    marks = glyphs is _GLYPHS
    _print_items(
        console, "Fix first", view.findings, TERMINAL_LIMITS["findings"], root, False, marks
    )
    _print_items(
        console,
        "To review (not scored)",
        view.candidates,
        TERMINAL_LIMITS["candidates"],
        root,
        True,
        marks,
    )
    steps = _steps(view)
    if steps:
        console.print("\n[bold] Next[/bold]")
        # A grid, so a step that does not fit continues under its own text.
        numbered = Table.grid(padding=(0, 1))
        numbered.add_column(no_wrap=True)
        numbered.add_column(overflow="fold")
        for i, step in enumerate(steps, 1):
            numbered.add_row(f"  {i}.", Text(step))
        console.print(numbered)
    console.print("\n[bright_black] Full tables: --details   Report file: -o report.md[/]")
    console.print("[bright_black] Choose reports to save: --interactive[/]")


def _print_items(
    console: Any,
    title: str,
    items: List[Item],
    limit: int,
    root: str,
    candidates: bool,
    cut_mark: bool = True,
) -> None:
    """One line per item: a message that does not fit is cut, never wrapped
    (`cut_mark`: with the mark of a cut line, where the console can print it)."""
    from rich.table import Table
    from rich.text import Text

    if not items:
        return
    shown, rest = top(items, limit)
    console.print(f"\n[bold] {title}[/bold]  [bright_black]{len(shown)} of {len(items)}[/]")
    # The location and the rule keep their width; only the message gives way.
    table = Table.grid(padding=(0, 2), expand=True)
    for _ in range(3):
        table.add_column(no_wrap=True)
    table.add_column(no_wrap=True, overflow="ellipsis" if cut_mark else "crop", ratio=1)
    for label, at, rule, message in _item_rows(shown, root, candidates):
        style = _SEVERITY_STYLE.get(label.lower(), "")
        first = Text(f" {label}" if label else " ", style=style)
        table.add_row(
            first, Text(at), Text(rule, style="bright_black"), Text(_first_clause(message))
        )
    console.print(table)
    if rest:
        console.print(f"  [bright_black]+{rest} more (--details or -o report.md)[/]")


_PHASE_GLYPHS = {"done": "\u2713", "now": "\u25b8", "todo": "\u00b7"}
_ASCII_PHASE_GLYPHS = {"done": "+", "now": ">", "todo": "."}
# Seconds between two drawings of the count while files are analyzed.
_REDRAW_EVERY = 0.1


class Progress:
    """What the scan is doing, in a box on a terminal that goes away when the
    scan ends; nothing when the stream is not a terminal.

    Phases: files found (per language), files analyzed (a rising count), the
    score. Drawing never ends a scan: any failure here stops the drawing only."""

    def __init__(self, stream: Any = None, clock: Any = None) -> None:
        self._stream = stream or sys.stderr
        self._on = bool(getattr(self._stream, "isatty", lambda: False)())
        self._clock = clock or time.monotonic
        self._live: Any = None
        self._glyphs: dict = _GLYPHS
        self._phase_glyphs: dict = _PHASE_GLYPHS
        self._found = ""
        self._index, self._total, self._name = 0, 0, ""
        self._phase = "find"
        self._drawn_at: Optional[float] = None

    @property
    def active(self) -> bool:
        """Whether the box is on the screen."""
        return self._live is not None

    def __call__(self, event: Any) -> None:
        if not self._on:
            return
        try:
            self._handle(event)
        except Exception:  # noqa: BLE001 - a display failure must not end the scan
            self._on = False
            self._stop()

    def _handle(self, event: Any) -> None:
        kind = event.kind
        if kind in ("completed", "failed", "cancelled"):
            self._stop()
            return
        if kind == "discovered":
            self._total = event.total or 0
            self._found = self._found_text(event.totals or {})
            self._phase = "analyze"
        elif kind == "file_done":
            self._index, self._total = event.index or 0, event.total or self._total
            self._name = Path(event.path or "").name
            if self._phase == "find":
                # A file scanned on its own sends no "discovered" event.
                self._phase, self._found = "analyze", self._found_text({})
            now = self._clock()
            if self._drawn_at is not None and now - self._drawn_at < _REDRAW_EVERY:
                return  # the next drawing, or the next phase, shows the count
        elif kind == "aggregating":
            self._phase = "score"
        else:
            return
        self._draw()

    def _found_text(self, totals: dict) -> str:
        from slop_detector import language_registry

        labels = {"python": "Python"}
        labels.update({a.name: a.label for a in language_registry.languages()})
        unit = "file" if self._total == 1 else "files"
        parts = [f"{self._total} {unit}"]
        parts += [f"{labels.get(name, name)} {n}" for name, n in totals.items() if n]
        return f" {self._glyphs['sep']} ".join(parts)

    def _start(self) -> None:
        from rich.console import Console
        from rich.live import Live

        console = Console(file=self._stream, force_terminal=True)
        self._glyphs = _glyphs(console)
        try:
            "".join(_PHASE_GLYPHS.values()).encode(console.encoding)
        except (UnicodeError, LookupError):
            self._phase_glyphs = _ASCII_PHASE_GLYPHS
        if self._glyphs is _ASCII_GLYPHS:
            self._phase_glyphs = _ASCII_PHASE_GLYPHS
        self._live = Live(console=console, transient=True, auto_refresh=False)
        self._live.start()

    def _stop(self) -> None:
        live, self._live = self._live, None
        if live is not None:
            try:
                live.stop()
            except Exception:  # noqa: BLE001 - the stream is gone; nothing to restore
                pass

    def _draw(self) -> None:
        if self._live is None:
            self._start()
        self._live.update(self._box(), refresh=True)
        self._drawn_at = self._clock()

    def _box(self) -> Any:
        from rich import box
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        order = ["find", "analyze", "score"]
        at = order.index(self._phase)
        width = 24
        filled = round(self._index / self._total * width) if self._total else 0
        bar = Text(self._glyphs["filled"] * filled, style="cyan")
        bar.append(self._glyphs["rest"] * (width - filled), style="bright_black")
        bar.append(f"  {self._index}/{self._total}  ")
        bar.append(self._name, style="bright_black")
        details = [Text(self._found, style="bright_black"), bar, Text("")]
        rows = Table.grid(padding=(0, 2))
        rows.add_column(no_wrap=True)
        rows.add_column(no_wrap=True)
        rows.add_column(no_wrap=True, overflow="ellipsis" if self._glyphs is _GLYPHS else "crop")
        for i, (label, detail) in enumerate(zip(("Find files", "Analyze", "Score"), details)):
            state = "done" if i < at else "now" if i == at else "todo"
            style = {"done": "green", "now": "bold cyan", "todo": "bright_black"}[state]
            name = Text(label, style="bold" if state == "now" else "" if state == "done" else style)
            shown = detail if state != "todo" else Text("")
            rows.add_row(Text(self._phase_glyphs[state], style=style), name, shown)
        return Panel(
            rows,
            title=Text.assemble(("AI SLOP Detector ", "bold"), (__version__, "bright_black")),
            title_align="left",
            box=box.ROUNDED if self._glyphs is _GLYPHS else box.ASCII,
            border_style="bright_black",
            padding=(0, 2),
        )
