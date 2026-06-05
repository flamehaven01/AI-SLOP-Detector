"""Analysis orchestration helpers for the CLI."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from slop_detector.core import SlopDetector
from slop_detector.models import FileAnalysis, ProjectAnalysis, SlopStatus


def _build_fallback_project_analysis(
    detector: SlopDetector, project_path: Path
) -> Optional[ProjectAnalysis]:
    """Reconstruct a project analysis from direct file walks when aggregate scan is empty."""
    ignore_patterns = detector.config.get_ignore_patterns()
    scan_root = (
        project_path if project_path.exists() and project_path.is_dir() else project_path.parent
    )
    python_files = [
        fp
        for fp in scan_root.rglob("*.py")
        if not detector._should_ignore(fp, ignore_patterns, root=scan_root)
    ]

    file_results = []
    for file_path in python_files:
        try:
            file_results.append(detector.analyze_file(str(file_path)))
        except Exception:
            continue

    js_results = detector._analyze_js_files(scan_root, ignore_patterns)
    go_results = detector._analyze_go_files(scan_root, ignore_patterns)
    all_results = file_results + js_results + go_results
    if not all_results:
        return None

    total_files = len(all_results)
    slop_files = sum(1 for result in all_results if detector._is_result_non_clean(result))
    clean_files = total_files - slop_files
    avg_deficit_score = (
        sum(detector._result_slop_score(result) for result in all_results) / total_files
    )

    ldr_scores = [detector._result_ldr_score(result) for result in all_results]
    avg_ldr = 0.6 * min(ldr_scores) + 0.4 * (sum(ldr_scores) / total_files)

    inflation_scores = [
        result.inflation.inflation_score
        for result in file_results
        if math.isfinite(result.inflation.inflation_score)
    ]
    avg_inflation = sum(inflation_scores) / max(1, len(inflation_scores))
    avg_ddc = sum(result.ddc.usage_ratio for result in file_results) / max(1, len(file_results))

    if detector.config.use_weighted_analysis():
        total_loc = sum(detector._result_total_lines(result) for result in all_results)
        weighted_deficit_score = (
            sum(
                detector._result_slop_score(result)
                * (detector._result_total_lines(result) / total_loc)
                for result in all_results
            )
            if total_loc > 0
            else avg_deficit_score
        )
    else:
        weighted_deficit_score = avg_deficit_score

    if weighted_deficit_score >= 50:
        overall_status = SlopStatus.CRITICAL_DEFICIT
    elif weighted_deficit_score >= 30:
        overall_status = SlopStatus.SUSPICIOUS
    else:
        overall_status = SlopStatus.CLEAN

    file_dcfs = [result.dcf for result in file_results if result.dcf]
    structural_coherence, coherence_level = detector._compute_coherence_vr(file_dcfs)
    suppression_ledger = [
        entry
        for file_result in file_results
        for entry in getattr(file_result, "suppression_ledger", [])
    ]
    priority_hotspots, churn_available, coverage_available = (
        detector.project_prioritizer.prioritize_project(str(scan_root), all_results)
    )

    return ProjectAnalysis(
        project_path=str(scan_root),
        total_files=total_files,
        deficit_files=slop_files,
        clean_files=clean_files,
        avg_deficit_score=avg_deficit_score,
        weighted_deficit_score=weighted_deficit_score,
        avg_ldr=avg_ldr,
        avg_inflation=avg_inflation,
        avg_ddc=avg_ddc,
        overall_status=overall_status,
        file_results=file_results,
        structural_coherence=structural_coherence,
        coherence_level=coherence_level,
        suppressed_issue_count=len(suppression_ledger),
        suppression_ledger=suppression_ledger,
        priority_hotspots=priority_hotspots,
        churn_analysis_available=churn_available,
        coverage_analysis_available=coverage_available,
    )


def _run_analysis_phase(args, detector):
    """Run file or project analysis. Returns (result, score)."""
    result: ProjectAnalysis | FileAnalysis
    if args.project:
        result = detector.analyze_project(args.path)
        return result, result.weighted_deficit_score
    result = detector.analyze_file(args.path)
    return result, result.deficit_score


def _apply_runtime_overrides(args, detector) -> None:
    """Apply CLI overrides onto detector config before analysis."""
    advanced = detector.config.config.setdefault("advanced", {})
    if getattr(args, "topology_ceiling", None) is not None:
        advanced["exact_topology_ceiling"] = args.topology_ceiling
    if getattr(args, "topology_mode", None) is not None:
        advanced["topology_mode_above_ceiling"] = args.topology_mode
