"""Route a scan target to the analysis it gets."""

from __future__ import annotations

from pathlib import Path
from typing import Union

from slop_detector.core import SlopDetector
from slop_detector.core_project import (
    build_project_analysis,
    record_analysis_failure,
    scan_coverage,
)
from slop_detector.models import FileAnalysis, ProjectAnalysis


def target_kind(target: Path, project: bool) -> str:
    """ "project", "python_file", or "source_file" (a single JS/TS or Go file)."""
    if project:
        return "project"
    suffix = target.suffix.lower()
    if suffix in SlopDetector._JS_EXTENSIONS | SlopDetector._GO_EXTENSIONS:
        return "source_file"
    return "python_file"


def analyze_single_source_file(detector: SlopDetector, path: Path) -> ProjectAnalysis:
    """A single JS/TS or Go file is a project of that one file, in its own language."""
    is_js = path.suffix.lower() in detector._JS_EXTENSIONS
    language = "javascript" if is_js else "go"
    analyze = detector.analyze_js_file if is_js else detector.analyze_go_file
    results: list = []
    failures: list = []
    try:
        results.append(analyze(str(path)))
    except Exception as exc:
        record_analysis_failure(failures, path, path.parent, language, exc)
    return build_project_analysis(
        str(path),
        str(path.parent),
        [],
        results if is_js else [],
        [] if is_js else results,
        scan_coverage([], []),
        detector.config.use_weighted_analysis(),
        detector._compute_coherence_vr,
        detector.project_prioritizer.prioritize_project,
        detector._ml_scoring,
        analysis_failures=failures,
    )


def analyze_target(
    detector: SlopDetector, target: str, project: bool
) -> Union[ProjectAnalysis, FileAnalysis]:
    """Analyze a target the way its kind requires."""
    kind = target_kind(Path(target), project)
    if kind == "project":
        return detector.analyze_project(target)
    if kind == "source_file":
        return analyze_single_source_file(detector, Path(target))
    return detector.analyze_file(target)
