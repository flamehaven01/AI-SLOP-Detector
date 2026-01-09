"""Command-line interface for SLOP detector."""

import argparse
import json
import logging
import sys
from pathlib import Path

from slop_detector import __version__
from slop_detector.core import SlopDetector
from slop_detector.patterns import get_all_patterns


def list_patterns() -> None:
    """List all available patterns."""
    patterns = get_all_patterns()

    print("Available Patterns:")
    print("=" * 80)

    by_category = {
        "Structural Issues": [],
        "Placeholder Code": [],
        "Cross-Language Patterns": [],
    }

    for pattern in patterns:
        if "structural" in pattern.__class__.__module__:
            by_category["Structural Issues"].append(pattern)
        elif "placeholder" in pattern.__class__.__module__:
            by_category["Placeholder Code"].append(pattern)
        elif "cross_language" in pattern.__class__.__module__:
            by_category["Cross-Language Patterns"].append(pattern)

    for category, category_patterns in by_category.items():
        if category_patterns:
            print(f"\n{category}:")
            print("-" * 80)
            for pattern in category_patterns:
                print(f"  {pattern.id:30s} [{pattern.severity.value:8s}] {pattern.message}")

    print("\n" + "=" * 80)
    print(f"Total: {len(patterns)} patterns")
    print("\nUsage: slop-detector --disable <pattern_id> ...")


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(levelname)s] %(message)s", stream=sys.stderr)

    return 0


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


def print_rich_report(result) -> None:
    """Print report using Rich."""
    console = Console()

    # Title
    console.print()
    console.print(
        Panel.fit(Text("AI CODE QUALITY REPORT", style="bold cyan"), style="blue", box=box.DOUBLE)
    )
    console.print()

    if hasattr(result, "project_path"):
        # Project Summary Table
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

        status_color = "red" if result.overall_status != "clean" else "green"
        summary_table.add_row(
            "Overall Status", f"[{status_color}]{result.overall_status.upper()}[/{status_color}]"
        )

        console.print(summary_table)
        console.print()

        # Metrics Table
        metrics_table = Table(title="Average Metrics", box=box.SIMPLE)
        metrics_table.add_column("Metric")
        metrics_table.add_column("Score")

        metrics_table.add_row("Deficit Score", f"{result.avg_deficit_score:.1f}/100")
        metrics_table.add_row("Weighted Score", f"{result.weighted_deficit_score:.1f}/100")
        metrics_table.add_row("LDR (Logic)", f"{result.avg_ldr:.2%}")
        metrics_table.add_row("ICR (Inflation)", f"{result.avg_inflation:.2f}")
        metrics_table.add_row("DDC (Deps)", f"{result.avg_ddc:.2%}")

        console.print(metrics_table)
        console.print()

        # Files Table
        files_table = Table(title="File Analysis", box=box.MINIMAL_DOUBLE_HEAD)
        files_table.add_column("File", style="bold")
        files_table.add_column("Status")
        files_table.add_column("Score", justify="right")
        files_table.add_column("LDR", justify="right")
        files_table.add_column("ICR", justify="right")
        files_table.add_column("DDC", justify="right")
        files_table.add_column("Notes")

        for file_result in result.file_results:
            if file_result.status == "clean":
                continue

            status_style = "red" if file_result.status == "critical" else "yellow"

            # Notes (Warnings + Jargon)
            notes = []
            if file_result.warnings:
                notes.append(f"{len(file_result.warnings)} Warnings")

            jargon_count = sum(
                1 for d in file_result.inflation.jargon_details if not d.get("justified")
            )
            if jargon_count > 0:
                notes.append(f"{jargon_count} Jargon Terms")

            files_table.add_row(
                Path(file_result.file_path).name,
                f"[{status_style}]{file_result.status.upper()}[/{status_style}]",
                f"{file_result.deficit_score:.1f}",
                f"{file_result.ldr.ldr_score:.0%}",
                f"{file_result.inflation.inflation_score:.2f}",
                f"{file_result.ddc.usage_ratio:.0%}",
                ", ".join(notes),
            )

            # Detailed Jargon row (if relevant)
            if jargon_count > 0:
                jargon_text = ", ".join(
                    [
                        f"{d['word']}(L{d['line']})"
                        for d in file_result.inflation.jargon_details
                        if not d.get("justified")
                    ]
                )
                files_table.add_row("", "", "", "", "", "", f"[dim]Jargon: {jargon_text}[/dim]")

        if result.deficit_files > 0:
            console.print(files_table)
        else:
            console.print(Panel("No deficit detected in project files.", style="green"))

    else:
        # Single File (Simple Panel)
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

        # Jargon
        jargon = [d for d in result.inflation.jargon_details if not d.get("justified")]
        if jargon:
            content.append("\nJargon Detected:\n", style="bold red")
            for d in jargon:
                content.append(f"- Line {d['line']}: {d['word']}\n")

        console.print(Panel(content, title="Single File Analysis", border_style=color))


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


