"""Rich console rendering for the SLOP detector CLI."""

from __future__ import annotations

from pathlib import Path

from slop_detector.patterns import get_all_patterns
from slop_detector.question_generator import QuestionGenerator
from slop_detector.renderer_glossary import (
    DEFICIT_BANDS,
    clone_metric_row,
    coherence_display,
    file_metric_rows,
    next_steps,
    project_metric_rows,
)

try:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

_PATTERN_MODULE_CATEGORIES = {
    "structural": "Structural Issues",
    "placeholder": "Placeholder Code",
    "cross_language": "Cross-Language Patterns",
    "python_advanced": "Python Advanced",
}


def _categorize_pattern(pattern) -> str:
    mod = pattern.__class__.__module__
    for key, label in _PATTERN_MODULE_CATEGORIES.items():
        if key in mod:
            return label
    return ""


def _print_pattern_category(category: str, category_patterns: list) -> None:
    if not category_patterns:
        return
    print(f"\n{category}:")
    print("-" * 80)
    for pattern in category_patterns:
        print(f"  {pattern.id:30s} [{pattern.severity.value:8s}] {pattern.message}")


def list_patterns() -> None:
    """List all available patterns."""
    from typing import Dict, List

    from slop_detector.patterns.base import BasePattern

    patterns = get_all_patterns()
    print("Available Patterns:")
    print("=" * 80)

    by_category: Dict[str, List[BasePattern]] = {
        "Structural Issues": [],
        "Placeholder Code": [],
        "Cross-Language Patterns": [],
        "Python Advanced": [],
    }
    for pattern in patterns:
        cat = _categorize_pattern(pattern)
        if cat:
            by_category[cat].append(pattern)

    for category, category_patterns in by_category.items():
        _print_pattern_category(category, category_patterns)

    print("\n" + "=" * 80)
    print(f"Total: {len(patterns)} patterns")
    print("\nUsage: slop-detector --disable <pattern_id> ...")


def _build_rich_summary_tables(result):
    """Build and return (summary_table, metrics_table) Rich Table objects."""
    summary_table = Table(title="Project Summary", box=box.ROUNDED)
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green")
    summary_table.add_row("Project", str(result.project_path))
    summary_table.add_row("Total Files", str(result.total_files))
    summary_table.add_row("Clean Files", str(result.clean_files))
    summary_table.add_row(
        "Deficit Files",
        (
            f"[red]{result.deficit_files}[/red]"
            if result.deficit_files > 0
            else str(result.deficit_files)
        ),
    )
    sc = "red" if result.overall_status != "clean" else "green"
    summary_table.add_row("Overall Status", f"[{sc}]{result.overall_status.upper()}[/{sc}]")
    coh = coherence_display(result)
    if coh:
        summary_table.add_row(coh["label"], f"{coh['value']} ({coh['direction']} is more cohesive)")
        summary_table.add_row("Coherence Check", coh["coverage"])

    metrics_table = Table(title="Project Metrics", box=box.ROUNDED, header_style="bold cyan")
    metrics_table.add_column("Metric", style="cyan", no_wrap=True)
    metrics_table.add_column("Value", justify="right")
    metrics_table.add_column("Healthy", justify="center", style="dim")
    metrics_table.add_column("What It Means", style="dim")
    health_color = {"good": "green", "warn": "yellow", "bad": "red"}
    for row in project_metric_rows(result):
        color = health_color.get(row["health"], "white")
        metrics_table.add_row(
            row["label"],
            f"[{color}]{row['value']}[/{color}]",
            row["direction"],
            row["means"],
        )
    return summary_table, metrics_table


