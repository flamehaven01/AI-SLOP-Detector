"""Project discovery, scope reporting, and result factories for ``core``."""

from __future__ import annotations

import fnmatch
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from slop_detector.finding_summary import build_finding_summary
from slop_detector.models import FileAnalysis, ProjectAnalysis, SlopStatus
from slop_detector.rust_scan import discover_project_files

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_PARTS = {
    ".claude",
    ".venv",
    "venv",
    "site-packages",
    "node_modules",
    "__pycache__",
    ".git",
    "build",
    "dist",
    ".tox",
    ".next",
    "htmlcov",
}
_COVERAGE_FILE_DETAIL_LIMIT = 200
_SUPPORTED_SOURCE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
    ".go": "go",
}
_UNSUPPORTED_SOURCE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".h",
    ".java",
    ".kt",
    ".kts",
    ".php",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".swift",
}


def ignore_reason(
    file_path: Path, patterns: List[str], root: Optional[Path] = None
) -> Optional[str]:
    """Return the exclusion source for a path, if any."""
    lowered_parts = {part.lower() for part in file_path.parts}
    default_parts = lowered_parts & DEFAULT_EXCLUDE_PARTS
    if default_parts:
        return f"directory:{sorted(default_parts)[0]}"

    if root is not None:
        try:
            normalized_paths = {str(file_path.relative_to(root)).replace("\\", "/")}
        except ValueError:
            normalized_paths = {str(file_path).replace("\\", "/")}
    else:
        normalized_paths = {str(file_path).replace("\\", "/")}

    for pattern in patterns:
        normalized_pattern = str(pattern).replace("\\", "/")
        for normalized in normalized_paths:
            if Path(normalized).match(normalized_pattern):
                return f"pattern:{normalized_pattern}"
            if fnmatch.fnmatch(normalized, normalized_pattern):
                return f"pattern:{normalized_pattern}"
            if normalized_pattern.startswith("**/") and fnmatch.fnmatch(
                normalized, normalized_pattern[3:]
            ):
                return f"pattern:{normalized_pattern}"
    return None


def should_ignore(file_path: Path, patterns: List[str], root: Optional[Path] = None) -> bool:
    """Return whether a source path is excluded from project analysis."""
    return ignore_reason(file_path, patterns, root=root) is not None


def discover_supported_files(
    project_path: Path,
    include_patterns: Sequence[str],
    extensions: set[str] | frozenset[str],
    ignore_patterns: List[str],
    rust_discoverer: Callable[
        [Path, Sequence[str], List[str]], Optional[List[Path]]
    ] = discover_project_files,
) -> List[Path]:
    """Use accelerated discovery only after matching root-relative fallback results."""
    fallback = [
        path
        for include_pattern in include_patterns
        for path in project_path.glob(include_pattern)
        if path.suffix.lower() in extensions
        and not should_ignore(path, ignore_patterns, root=project_path)
    ]
    discovered = rust_discoverer(project_path, include_patterns, ignore_patterns)
    if discovered is None:
        return fallback

    accelerated = [
        path
        for path in discovered
        if path.suffix.lower() in extensions
        and not should_ignore(path, ignore_patterns, root=project_path)
    ]
    if {path.resolve() for path in accelerated} != {path.resolve() for path in fallback}:
        logger.warning(
            "Rust file discovery disagreed with root-relative discovery for %s; using the verified fallback",
            project_path,
        )
        return fallback
    return accelerated