def generate_markdown_report(result) -> str:
    """Generates a detailed developer-focused Markdown report."""

    # Handle both ProjectAnalysis and single FileAnalysis
    is_project = hasattr(result, "project_path")
    root_dir = result.project_path if is_project else str(Path(result.file_path).parent)
    status = result.overall_status if is_project else result.status
    avg_deficit = result.avg_deficit_score if is_project else result.deficit_score
    avg_inflation = result.avg_inflation if is_project else result.inflation.inflation_score
    timestamp = getattr(result, "timestamp", None)

    lines = []
    lines.append("# AI Code Quality Audit Report")
    if timestamp:
        lines.append(f"**Date**: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Target**: `{root_dir}`")
    lines.append(f"**Status**: {status.value.upper()}")
    lines.append("")

    # 1. Executive Summary
    lines.append("## 1. Executive Summary")
    lines.append("| Metric | Score | Status | Description |")
    lines.append("| :--- | :--- | :--- | :--- |")
    lines.append(
        f"| **Deficit Score** | {avg_deficit:.2f} | {status.value.upper()} | Closer to 0.0 is better. High score indicates low logic density. |"
    )
    lines.append(
        f"| **Inflation (Jargon)** | {avg_inflation:.2f} | - | Density of non-functional 'marketing' terms. |"
    )
    lines.append("")

    # 2. Detailed Findings
    lines.append("## 2. Detailed Findings")

    file_results = []
    if is_project:
        if hasattr(result, "files") and result.files:
            # If result.files is a dict (path -> FileAnalysis)
            file_results = result.files.items()
        elif hasattr(result, "file_results"):
            # If result.file_results is a list [FileAnalysis]
            file_results = [(r.file_path, r) for r in result.file_results]
    else:
        file_results = [(result.file_path, result)]

    if not file_results:
        lines.append("_No files analyzed._")

    for file_path, f_res in file_results:
        # Only report files with issues
        if (
            f_res.deficit_score < 0.3
            and not f_res.pattern_issues
            and not f_res.inflation.jargon_details
        ):
            continue

        lines.append(f"### 📄 `{Path(str(file_path)).name}`")
        lines.append(f"- **Deficit Score**: {f_res.deficit_score:.2f}")
        lines.append(f"- **Lines of Code**: {f_res.ldr.total_lines}")

        # Inflation / Jargon
        jargon_issues = [d for d in f_res.inflation.jargon_details if not d.get("justified")]
        if jargon_issues:
            lines.append("#### 🔴 Inflation (Jargon) Detected")
            lines.append("| Line | Term | Category | Actionable Mitigation |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for det in jargon_issues:
                mitigation = get_mitigation("jargon")
                lines.append(
                    f"| {det['line']} | `{det['word']}` | {det['category']} | {mitigation} |"
                )
            lines.append("")

        # Patterns (Static Analysis)
        if hasattr(f_res, "pattern_issues") and f_res.pattern_issues:
            lines.append("#### ⚠️ Anti-Patterns & Risk")
            lines.append("| Line | Issue | Mitigation Strategy |")
            lines.append("| :--- | :--- | :--- |")
            for p in f_res.pattern_issues:
                # Handle both object and string representation (just in case)
                if hasattr(p, "message"):
                    desc = p.message
                    line_val = p.line
                else:
                    desc = str(p)
                    line_val = "-"

                issue_key = "unknown"
                desc_lower = desc.lower()
                if "mutable default" in desc_lower:
                    issue_key = "mutable_default"
                elif "bare except" in desc_lower:
                    issue_key = "bare_except"
                elif "broad exception" in desc_lower:
                    issue_key = "broad_except"
                elif "empty function" in desc_lower:
                    issue_key = "empty_function"
                elif "unused import" in desc_lower:
                    issue_key = "unused_import"

                mitigation = get_mitigation(issue_key, desc)
                lines.append(f"| {line_val} | {desc} | {mitigation} |")
            lines.append("")

        lines.append("---")

    # 3. Recommendations
    lines.append("## 3. Global Recommendations")
    lines.append(
        "- **Refactor High-Deficit Modules**: Files with scores > 0.5 lack sufficient logic. Verify they aren't just empty wrappers."
    )
    lines.append(
        "- **Purify Terminology**: Replace abstract 'hype' terms with concrete engineering definitions."
    )
    lines.append(
        "- **Harden Error Handling**: Eliminate bare except clauses to ensure system stability and debuggability."
    )

    return "\n".join(lines)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="AI SLOP Detector - Production-ready code quality analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  slop-detector file.py                    # Analyze single file
  slop-detector --project src/             # Analyze project
  slop-detector --project . --json         # JSON output
  slop-detector --project . -o report.html # HTML report
  slop-detector --version                  # Show version
        """,
    )

    parser.add_argument("path", help="Path to Python file or project directory")
    parser.add_argument("--project", action="store_true", help="Analyze entire project")
    parser.add_argument("--output", "-o", help="Output file (txt, json, or html)")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("--config", "-c", help="Path to .slopconfig.yaml configuration file")
    parser.add_argument(
        "--disable",
        "-d",
        action="append",
        default=[],
        metavar="PATTERN_ID",
        help="Disable specific pattern by ID (can be repeated)",
    )

    parser.add_argument(
        "--patterns-only",
        action="store_true",
        help="Only run pattern detection (skip metrics)",
    )

    parser.add_argument(
        "--list-patterns",
        action="store_true",
        help="List all available patterns and exit",
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

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Auto-detect project mode for directories
    if Path(args.path).is_dir() and not args.project:
        args.project = True
        logging.info("Directory detected, enabling --project mode")

    # v2.1: List patterns if requested
    if args.list_patterns:
        list_patterns()
        return 0

    # Initialize detector
    try:
        detector = SlopDetector(config_path=args.config)
    except Exception as e:
        print(f"[!] Failed to initialize detector: {e}", file=sys.stderr)
        return 1

    # Analyze
    try:
        if args.project:
            result = detector.analyze_project(args.path)
            score = result.weighted_deficit_score
        else:
            result = detector.analyze_file(args.path)
            score = result.deficit_score
    except Exception as e:
        print(f"[!] Analysis failed: {e}", file=sys.stderr)
        return 1

    # Output
    if args.json:
        output = json.dumps(result.to_dict(), indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
        else:
            print(output)
    elif args.output and str(args.output).endswith(".html"):
        # HTML report
        html = generate_html_report(result)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[+] HTML report saved to {args.output}")
    elif args.output and str(args.output).endswith(".md"):
        # Markdown report
        md_report = generate_markdown_report(result)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md_report)
        print(f"[+] Markdown report saved to {args.output}")
    else:
        # Console / Text Report
        if args.output:
            # If writing to file (and not json/html/md), use plain text or markdown?
            # Let's default to markdown if extension unknown, or just text.
            # For now, text fallback.
            report = generate_text_report(result)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
        else:
            # If printing to stdout, check Rich availability
            if RICH_AVAILABLE and not args.no_color:
                print_rich_report(result)
            else:
                print(generate_text_report(result))

    # Check threshold
    if args.fail_threshold is not None:
        if score > args.fail_threshold:
            print(
                f"\n[!] FAIL: Deficit score {score:.1f} exceeds threshold {args.fail_threshold}",
                file=sys.stderr,
            )
            return 1

    return 0


def generate_text_report(result) -> str:
    """Generate text report."""
    lines = []
    lines.append("=" * 80)
    lines.append("AI CODE QUALITY REPORT")
    lines.append("=" * 80)
    lines.append("")

    if hasattr(result, "project_path"):
        # Project analysis
        lines.append(f"Project: {result.project_path}")
        lines.append(f"Total Files: {result.total_files}")
        lines.append(f"Clean Files: {result.clean_files}")
        lines.append(f"Deficit Files: {result.deficit_files}")
        lines.append(f"Overall Status: {result.overall_status.upper()}")
        lines.append("")
        lines.append("Average Metrics:")
        lines.append(f"  Deficit Score: {result.avg_deficit_score:.1f}/100")
        lines.append(f"  Weighted Deficit Score: {result.weighted_deficit_score:.1f}/100")
        lines.append(f"  Logic Density (LDR): {result.avg_ldr:.2%}")
        lines.append(f"  Inflation Ratio (ICR): {result.avg_inflation:.2f}")
        lines.append(f"  Dependency Usage (DDC): {result.avg_ddc:.2%}")
        lines.append("")

        # File details
        lines.append("=" * 80)
        lines.append("FILE-LEVEL ANALYSIS")
        lines.append("=" * 80)
        lines.append("")

        for file_result in result.file_results:
            if file_result.status != "clean":
                lines.append(f"[!] {Path(file_result.file_path).name}")
                lines.append(f"    Status: {file_result.status.upper()}")
                lines.append(f"    Deficit Score: {file_result.deficit_score:.1f}/100")
                lines.append(f"    LDR: {file_result.ldr.ldr_score:.2%} ({file_result.ldr.grade})")
                lines.append(
                    f"    ICR: {file_result.inflation.inflation_score:.2f} ({file_result.inflation.status})"
                )

                # Show jargon locations
                if file_result.inflation.jargon_details:
                    lines.append("    Jargon Locations:")
                    for detail in file_result.inflation.jargon_details:
                        if not detail.get("justified"):
                            lines.append(f"      - Line {detail['line']}: \"{detail['word']}\"")

                lines.append(
                    f"    DDC: {file_result.ddc.usage_ratio:.2%} ({file_result.ddc.grade})"
                )
                if file_result.warnings:
                    lines.append("    Warnings:")
                    for warning in file_result.warnings:
                        lines.append(f"      - {warning}")
                lines.append("")
    else:
        # Single file analysis
        lines.append(f"File: {result.file_path}")
        lines.append(f"Status: {result.status.upper()}")
        lines.append(f"Deficit Score: {result.deficit_score:.1f}/100")
        lines.append("")
        lines.append(f"LDR: {result.ldr.ldr_score:.2%} ({result.ldr.grade})")
        lines.append(f"ICR: {result.inflation.inflation_score:.2f} ({result.inflation.status})")
        lines.append(f"DDC: {result.ddc.usage_ratio:.2%} ({result.ddc.grade})")

        if result.warnings:
            lines.append("")
            lines.append("Warnings:")
            for warning in result.warnings:
                lines.append(f"  - {warning}")

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