def _build_rich_files_table(result):
    """Build and return the Rich Table for file-level analysis."""
    files_table = Table(
        title="File Analysis", box=box.ROUNDED, header_style="bold cyan", show_lines=False
    )
    for col, kw in [
        ("File", {"style": "bold"}),
        ("Status", {}),
        ("Score", {"justify": "right"}),
        ("LDR", {"justify": "right"}),
        ("ICR", {"justify": "right"}),
        ("DDC", {"justify": "right"}),
        ("Notes", {"style": "dim"}),
    ]:
        files_table.add_column(col, **kw)
    for fr in result.file_results:
        if fr.status == "clean":
            continue
        ss = "red" if fr.status in ("critical", "critical_deficit") else "yellow"
        notes = [f"{len(fr.warnings)} warnings"] if fr.warnings else []
        jc = sum(1 for d in fr.inflation.jargon_details if not d.get("justified"))
        if jc > 0:
            preview = [d["word"] for d in fr.inflation.jargon_details if not d.get("justified")][:3]
            suffix = f" +{jc - 3} more" if jc > 3 else ""
            notes.append(f"{jc} jargon ({', '.join(preview)}{suffix})")
        files_table.add_row(
            Path(fr.file_path).name,
            f"[{ss}]{fr.status.upper()}[/{ss}]",
            f"{fr.deficit_score:.1f}",
            f"{fr.ldr.ldr_score:.0%}",
            f"{fr.inflation.inflation_score:.2f}",
            f"{fr.ddc.usage_ratio:.0%}",
            "\n".join(notes),
        )
    return files_table


def _render_rich_project(console, result) -> None:
    summary_table, metrics_table = _build_rich_summary_tables(result)
    console.print(summary_table)
    console.print()
    console.print(metrics_table)
    console.print(f"[dim]Deficit bands:[/dim] {DEFICIT_BANDS}")
    console.print()
    steps = next_steps(result)
    if steps:
        body = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
        console.print(Panel(body, title="Next Steps", border_style="cyan", title_align="left"))
        console.print()
    suppression_ledger = getattr(result, "suppression_ledger", [])
    if suppression_ledger:
        sup_table = Table(
            title="Inline Suppression Ledger", box=box.ROUNDED, header_style="bold cyan"
        )
        sup_table.add_column("File", style="bold")
        sup_table.add_column("Line", justify="right")
        sup_table.add_column("Pattern")
        sup_table.add_column("Directive", justify="right")
        sup_table.add_column("Scope")
        for entry in suppression_ledger[:10]:
            sup_table.add_row(
                Path(entry.file_path).name,
                str(entry.suppressed_line),
                entry.pattern_id,
                str(entry.directive_line),
                entry.scope,
            )
        console.print(sup_table)
        console.print()
        if len(suppression_ledger) >= 10:
            console.print(
                Panel(
                    "High inline suppression usage detected. Review whether muted patterns should be fixed instead.",
                    style="yellow",
                )
            )
            console.print()
    priority_hotspots = getattr(result, "priority_hotspots", [])
    if priority_hotspots:
        hotspot_table = Table(title="Priority Hotspots", box=box.ROUNDED, header_style="bold cyan")
        hotspot_table.add_column("File", style="bold")
        hotspot_table.add_column("Priority", justify="right")
        hotspot_table.add_column("Deficit", justify="right")
        hotspot_table.add_column("Churn", justify="right")
        hotspot_table.add_column("Coverage", justify="right")
        hotspot_table.add_column("Reasons", style="dim")
        for hotspot in priority_hotspots[:10]:
            coverage = "n/a" if hotspot.coverage_ratio is None else f"{hotspot.coverage_ratio:.0%}"
            hotspot_table.add_row(
                Path(hotspot.file_path).name,
                f"{hotspot.priority_score:.1f}/100",
                f"{hotspot.deficit_score:.1f}",
                str(hotspot.churn_count),
                coverage,
                ", ".join(hotspot.reasons),
            )
        console.print(hotspot_table)
        console.print(
            f"[dim]Signals: churn={'yes' if getattr(result, 'churn_analysis_available', False) else 'no'}, "
            f"coverage={'yes' if getattr(result, 'coverage_analysis_available', False) else 'no'}[/dim]"
        )
        console.print()
    if result.deficit_files > 0:
        console.print(_build_rich_files_table(result))
    else:
        console.print(Panel("No deficit detected in project files.", style="green"))


def _append_pattern_issues_rich(content, result) -> None:
    issues = getattr(result, "pattern_issues", None)
    if not issues:
        return
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_issues = sorted(
        issues,
        key=lambda p: sev_order.get(getattr(getattr(p, "severity", None), "value", "low"), 3),
    )
    content.append("\nPattern Issues:\n", style="bold red")
    for p in sorted_issues[:10]:
        sev = getattr(getattr(p, "severity", None), "value", "low")
        sev_style = "bold red" if sev == "critical" else "yellow" if sev == "high" else "dim"
        content.append(
            f"  L{getattr(p, 'line', '-')} [{sev.upper()}] {getattr(p, 'message', str(p))}\n",
            style=sev_style,
        )
    if len(issues) > 10:
        content.append(f"  ... and {len(issues) - 10} more\n", style="dim")
    adv_parts = [
        f"{sum(1 for p in issues if getattr(p, 'pattern_id', '') == pid)} {label}"
        for pid, label in [
            ("god_function", "god-fn"),
            ("dead_code", "dead-code"),
            ("deep_nesting", "deep-nest"),
        ]
        if any(getattr(p, "pattern_id", "") == pid for p in issues)
    ]
    if adv_parts:
        content.append(f"  Advanced: {', '.join(adv_parts)}\n", style="dim cyan")


