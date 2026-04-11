"""Command-line interface for SLOP detector."""

import argparse
import json
import logging
import sys
from pathlib import Path

from slop_detector import __version__
from slop_detector.core import SlopDetector
from slop_detector.models import FileAnalysis, ProjectAnalysis
from slop_detector.patterns import get_all_patterns
from slop_detector.question_generator import QuestionGenerator

_PATTERN_MODULE_CATEGORIES = {
    "structural": "Structural Issues",
    "placeholder": "Placeholder Code",
    "cross_language": "Cross-Language Patterns",
    "python_advanced": "Python Advanced",
}


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


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stderr)


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


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="AI SLOP Detector v4.0 - Sovereign Gate Edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  slop-detector --init                       # Bootstrap .slopconfig.yaml + .gitignore
  slop-detector file.py                      # Analyze single file
  slop-detector --project src/               # Analyze project
  slop-detector --project . --json           # JSON output
  slop-detector --project . -o report.html   # HTML report
  slop-detector file.py --fix --dry-run      # Preview auto-fixes
  slop-detector file.py --fix                # Apply auto-fixes
  slop-detector file.py --gate               # Show SNP gate decision
  slop-detector src/ --js                    # Analyze JS/TS files
  slop-detector src/ --cross-file            # Cross-file analysis
  slop-detector src/ --governance            # Emit CR-EP session artifacts
  slop-detector --self-calibrate             # Optimize weights from run history
  slop-detector --version                    # Show version
        """,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to Python file or project directory (default: current directory)",
    )
    parser.add_argument("--project", action="store_true", help="Analyze entire project")
    parser.add_argument("--output", "-o", help="Output file (txt, json, or html)")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("--config", "-c", help="Path to .slopconfig.yaml configuration file")
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply auto-fixes for detected patterns (use --dry-run to preview)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview fixes without writing to disk (use with --fix)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Show SNP-compatible gate decision (PASS/HALT) with sr9/di2/jsd/ove metrics",
    )
    parser.add_argument(
        "--js",
        action="store_true",
        help="Analyze JavaScript/TypeScript files in addition to Python",
    )
    parser.add_argument(
        "--cross-file",
        action="store_true",
        help="Run cross-file analysis (cycles, duplicates, hotspots)",
    )
    parser.add_argument(
        "--governance",
        action="store_true",
        help="Emit CR-EP v2.7.2 session artifacts to .cr-ep/ directory",
    )
    parser.add_argument(
        "--disable",
        "-d",
        action="append",
        default=[],
        metavar="PATTERN_ID",
        help="Disable specific pattern by ID (can be repeated)",
    )
    parser.add_argument(
        "--patterns-only", action="store_true", help="Only run pattern detection (skip metrics)"
    )
    parser.add_argument(
        "--list-patterns", action="store_true", help="List all available patterns and exit"
    )
    parser.add_argument(
        "--fail-threshold",
        type=float,
        default=None,
        help="Exit with code 1 if slop score exceeds threshold",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--version", action="version", version=f"ai-slop-detector {__version__}")
    parser.add_argument(
        "--no-color", action="store_true", help="Disable rich output (force plain text)"
    )
    # History tracking (v2.9.0)
    parser.add_argument(
        "--no-history",
        action="store_true",
        help="Skip recording this run to history (~/.slop-detector/history.db)",
    )
    parser.add_argument(
        "--show-history", action="store_true", help="Show trend history for the given file and exit"
    )
    parser.add_argument(
        "--history-trends",
        action="store_true",
        help="Show project-wide daily trends (last 7 days) and exit",
    )
    parser.add_argument(
        "--export-history", metavar="PATH", help="Export full history to JSONL file and exit"
    )
    # Self-Calibration (v2.9.2)
    parser.add_argument(
        "--self-calibrate",
        action="store_true",
        help="Analyze usage history to find optimal ldr/inflation/ddc weights for this codebase",
    )
    parser.add_argument(
        "--apply-calibration",
        metavar="CONFIG",
        nargs="?",
        const=".slopconfig.yaml",
        help="Write calibrated weights to .slopconfig.yaml (or specified path). Use with --self-calibrate",
    )
    parser.add_argument(
        "--min-history",
        type=int,
        default=5,
        metavar="N",
        help="Minimum labeled events per class (improvements / FP candidates) before calibration runs (default: 5 per class)",
    )
    # Bootstrap (v3.2.0)
    parser.add_argument(
        "--init",
        action="store_true",
        help="Bootstrap .slopconfig.yaml for this project and add it to .gitignore",
    )
    parser.add_argument(
        "--force-init",
        action="store_true",
        help="Overwrite existing .slopconfig.yaml when using --init",
    )
    # CI/CD Gate options (v2.2)
    parser.add_argument(
        "--ci-mode",
        choices=["soft", "hard", "quarantine"],
        help="CI gate mode: soft (PR comments only), hard (fail build), quarantine (track repeat offenders)",
    )
    parser.add_argument(
        "--ci-report",
        action="store_true",
        help="Output CI gate report and exit with appropriate code",
    )
    parser.add_argument(
        "--ci-claims-strict",
        action="store_true",
        help="Enable claim-based enforcement: fail if production/enterprise/scalable/fault-tolerant claims lack integration tests (v2.6.2)",
    )
    return parser


def _write_file(path: str, content: str, label: str = "") -> None:
    """Write content to a file, with optional console confirmation."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if label:
        print(f"[+] {label} saved to {path}")


