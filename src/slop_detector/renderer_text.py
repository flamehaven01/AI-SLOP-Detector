"""Plain-text report generation for the SLOP detector CLI."""

from __future__ import annotations

from pathlib import Path

from slop_detector.renderer_glossary import DEFICIT_BANDS, next_steps, project_metric_rows
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
        "Project Metrics:",
    ]
    rows = project_metric_rows(result)
    label_w = max(len(r["label"]) for r in rows)
    val_w = max(len(r["value"]) for r in rows)
    header = f"  {'Metric':<{label_w}}  {'Value':>{val_w}}  {'Healthy':<7} What It Means"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))
    for r in rows:
        lines.append(
            f"  {r['label']:<{label_w}}  {r['value']:>{val_w}}  "
            f"{r['direction']:<7} {r['means']}"
        )
    lines.append("")
    lines.append(f"  Deficit bands: {DEFICIT_BANDS}")
    lines.append("")
    steps = next_steps(result)
    if steps:
        lines.append("Next Steps:")
        for idx, step in enumerate(steps, 1):
            lines.append(f"  {idx}. {step}")
        lines.append("")
    coherence_level = getattr(result, "coherence_level", "none")
    if coherence_level != "none":
        label = (
            "deterministic approximation"
            if coherence_level == "vr_structural_approx"
            else "exact MST"
        )
        lines += [
            "Structural Coherence:",
            f"  Score: {result.structural_coherence:.4f}",
            f"  Mode: {coherence_level} ({label})",
            "",
        ]
    suppression_ledger = getattr(result, "suppression_ledger", [])
    if suppression_ledger:
        lines += [
            "Inline Suppressions:",
            f"  Suppressed Issues: {len(suppression_ledger)}",
        ]
        if len(suppression_ledger) >= 10:
            lines.append("  [!] Warning: high inline suppression usage across the project")
        for entry in suppression_ledger[:10]:
            lines.append(
                f"  - {Path(entry.file_path).name}: L{entry.suppressed_line} "
                f"({entry.pattern_id}) via L{entry.directive_line} [{entry.scope}]"
            )
        if len(suppression_ledger) > 10:
            lines.append(f"  - ... and {len(suppression_ledger) - 10} more")
        lines.append("")
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
    priority_hotspots = getattr(result, "priority_hotspots", [])
    if priority_hotspots:
        lines += [
            "Priority Hotspots:",
            "  Focus order uses deficit + churn + coverage gap",
            f"  Churn Data: {'yes' if getattr(result, 'churn_analysis_available', False) else 'no'}",
            f"  Coverage Data: {'yes' if getattr(result, 'coverage_analysis_available', False) else 'no'}",
        ]
        for hotspot in priority_hotspots[:10]:
            coverage = "n/a" if hotspot.coverage_ratio is None else f"{hotspot.coverage_ratio:.0%}"
            lines.append(
                f"  - {Path(hotspot.file_path).name}: priority {hotspot.priority_score:.1f}/100, "
                f"deficit {hotspot.deficit_score:.1f}, churn {hotspot.churn_count}, "
                f"coverage {coverage} ({', '.join(hotspot.reasons)})"
            )
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
    suppression_ledger = getattr(result, "suppression_ledger", [])
    if suppression_ledger:
        lines += ["", "Inline Suppressions:"]
        for entry in suppression_ledger[:10]:
            lines.append(
                f"  - L{entry.suppressed_line} {entry.pattern_id} via L{entry.directive_line} [{entry.scope}]"
            )
        if len(suppression_ledger) > 10:
            lines.append(f"  - ... and {len(suppression_ledger) - 10} more")
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
