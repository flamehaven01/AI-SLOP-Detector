"""Markdown report generation for the SLOP detector CLI."""

from __future__ import annotations

import ast
from pathlib import Path

from slop_detector import __version__
from slop_detector.ast_index import walk_nodes
from slop_detector.core_project import score_is_valid
from slop_detector.finding_summary import get_finding_summary
from slop_detector.metrics.context_jargon import PRODUCTION_CLAIMS
from slop_detector.path_facts import facts_for
from slop_detector.renderer_glossary import (
    DEFICIT_BANDS,
    capability_notes,
    coherence_display,
    file_metric_rows,
    incomplete_notes,
    next_steps,
    project_metric_rows,
    status_label,
)

# Health icons emitted into Markdown output, written as ASCII source escapes
# (CLAUDE.md: Python source stays ASCII for cp949 safety).
_MD_HEALTH_ICON = {"good": "\u2705", "warn": "\u26a0\ufe0f", "bad": "\U0001f6a8"}

_PRODUCTION_CLAIMS_CLI: frozenset = PRODUCTION_CLAIMS


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
            for node in walk_nodes(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        )
    except (OSError, SyntaxError):
        return 0


def _collect_test_evidence_stats(file_results, project_root=None) -> dict:
    """Collect test evidence statistics from file results.

    Test identity and kind are root-relative path facts (slop_detector.path_facts),
    relative to `project_root` (without it, each file's single-file root).
    """
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
        facts = facts_for(f_res.file_path, project_root)
        if not facts.is_test:
            continue
        stats["total_test_files"] += 1
        is_integration = facts.test_kind in ("integration", "e2e")
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


def _md_summary_section(score_label: str, score: str, inflation: str, status: str) -> list:
    # The status sits next to the score it was derived from (a project's status is
    # the band of its weighted deficit; the average is in Project Metrics).
    return [
        "## Executive Summary",
        "| Metric | Score | Status | Description |",
        "| :--- | :--- | :--- | :--- |",
        f"| **{score_label}** | {score} | {status} | Closer to 0.0 is better. High score indicates low logic density. |",
        f"| **Inflation (Jargon)** | {inflation} | - | Density of non-functional 'marketing' terms. |",
        "",
    ]


def _md_project_metrics_section(result) -> list:
    """Friendly project metrics table: value, healthy direction, plain meaning."""
    # Emoji emitted into the Markdown output, written as ASCII source escapes
    # (CLAUDE.md: Python source stays ASCII for cp949 safety).
    health_icon = _MD_HEALTH_ICON
    lines = [
        "## Project Metrics",
        "| Metric | Value | Healthy Direction | What It Means |",
        "| :--- | ---: | :---: | :--- |",
    ]
    for r in project_metric_rows(result):
        icon = health_icon.get(r["health"], "")
        lines.append(f"| {r['label']} | {icon} {r['value']} | {r['direction']} | {r['means']} |")
    lines += ["", f"_Deficit bands: {DEFICIT_BANDS}_", ""]
    return lines


def _md_finding_summary_section(result) -> list:
    """Render aggregate findings even when no file crosses the score threshold."""
    summary = get_finding_summary(result)
    severity = summary["severity"]
    return [
        "## Finding Summary",
        "| Total | Affected Files | Critical | High | Medium | Low |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {summary['total']} | {summary['affected_files']} | "
            f"{severity['critical']} | {severity['high']} | "
            f"{severity['medium']} | {severity['low']} |"
        ),
        "",
        "_Finding totals are evidence independent of the weighted deficit status._",
        "",
    ]


def _md_scan_coverage_section(result) -> list:
    coverage = getattr(result, "scan_coverage", {})
    if not coverage:
        return []
    analyzed = coverage["analyzed"]
    excluded = coverage["excluded"]
    unsupported = coverage.get("unsupported", {})
    return [
        "## Scan Coverage",
        "| Analyzed | Python | JS/TS | Go | Excluded Supported Source Files | Unsupported Source Files |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| {analyzed['total']} | {analyzed['python']} | "
            f"{analyzed['javascript']} | {analyzed['go']} | {excluded['total']} | "
            f"{unsupported.get('total', 0)} |"
        ),
        "",
        (
            f"Excluded test files: {excluded.get('tests', 0)}; "
            f"excluded by custom ignore rules: {excluded.get('by_source', {}).get('custom', 0)}"
        ),
        "",
        *[f"- Analysis capability: {note}" for note in capability_notes(coverage)],
        *[f"- **Incomplete scan:** {note}" for note in incomplete_notes(coverage)],
        "",
        "_JSON output includes each excluded path and its matching ignore rule._",
        "",
    ]