def _build_header_table(result) -> "Table":
    """Build Panel 1: File / Status / Deficit Score with right-aligned values."""
    color = "red" if result.status != "clean" else "green"
    t = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    t.add_column("key", style="cyan", no_wrap=True)
    t.add_column("val", justify="right", no_wrap=True)
    t.add_row("File:", Path(result.file_path).name)
    t.add_row("Status:", f"[bold {color}]{result.status.upper()}[/bold {color}]")
    t.add_row("Deficit Score:", f"[bold]{result.deficit_score:.1f}/100[/bold]")
    return t


def _build_metrics_table(result) -> "Table":
    """Build Panel 2: friendly core metrics (value / healthy direction / meaning).

    Deficit Score is omitted here because it headlines Panel 1.
    """
    t = Table(box=None, show_header=True, header_style="bold cyan", padding=(0, 2), expand=True)
    t.add_column("Metric", style="cyan", no_wrap=True)
    t.add_column("Value", justify="right")
    t.add_column("Healthy", justify="center", style="dim")
    t.add_column("What It Means", style="dim")
    health_color = {"good": "green", "warn": "yellow", "bad": "red"}
    for row in file_metric_rows(result):
        if row["label"] == "Deficit Score":
            continue
        color = health_color.get(row["health"], "white")
        t.add_row(
            row["label"],
            f"[{color}]{row['value']}[/{color}]",
            row["direction"],
            row["means"],
        )

    total_j = len(result.inflation.jargon_details)
    if total_j > 0:
        justified = sum(1 for d in result.inflation.jargon_details if d.get("justified"))
        ratio = justified / total_j
        jr_color = "green" if ratio >= 0.7 else "yellow" if ratio >= 0.3 else "red"
        t.add_row(
            "Justification Ratio",
            f"[{jr_color}]{ratio:.0%}[/{jr_color}]",
            "Higher",
            "Share of flagged jargon backed by real complexity.",
        )

    ml = getattr(result, "ml_score", None)
    if ml is not None:
        ml_color = (
            "red"
            if ml.slop_probability >= 0.70
            else "yellow" if ml.slop_probability >= 0.40 else "green"
        )
        t.add_row(
            "ML Slop Probability",
            f"[{ml_color}]{ml.slop_probability:.1%} [{ml.label.upper()}][/{ml_color}]",
            "Lower",
            "Optional ML secondary signal.",
        )

    clone_row = clone_metric_row(result)
    if clone_row:
        clone_color = "red" if clone_row["health"] == "bad" else "yellow"
        t.add_row(
            "Clone Detection:",
            f"[{clone_color}]{clone_row['value']}[/{clone_color}]",
            clone_row["direction"],
            clone_row["means"],
        )
    else:
        t.add_row(
            "Clone Detection:",
            "[green]PASS[/green]",
            "Lower",
            "No exact duplicate pair or near-identical function cluster was detected.",
        )

    return t


def _build_questions_panel(questions) -> "Panel":
    """Build Panel 3: inline [CRITICAL]/[WARNING]/[INFO] badge per question."""
    content = Text()
    for q in questions:
        if q.severity == "critical":
            content.append("[CRITICAL] ", style="bold red")
        elif q.severity == "warning":
            content.append("[WARNING] ", style="bold yellow")
        else:
            content.append("[INFO] ", style="bold cyan")
        if q.line:
            content.append(f"(Line {q.line}) ", style="dim")
        content.append(q.question + "\n")
    return Panel(
        content, title="[bold]Review Questions[/bold]", border_style="blue", box=box.ROUNDED
    )


