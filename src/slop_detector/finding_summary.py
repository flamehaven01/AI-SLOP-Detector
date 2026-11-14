"""Project-level pattern finding summaries shared by every output surface."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

_SEVERITIES = ("critical", "high", "medium", "low")


def _issue_severity(issue: Any) -> str:
    raw = getattr(issue, "severity", "low")
    value = getattr(raw, "value", raw)
    severity = str(value).lower()
    return severity if severity in _SEVERITIES else "low"


def build_finding_summary(file_results: Iterable[Any]) -> Dict[str, Any]:
    """Return stable aggregate finding counts without changing score semantics."""
    severity = {name: 0 for name in _SEVERITIES}
    affected_files = 0

    for result in file_results:
        issues = getattr(result, "pattern_issues", getattr(result, "issues", [])) or []
        if issues:
            affected_files += 1
        for issue in issues:
            severity[_issue_severity(issue)] += 1

    total = sum(severity.values())
    return {
        "total": total,
        "affected_files": affected_files,
        "severity": severity,
        "has_critical": severity["critical"] > 0,
        "score_semantics": "independent_of_weighted_deficit_status",
    }


def get_finding_summary(project_result: Any) -> Dict[str, Any]:
    """Use stored project data when available, otherwise support legacy callers."""
    summary = getattr(project_result, "finding_summary", None)
    if summary:
        return summary
    from slop_detector.language_registry import all_file_results

    return build_finding_summary(all_file_results(project_result))


def severity_counts(file_result: Any) -> Dict[str, int]:
    """Finding counts of one file (any language) by severity."""
    counts = {name: 0 for name in _SEVERITIES}
    issues = getattr(file_result, "pattern_issues", getattr(file_result, "issues", [])) or []
    for issue in issues:
        counts[_issue_severity(issue)] += 1
    return counts


def review_order(file_results: Iterable[Any]) -> List[Tuple[Any, Dict[str, int]]]:
    """Files with findings, the most severe first: by critical, then high,
    medium and low counts, then path. It compares findings, not scores, so
    files of different languages (scored differently) are ranked alike."""
    rows = [(f, severity_counts(f)) for f in file_results]
    rows = [(f, c) for f, c in rows if any(c.values())]
    return sorted(
        rows,
        key=lambda row: (
            *(-row[1][name] for name in _SEVERITIES),
            str(getattr(row[0], "file_path", "")),
        ),
    )