def _write_json_output(args, result) -> None:
    """Serialize result to JSON and write to file or stdout."""
    output = json.dumps(result.to_dict(), indent=2)
    if args.output:
        _write_file(args.output, output)
    else:
        print(output)


def _route_file_output(out: str, result, rich_ok: bool) -> None:
    """Write result to file or console based on output extension and flags."""
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
    if args.json:
        _write_json_output(args, result)
        return
    out = str(args.output) if args.output else ""
    _route_file_output(out, result, RICH_AVAILABLE and not args.no_color)


def _evaluate_ci_gate(args, result):
    """Run CI gate evaluation; return exit code or None to continue."""
    claims_strict = getattr(args, "ci_claims_strict", False)
    if not (args.ci_mode or args.ci_report or claims_strict):
        return None
    from slop_detector.ci_gate import CIGate, GateMode

    gate_mode = GateMode(args.ci_mode) if args.ci_mode else GateMode.SOFT
    gate_result = CIGate(mode=gate_mode, claims_strict=claims_strict).evaluate(result)
    if args.ci_report:
        if args.json:
            print(json.dumps(gate_result.to_dict(), indent=2))
        else:
            print(gate_result.pr_comment or gate_result.message)
        return 1 if gate_result.should_fail_build else 0
    return None


def _run_optional_features(args, result) -> None:
    """Run optional post-output features (gate, fix, js, cross-file, governance)."""
    if getattr(args, "gate", False):
        _run_gate(result)
    if getattr(args, "fix", False):
        _run_autofix(result, dry_run=getattr(args, "dry_run", True))
    if getattr(args, "js", False):
        _run_js_analysis(args.path)
    if getattr(args, "cross_file", False) and hasattr(result, "project_path"):
        _run_cross_file(result)
    if getattr(args, "governance", False):
        _run_governance(args.path, result)


def _run_analysis_phase(args, detector):
    """Run file or project analysis. Returns (result, score)."""
    from typing import Union

    result: Union[ProjectAnalysis, FileAnalysis]
    if args.project:
        result = detector.analyze_project(args.path)
        return result, result.weighted_deficit_score
    result = detector.analyze_file(args.path)
    return result, result.deficit_score


def main() -> int:
    """CLI entry point."""
    args = _build_arg_parser().parse_args()
    setup_logging(args.verbose)

    if getattr(args, "history_trends", False):
        _show_trends()
        return 0
    if getattr(args, "export_history", None):
        _export_history(args.export_history)
        return 0
    if getattr(args, "show_history", False):
        _show_file_history(args.path)
        return 0
    if getattr(args, "init", False):
        return _run_init(args)
    if getattr(args, "self_calibrate", False):
        return _run_self_calibration(args)

    if Path(args.path).is_dir() and not args.project:
        args.project = True
        logging.info("Directory detected, enabling --project mode")

    if args.list_patterns:
        list_patterns()
        return 0

    try:
        detector = SlopDetector(config_path=args.config)
    except Exception as e:
        print(f"[!] Failed to initialize detector: {e}", file=sys.stderr)
        return 1

    try:
        result, score = _run_analysis_phase(args, detector)
    except Exception as e:
        print(f"[!] Analysis failed: {e}", file=sys.stderr)
        return 1

    ci_exit = _evaluate_ci_gate(args, result)
    if ci_exit is not None:
        return ci_exit

    _handle_output(args, result)

    if args.fail_threshold is not None and score > args.fail_threshold:
        print(
            f"\n[!] FAIL: Deficit score {score:.1f} exceeds threshold {args.fail_threshold}",
            file=sys.stderr,
        )
        return 1

    _run_optional_features(args, result)

    if not getattr(args, "no_history", False):
        _record_history(result)
        _check_calibration_hint(args)

    return 0


