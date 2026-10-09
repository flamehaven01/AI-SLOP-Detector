"""Project discovery, scope reporting, and result factories for ``core``."""

from __future__ import annotations

import fnmatch
import logging
import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from slop_detector.diagnostic_bands import classify_deficit
from slop_detector.finding_summary import build_finding_summary
from slop_detector.models import FileAnalysis, ProjectAnalysis, SlopStatus
from slop_detector.path_facts import default_exclusion_reason, relative_to_root
from slop_detector.rust_scan import discover_project_files

logger = logging.getLogger(__name__)

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
    """Return the exclusion source for a path, if any.

    With a root only the part of the path below it is matched: a directory
    above the root (the checkout living under `build/`) excludes nothing.
    """
    relative = relative_to_root(file_path, root) if root is not None else None
    below_root = relative if relative is not None else file_path
    default_reason = default_exclusion_reason(below_root.parts)
    if default_reason:
        return default_reason

    normalized_paths = {str(below_root).replace("\\", "/")}

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
    """Use accelerated discovery only after matching root-relative fallback results.

    Either way the files come back in one canonical order (root-relative POSIX
    path), so position-dependent results (approximate topology sampling, the
    first of tied files) do not depend on whether the Rust helper is present.
    """
    fallback = [
        path
        for include_pattern in include_patterns
        for path in project_path.glob(include_pattern)
        if path.suffix.lower() in extensions
        and not should_ignore(path, ignore_patterns, root=project_path)
    ]
    fallback = _canonical_order(project_path, fallback)
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
    return _canonical_order(project_path, accelerated)


def _canonical_order(project_path: Path, paths: List[Path]) -> List[Path]:
    def key(path: Path) -> str:
        try:
            return path.relative_to(project_path).as_posix()
        except ValueError:
            return path.as_posix()

    return sorted(paths, key=key)


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


def create_error_analysis(file_path: str, error: str, content: str = "") -> FileAnalysis:
    """Create JSON-safe critical analysis for source that cannot parse.

    The file keeps its weight in the project score: total_lines counts its
    non-blank, non-comment lines (the rule LDR uses), so an unparseable file
    cannot vanish from the weighted score. It is flagged `parse_error` and left
    out of the project's metric averages.
    """
    from slop_detector.models import DDCResult, InflationResult, LDRResult

    lines = sum(1 for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("#"))
    return FileAnalysis(
        file_path=file_path,
        ldr=LDRResult(lines, 0, lines, 0.0, "N/A"),
        inflation=InflationResult(0, 0.0, 999.0, "error", []),
        ddc=DDCResult([], [], [], [], [], 0.0, "N/A"),
        deficit_score=100.0,
        status=classify_deficit(100.0),
        warnings=[f"Parse error: {error}"],
        flags=["parse_error"],
    )


def is_parse_error(result: Any) -> bool:
    """Whether a result stands for a Python file that could not be parsed."""
    return "parse_error" in getattr(result, "flags", ())


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


def record_analysis_failure(
    failures: List[Dict[str, str]], file_path: Any, root: Any, language: str, exc: BaseException
) -> None:
    """Keep a file whose analysis raised in the coverage instead of dropping it."""
    path = Path(file_path)
    try:
        relative = path.relative_to(Path(root)).as_posix()
    except ValueError:
        relative = path.as_posix()
    failures.append({"path": relative, "language": language, "error_type": type(exc).__name__})


def set_failed_scan_coverage(
    scan_coverage: Dict[str, Any], failures: Optional[List[Dict[str, str]]]
) -> None:
    """Report files whose analysis failed; any failure makes the scan incomplete.

    A failed file is not scored: an analyzer or environment failure says nothing
    about the analyzed code (a syntax error is a parse_error result instead).
    """
    files = sorted(failures or [], key=lambda f: (f["path"], f["language"]))
    scan_coverage["failed"] = {
        "total": len(files),
        "files": files[:_COVERAGE_FILE_DETAIL_LIMIT],
        "omitted_file_details": max(0, len(files) - _COVERAGE_FILE_DETAIL_LIMIT),
        "by_language": dict(sorted(Counter(f["language"] for f in files).items())),
        "by_error_type": dict(sorted(Counter(f["error_type"] for f in files).items())),
    }
    scan_coverage["complete"] = not files


def set_analysis_modes(scan_coverage: Dict[str, Any], js_results: List[Any]) -> None:
    """Say how JS/TS was analyzed (the per-file `ast_mode`, summarized).

    Regex fallback finds fewer patterns than tree-sitter (no god functions), so
    two scores of one project are comparable only in the same mode.
    """
    modes: Dict[str, Any] = {}
    if js_results:
        from slop_detector.languages import js_analyzer

        seen = {bool(getattr(result, "ast_mode", False)) for result in js_results}
        mode = (
            "tree_sitter_ast"
            if seen == {True}
            else "regex_fallback" if seen == {False} else "mixed"
        )
        modes["javascript"] = {"mode": mode, "ast_available": bool(js_analyzer._TS_AVAILABLE)}
    scan_coverage["analysis_modes"] = modes


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
    analysis_failures: Optional[List[Dict[str, str]]] = None,
) -> ProjectAnalysis:
    """Aggregate analyzed language results into the stable project contract."""
    all_results = python_results + js_results + go_results
    set_analyzed_scan_counts(scan_coverage, python_results, js_results, go_results)
    set_failed_scan_coverage(scan_coverage, analysis_failures)
    set_analysis_modes(scan_coverage, js_results)
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
    # Metric averages describe parsed code; a parse failure has no metrics.
    measured = [result for result in all_results if not is_parse_error(result)]
    measured_python = [result for result in python_results if not is_parse_error(result)]
    # A module without executable code has no LDR or DDC to average.
    with_code = [r for r in measured if "no_executable_code" not in getattr(r, "flags", [])]
    with_code_python = [r for r in measured_python if "no_executable_code" not in r.flags]
    ldr_scores = [result_ldr_score(result) for result in with_code] or [0.0]
    average_ldr = 0.6 * min(ldr_scores) + 0.4 * (sum(ldr_scores) / len(ldr_scores))
    finite_python_inflation = [
        result.inflation.inflation_score
        for result in measured_python
        if math.isfinite(result.inflation.inflation_score)
    ]
    average_inflation = sum(finite_python_inflation) / max(1, len(finite_python_inflation))
    average_ddc = sum(result.ddc.usage_ratio for result in with_code_python) / max(
        1, len(with_code_python)
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

    overall_status = classify_deficit(weighted_deficit)

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
        parse_error_files=sum(1 for result in python_results if is_parse_error(result)),
    )
