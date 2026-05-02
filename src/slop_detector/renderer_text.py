"""Plain-text report generation for the SLOP detector CLI."""

from __future__ import annotations

from pathlib import Path

from slop_detector.renderer_markdown import _collect_test_evidence_stats


def _text_file_lines(fr) -> list:
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
    """Generate plain-text report."""
    lines = ["=" * 80, "AI CODE QUALITY REPORT", "=" * 80, ""]
    if hasattr(result, "project_path"):
        lines += _text_project_section(result)
    else:
        lines += _text_single_file_section(result)
    return "\n".join(lines)