def _run_gate(result) -> None:
    """Display SNP-compatible gate decision."""
    from slop_detector.gate.slop_gate import SlopGate

    gate = SlopGate()
    if hasattr(result, "file_results"):
        avg_ldr = getattr(result, "avg_ldr", 0.0)
        avg_inflation = getattr(result, "avg_inflation", 0.0)
        avg_ddc = getattr(result, "avg_ddc", 1.0)
        pattern_penalty = min(result.deficit_files * 5.0, 50.0)
        decision = gate.evaluate(avg_ldr, avg_ddc, avg_inflation, pattern_penalty, "project")
    else:
        decision = gate.evaluate_from_file_analysis(result)

    print("\n[Gate Decision]")
    print(f"  Status   : {decision.status}")
    print(f"  Allowed  : {decision.allowed}")
    m = decision.metrics_snapshot
    print(f"  sr9={m['sr9']:.4f}  di2={m['di2']:.4f}  jsd={m['jsd']:.4f}  ove={m['ove']:.4f}")
    if decision.halt_reason:
        print(f"  Halt     : {decision.halt_reason}")
    if decision.recommendation:
        print(f"  Recommend: {decision.recommendation}")
    print(f"  AuditHash: {decision.audit_hash[:16]}...")


def _run_autofix(result, dry_run: bool = True) -> None:
    """Run auto-fix engine on analysis results."""
    from slop_detector.autofix.engine import FixEngine

    engine = FixEngine()
    mode = "DRY RUN" if dry_run else "APPLYING"
    print(f"\n[Auto-Fix] {mode}")

    if hasattr(result, "file_results"):
        file_analyses = [
            (fa.file_path, getattr(fa, "pattern_issues", [])) for fa in result.file_results
        ]
    else:
        file_analyses = [(result.file_path, getattr(result, "pattern_issues", []))]

    fix_results = engine.fix_project(file_analyses, dry_run=dry_run)

    if not fix_results:
        print("  [+] No auto-fixable issues found.")
        return

    total_fixed = 0
    for fix_result in fix_results:
        if fix_result.changed:
            print(f"\n  File: {fix_result.file_path}")
            for ch in fix_result.changes:
                print(f"    [L{ch.line}] {ch.pattern_id} (confidence={ch.confidence:.0%})")
                print(f"      - {ch.original.strip()!r}")
                print(f"      + {ch.replacement.strip()!r}")
            total_fixed += fix_result.change_count
        if fix_result.unfixable:
            print(f"  Unfixable (manual): {', '.join(fix_result.unfixable)}")

    action = "Would fix" if dry_run else "Fixed"
    print(f"\n  [+] {action} {total_fixed} issues across {len(fix_results)} files.")
    if dry_run:
        print("  Run without --dry-run to apply changes.")


def _run_js_analysis(path: str) -> None:
    """Analyze JS/TS files in a directory."""
    from slop_detector.languages.js_analyzer import JSAnalyzer

    analyzer = JSAnalyzer()
    target = Path(path)

    if target.is_file() and target.suffix.lower() in (".js", ".jsx", ".ts", ".tsx"):
        results = [analyzer.analyze(str(target))]
    elif target.is_dir():
        results = analyzer.analyze_directory(str(target))
    else:
        print(f"[!] No JS/TS files found at {path}")
        return

    print(f"\n[JS/TS Analysis] {len(results)} files")
    clean = sum(1 for r in results if r.status == "clean")
    suspicious = sum(1 for r in results if r.status == "suspicious")
    critical = sum(1 for r in results if r.status == "critical_deficit")
    print(f"  Clean: {clean}  Suspicious: {suspicious}  Critical: {critical}")

    for r in sorted(results, key=lambda x: x.slop_score, reverse=True):
        if r.status == "clean":
            continue
        print(f"\n  [{r.status.upper()}] {r.file_path}")
        print(f"    Score={r.slop_score:.1f}  LDR={r.ldr_equivalent:.2%}  Issues={len(r.issues)}")
        for issue in r.issues[:5]:
            print(f"    L{issue.line} [{issue.severity}] {issue.message}")


