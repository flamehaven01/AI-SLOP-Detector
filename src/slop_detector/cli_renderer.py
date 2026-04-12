"""Rendering helpers for the SLOP detector CLI (Rich, Markdown, text, HTML)."""

from pathlib import Path

from slop_detector.patterns import get_all_patterns
from slop_detector.question_generator import QuestionGenerator

# --- Rich Support ---

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

_PRODUCTION_CLAIMS_CLI: frozenset = frozenset(
    {
        "production-ready",
        "production ready",
        "enterprise-grade",
        "enterprise grade",
        "scalable",
        "fault-tolerant",
        "fault tolerant",
    }
)

_INTEGRATION_MARKERS = (
    "integration",
    "e2e",
    "/it/",
    "\\it\\",
    "integration_tests",
    "test_integration",
    "integration_test",
)


def _categorize_pattern(pattern) -> str:
    """Return the display category for a pattern based on its module path."""
    mod = pattern.__class__.__module__
    for key, label in _PATTERN_MODULE_CATEGORIES.items():
        if key in mod:
            return label
    return ""


def _print_pattern_category(category: str, category_patterns: list) -> None:
    """Print a single pattern category to stdout."""
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
    """Render project summary, metrics, and file tables via Rich."""
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
    """Append pattern issues block to a Rich Text object."""
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

    # Clone / structural duplication signal — surfaced from pattern_issues
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
    """Render single-file analysis as 3 rounded panels matching the README screenshot."""
    color = "red" if result.status != "clean" else "green"

    # Panel 1: File / Status / Deficit Score
    console.print(Panel(_build_header_table(result), border_style=color, box=box.ROUNDED))
    console.print()

    # Panel 2: Core Metrics
    console.print(
        Panel(
            _build_metrics_table(result),
            title="[bold cyan]Core Metrics[/bold cyan]",
            border_style="blue",
            box=box.ROUNDED,
        )
    )
    console.print()

    # Panel 3: Review Questions
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


def get_mitigation(issue_type: str, detail: str = "") -> str:
    """Returns an actionable mitigation strategy for a given issue type."""
    strategies = {
        "jargon": "Replace vague marketing terminology with precise technical descriptions. Focus on *how* it works, not just *that* it works.",
        "deficit": "The code has low information density. Ensure functions contain actual logic and aren't just empty wrappers.",
        "empty_function": "Implement the function's logic, mark it as abstract (if using ABC), or remove it if it's dead code.",
        "mutable_default": "Use `None` as the default value and initialize the mutable object (list/dict) inside the function body to avoid state persistence across calls.",
        "bare_except": "Catch specific exceptions (e.g., `ValueError`, `KeyError`) instead of a bare `except:`. A bare except can hide system interrupts and syntax errors.",
        "broad_except": "Refine the exception handler to catch only expected errors. `Exception` is too broad and may mask bugs.",
        "complex_logic": "Cyclomatic complexity is high. Refactor by extracting sub-routines or simplifying conditional logic.",
        "unused_import": "Remove the unused import to reduce clutter and potential circular dependency risks.",
    }
    return strategies.get(issue_type, "Review specific line for code quality improvements.")


def _file_has_production_claims(f_res) -> bool:
    """Return True if the file contains any production-tier jargon claims."""
    ctx = getattr(f_res, "context_jargon", None)
    if not ctx or not hasattr(ctx, "evidence_details"):
        return False
    return any(e.jargon.lower() in _PRODUCTION_CLAIMS_CLI for e in ctx.evidence_details)


def _collect_test_evidence_stats(file_results) -> dict:
    """Collect test evidence statistics from file results."""
    stats = {
        "unit_test_files": 0,
        "integration_test_files": 0,
        "total_test_files": 0,
        "unit_test_functions": 0,
        "integration_test_functions": 0,
        "total_test_functions": 0,
        "has_production_claims": False,
    }
    for f_res in file_results:
        if _file_has_production_claims(f_res):
            stats["has_production_claims"] = True
        file_path = str(f_res.file_path).lower()
        is_test_file = (
            "test_" in file_path
            or "_test.py" in file_path
            or "/tests/" in file_path
            or "\\tests\\" in file_path
        )
        if not is_test_file:
            continue
        stats["total_test_files"] += 1
        is_integration = any(m in file_path for m in _INTEGRATION_MARKERS)
        if is_integration:
            stats["integration_test_files"] += 1
            stats["integration_test_functions"] += 5
            stats["total_test_functions"] += 5
        else:
            stats["unit_test_files"] += 1
            stats["unit_test_functions"] += 10
            stats["total_test_functions"] += 10
    return stats