def _build_single_file_content(result) -> "Text":
    """Build single-file Rich Text (used by text-report fallback path)."""
    color = "red" if result.status != "clean" else "green"
    content = Text()
    content.append(f"File: {result.file_path}\n")
    content.append(f"Status: {result.status.upper()}\n", style="bold " + color)
    content.append(f"Score: {result.deficit_score:.1f}/100\n\n")
    content.append(f"LDR: {result.ldr.ldr_score:.2%} ({result.ldr.grade})\n")
    content.append(f"ICR: {result.inflation.inflation_score:.2f} ({result.inflation.status})\n")
    content.append(f"DDC: {result.ddc.usage_ratio:.2%} ({result.ddc.grade})\n")
    if result.warnings:
        content.append("\nWarnings:\n", style="bold yellow")
        for w in result.warnings:
            content.append(f"- {w}\n")
    jargon = [d for d in result.inflation.jargon_details if not d.get("justified")]
    if jargon:
        content.append("\nJargon Detected:\n", style="bold red")
        for d in jargon:
            content.append(f"- Line {d['line']}: {d['word']}\n")
    if result.docstring_inflation and result.docstring_inflation.details:
        di = result.docstring_inflation
        content.append("\nDocstring Inflation:\n", style="bold yellow")
        content.append(
            f"Overall: {di.total_docstring_lines} doc lines / {di.total_implementation_lines} impl lines (ratio: {di.overall_ratio:.2f})\n"
        )
        if di.inflated_count > 0:
            content.append(f"{di.inflated_count} inflated functions/classes:\n")
            for det in di.details[:3]:
                content.append(
                    f"- Line {det.line}: {det.name} ({det.docstring_lines}doc/{det.implementation_lines}impl = {det.inflation_ratio:.1f}x)\n"
                )
    suppression_ledger = getattr(result, "suppression_ledger", [])
    if suppression_ledger:
        content.append("\nInline Suppressions:\n", style="bold yellow")
        for entry in suppression_ledger[:10]:
            content.append(
                f"  L{entry.suppressed_line} {entry.pattern_id} via L{entry.directive_line} [{entry.scope}]\n",
                style="yellow",
            )
    _append_pattern_issues_rich(content, result)
    ml = getattr(result, "ml_score", None)
    if ml is not None:
        ml_color = (
            "red"
            if ml.slop_probability >= 0.70
            else "yellow" if ml.slop_probability >= 0.40 else "green"
        )
        content.append("\nML Score:\n", style="bold cyan")
        content.append(
            f"  Slop Probability: {ml.slop_probability:.1%} [{ml.label.upper()}]\n", style=ml_color
        )
        content.append(
            f"  Confidence: {ml.confidence:.1%}  Model: {ml.model_type}  Agreement: {'yes' if ml.agreement else 'no'}\n",
            style="dim",
        )
    return content


def _render_rich_single_file(console, result) -> None:
    """Render single-file analysis as 3 rounded panels."""
    color = "red" if result.status != "clean" else "green"
    console.print(Panel(_build_header_table(result), border_style=color, box=box.ROUNDED))
    console.print()
    console.print(
        Panel(
            _build_metrics_table(result),
            title="[bold cyan]Core Metrics[/bold cyan]",
            border_style="blue",
            box=box.ROUNDED,
        )
    )
    console.print(f"[dim]Deficit bands:[/dim] {DEFICIT_BANDS}")
    console.print()
    questions = QuestionGenerator().generate_questions(result)
    if questions:
        console.print(_build_questions_panel(questions))
        console.print()
    extra = Text()
    suppression_ledger = getattr(result, "suppression_ledger", [])
    if suppression_ledger:
        extra.append("Inline Suppressions:\n", style="bold yellow")
        for entry in suppression_ledger[:10]:
            extra.append(
                f"  L{entry.suppressed_line} {entry.pattern_id} via L{entry.directive_line} [{entry.scope}]\n",
                style="yellow",
            )
    if result.warnings:
        extra.append("\nWarnings:\n", style="bold yellow")
        for w in result.warnings:
            extra.append(f"  - {w}\n")
    if extra.plain.strip():
        console.print(
            Panel(
                extra,
                title="[bold yellow]Audit Notes[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )
        console.print()


def print_rich_report(result) -> None:
    """Print report using Rich."""
    console = Console()
    console.print()
    console.print(
        Panel.fit(Text("AI CODE QUALITY REPORT", style="bold cyan"), style="blue", box=box.ROUNDED)
    )
    console.print()

    if hasattr(result, "project_path"):
        _render_rich_project(console, result)
    else:
        _render_rich_single_file(console, result)