def collect_project_scan_coverage(project_path: Path, ignore_patterns: List[str]) -> Dict[str, Any]:
    """Report excluded supported files and unexcluded unsupported source files."""
    excluded: List[Dict[str, str]] = []
    unsupported: List[Dict[str, str]] = []
    excluded_by_reason: Counter[str] = Counter()
    unsupported_count = 0
    try:
        for path in project_path.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            reason = ignore_reason(path, ignore_patterns, root=project_path)
            if suffix in _SUPPORTED_SOURCE_EXTENSIONS and reason is not None:
                excluded_by_reason[reason] += 1
                if len(excluded) < _COVERAGE_FILE_DETAIL_LIMIT:
                    excluded.append(
                        {
                            "path": str(path.relative_to(project_path)).replace("\\", "/"),
                            "language": _SUPPORTED_SOURCE_EXTENSIONS[suffix],
                            "reason": reason,
                        }
                    )
                continue
            if suffix in _UNSUPPORTED_SOURCE_EXTENSIONS and reason is None:
                unsupported_count += 1
                if len(unsupported) < _COVERAGE_FILE_DETAIL_LIMIT:
                    unsupported.append(
                        {
                            "path": str(path.relative_to(project_path)).replace("\\", "/"),
                            "extension": suffix,
                        }
                    )
    except OSError as exc:
        logger.debug("Could not collect full scan coverage for %s: %s", project_path, exc)

    excluded_count = sum(excluded_by_reason.values())
    return {
        "analyzed": {"total": 0, "python": 0, "javascript": 0, "go": 0},
        "excluded": {
            "total": excluded_count,
            "files": excluded,
            "omitted_file_details": max(0, excluded_count - len(excluded)),
            "by_reason": dict(sorted(excluded_by_reason.items())),
        },
        "unsupported": {
            "total": unsupported_count,
            "files": unsupported,
            "omitted_file_details": max(0, unsupported_count - len(unsupported)),
        },
    }


def set_analyzed_scan_counts(
    scan_coverage: Dict[str, Any],
    python_results: List[Any],
    js_results: List[Any],
    go_results: List[Any],
) -> None:
    """Populate language totals after all project analyzers complete."""
    analyzed = scan_coverage["analyzed"]
    analyzed["python"] = len(python_results)
    analyzed["javascript"] = len(js_results)
    analyzed["go"] = len(go_results)
    analyzed["total"] = len(python_results) + len(js_results) + len(go_results)


def result_status_value(result: Any) -> str:
    """Normalize Python and language-adapter status values to a string."""
    status = getattr(result, "status", SlopStatus.CLEAN)
    return status.value if isinstance(status, SlopStatus) else str(status)


def is_result_non_clean(result: Any) -> bool:
    """Return whether a result's normalized status is non-clean."""
    return result_status_value(result) != SlopStatus.CLEAN.value


def result_slop_score(result: Any) -> float:
    """Read the score name exposed by Python or language-specific results."""
    if hasattr(result, "deficit_score"):
        return float(result.deficit_score)
    return float(getattr(result, "slop_score", 0.0))


def result_total_lines(result: Any) -> int:
    """Read total source lines from Python or language-specific results."""
    if hasattr(result, "ldr"):
        return int(getattr(result.ldr, "total_lines", 0))
    return int(getattr(result, "total_lines", 0))


def result_ldr_score(result: Any) -> float:
    """Read LDR or its language-adapter equivalent from an analysis result."""
    if hasattr(result, "ldr"):
        return float(getattr(result.ldr, "ldr_score", 0.0))
    return float(getattr(result, "ldr_equivalent", 0.0))


def create_error_analysis(file_path: str, error: str) -> FileAnalysis:
    """Create JSON-safe critical analysis for source that cannot parse."""
    from slop_detector.models import DDCResult, InflationResult, LDRResult

    return FileAnalysis(
        file_path=file_path,
        ldr=LDRResult(0, 0, 0, 0.0, "N/A"),
        inflation=InflationResult(0, 0.0, 999.0, "error", []),
        ddc=DDCResult([], [], [], [], [], 0.0, "N/A"),
        deficit_score=100.0,
        status=SlopStatus.CRITICAL_DEFICIT,
        warnings=[f"Parse error: {error}"],
    )


