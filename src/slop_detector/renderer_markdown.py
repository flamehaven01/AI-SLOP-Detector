"""Markdown report generation for the SLOP detector CLI."""

from __future__ import annotations

import ast
from pathlib import Path

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
    ctx = getattr(f_res, "context_jargon", None)
    if not ctx or not hasattr(ctx, "evidence_details"):
        return False
    return any(e.jargon.lower() in _PRODUCTION_CLAIMS_CLI for e in ctx.evidence_details)


def _count_test_functions_ast(file_path: str) -> int:
    try:
        tree = ast.parse(Path(file_path).read_text(encoding="utf-8"))
        return sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
    except (OSError, SyntaxError):
        return 0


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
        fn_count = _count_test_functions_ast(str(f_res.file_path))
        if is_integration:
            stats["integration_test_files"] += 1
            stats["integration_test_functions"] += fn_count
            stats["total_test_functions"] += fn_count
        else:
            stats["unit_test_files"] += 1
            stats["unit_test_functions"] += fn_count
            stats["total_test_functions"] += fn_count
    return stats


def _md_summary_section(avg_deficit: float, avg_inflation: float, status) -> list:
    return [
        "## 1. Executive Summary",
        "| Metric | Score | Status | Description |",
        "| :--- | :--- | :--- | :--- |",
        f"| **Deficit Score** | {avg_deficit:.2f} | {status.value.upper()} | Closer to 0.0 is better. High score indicates low logic density. |",
        f"| **Inflation (Jargon)** | {avg_inflation:.2f} | - | Density of non-functional 'marketing' terms. |",
        "",
    ]


def _md_test_evidence_section(result) -> list:
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
    lines = ["## 3. Detailed Findings"]
    if not file_results:
        return lines + ["_No files analyzed._"]

    for file_path, f_res in file_results:
        if (
            f_res.deficit_score < 30.0
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
    """Generate a detailed developer-focused Markdown report."""
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
