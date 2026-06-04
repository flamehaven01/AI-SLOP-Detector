"""Operational command helpers for review, cleanup, and watch workflows."""

from __future__ import annotations

import ast
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List

from slop_detector.analysis.cross_file import CrossFileAnalyzer
from slop_detector.ci_gate import CIGate
from slop_detector.gate.models import GateMode
from slop_detector.renderer_markdown import get_mitigation


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
    diffs = _run_git(["diff", "--name-only", "--diff-filter=ACM"], cwd=root)
    return diffs


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


def _looks_like_dead_code(file_path: str) -> bool:
    """Return True for obvious placeholder / dead-code only files."""
    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return False

    if "TODO" in source or "FIXME" in source:
        return True

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            if all(isinstance(item, (ast.Pass, ast.Expr)) for item in body):
                if any(isinstance(item, ast.Pass) for item in body):
                    return True
                if any(
                    isinstance(item, ast.Expr)
                    and isinstance(getattr(item, "value", None), ast.Constant)
                    and getattr(item.value, "value", None) in (Ellipsis, "")
                    for item in body
                ):
                    return True
    return False


def build_audit_payload(result, project_path: Path, base_ref: str = "HEAD") -> Dict[str, Any]:
    """Build the changed-code audit JSON contract."""
    gate_result = CIGate(mode=GateMode.HARD).evaluate(result)
    changed = set(get_changed_files(project_path, base_ref=base_ref))
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


def build_cleanup_payload(result, kind: str) -> Dict[str, Any]:
    """Build a cleanup-focused payload for a family of commands."""
    analyzer = CrossFileAnalyzer()
    project_path = Path(result.project_path)
    cross = analyzer.analyze(str(project_path), result.file_results)
    issues: List[Dict[str, Any]] = []

    if kind == "dead-code":
        for fr in result.file_results:
            if (
                getattr(fr, "pattern_issues", [])
                or getattr(fr, "deficit_score", 0.0) >= 30
                or _looks_like_dead_code(fr.file_path)
            ):
                issues.append(
                    {
                        "file_path": fr.file_path,
                        "deficit_score": getattr(fr, "deficit_score", 0.0),
                        "pattern_count": len(getattr(fr, "pattern_issues", [])),
                        "reason": "dead code placeholder",
                    }
                )
    elif kind == "dupes":
        for dup in cross.duplicates:
            issues.append(
                {
                    "file_a": dup.file_a,
                    "file_b": dup.file_b,
                    "func_a": dup.func_a,
                    "func_b": dup.func_b,
                    "similarity": dup.similarity,
                }
            )
    elif kind == "unused-deps":
        for fr in result.file_results:
            if getattr(fr.ddc, "unused", []):
                issues.append(
                    {
                        "file_path": fr.file_path,
                        "usage_ratio": fr.ddc.usage_ratio,
                        "unused": list(fr.ddc.unused),
                    }
                )
    elif kind == "stale-suppressions":
        ledger_entries = getattr(result, "suppression_ledger", []) or []
        directives = (
            getattr(result.file_results[0], "suppression_directives", [])
            if result.file_results
            else []
        )
        directive_lines = {entry.directive_line for entry in ledger_entries}
        for directive in directives:
            if directive.lineno not in directive_lines:
                issues.append(
                    {
                        "lineno": directive.lineno,
                        "scope": directive.scope,
                        "rules": list(directive.rules),
                        "source": directive.source,
                    }
                )
    elif kind == "boundary-violations":
        for cycle in cross.import_cycles:
            issues.append({"cycle": list(cycle.cycle), "display": str(cycle)})

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


def build_explain_payload(identifier: str) -> Dict[str, Any]:
    """Return a mitigation-oriented explanation for a rule or target name."""
    mapping = {
        "dead-code": ("complex_logic", "Cleanup dead code and simplify branches."),
        "dupes": ("complex_logic", "Deduplicate similar blocks into a shared helper."),
        "unused-deps": ("unused_import", "Remove dependencies that are never used."),
        "stale-suppressions": ("jargon", "Remove suppressions that no longer silence findings."),
        "boundary-violations": (
            "complex_logic",
            "Refactor cross-file dependencies to restore clear boundaries.",
        ),
    }
    issue_key, summary = mapping.get(identifier, ("unknown", "Review the rule or target manually."))
    return {
        "command": "explain",
        "identifier": identifier,
        "summary": {
            "category": identifier,
            "message": summary,
            "mitigation": get_mitigation(issue_key),
        },
        "mitigation": get_mitigation(issue_key),
    }


def render_payload_text(payload: Dict[str, Any]) -> str:
    """Render a compact human-readable view for command payloads."""
    lines = [f"{payload.get('command', 'command').upper()}"]
    verdict = payload.get("verdict")
    if verdict:
        lines.append(f"Verdict: {str(verdict).upper()}")
    summary = payload.get("summary", {})
    if isinstance(summary, dict):
        for key, value in summary.items():
            lines.append(f"{key}: {value}")
    elif summary:
        lines.append(f"summary: {summary}")
    targets = payload.get("targets", [])
    if targets:
        lines.append("Targets:")
        for item in targets[:5]:
            lines.append(f"  - {item['file_path']} ({item.get('reason', 'review')})")
    issues = payload.get("issues", [])
    if issues:
        lines.append("Issues:")
        for item in issues[:5]:
            label = item.get("file_path") or item.get("display") or item.get("lineno")
            lines.append(f"  - {label}")
    return "\n".join(lines)


def render_payload_markdown(payload: Dict[str, Any]) -> str:
    """Render a compact markdown view for command payloads."""
    lines = [f"# {payload.get('command', 'command').title()} Report", ""]
    if payload.get("verdict"):
        lines += [f"**Verdict**: `{str(payload['verdict']).upper()}`", ""]
    summary = payload.get("summary", {})
    if summary:
        lines += ["## Summary", ""]
        if isinstance(summary, dict):
            for key, value in summary.items():
                lines.append(f"- **{key}**: `{value}`")
        else:
            lines.append(f"- `{summary}`")
        lines.append("")
    targets = payload.get("targets", [])
    if targets:
        lines += ["## Targets", "", "| File | Priority | Reason |", "| :--- | :--- | :--- |"]
        for item in targets[:10]:
            lines.append(
                f"| `{Path(item['file_path']).name}` | {item.get('priority_score', 0):.1f} | "
                f"{', '.join(item.get('reasons', [])) or 'review'} |"
            )
        lines.append("")
    issues = payload.get("issues", [])
    if issues:
        lines += ["## Issues", "", "| Item | Details |", "| :--- | :--- |"]
        for item in issues[:10]:
            detail = item.get("display") or item.get("reason") or item.get("file_path") or ""
            lines.append(f"| `{item.get('file_path', item.get('lineno', 'item'))}` | {detail} |")
        lines.append("")
    return "\n".join(lines)


def watch_project(result_factory, interval: float = 2.0, follow: bool = False) -> int:
    """Poll a project scan periodically. `result_factory` returns a fresh payload."""
    try:
        while True:
            payload = result_factory()
            print(render_payload_text(payload))
            if not follow:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        return 130