def create_empty_project_analysis(project_path: str) -> ProjectAnalysis:
    """Create the canonical empty project result."""
    return ProjectAnalysis(
        project_path=project_path,
        total_files=0,
        deficit_files=0,
        clean_files=0,
        avg_deficit_score=0.0,
        weighted_deficit_score=0.0,
        avg_ldr=0.0,
        avg_inflation=0.0,
        avg_ddc=0.0,
        overall_status=SlopStatus.CLEAN,
        file_results=[],
        suppressed_issue_count=0,
        suppression_ledger=[],
        priority_hotspots=[],
        churn_analysis_available=False,
        coverage_analysis_available=False,
    )


def build_project_analysis(
    project_path: str,
    prioritization_path: str,
    python_results: List[FileAnalysis],
    js_results: List[Any],
    go_results: List[Any],
    scan_coverage: Dict[str, Any],
    use_weighted_analysis: bool,
    coherence_calculator: Callable[[List[Dict[str, float]]], tuple[float, str]],
    prioritize_project: Callable[[str, List[FileAnalysis]], tuple[List[Any], bool, bool]],
    ml_scoring: Dict[str, Any],
) -> ProjectAnalysis:
    """Aggregate analyzed language results into the stable project contract."""
    all_results = python_results + js_results + go_results
    set_analyzed_scan_counts(scan_coverage, python_results, js_results, go_results)
    if not all_results:
        result = create_empty_project_analysis(project_path)
        result.js_file_results = js_results
        result.go_file_results = go_results
        result.scan_coverage = scan_coverage
        result.ml_scoring = ml_scoring
        return result

    total_files = len(all_results)
    deficit_files = sum(1 for result in all_results if is_result_non_clean(result))
    average_deficit = sum(result_slop_score(result) for result in all_results) / total_files
    ldr_scores = [result_ldr_score(result) for result in all_results]
    average_ldr = 0.6 * min(ldr_scores) + 0.4 * (sum(ldr_scores) / total_files)
    finite_python_inflation = [
        result.inflation.inflation_score
        for result in python_results
        if math.isfinite(result.inflation.inflation_score)
    ]
    average_inflation = sum(finite_python_inflation) / max(1, len(finite_python_inflation))
    average_ddc = sum(result.ddc.usage_ratio for result in python_results) / max(
        1, len(python_results)
    )

    if use_weighted_analysis:
        total_lines = sum(result_total_lines(result) for result in all_results)
        weighted_deficit = (
            sum(
                result_slop_score(result) * (result_total_lines(result) / total_lines)
                for result in all_results
            )
            if total_lines > 0
            else average_deficit
        )
    else:
        weighted_deficit = average_deficit

    if weighted_deficit >= 50:
        overall_status = SlopStatus.CRITICAL_DEFICIT
    elif weighted_deficit >= 30:
        overall_status = SlopStatus.SUSPICIOUS
    else:
        overall_status = SlopStatus.CLEAN

    structural_coherence, coherence_level = coherence_calculator(
        [result.dcf for result in python_results if result.dcf]
    )
    suppression_ledger = [
        entry for result in python_results for entry in getattr(result, "suppression_ledger", [])
    ]
    priority_hotspots, churn_available, coverage_available = prioritize_project(
        prioritization_path, python_results
    )
    return ProjectAnalysis(
        project_path=project_path,
        total_files=total_files,
        deficit_files=deficit_files,
        clean_files=total_files - deficit_files,
        avg_deficit_score=average_deficit,
        weighted_deficit_score=weighted_deficit,
        avg_ldr=average_ldr,
        avg_inflation=average_inflation,
        avg_ddc=average_ddc,
        overall_status=overall_status,
        file_results=python_results,
        structural_coherence=structural_coherence,
        coherence_level=coherence_level,
        suppressed_issue_count=len(suppression_ledger),
        suppression_ledger=suppression_ledger,
        priority_hotspots=priority_hotspots,
        churn_analysis_available=churn_available,
        coverage_analysis_available=coverage_available,
        js_file_results=js_results,
        go_file_results=go_results,
        finding_summary=build_finding_summary(all_results),
        scan_coverage=scan_coverage,
        ml_scoring=ml_scoring,
    )