def _md_ml_scoring_section(result) -> list:
    ml_scoring = getattr(result, "ml_scoring", {})
    if not ml_scoring:
        return []
    lines = ["## ML Scoring Capability", f"- **Status:** `{ml_scoring['status']}`"]
    if ml_scoring.get("reason"):
        lines.append(f"- **Reason:** {ml_scoring['reason']}")
    lines += [
        "- ML scoring is an optional secondary signal; core scoring remains deterministic.",
        "",
    ]
    return lines


def _md_file_metrics_section(fr) -> list:
    """Friendly per-file metrics table (single-file reports)."""
    lines = [
        "## File Metrics",
        "| Metric | Value | Healthy Direction | What It Means |",
        "| :--- | ---: | :---: | :--- |",
    ]
    for r in file_metric_rows(fr):
        icon = _MD_HEALTH_ICON.get(r["health"], "")
        lines.append(f"| {r['label']} | {icon} {r['value']} | {r['direction']} | {r['means']} |")
    lines += ["", f"_Deficit bands: {DEFICIT_BANDS}_", ""]
    return lines


def _md_next_steps_section(result) -> list:
    """Deterministic 'what to do now' guidance derived from the metrics."""
    steps = next_steps(result)
    if not steps:
        return []
    lines = ["## Next Steps"]
    for idx, step in enumerate(steps, 1):
        lines.append(f"{idx}. {step}")
    lines.append("")
    return lines


def _md_structural_coherence_section(result) -> list:
    coh = coherence_display(result)
    if not coh:
        return []
    return [
        "## Structural Coherence",
        "| Metric | Value |",
        "| :--- | :--- |",
        f"| Structure coherence | {coh['value']} ({coh['direction']} is more cohesive) |",
        f"| Checked | {coh['coverage']} |",
        f"| What it means | {coh['means']} |",
        "",
    ]


