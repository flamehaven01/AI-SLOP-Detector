"""Rich console rendering for the SLOP detector CLI."""

from __future__ import annotations

from pathlib import Path

from slop_detector.patterns import get_all_patterns
from slop_detector.question_generator import QuestionGenerator

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

    metrics_table = Table(title="Average Metrics", box=box.ROUNDED, header_style="bold cyan")
    metrics_table.add_column("Metric", style="cyan")
    metrics_table.add_column("Score", justify="right")
    metrics_table.add_row("Deficit Score", f"{result.avg_deficit_score:.1f}/100")
    metrics_table.add_row("Weighted Score", f"{result.weighted_deficit_score:.1f}/100")
    metrics_table.add_row("LDR (Logic)", f"{result.avg_ldr:.2%}")
    metrics_table.add_row("ICR (Inflation)", f"{result.avg_inflation:.2f}")
    metrics_table.add_row("DDC (Deps)", f"{result.avg_ddc:.2%}")
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
    """Build Panel 2: LDR / ICR / DDC / Justification Ratio with right-aligned values."""
    t = Table(box=None, show_header=False, padding=(0, 2), expand=True)
    t.add_column("key", style="cyan", no_wrap=True)
    t.add_column("val", justify="right", no_wrap=True)

    ldr = result.ldr.ldr_score
    ldr_color = "green" if ldr >= 0.7 else "yellow" if ldr >= 0.4 else "red"
    t.add_row("LDR (Logic Density):", f"[{ldr_color}]{ldr:.2%} ({result.ldr.grade})[/{ldr_color}]")

    icr = result.inflation.inflation_score
    icr_color = "red" if icr >= 1.0 else "yellow" if icr >= 0.5 else "green"
    t.add_row(
        "ICR (Inflation Check):",
        f"[{icr_color}]{icr:.2f} ({result.inflation.status})[/{icr_color}]",
    )

    ddc = result.ddc.usage_ratio
    ddc_color = "red" if ddc < 0.3 else "yellow" if ddc < 0.7 else "green"
    t.add_row(
        "DDC (Dependency Check):", f"[{ddc_color}]{ddc:.2%} ({result.ddc.grade})[/{ddc_color}]"
    )

    total_j = len(result.inflation.jargon_details)
    if total_j > 0:
        justified = sum(1 for d in result.inflation.jargon_details if d.get("justified"))
        ratio = justified / total_j
        jr_color = "green" if ratio >= 0.7 else "yellow" if ratio >= 0.3 else "red"
        t.add_row("Justification Ratio:", f"[{jr_color}]{ratio:.0%} evidence[/{jr_color}]")

    ml = getattr(result, "ml_score", None)
    if ml is not None:
        ml_color = (
            "red"
            if ml.slop_probability >= 0.70
            else "yellow" if ml.slop_probability >= 0.40 else "green"
        )
        t.add_row(
            "ML Slop Probability:",
            f"[{ml_color}]{ml.slop_probability:.1%} [{ml.label.upper()}][/{ml_color}]",
        )

    clone_issues = [
        i
        for i in getattr(result, "pattern_issues", [])
        if getattr(i, "pattern_id", None) == "function_clone_cluster"
    ]
    if clone_issues:
        top = clone_issues[0]
        sev = getattr(top, "severity", None)
        sev_val = sev.value if sev is not None else ""
        clone_color = "red" if sev_val == "critical" else "yellow"
        t.add_row(
            "Clone Detection:",
            f"[{clone_color}]{sev_val.upper()} — structural duplicates detected[/{clone_color}]",
        )
    else:
        t.add_row("Clone Detection:", "[green]PASS[/green]")

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
    console.print()
    questions = QuestionGenerator().generate_questions(result)
    if questions:
        console.print(_build_questions_panel(questions))
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