def _run_cross_file(result) -> None:
    """Run cross-file analysis on project results."""
    from slop_detector.analysis.cross_file import CrossFileAnalyzer

    analyzer = CrossFileAnalyzer()
    report = analyzer.analyze(
        result.project_path,
        result.file_results,
    )

    print("\n[Cross-File Analysis]")
    print(f"  Files: {report.total_files}  Risk Score: {report.risk_score:.2f}")

    if report.import_cycles:
        print(f"\n  Import Cycles ({len(report.import_cycles)}):")
        for cycle in report.import_cycles[:5]:
            print(f"    {cycle}")

    if report.duplicates:
        print(f"\n  Duplicate Functions ({len(report.duplicates)}):")
        for dup in report.duplicates[:5]:
            a = Path(dup.file_a).name
            b = Path(dup.file_b).name
            print(f"    {a}:{dup.func_a}() == {b}:{dup.func_b}() (sim={dup.similarity:.0%})")

    if report.hotspots:
        print(f"\n  Slop Hotspots ({len(report.hotspots)}) - heavily imported + sloppy:")
        for h in report.hotspots:
            print(
                f"    {Path(h.file_path).name}  score={h.slop_score:.1f}  imported_by={h.import_count}"
            )

    if not report.import_cycles and not report.duplicates and not report.hotspots:
        print("  [+] No cross-file issues detected.")


def _run_governance(path: str, result) -> None:
    """Emit CR-EP v2.7.2 session artifacts."""
    from slop_detector.governance.session import AnalysisSession

    project_path = Path(path).resolve()
    if not project_path.is_dir():
        project_path = project_path.parent

    session = AnalysisSession(project_path=project_path)

    if hasattr(result, "file_results"):
        planned = [fa.file_path for fa in result.file_results]
        actual = planned
        total_issues = sum(len(getattr(fa, "pattern_issues", [])) for fa in result.file_results)
        halt_count = sum(
            1
            for fa in result.file_results
            if getattr(fa, "status", "") in {"critical_deficit", "suspicious"}
        )
        for fa in result.file_results:
            session.record_file_analyzed(
                file_path=fa.file_path,
                slop_score=getattr(fa, "deficit_score", 0.0),
                status=str(getattr(fa, "status", "unknown")),
                issues_count=len(getattr(fa, "pattern_issues", [])),
            )
    else:
        planned = [result.file_path]
        actual = planned
        total_issues = len(getattr(result, "pattern_issues", []))
        halt_count = 1 if str(getattr(result, "status", "")) == "critical_deficit" else 0
        session.record_file_analyzed(
            file_path=result.file_path,
            slop_score=getattr(result, "deficit_score", 0.0),
            status=str(getattr(result, "status", "unknown")),
            issues_count=total_issues,
        )

    session.record_enforcement("SD-0", "CONFIRMED", f"Analyzing {len(planned)} files")
    cr_ep_dir = session.finalize(planned, actual, total_issues, halt_count)
    print(f"\n[Governance] CR-EP v2.7.2 artifacts written to: {cr_ep_dir}")
    print("  session.json, why_gate.json, scope_declaration.json")
    print("  enforcement_log.jsonl, change_events.jsonl, review_contract.json")


def _detect_project_type(path: Path) -> str:
    """Infer project type from root directory structure."""
    if (path / "package.json").exists():
        return "javascript"
    if (path / "go.mod").exists():
        return "go"
    return "python"  # pyproject.toml / setup.py / .py files — default


def _inject_gitignore_entry(gitignore_path: Path, entry: str, comment: str) -> None:
    """Append entry to .gitignore if not already present."""
    if gitignore_path.exists():
        text = gitignore_path.read_text(encoding="utf-8")
        if entry in text:
            return
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write(f"\n{comment}\n{entry}\n")
    else:
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write(f"{comment}\n{entry}\n")
    print(f"[+] {entry} added to {gitignore_path}")


def _run_init(args: argparse.Namespace) -> int:
    """Bootstrap .slopconfig.yaml and secure it in .gitignore."""
    from slop_detector.config import generate_slopconfig_template

    config_path = Path(".slopconfig.yaml")
    force = getattr(args, "force_init", False)

    if config_path.exists() and not force:
        print("[!] .slopconfig.yaml already exists. Use --force-init to overwrite.")
        return 1

    project_type = _detect_project_type(Path("."))
    template = generate_slopconfig_template(project_type)
    config_path.write_text(template, encoding="utf-8")
    print(f"[+] .slopconfig.yaml generated (project_type={project_type})")

    _inject_gitignore_entry(
        Path(".gitignore"),
        entry=".slopconfig.yaml",
        comment="# slop-detector: governance config (contains codebase complexity surface — keep private)",
    )

    print()
    print("[>] Next steps:")
    print("    slop-detector --project . --config .slopconfig.yaml")
    print()
    print("[!] Security: .slopconfig.yaml is in .gitignore (maps acceptable-complexity surface).")
    print("    To share governance config with your team, remove it from .gitignore.")
    return 0