def _md_summary_section(avg_deficit: float, avg_inflation: float, status) -> list:
    """Return markdown lines for the Executive Summary section."""
    lines = [
        "## 1. Executive Summary",
        "| Metric | Score | Status | Description |",
        "| :--- | :--- | :--- | :--- |",
        f"| **Deficit Score** | {avg_deficit:.2f} | {status.value.upper()} | Closer to 0.0 is better. High score indicates low logic density. |",
        f"| **Inflation (Jargon)** | {avg_inflation:.2f} | - | Density of non-functional 'marketing' terms. |",
        "",
    ]
    return lines


def _md_test_evidence_section(result) -> list:
    """Return markdown lines for the Test Evidence section (projects only)."""
    if not hasattr(result, "file_results"):
        return []
    test_evidence = _collect_test_evidence_stats(result.file_results)
    if test_evidence["total_test_files"] == 0:
        return []
    lines = [
        "## 2. Test Evidence Summary",
        "| Test Type | Files | Functions | Coverage Notes |",
        "| :--- | :--- | :--- | :--- |",
        f"| **Unit Tests** | {test_evidence['unit_test_files']} | {test_evidence['unit_test_functions']} | Fast, isolated tests |",
        f"| **Integration Tests** | {test_evidence['integration_test_files']} | {test_evidence['integration_test_functions']} | Tests hitting real dependencies |",
        f"| **Total** | {test_evidence['total_test_files']} | {test_evidence['total_test_functions']} | - |",
    ]
    if test_evidence["integration_test_files"] == 0 and test_evidence.get("has_production_claims"):
        lines += [
            "",
            "[!] **Warning**: No integration tests detected, but codebase contains production-ready/enterprise-grade/scalable claims.",
        ]
    lines.append("")
    return lines


