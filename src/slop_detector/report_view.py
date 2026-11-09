"""One read-only view of an analysis result for every human report.

Renderers format this view; they do not compute counts, states or rankings
of their own, so two surfaces cannot disagree. It never changes the score,
the status or the JSON contract (docs/REPORTS.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from slop_detector.core_project import score_is_valid
from slop_detector.finding_summary import _SEVERITIES, _issue_severity

FINDING = "FINDING"
REVIEW_CANDIDATE = "REVIEW_CANDIDATE"
NOT_APPLICABLE = "NOT_APPLICABLE"
# How many items the terminal lists before "+N more" (Inspector decision
# FH-A0-A2-OUTPUT-CONTRACT: 5 pattern findings, 3 hollow candidates).
TERMINAL_LIMITS = {"findings": 5, "candidates": 3}
# PDF page 1: the top 5 items by priority, at most 3 of them hollow candidates.
BRIEF_LIMITS = {"items": 5, "candidates": 3}
# Priority on page 1: critical and high findings, then hollow candidates,
# then the rest.
_PRIORITY = {"critical": 0, "high": 1, "": 2, "medium": 3, "low": 4}


@dataclass(frozen=True)
class Item:
    """One finding or review candidate, located in the source."""

    kind: str
    rule: str
    severity: str
    file: str
    line: int
    message: str
    suggestion: str = ""
    # The docstring promise this item breaks (claim_findings.ClaimFinding.to_dict),
    # on a claim candidate or on the pattern finding it was merged into.
    promise: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class SemanticState:
    """What the hollow channel measured: files per state and, over the
    measured files, functions decided and not decidable."""

    state: str
    files: Dict[str, int] = field(default_factory=dict)
    functions: int = 0
    unknown: int = 0
    unknown_reasons: Dict[str, int] = field(default_factory=dict)


# Claim counts kept in the view (claim_judge.ClaimJudgment.coverage keys).
CLAIM_COUNTS = (
    "extracted_claims", "supported", "delegated_in_module", "provided_elsewhere", "undecided",
    "contradicted", "unmeasured", "not_evaluated", "candidates", "merged",
)


@dataclass(frozen=True)
class ClaimState:
    """What the claim channel measured: files per state and, over the measured
    files, claims per state (claim_judge) and UNDECIDED claims by reason."""

    state: str
    files: Dict[str, int] = field(default_factory=dict)
    counts: Dict[str, int] = field(default_factory=lambda: dict.fromkeys(CLAIM_COUNTS, 0))
    undecided_by_reason: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ReportView:
    target: str
    is_project: bool
    files: int
    score: Optional[float]
    status: str
    measurement: str
    findings: List[Item]
    severity: Dict[str, int]
    candidates: List[Item]
    semantic: SemanticState
    next_steps: List[str]
    claims: ClaimState = ClaimState("NOT_APPLICABLE")
    coverage: Dict[str, int] = field(default_factory=dict)
    coverage_notes: List[str] = field(default_factory=list)
    metrics: List[Dict[str, str]] = field(default_factory=list)
    file_rows: List[Tuple[str, Optional[float], str, int]] = field(default_factory=list)


def build_report_view(result: Any) -> ReportView:
    """The view of a project or single-file result."""
    is_project = hasattr(result, "project_path")
    files = _file_results(result) if is_project else [result]
    findings = sorted(
        (item for f in files for item in _pattern_items(f)),
        key=lambda i: (_SEVERITIES.index(i.severity), i.file, i.line, i.rule),
    )
    candidates = sorted(
        (item for f in files for item in _candidate_items(f)), key=lambda i: (i.file, i.line, i.rule)
    )
    severity = {name: sum(1 for i in findings if i.severity == name) for name in _SEVERITIES}
    from slop_detector.renderer_glossary import file_metric_rows, next_steps, project_metric_rows

    return ReportView(
        target=str(getattr(result, "project_path", None) or getattr(result, "file_path", "")),
        is_project=is_project,
        files=len(files),
        score=_score(result, is_project),
        status=_status(result, is_project),
        measurement=_measurement(result, is_project),
        findings=findings,
        severity=severity,
        candidates=candidates,
        semantic=_semantic_state(files),
        claims=_claim_state(files),
        next_steps=next_steps(result) if is_project else [],
        coverage=_coverage(result, is_project),
        coverage_notes=_coverage_notes(result) if is_project else [],
        metrics=(project_metric_rows(result) if is_project else file_metric_rows(result))
        if score_is_valid(result) else [],
        file_rows=[_file_row(f) for f in files],
    )


def brief_items(view: ReportView) -> Tuple[List[Item], int]:
    """Page 1 of the PDF: the top items by priority (critical and high
    findings, then hollow candidates, then the rest), at most
    BRIEF_LIMITS["candidates"] candidates; and how many items are left out."""
    ranked = sorted(view.findings + view.candidates, key=lambda i: _PRIORITY.get(i.severity, 5))
    chosen: List[Item] = []
    candidates = 0
    for item in ranked:
        if len(chosen) == BRIEF_LIMITS["items"]:
            break
        if item.kind == REVIEW_CANDIDATE:
            if candidates == BRIEF_LIMITS["candidates"]:
                continue
            candidates += 1
        chosen.append(item)
    return chosen, len(ranked) - len(chosen)


def top(items: List[Item], limit: int) -> Tuple[List[Item], int]:
    """The first `limit` items and how many were left out."""
    return items[:limit], max(0, len(items) - limit)


def _coverage(result: Any, is_project: bool) -> Dict[str, int]:
    """Files analyzed, excluded, unsupported, failed and not fully measured."""
    if not is_project:
        return {"analyzed": 1}
    coverage = getattr(result, "scan_coverage", None) or {}
    return {
        key: int((coverage.get(key) or {}).get("total", 0) or 0)
        for key in ("analyzed", "excluded", "unsupported", "failed", "unmeasured")
    }


def _coverage_notes(result: Any) -> List[str]:
    from slop_detector.renderer_glossary import capability_notes, incomplete_notes

    coverage = getattr(result, "scan_coverage", None) or {}
    if not coverage:
        return []
    return capability_notes(coverage) + incomplete_notes(coverage)


def _file_row(f: Any) -> Tuple[str, Optional[float], str, int]:
    score = getattr(f, "deficit_score", None)
    return (
        str(getattr(f, "file_path", "")),
        None if score is None else float(score),
        _value(getattr(f, "status", "")).upper(),
        len(getattr(f, "pattern_issues", None) or []),
    )


def _file_results(result: Any) -> List[Any]:
    out = list(getattr(result, "file_results", []) or [])
    out += list(getattr(result, "js_file_results", []) or [])
    out += list(getattr(result, "go_file_results", []) or [])
    return out


def _value(raw: Any) -> str:
    return str(getattr(raw, "value", raw) or "")


def _score(result: Any, is_project: bool) -> Optional[float]:
    if not score_is_valid(result):
        return None
    return float(result.weighted_deficit_score if is_project else result.deficit_score)


def _status(result: Any, is_project: bool) -> str:
    if not score_is_valid(result):
        return "NOT EVALUATED"
    return _value(result.overall_status if is_project else result.status).upper()


def _measurement(result: Any, is_project: bool) -> str:
    """The pattern channel: COMPLETE / PARTIAL / NO_MEASUREMENT for a project
    (`scan_coverage.measurement_state`), COMPLETE or PARTIAL for a file."""
    if is_project:
        return str((getattr(result, "scan_coverage", None) or {}).get("measurement_state", "COMPLETE"))
    return "PARTIAL" if getattr(result, "pattern_errors", None) else "COMPLETE"


def _pattern_items(f: Any) -> List[Item]:
    path = str(getattr(f, "file_path", ""))
    merged = {
        (rule, int(_field(c, "line", 0) or 0)): c
        for c in (getattr(f, "claim_findings", None) or [])
        for rule in (_field(c, "same_cause_as", None) or [])
    }
    items = []
    for issue in getattr(f, "pattern_issues", None) or []:
        rule = str(getattr(issue, "pattern_id", ""))
        line = int(getattr(issue, "line", 0) or 0)
        message = str(getattr(issue, "message", ""))
        claim = merged.get((rule, line))
        if claim is not None:
            message += f"; also breaks its docstring: {_field(claim, 'evidence')}"
        items.append(
            Item(
                kind=FINDING,
                rule=rule,
                severity=_issue_severity(issue),
                file=path,
                line=line,
                message=message,
                suggestion=str(getattr(issue, "suggestion", "") or ""),
                promise=_promise(claim),
            )
        )
    return items


def _promise(claim: Any) -> Optional[Dict[str, Any]]:
    if claim is None:
        return None
    return claim.to_dict() if hasattr(claim, "to_dict") else dict(claim)


def _field(obj: Any, name: str, default: Any = "") -> Any:
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _candidate_items(f: Any) -> List[Item]:
    path = str(getattr(f, "file_path", ""))
    return [
        Item(
            kind=REVIEW_CANDIDATE,
            rule=str(_field(c, "kind")),
            severity="",
            file=path,
            line=int(_field(c, "line", 0) or 0),
            message=f"{_field(c, 'function')}: {_field(c, 'evidence')}".rstrip(": "),
        )
        for c in (getattr(f, "semantic_findings", None) or [])
    ] + [
        Item(
            kind=REVIEW_CANDIDATE,
            rule=str(_field(c, "kind")),
            severity="",
            file=path,
            line=int(_field(c, "line", 0) or 0),
            message=f"{_field(c, 'function')}: {_field(c, 'evidence')}",
            suggestion=str(_field(c, "resolves")),
            promise=_promise(c),
        )
        for c in (getattr(f, "claim_findings", None) or [])
        if not _field(c, "same_cause_as", None)
    ]


def _semantic_state(files: List[Any]) -> SemanticState:
    """Files per state (a file without the channel, JS / Go, is not counted);
    MEASURED only when every counted file was measured. A file not measured
    carries no function counts."""
    states: Dict[str, int] = {}
    functions = unknown = 0
    reasons: Dict[str, int] = {}
    for f in files:
        coverage = getattr(f, "semantic_coverage", None) or {}
        state = coverage.get("state")
        if not state:
            continue
        states[state] = states.get(state, 0) + 1
        functions += int(coverage.get("functions", 0) or 0)
        unknown += int((coverage.get("effect_states") or {}).get("EFFECT_UNKNOWN", 0) or 0)
        for reason, n in (coverage.get("unknown_reasons") or {}).items():
            reasons[reason] = reasons.get(reason, 0) + int(n)
    return SemanticState(
        state=_overall(states), files=states, functions=functions, unknown=unknown, unknown_reasons=reasons
    )


def _claim_state(files: List[Any]) -> ClaimState:
    """Files per state (a file without the channel is not counted); claims
    counted over the measured files only."""
    states: Dict[str, int] = {}
    counts = {key: 0 for key in CLAIM_COUNTS}
    reasons: Dict[str, int] = {}
    for f in files:
        coverage = getattr(f, "claim_coverage", None) or {}
        state = coverage.get("state")
        if not state:
            continue
        states[state] = states.get(state, 0) + 1
        for key in CLAIM_COUNTS:
            value = coverage.get(key, 0)
            counts[key] += sum(value.values()) if isinstance(value, dict) else int(value or 0)
        for reason, n in (coverage.get("undecided_by_reason") or {}).items():
            reasons[reason] = reasons.get(reason, 0) + int(n)
    return ClaimState(state=_overall(states), files=states, counts=counts, undecided_by_reason=reasons)


def _overall(states: Dict[str, int]) -> str:
    if not states:
        return NOT_APPLICABLE
    if len(states) == 1:
        return next(iter(states))
    return "PARTIAL"


def short_path(path: str, root: str) -> str:
    """`path` relative to the scanned root when it is inside it."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()
