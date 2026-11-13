"""Route a scan target to the analysis it gets."""

from __future__ import annotations

from pathlib import Path

from slop_detector import language_registry
from slop_detector.core import SlopDetector
from slop_detector.core_project import (
    build_project_analysis,
    record_analysis_failure,
    scan_coverage,
)
from slop_detector.models import ProjectAnalysis


def target_kind(target: Path, project: bool) -> str:
    """ "project", "python_file", or "source_file" (a single file of a
    registered language other than Python)."""
    if project:
        return "project"
    if language_registry.spec_for_suffix(target.suffix) is not None:
        return "source_file"
    return "python_file"


def analyze_single_source_file(detector: SlopDetector, path: Path) -> ProjectAnalysis:
    """A single file of a registered language is a project of that one file."""
    adapter = language_registry.spec_for_suffix(path.suffix)
    if adapter is None:
        raise ValueError(f"{path} is not a file of a registered language")
    results: list = []
    failures: list = []
    try:
        results.append(detector.analyze_language_file(adapter, str(path)))
    except Exception as exc:
        record_analysis_failure(failures, path, path.parent, adapter.name, exc)
    return build_project_analysis(
        str(path),
        str(path.parent),
        [],
        {adapter.name: results},
        scan_coverage([], []),
        detector.config.use_weighted_analysis(),
        detector._compute_coherence_vr,
        detector.project_prioritizer.prioritize_project,
        detector._ml_scoring,
        analysis_failures=failures,
    )
