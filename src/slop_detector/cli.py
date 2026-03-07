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
        if "structural" in pattern.__class__.__module__:
            by_category["Structural Issues"].append(pattern)
        elif "placeholder" in pattern.__class__.__module__:
            by_category["Placeholder Code"].append(pattern)
        elif "cross_language" in pattern.__class__.__module__:
            by_category["Cross-Language Patterns"].append(pattern)
        elif "python_advanced" in pattern.__class__.__module__:
            by_category["Python Advanced"].append(pattern)

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

        # Docstring Inflation (v2.2)
        if result.docstring_inflation and result.docstring_inflation.details:
            doc_inflation = result.docstring_inflation
            content.append("\nDocstring Inflation:\n", style="bold yellow")
            content.append(
                f"Overall: {doc_inflation.total_docstring_lines} doc lines / "
                f"{doc_inflation.total_implementation_lines} impl lines "
                f"(ratio: {doc_inflation.overall_ratio:.2f})\n"
            )
            if doc_inflation.inflated_count > 0:
                content.append(f"{doc_inflation.inflated_count} inflated functions/classes:\n")
                for detail in doc_inflation.details[:3]:  # Show top 3
                    content.append(
                        f"- Line {detail.line}: {detail.name} "
                        f"({detail.docstring_lines}doc/{detail.implementation_lines}impl = {detail.inflation_ratio:.1f}x)\n"
                    )

        # Pattern Issues (v2.8.0)
        if getattr(result, "pattern_issues", None):
            sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_issues = sorted(
                result.pattern_issues,
                key=lambda p: sev_order.get(
                    getattr(getattr(p, "severity", None), "value", "low"), 3
                ),
            )
            content.append("\nPattern Issues:\n", style="bold red")
            for p in sorted_issues[:10]:
                sev = getattr(getattr(p, "severity", None), "value", "low")
                line = getattr(p, "line", "-")
                msg = getattr(p, "message", str(p))
                sev_style = (
                    "bold red" if sev == "critical" else "yellow" if sev == "high" else "dim"
                )
                content.append(f"  L{line} [{sev.upper()}] {msg}\n", style=sev_style)
            if len(result.pattern_issues) > 10:
                content.append(f"  ... and {len(result.pattern_issues) - 10} more\n", style="dim")
            # Advanced pattern summary
            god_fn = sum(
                1 for p in result.pattern_issues if getattr(p, "pattern_id", "") == "god_function"
            )
            dead = sum(
                1 for p in result.pattern_issues if getattr(p, "pattern_id", "") == "dead_code"
            )
            nesting = sum(
                1 for p in result.pattern_issues if getattr(p, "pattern_id", "") == "deep_nesting"
            )
            adv_parts = []
            if god_fn:
                adv_parts.append(f"{god_fn} god-fn")
            if dead:
                adv_parts.append(f"{dead} dead-code")
            if nesting:
                adv_parts.append(f"{nesting} deep-nest")
            if adv_parts:
                content.append(f"  Advanced: {', '.join(adv_parts)}\n", style="dim cyan")

        # ML Score (v2.8.0)
        ml = getattr(result, "ml_score", None)
        if ml is not None:
            ml_color = (
                "red"
                if ml.slop_probability >= 0.70
                else "yellow" if ml.slop_probability >= 0.40 else "green"
            )
            content.append("\nML Score:\n", style="bold cyan")
            content.append(
                f"  Slop Probability: {ml.slop_probability:.1%} [{ml.label.upper()}]\n",
                style=ml_color,
            )
            agreement_str = "yes" if ml.agreement else "no"
            content.append(
                f"  Confidence: {ml.confidence:.1%}  "
                f"Model: {ml.model_type}  "
                f"Agreement: {agreement_str}\n",
                style="dim",
            )

        console.print(Panel(content, title="Single File Analysis", border_style=color))

        # Generate review questions
        question_gen = QuestionGenerator()
        questions = question_gen.generate_questions(result)

        if questions:
            console.print()
            console.print(Panel.fit(Text("REVIEW QUESTIONS", style="bold yellow"), style="yellow"))

            critical = [q for q in questions if q.severity == "critical"]
            warnings = [q for q in questions if q.severity == "warning"]
            info = [q for q in questions if q.severity == "info"]

            if critical:
                console.print("\n[bold red]CRITICAL QUESTIONS:[/bold red]")
                for i, q in enumerate(critical, 1):
                    loc = f" [dim](Line {q.line})[/dim]" if q.line else ""
                    console.print(f"{i}.{loc} {q.question}")

            if warnings:
                console.print("\n[bold yellow]WARNING QUESTIONS:[/bold yellow]")
                for i, q in enumerate(warnings, 1):
                    loc = f" [dim](Line {q.line})[/dim]" if q.line else ""
                    console.print(f"{i}.{loc} {q.question}")

            if info:
                console.print("\n[bold cyan]INFO QUESTIONS:[/bold cyan]")
                for i, q in enumerate(info, 1):
                    loc = f" [dim](Line {q.line})[/dim]" if q.line else ""
                    console.print(f"{i}.{loc} {q.question}")

            console.print()


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

    production_claims = {
        "production-ready",
        "production ready",
        "enterprise-grade",
        "enterprise grade",
        "scalable",
        "fault-tolerant",
        "fault tolerant",
    }

    for f_res in file_results:
        # Check if file has context jargon analysis
        if hasattr(f_res, "context_jargon") and hasattr(f_res.context_jargon, "evidence_details"):
            for evidence in f_res.context_jargon.evidence_details:
                if evidence.jargon.lower() in production_claims:
                    stats["has_production_claims"] = True

        # Check if file is a test file (by path)
        file_path = str(f_res.file_path).lower()
        is_test_file = (
            "test_" in file_path
            or "_test.py" in file_path
            or "/tests/" in file_path
            or "\\tests\\" in file_path
        )

        if is_test_file:
            # Count as test file
            stats["total_test_files"] += 1

            # Determine if unit or integration test
            is_integration = any(
                part in file_path
                for part in [
                    "integration",
                    "e2e",
                    "/it/",
                    "\\it\\",
                    "integration_tests",
                    "test_integration",
                    "integration_test",
                ]
            )

            if is_integration:
                stats["integration_test_files"] += 1
                # Rough estimate: assume 5 test functions per integration test file
                stats["integration_test_functions"] += 5
            else:
                stats["unit_test_files"] += 1
                # Rough estimate: assume 10 test functions per unit test file
                stats["unit_test_functions"] += 10

            stats["total_test_functions"] += 10 if not is_integration else 5

    return stats


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

    # 2. Test Evidence Summary (for projects only)
    if is_project and hasattr(result, "file_results"):
        test_evidence = _collect_test_evidence_stats(result.file_results)
        if test_evidence["total_test_files"] > 0:
            lines.append("## 2. Test Evidence Summary")
            lines.append("| Test Type | Files | Functions | Coverage Notes |")
            lines.append("| :--- | :--- | :--- | :--- |")
            lines.append(
                f"| **Unit Tests** | {test_evidence['unit_test_files']} | {test_evidence['unit_test_functions']} | Fast, isolated tests |"
            )
            lines.append(
                f"| **Integration Tests** | {test_evidence['integration_test_files']} | {test_evidence['integration_test_functions']} | Tests hitting real dependencies |"
            )
            lines.append(
                f"| **Total** | {test_evidence['total_test_files']} | {test_evidence['total_test_functions']} | - |"
            )

            # Warning if no integration tests but production claims exist
            if test_evidence["integration_test_files"] == 0 and test_evidence.get(
                "has_production_claims", False
            ):
                lines.append("")
                lines.append(
                    "[!] **Warning**: No integration tests detected, but codebase contains production-ready/enterprise-grade/scalable claims."
                )

            lines.append("")

    # 3. Detailed Findings
    lines.append("## 3. Detailed Findings")

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

        lines.append(f"### [L] `{Path(str(file_path)).name}`")
        lines.append(f"- **Deficit Score**: {f_res.deficit_score:.2f}")
        lines.append(f"- **Lines of Code**: {f_res.ldr.total_lines}")

        # Empty file handling - add table to avoid confusion
        if f_res.ldr.total_lines == 0:
            lines.append("#### [!] Anti-Patterns & Risk")
            lines.append("| Line | Issue | Mitigation Strategy |")
            lines.append("| :--- | :--- | :--- |")
            lines.append(
                "| — | Empty file (0 LOC): nothing to analyze | Remove the file if unused, or add implementation / mark as intentional stub |"
            )
            lines.append("")
            lines.append("---")
            continue  # Skip jargon/pattern checks for empty files

        # Inflation / Jargon
        jargon_issues = [d for d in f_res.inflation.jargon_details if not d.get("justified")]
        if jargon_issues:
            lines.append("#### [-] Inflation (Jargon) Detected")
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
            lines.append("#### [!] Anti-Patterns & Risk")
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

    # 4. Recommendations
    lines.append("## 4. Global Recommendations")
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
        description="AI SLOP Detector v4.0 - Sovereign Gate Edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  slop-detector file.py                    # Analyze single file
  slop-detector --project src/             # Analyze project
  slop-detector --project . --json         # JSON output
  slop-detector --project . -o report.html # HTML report
  slop-detector file.py --fix --dry-run    # Preview auto-fixes
  slop-detector file.py --fix              # Apply auto-fixes
  slop-detector file.py --gate             # Show SNP gate decision
  slop-detector src/ --js                  # Analyze JS/TS files
  slop-detector src/ --cross-file          # Cross-file analysis
  slop-detector src/ --governance          # Emit CR-EP session artifacts
  slop-detector --version                  # Show version
        """,
    )

    parser.add_argument("path", help="Path to Python file or project directory")
    parser.add_argument("--project", action="store_true", help="Analyze entire project")
    parser.add_argument("--output", "-o", help="Output file (txt, json, or html)")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("--config", "-c", help="Path to .slopconfig.yaml configuration file")

    # v4.0: Auto-Fix
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

    # v4.0: SNP Gate
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Show SNP-compatible gate decision (PASS/HALT) with sr9/di2/jsd/ove metrics",
    )

    # v4.0: JS/TS Analysis
    parser.add_argument(
        "--js",
        action="store_true",
        help="Analyze JavaScript/TypeScript files in addition to Python",
    )

    # v4.0: Cross-File Analysis
    parser.add_argument(
        "--cross-file",
        action="store_true",
        help="Run cross-file analysis (cycles, duplicates, hotspots)",
    )

    # v4.0: CR-EP Governance
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
        from typing import Union

        result: Union[ProjectAnalysis, FileAnalysis]
        if args.project:
            result = detector.analyze_project(args.path)
            score = result.weighted_deficit_score
        else:
            result = detector.analyze_file(args.path)
            score = result.deficit_score
    except Exception as e:
        print(f"[!] Analysis failed: {e}", file=sys.stderr)
        return 1

    # CI Gate evaluation (v2.2)
    claims_strict = getattr(args, "ci_claims_strict", False)
    if args.ci_mode or args.ci_report or claims_strict:
        from slop_detector.ci_gate import CIGate, GateMode

        gate_mode = GateMode(args.ci_mode) if args.ci_mode else GateMode.SOFT
        ci_gate = CIGate(mode=gate_mode, claims_strict=claims_strict)
        gate_result = ci_gate.evaluate(result)

        if args.ci_report:
            # Output CI gate report and exit
            if args.json:
                print(json.dumps(gate_result.to_dict(), indent=2))
            else:
                print(gate_result.pr_comment or gate_result.message)

            # Exit with appropriate code
            return 1 if gate_result.should_fail_build else 0

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

    # v4.0: SNP Gate Decision
    if getattr(args, "gate", False):
        _run_gate(result)

    # v4.0: Auto-Fix
    if getattr(args, "fix", False):
        dry_run = getattr(args, "dry_run", True)
        _run_autofix(result, dry_run=dry_run)

    # v4.0: JS/TS Analysis
    if getattr(args, "js", False):
        _run_js_analysis(args.path)

    # v4.0: Cross-File Analysis
    if getattr(args, "cross_file", False) and hasattr(result, "project_path"):
        _run_cross_file(result)

    # v4.0: CR-EP Governance
    if getattr(args, "governance", False):
        _run_governance(args.path, result)

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

        # Test evidence summary
        if hasattr(result, "file_results"):
            test_evidence = _collect_test_evidence_stats(result.file_results)
            if test_evidence["total_test_files"] > 0:
                lines.append("Test Evidence:")
                lines.append(
                    f"  Unit Tests: {test_evidence['unit_test_files']} files, {test_evidence['unit_test_functions']} functions"
                )
                lines.append(
                    f"  Integration Tests: {test_evidence['integration_test_files']} files, {test_evidence['integration_test_functions']} functions"
                )
                lines.append(f"  Total: {test_evidence['total_test_files']} test files")

                if test_evidence["integration_test_files"] == 0 and test_evidence.get(
                    "has_production_claims", False
                ):
                    lines.append("  [!] WARNING: No integration tests, but has production claims")

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