def _check_calibration_hint(args) -> None:
    """At every CALIBRATION_MILESTONE scan, auto-run calibration and apply if confident."""
    if getattr(args, "no_history", False):
        return
    try:
        from slop_detector.history import HistoryTracker
        from slop_detector.ml.self_calibrator import CALIBRATION_MILESTONE, SelfCalibrator
        from slop_detector.config import Config

        tracker = HistoryTracker()
        n = tracker.count_total_records()
        if n < CALIBRATION_MILESTONE or n % CALIBRATION_MILESTONE != 0:
            return

        # Auto-calibrate at milestone
        config = Config(config_path=getattr(args, "config", None))
        current_weights = config.get_weights()
        result = SelfCalibrator().calibrate(current_weights=current_weights)
        config_path = getattr(args, "config", None) or ".slopconfig.yaml"

        if result.status == "ok" and Path(config_path).exists():
            written = SelfCalibrator.apply_to_config(result.optimal_weights, config_path=config_path)
            print(f"\n[*] Auto-calibration ({n} records): weights updated -> {written}")
            for k in ("ldr", "inflation", "ddc", "purity"):
                old_v = current_weights.get(k, 0.0)
                new_v = result.optimal_weights.get(k, 0.0)
                if abs(old_v - new_v) > 0.001:
                    print(f"    {k}: {old_v:.2f} -> {new_v:.2f}")
        elif result.status == "no_change":
            print(f"\n[*] Calibration milestone ({n} records): weights already optimal.")
        else:
            print(
                f"\n[*] Calibration milestone ({n} records): {result.message} "
                f"Run --self-calibrate for details."
            )
    except Exception:  # noqa: BLE001 — hint is informational; never block main flow
        pass


def _get_git_context():
    """Capture current git commit (short SHA) and branch. Returns (None, None) if not in a repo."""
    import subprocess
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip() or None
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip() or None
        return commit, branch
    except Exception:
        return None, None


def _record_history(result) -> None:
    """Auto-record analysis result(s) to history DB with git context."""
    try:
        from slop_detector.history import HistoryTracker

        git_commit, git_branch = _get_git_context()
        tracker = HistoryTracker()
        if hasattr(result, "file_results"):
            for fa in result.file_results:
                tracker.record(fa, git_commit=git_commit, git_branch=git_branch)
        else:
            tracker.record(result, git_commit=git_commit, git_branch=git_branch)
    except Exception as exc:  # noqa: BLE001 — history is best-effort; never block main flow
        import logging as _logging

        _logging.getLogger(__name__).debug("history record skipped: %s", exc)


def _show_file_history(file_path: str) -> None:
    """Print trend history for a single file."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    resolved = str(Path(file_path).resolve())
    history = tracker.get_file_history(resolved, limit=20)
    file_path = resolved

    if not history:
        print(f"No history found for: {file_path}")
        print(f"  DB: {tracker.db_path}")
        return

    print(f"History: {file_path}")
    print(f"  DB: {tracker.db_path}")
    print("-" * 70)
    print(f"  {'Timestamp':<24} {'Deficit':>7} {'LDR':>6} {'Patterns':>8}  Grade")
    print("-" * 70)
    for h in history:
        ts = h["timestamp"][:19]
        print(
            f"  {ts:<24} {h['deficit_score']:>7.1f} {h['ldr_score']:>6.3f}"
            f" {h['pattern_count']:>8}  {h['grade']}"
        )

    if len(history) >= 2:
        first = history[-1]["deficit_score"]
        last = history[0]["deficit_score"]
        delta = last - first
        direction = "improved" if delta < 0 else "degraded" if delta > 0 else "stable"
        print("-" * 70)
        print(f"  Trend ({len(history)} runs): {direction}  delta={delta:+.1f}")


def _show_trends() -> None:
    """Print project-wide daily trend table."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    trends = tracker.get_project_trends(days=7)

    if not trends["data_points"]:
        print("No history found.")
        print(f"  DB: {tracker.db_path}")
        return

    print("Project Trends (last 7 days)")
    print(f"  DB: {tracker.db_path}")
    print("-" * 65)
    print(f"  {'Date':<12} {'Avg Deficit':>11} {'Avg LDR':>8} {'Patterns':>9} {'Files':>6}")
    print("-" * 65)
    for d in trends["daily_trends"]:
        print(
            f"  {d['date']:<12} {d['avg_deficit']:>11.1f} {d['avg_ldr']:>8.3f}"
            f" {d['total_patterns']:>9} {d['files_analyzed']:>6}"
        )


