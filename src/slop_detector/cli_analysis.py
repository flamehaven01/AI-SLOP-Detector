"""Analysis orchestration helpers for the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from slop_detector.core import SlopDetector
from slop_detector.core_project import build_project_analysis, record_analysis_failure
from slop_detector.models import FileAnalysis, ProjectAnalysis


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
    failures: list = []
    for file_path in python_files:
        try:
            file_results.append(detector.analyze_file(str(file_path), root=str(scan_root)))
        except Exception as exc:
            record_analysis_failure(failures, file_path, scan_root, "python", exc)

    js_results = detector._analyze_js_files(scan_root, ignore_patterns, failures)
    go_results = detector._analyze_go_files(scan_root, ignore_patterns, failures)
    all_results = file_results + js_results + go_results
    if not all_results:
        return None

    # One aggregation for every project result (bands, weights, parse errors).
    scan_coverage = detector._collect_project_scan_coverage(scan_root, ignore_patterns)
    return build_project_analysis(
        str(scan_root),
        str(scan_root),
        file_results,
        js_results,
        go_results,
        scan_coverage,
        detector.config.use_weighted_analysis(),
        detector._compute_coherence_vr,
        detector.project_prioritizer.prioritize_project,
        detector._ml_scoring,
        analysis_failures=failures,
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
    if getattr(args, "include_tests", False):
        detector.config.include_default_tests()
    if getattr(args, "topology_ceiling", None) is not None:
        advanced["exact_topology_ceiling"] = args.topology_ceiling
    if getattr(args, "topology_mode", None) is not None:
        advanced["topology_mode_above_ceiling"] = args.topology_mode
    if getattr(args, "patterns_only", False):
        advanced["patterns_only"] = True
    _apply_disabled_patterns(getattr(args, "disable", None) or [], detector)


def _apply_disabled_patterns(pattern_ids, detector) -> None:
    """Disable patterns by ID; an unknown ID is an error. Recorded in config (cache key)."""
    unknown = sorted({pid for pid in pattern_ids if detector.pattern_registry.get(pid) is None})
    if unknown:
        raise ValueError(f"--disable: unknown pattern id {', '.join(unknown)}; see --list-patterns")
    if not pattern_ids:
        return
    patterns = detector.config.config.setdefault("patterns", {})
    patterns["disabled"] = sorted(set(patterns.get("disabled") or []) | set(pattern_ids))
    for pid in pattern_ids:
        detector.pattern_registry.disable(pid)
