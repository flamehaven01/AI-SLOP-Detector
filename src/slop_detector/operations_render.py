"""Explain/text/markdown rendering helpers for operations payloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from slop_detector.renderer_markdown import get_mitigation


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
    if identifier in mapping:
        issue_key, summary = mapping[identifier]
        return {
            "command": "explain",
            "identifier": identifier,
            "known": True,
            "kind": "cleanup_family",
            "summary": {
                "category": identifier,
                "message": summary,
                "mitigation": get_mitigation(issue_key),
            },
            "mitigation": get_mitigation(issue_key),
        }
    return _explain_rule(identifier)


def _explain_rule(rule: str) -> Dict[str, Any]:
    """A rule as the work order states it (config/work_order_rules.json): its family's
    VERIFY question (what to check, when to ACK and when to REJECT), what a finding does
    not prove and what a fix may not do. Python rules add their default severity and
    description from the pattern registry."""
    from slop_detector.patterns import get_all_patterns
    from slop_detector.work_order_rules import load_ruleset

    rules, _ = load_ruleset()
    family = next((name for name, fam in rules.families.items() if rule in fam.rules), None)
    if family is None:
        return {
            "command": "explain",
            "identifier": rule,
            "known": False,
            "summary": {
                "category": rule,
                "message": "No rule or cleanup family has this id (rule ids: docs/PATTERNS.md).",
                "mitigation": "",
            },
        }
    question = rules.families[family].question
    limit = next((line for line in rules.invariants if "FINDING" in line), rules.invariants[0])
    pattern = next((p for p in get_all_patterns() if p.id == rule), None)
    doc = (type(pattern).__doc__ or "").strip().splitlines() if pattern is not None else []
    return {
        "command": "explain",
        "identifier": rule,
        "known": True,
        "kind": "rule",
        "family": family,
        "severity": pattern.severity.value if pattern is not None else None,
        "description": doc[0] if doc else None,
        "verify_question": question,
        "limits": list(rules.invariants),
        "forbid": list(rules.forbid),
        "summary": {"category": rule, "message": question, "mitigation": limit},
        "mitigation": limit,
    }


def render_payload_text(payload: Dict[str, Any]) -> str:
    """Render a compact human-readable view for command payloads."""
    lines = [f"{payload.get('command', 'command').upper()}"]
    verdict = payload.get("verdict")
    if verdict:
        lines.append(f"Verdict: {str(verdict).upper()}{_verdict_basis(payload)}")
    summary = payload.get("summary", {})
    lines.extend(_render_summary_lines(summary))
    lines.extend(_render_target_lines(payload.get("targets", [])))
    lines.extend(_render_issue_lines(payload.get("issues", [])))
    return "\n".join(lines)


def _verdict_basis(payload: Dict[str, Any]) -> str:
    """The gate judges each file; overall_status is the project's score band.
    Say so next to the verdict, or WARN beside "clean" reads as a contradiction."""
    gate = payload.get("gate")
    if not isinstance(gate, dict):
        return ""
    total = (payload.get("summary") or {}).get("total_files")
    counts = (
        f"{len(gate.get('failed_files') or [])} failed, "
        f"{len(gate.get('warned_files') or [])} warned"
    )
    quarantined = len(gate.get("quarantined_files") or [])
    if quarantined:
        counts += f", {quarantined} quarantined"
    return f" - per file: {counts}" + (f" of {total} files" if total is not None else "")


def _render_summary_lines(summary: Any) -> List[str]:
    if isinstance(summary, dict):
        return [f"{key}: {value}" for key, value in summary.items()]
    if summary:
        return [f"summary: {summary}"]
    return []


def _render_target_lines(targets: List[Dict[str, Any]]) -> List[str]:
    if not targets:
        return []
    lines = ["Targets:"]
    for item in targets[:5]:
        lines.append(f"  - {item['file_path']} ({item.get('reason', 'review')})")
    return lines


def _render_issue_lines(issues: List[Dict[str, Any]]) -> List[str]:
    if not issues:
        return []
    lines = ["Issues:"]
    for item in issues[:5]:
        label = item.get("file_path") or item.get("display") or item.get("lineno")
        lines.append(f"  - {label}")
    return lines


def render_payload_markdown(payload: Dict[str, Any]) -> str:
    """Render a compact markdown view for command payloads."""
    lines = [f"# {payload.get('command', 'command').title()} Report", ""]
    if payload.get("verdict"):
        lines += [
            f"**Verdict**: `{str(payload['verdict']).upper()}`{_verdict_basis(payload)}",
            "",
        ]
    summary = payload.get("summary", {})
    lines.extend(_render_markdown_summary(summary))
    lines.extend(_render_markdown_targets(payload.get("targets", [])))
    lines.extend(_render_markdown_issues(payload.get("issues", [])))
    return "\n".join(lines)


def _render_markdown_summary(summary: Any) -> List[str]:
    if not summary:
        return []
    lines = ["## Summary", ""]
    if isinstance(summary, dict):
        for key, value in summary.items():
            lines.append(f"- **{key}**: `{value}`")
    else:
        lines.append(f"- `{summary}`")
    lines.append("")
    return lines


def _render_markdown_targets(targets: List[Dict[str, Any]]) -> List[str]:
    if not targets:
        return []
    lines = ["## Targets", "", "| File | Priority | Reason |", "| :--- | :--- | :--- |"]
    for item in targets[:10]:
        lines.append(
            f"| `{Path(item['file_path']).name}` | {item.get('priority_score', 0):.1f} | "
            f"{', '.join(item.get('reasons', [])) or 'review'} |"
        )
    lines.append("")
    return lines


def _render_markdown_issues(issues: List[Dict[str, Any]]) -> List[str]:
    if not issues:
        return []
    lines = ["## Issues", "", "| Item | Details |", "| :--- | :--- |"]
    for item in issues[:10]:
        detail = item.get("display") or item.get("reason") or item.get("file_path") or ""
        lines.append(f"| `{item.get('file_path', item.get('lineno', 'item'))}` | {detail} |")
    lines.append("")
    return lines
