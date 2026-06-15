"""Payload builders for review, health, and cleanup commands."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List

from slop_detector.analysis.cross_file import CrossFileAnalyzer
from slop_detector.ci_gate import CIGate
from slop_detector.gate.models import GateMode
from slop_detector.operations_cleanup import _collect_cleanup_issues


def _run_git(args: List[str], cwd: Path) -> List[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def get_changed_files(project_path: Path, base_ref: str = "HEAD") -> List[str]:
    """Return repo-relative changed files for an audit baseline."""
    root = project_path.resolve()
    diffs = _run_git(
        ["diff", "--name-only", "--diff-filter=ACM", f"{base_ref}...HEAD"],
        cwd=root,
    )
    if diffs:
        return diffs
    return _run_git(["diff", "--name-only", "--diff-filter=ACM"], cwd=root)


def _top_targets(result, limit: int = 10) -> List[Dict[str, Any]]:
    hotspots = list(getattr(result, "priority_hotspots", []) or [])
    if hotspots:
        return [
            {
                "file_path": h.file_path,
                "priority_score": h.priority_score,
                "deficit_score": h.deficit_score,
                "reasons": list(h.reasons),
                "coverage_ratio": h.coverage_ratio,
                "churn_count": h.churn_count,
            }
            for h in hotspots[:limit]
        ]

    file_results = sorted(
        getattr(result, "file_results", []) or [],
        key=lambda fr: getattr(fr, "deficit_score", 0.0),
        reverse=True,
    )
    targets: List[Dict[str, Any]] = []
    for fr in file_results[:limit]:
        targets.append(
            {
                "file_path": fr.file_path,
                "priority_score": float(getattr(fr, "deficit_score", 0.0)),
                "deficit_score": float(getattr(fr, "deficit_score", 0.0)),
                "reasons": ["high deficit"] if getattr(fr, "deficit_score", 0.0) >= 30 else [],
                "coverage_ratio": None,
                "churn_count": 0,
            }
        )
    return targets


def _find_findings(result, limit: int = 20) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for fr in sorted(
        getattr(result, "file_results", []) or [],
        key=lambda item: getattr(item, "deficit_score", 0.0),
        reverse=True,
    ):
        if getattr(fr, "deficit_score", 0.0) < 30 and not getattr(fr, "pattern_issues", []):
            continue
        findings.append(
            {
                "file_path": fr.file_path,
                "status": getattr(fr.status, "value", str(fr.status)),
                "deficit_score": getattr(fr, "deficit_score", 0.0),
                "introduced": False,
                "issues": [
                    getattr(issue, "pattern_id", str(issue))
                    for issue in getattr(fr, "pattern_issues", [])[:10]
                ],
            }
        )
        if len(findings) >= limit:
            break
    return findings


def _relative_project_path(file_path: str, project_path: Path) -> str:
    path_obj = Path(file_path)
    try:
        return str(path_obj.resolve().relative_to(project_path.resolve()))
    except Exception:
        return str(path_obj)


def build_audit_payload(
    result,
    project_path: Path,
    base_ref: str = "HEAD",
    get_changed_files_func: Callable[[Path, str], List[str]] = get_changed_files,
) -> Dict[str, Any]:
    """Build the changed-code audit JSON contract."""
    gate_result = CIGate(mode=GateMode.HARD).evaluate(result)
    changed = set(get_changed_files_func(project_path, base_ref=base_ref))
    file_results = list(getattr(result, "file_results", []) or [])
    introduced = []
    inherited = []
    for fr in file_results:
        rel_path = _relative_project_path(fr.file_path, project_path)
        abs_path = str(Path(fr.file_path).resolve())
        changed_names = {Path(p).name for p in changed}
        if (
            rel_path in changed
            or abs_path in changed
            or Path(rel_path).name in changed_names
            or Path(abs_path).name in changed_names
        ):
            introduced.append(rel_path)
        else:
            inherited.append(rel_path)

    actions = [
        {
            "kind": "review",
            "file_path": item["file_path"],
            "priority_score": item["priority_score"],
            "reason": ", ".join(item["reasons"]) if item["reasons"] else "high deficit",
        }
        for item in _top_targets(result, limit=5)
    ]

    return {
        "command": "audit",
        "verdict": getattr(gate_result.verdict, "value", str(gate_result.verdict)),
        "should_fail_build": gate_result.should_fail_build,
        "attribution": {
            "introduced_files": introduced,
            "inherited_files": inherited,
            "introduced_count": len(introduced),
            "inherited_count": len(inherited),
        },
        "summary": {
            "project_path": result.project_path,
            "total_files": result.total_files,
            "deficit_files": result.deficit_files,
            "clean_files": result.clean_files,
            "avg_deficit_score": result.avg_deficit_score,
            "weighted_deficit_score": result.weighted_deficit_score,
            "overall_status": getattr(result.overall_status, "value", str(result.overall_status)),
        },
        "targets": _top_targets(result),
        "actions": actions,
        "findings": _find_findings(result),
        "gate": gate_result.to_dict(),
    }


def build_health_payload(result) -> Dict[str, Any]:
    """Build a health summary centered on next actions."""
    return {
        "command": "health",
        "summary": {
            "project_path": result.project_path,
            "overall_status": getattr(result.overall_status, "value", str(result.overall_status)),
            "weighted_deficit_score": result.weighted_deficit_score,
            "avg_deficit_score": result.avg_deficit_score,
            "avg_ldr": result.avg_ldr,
            "avg_inflation": result.avg_inflation,
            "avg_ddc": result.avg_ddc,
        },
        "targets": _top_targets(result),
        "signals": {
            "churn_analysis_available": getattr(result, "churn_analysis_available", False),
            "coverage_analysis_available": getattr(result, "coverage_analysis_available", False),
            "priority_hotspots": len(getattr(result, "priority_hotspots", []) or []),
        },
    }


def build_cleanup_payload(
    result,
    kind: str,
    config=None,
    collect_cleanup_issues_func: Callable[..., List[Dict[str, Any]]] = _collect_cleanup_issues,
) -> Dict[str, Any]:
    """Build a cleanup-focused payload for a family of commands."""
    analyzer = CrossFileAnalyzer()
    project_path = Path(result.project_path)
    cross = analyzer.analyze(str(project_path), result.file_results)
    issues = collect_cleanup_issues_func(kind, result, project_path, cross, config)

    verdict = "fail" if issues else "pass"
    return {
        "command": kind,
        "verdict": verdict,
        "summary": {
            "project_path": result.project_path,
            "issue_count": len(issues),
            "overall_status": getattr(result.overall_status, "value", str(result.overall_status)),
        },
        "issues": issues,
    }