def _export_history(output_path: str) -> None:
    """Export history to JSONL."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    count = tracker.export_jsonl(output_path)
    print(f"[+] Exported {count} records to {output_path}")


def _run_self_calibration(args: argparse.Namespace) -> int:
    """Run self-calibration and optionally apply results to .slopconfig.yaml."""
    from slop_detector.config import Config
    from slop_detector.ml.self_calibrator import SelfCalibrator

    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table

        console = Console()
        _rich = True
    except ImportError:
        console = None  # type: ignore[assignment]
        _rich = False

    config = Config(config_path=getattr(args, "config", None))
    current_weights = config.get_weights()
    min_events = getattr(args, "min_history", 5)

    calibrator = SelfCalibrator()
    result = calibrator.calibrate(current_weights=current_weights, min_events=min_events)

    # --- Print summary ---
    if _rich and console:
        from rich.panel import Panel
        from rich.text import Text

        status_color = {"ok": "green", "no_change": "yellow", "insufficient_data": "red"}.get(
            result.status, "white"
        )
        header = Text(f"Self-Calibration — {result.status.upper()}", style=f"bold {status_color}")
        console.print(Panel(header, box=box.ROUNDED))

        t = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        t.add_column("Metric", style="cyan")
        t.add_column("Value", justify="right")
        t.add_row("Unique files in history", str(result.unique_files))
        t.add_row("Improvement events (true positives)", str(result.improvement_events))
        t.add_row("FP candidates (flagged, never fixed)", str(result.fp_candidates))
        t.add_row("Confidence gap", f"{result.confidence_gap:.4f}")
        console.print(t)

        wt = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        wt.add_column("Dimension", style="cyan")
        wt.add_column("Current", justify="right")
        wt.add_column("Optimal", justify="right")
        wt.add_column("Delta", justify="right")
        for dim in ("ldr", "inflation", "ddc", "purity"):
            cur = current_weights.get(dim, 0.0)
            opt = result.optimal_weights.get(dim, cur)
            delta = opt - cur
            delta_str = f"{delta:+.2f}" if abs(delta) > 0.001 else "—"
            color = "green" if delta < -0.001 else ("red" if delta > 0.001 else "white")
            wt.add_row(dim, f"{cur:.2f}", f"{opt:.2f}", f"[{color}]{delta_str}[/{color}]")
        console.print(wt)

        if result.status == "ok":
            err_before = result.fn_rate_before + result.fp_rate_before
            err_after = result.fn_rate_after + result.fp_rate_after
            console.print(
                f"\nCombined error: [yellow]{err_before:.4f}[/yellow] -> [green]{err_after:.4f}[/green]"
                f"  (FN {result.fn_rate_before:.4f}->{result.fn_rate_after:.4f},"
                f"  FP {result.fp_rate_before:.4f}->{result.fp_rate_after:.4f})"
            )

        console.print(f"\n[dim]{result.message}[/dim]")
    else:
        print(f"[Self-Calibration] status={result.status}")
        print(f"  unique_files={result.unique_files}")
        print(f"  improvement_events={result.improvement_events}")
        print(f"  fp_candidates={result.fp_candidates}")
        print(f"  confidence_gap={result.confidence_gap:.4f}")
        print(f"  current_weights={current_weights}")
        print(f"  optimal_weights={result.optimal_weights}")
        print(f"  {result.message}")

    # --- Apply if requested ---
    apply_path = getattr(args, "apply_calibration", None)
    if apply_path and result.status == "ok":
        written = SelfCalibrator.apply_to_config(result.optimal_weights, config_path=apply_path)
        msg = f"[+] Calibrated weights written to {written}"
        if _rich and console:
            console.print(f"\n[green]{msg}[/green]")
        else:
            print(msg)
    elif apply_path and result.status != "ok":
        msg = "[-] --apply-calibration skipped: calibration did not produce a confident result."
        if _rich and console:
            console.print(f"\n[yellow]{msg}[/yellow]")
        else:
            print(msg)

    return 0 if result.status in ("ok", "no_change") else 1


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


if __name__ == "__main__":
    sys.exit(main())