def _md_findings_section(file_results) -> list:
    """Return markdown lines for the Detailed Findings section."""
    lines = ["## 3. Detailed Findings"]
    if not file_results:
        return lines + ["_No files analyzed._"]

    for file_path, f_res in file_results:
        if (
            f_res.deficit_score < 0.3
            and not f_res.pattern_issues
            and not f_res.inflation.jargon_details
        ):
            continue
        lines += [
            f"### [L] `{Path(str(file_path)).name}`",
            f"- **Deficit Score**: {f_res.deficit_score:.2f}",
            f"- **Lines of Code**: {f_res.ldr.total_lines}",
        ]
        if f_res.ldr.total_lines == 0:
            lines += [
                "#### [!] Anti-Patterns & Risk",
                "| Line | Issue | Mitigation Strategy |",
                "| :--- | :--- | :--- |",
                "| — | Empty file (0 LOC): nothing to analyze | Remove the file if unused, or add implementation / mark as intentional stub |",
                "",
                "---",
            ]
            continue

        jargon_issues = [d for d in f_res.inflation.jargon_details if not d.get("justified")]
        if jargon_issues:
            lines += [
                "#### [-] Inflation (Jargon) Detected",
                "| Line | Term | Category | Actionable Mitigation |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for det in jargon_issues:
                lines.append(
                    f"| {det['line']} | `{det['word']}` | {det['category']} | {get_mitigation('jargon')} |"
                )
            lines.append("")

        if hasattr(f_res, "pattern_issues") and f_res.pattern_issues:
            lines += [
                "#### [!] Anti-Patterns & Risk",
                "| Line | Issue | Mitigation Strategy |",
                "| :--- | :--- | :--- |",
            ]
            for p in f_res.pattern_issues:
                desc = p.message if hasattr(p, "message") else str(p)
                line_val = p.line if hasattr(p, "line") else "-"
                desc_lower = desc.lower()
                issue_key = (
                    "mutable_default"
                    if "mutable default" in desc_lower
                    else (
                        "bare_except"
                        if "bare except" in desc_lower
                        else (
                            "broad_except"
                            if "broad exception" in desc_lower
                            else (
                                "empty_function"
                                if "empty function" in desc_lower
                                else "unused_import" if "unused import" in desc_lower else "unknown"
                            )
                        )
                    )
                )
                lines.append(f"| {line_val} | {desc} | {get_mitigation(issue_key, desc)} |")
            lines.append("")

        lines.append("---")
    return lines


def generate_markdown_report(result) -> str:
    """Generates a detailed developer-focused Markdown report."""
    is_project = hasattr(result, "project_path")
    root_dir = result.project_path if is_project else str(Path(result.file_path).parent)
    status = result.overall_status if is_project else result.status
    avg_deficit = result.avg_deficit_score if is_project else result.deficit_score
    avg_inflation = result.avg_inflation if is_project else result.inflation.inflation_score
    timestamp = getattr(result, "timestamp", None)

    lines = ["# AI Code Quality Audit Report"]
    if timestamp:
        lines.append(f"**Date**: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    lines += [f"**Target**: `{root_dir}`", f"**Status**: {status.value.upper()}", ""]

    lines += _md_summary_section(avg_deficit, avg_inflation, status)

    if is_project:
        lines += _md_test_evidence_section(result)

    if is_project:
        if hasattr(result, "files") and result.files:
            file_results = list(result.files.items())
        elif hasattr(result, "file_results"):
            file_results = [(r.file_path, r) for r in result.file_results]
        else:
            file_results = []
    else:
        file_results = [(result.file_path, result)]

    lines += _md_findings_section(file_results)

    lines += [
        "## 4. Global Recommendations",
        "- **Refactor High-Deficit Modules**: Files with scores > 0.5 lack sufficient logic. Verify they aren't just empty wrappers.",
        "- **Purify Terminology**: Replace abstract 'hype' terms with concrete engineering definitions.",
        "- **Harden Error Handling**: Eliminate bare except clauses to ensure system stability and debuggability.",
    ]
    return "\n".join(lines)


def _text_file_lines(fr) -> list:
    """Return text lines describing a single deficit file."""
    lines = [
        f"[!] {Path(fr.file_path).name}",
        f"    Status: {fr.status.upper()}",
        f"    Deficit Score: {fr.deficit_score:.1f}/100",
        f"    LDR: {fr.ldr.ldr_score:.2%} ({fr.ldr.grade})",
        f"    ICR: {fr.inflation.inflation_score:.2f} ({fr.inflation.status})",
    ]
    if fr.inflation.jargon_details:
        lines.append("    Jargon Locations:")
        lines += [
            f"      - Line {det['line']}: \"{det['word']}\""
            for det in fr.inflation.jargon_details
            if not det.get("justified")
        ]
    lines.append(f"    DDC: {fr.ddc.usage_ratio:.2%} ({fr.ddc.grade})")
    if fr.warnings:
        lines.append("    Warnings:")
        lines += [f"      - {w}" for w in fr.warnings]
    lines.append("")
    return lines


def _text_project_section(result) -> list:
    """Return text lines for the project-level portion of the text report."""
    lines = [
        f"Project: {result.project_path}",
        f"Total Files: {result.total_files}",
        f"Clean Files: {result.clean_files}",
        f"Deficit Files: {result.deficit_files}",
        f"Overall Status: {result.overall_status.upper()}",
        "",
        "Average Metrics:",
        f"  Deficit Score: {result.avg_deficit_score:.1f}/100",
        f"  Weighted Deficit Score: {result.weighted_deficit_score:.1f}/100",
        f"  Logic Density (LDR): {result.avg_ldr:.2%}",
        f"  Inflation Ratio (ICR): {result.avg_inflation:.2f}",
        f"  Dependency Usage (DDC): {result.avg_ddc:.2%}",
        "",
    ]
    if hasattr(result, "file_results"):
        te = _collect_test_evidence_stats(result.file_results)
        if te["total_test_files"] > 0:
            lines += [
                "Test Evidence:",
                f"  Unit Tests: {te['unit_test_files']} files, {te['unit_test_functions']} functions",
                f"  Integration Tests: {te['integration_test_files']} files, {te['integration_test_functions']} functions",
                f"  Total: {te['total_test_files']} test files",
            ]
            if te["integration_test_files"] == 0 and te.get("has_production_claims"):
                lines.append("  [!] WARNING: No integration tests, but has production claims")
            lines.append("")
    lines += ["=" * 80, "FILE-LEVEL ANALYSIS", "=" * 80, ""]
    for fr in result.file_results:
        if fr.status != "clean":
            lines += _text_file_lines(fr)
    return lines


def _text_single_file_section(result) -> list:
    """Return text lines for a single-file text report."""
    lines = [
        f"File: {result.file_path}",
        f"Status: {result.status.upper()}",
        f"Deficit Score: {result.deficit_score:.1f}/100",
        "",
        f"LDR: {result.ldr.ldr_score:.2%} ({result.ldr.grade})",
        f"ICR: {result.inflation.inflation_score:.2f} ({result.inflation.status})",
        f"DDC: {result.ddc.usage_ratio:.2%} ({result.ddc.grade})",
    ]
    if result.warnings:
        lines += ["", "Warnings:"] + [f"  - {w}" for w in result.warnings]
    return lines


def generate_text_report(result) -> str:
    """Generate text report."""
    lines = ["=" * 80, "AI CODE QUALITY REPORT", "=" * 80, ""]
    if hasattr(result, "project_path"):
        lines += _text_project_section(result)
    else:
        lines += _text_single_file_section(result)
    return "\n".join(lines)


def generate_html_report(result) -> str:
    """Generate HTML report (simplified version)."""
    # In production, use Jinja2 templates
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>SLOP Detection Report</title>
    <style>
        body {{ font-family: monospace; max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .score {{ font-size: 2em; font-weight: bold; }}
        .clean {{ color: green; }}
        .suspicious {{ color: orange; }}
        .critical {{ color: red; }}
    </style>
</head>
<body>
    <h1>AI Code Quality Report</h1>
    <div class="score">Score: {getattr(result, 'weighted_deficit_score', result.deficit_score):.1f}/100</div>
    <pre>{generate_text_report(result)}</pre>
</body>
</html>
    """
    return html