def _md_suppression_section(result) -> list:
    suppression_ledger = getattr(result, "suppression_ledger", [])
    if not suppression_ledger:
        return []
    lines = [
        "## Inline Suppression Ledger",
        "| File | Suppressed Line | Pattern | Directive Line | Scope |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for entry in suppression_ledger[:20]:
        lines.append(
            f"| `{Path(entry.file_path).name}` | {entry.suppressed_line} | "
            f"`{entry.pattern_id}` | {entry.directive_line} | {entry.scope} |"
        )
    if len(suppression_ledger) >= 10:
        lines += [
            "",
            "[!] **Warning**: high inline suppression usage detected. Review whether suppressed patterns should be fixed instead of muted.",
        ]
    lines.append("")
    return lines


def _md_test_evidence_section(result) -> list:
    if not hasattr(result, "file_results"):
        return []
    test_evidence = _collect_test_evidence_stats(
        result.file_results, getattr(result, "project_path", None)
    )
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


def _md_priority_hotspots_section(result) -> list:
    hotspots = getattr(result, "priority_hotspots", [])
    if not hotspots:
        return []
    lines = [
        "## Priority Hotspots",
        "",
        f"- Churn data available: `{getattr(result, 'churn_analysis_available', False)}`",
        f"- Coverage data available: `{getattr(result, 'coverage_analysis_available', False)}`",
        "",
        "| File | Priority | Deficit | Churn | Coverage | Reasons |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for hotspot in hotspots[:10]:
        coverage = "n/a" if hotspot.coverage_ratio is None else f"{hotspot.coverage_ratio:.0%}"
        lines.append(
            f"| `{Path(hotspot.file_path).name}` | {hotspot.priority_score:.1f}/100 | "
            f"{hotspot.deficit_score:.1f} | {hotspot.churn_count} | {coverage} | "
            f"{', '.join(hotspot.reasons)} |"
        )
    lines.append("")
    return lines


def _md_cell(text: object) -> str:
    """One Markdown table cell: a pipe or a line break in repository text
    cannot open another cell or row."""
    return str(text).replace("|", chr(92) + "|").replace("\r", " ").replace("\n", " ")


def _md_findings_section(result, root_dir: str, file_results) -> list:
    """The findings of the report view, the one behind the HTML report too:
    every language, each with its own fix; then the files, then unjustified
    jargon per file (docs/REPORTS.md)."""
    from slop_detector.report_view import build_report_view, short_path

    view = build_report_view(result)
    lines = [f"## Findings ({len(view.findings)})", ""]
    if view.findings:
        lines += ["| Severity | Location | Rule | Finding | Fix |", "|---|---|---|---|---|"]
        for item in view.findings:
            lines.append(
                f"| {item.severity.upper()} | `{_md_cell(short_path(item.file, root_dir))}:"
                f"{item.line}` | `{item.rule}` | {_md_cell(item.message)} | "
                f"{_md_cell(item.suggestion) if item.suggestion else '-'} |"
            )
    else:
        lines.append("_No pattern findings._")
    lines.append("")

    if view.file_rows:
        lines += ["### Files", "", "| File | Score | Status | Findings |", "|---|---:|---|---:|"]
        for path, score, state, count in sorted(view.file_rows, key=lambda r: -(r[1] or 0)):
            shown = "N/A" if score is None else f"{score:.1f}"
            lines.append(
                f"| `{_md_cell(short_path(path, root_dir))}` | {shown} | "
                f"{state.replace('_', ' ')} | {count} |"
            )
        lines.append("")

    for file_path, f_res in file_results:
        jargon = [d for d in f_res.inflation.jargon_details if not d.get("justified")]
        if not jargon:
            continue
        lines += [
            f"### Jargon in `{_md_cell(short_path(str(file_path), root_dir))}`",
            "",
            "| Line | Term | Category | Fix |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for det in jargon:
            lines.append(
                f"| {det['line']} | `{det['word']}` | {det['category']} | {get_mitigation('jargon')} |"
            )
        lines.append("")
    return lines


def _md_hollow_section(result, root_dir: str) -> list:
    """Hollow review candidates with what was measured (docs/REPORTS.md 2):
    never scored, and "not measured" is never written as zero."""
    from slop_detector.renderer_terminal import claim_line, hollow_line
    from slop_detector.report_view import build_report_view, short_path

    view = build_report_view(result)
    lines = [
        "## Hollow Review Candidates (not scored)",
        "",
        f"- Hollow channel: {hollow_line(view)}",
    ]
    sem = view.semantic
    if sem.files:
        states = ", ".join(f"{state} {n}" for state, n in sorted(sem.files.items()))
        lines.append(f"- Files by state: {states}")
    if sem.unknown_reasons:
        reasons = ", ".join(
            f"{k} {v}" for k, v in sorted(sem.unknown_reasons.items(), key=lambda kv: -kv[1])
        )
        lines.append(f"- Why functions were not decidable: {reasons}")
    lines.append(f"- Docstring promises: {claim_line(view)}")
    undecided = view.claims.undecided_by_reason
    if undecided:
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(undecided.items(), key=lambda kv: -kv[1]))
        lines.append(f"- Why promises were undecided: {reasons}")
    lines.append(
        "- A candidate is evidence for a review, not a verdict; it does not change the score."
    )
    lines.append("")
    if view.candidates:
        lines += ["| Location | Rule | Function: evidence |", "|---|---|---|"]
        for item in view.candidates:
            message = item.message.replace("|", chr(92) + "|")
            lines.append(
                f"| `{short_path(item.file, root_dir)}:{item.line}` | `{item.rule}` | {message} |"
            )
        lines.append("")
    return lines


def generate_markdown_report(result) -> str:
    """Generate a detailed developer-focused Markdown report."""
    is_project = hasattr(result, "project_path")
    root_dir = result.project_path if is_project else str(Path(result.file_path).parent)
    status = status_label(result)
    score_label = "Weighted Deficit Score" if is_project else "Deficit Score"
    score = result.weighted_deficit_score if is_project else result.deficit_score
    avg_inflation = result.avg_inflation if is_project else result.inflation.inflation_score
    measured = score_is_valid(result)
    timestamp = getattr(result, "timestamp", None)

    lines = ["# AI Code Quality Audit Report"]
    if timestamp:
        lines.append(f"**Date**: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    lines += [
        f"**Target**: `{root_dir}`",
        f"**Status**: {status}",
        f"**Tool**: ai-slop-detector {__version__}",
        "",
    ]

    lines += _md_summary_section(
        score_label,
        f"{score:.2f}" if measured else "N/A",
        f"{avg_inflation:.2f}" if measured else "N/A",
        status,
    )

    if is_project:
        lines += _md_project_metrics_section(result)
        lines += _md_finding_summary_section(result)
        lines += _md_hollow_section(result, root_dir)
        lines += _md_scan_coverage_section(result)
        lines += _md_ml_scoring_section(result)
        lines += _md_next_steps_section(result)
        lines += _md_structural_coherence_section(result)
        lines += _md_suppression_section(result)
        lines += _md_test_evidence_section(result)
        lines += _md_priority_hotspots_section(result)
    else:
        lines += _md_file_metrics_section(result)
        lines += _md_hollow_section(result, root_dir)
        lines += _md_ml_scoring_section(result)
        lines += _md_suppression_section(result)

    if is_project:
        if hasattr(result, "files") and result.files:
            file_results = list(result.files.items())
        elif hasattr(result, "file_results"):
            file_results = [(r.file_path, r) for r in result.file_results]
        else:
            file_results = []
    else:
        file_results = [(result.file_path, result)]

    lines += _md_findings_section(result, root_dir, file_results)
    return "\n".join(lines)
