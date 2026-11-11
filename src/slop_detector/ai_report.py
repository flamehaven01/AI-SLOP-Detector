"""The AI report `ai-slop-report/1`: JSON Lines for an agent (docs/REPORTS.md 7).

Line 1 is the header (versions, target, measurement, counts, and the rules
shared by every item: hold, forbidden fixes, verify, prove); every other
line is one finding or hollow review candidate, bound to the SHA-256 of the
file it was computed from. Each record is validated against
its model before anything is written: an invalid report is never emitted.
`prove` is a verification suggestion; nothing here is meant to be run by an
agent unattended.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from slop_detector import __version__
from slop_detector.claim_findings import RULE as CLAIM_RULE
from slop_detector.finding_identity import MODULE, semantic_part
from slop_detector.work_order_rules import Ruleset, RulesetInvalid, header_fields, load_ruleset
from slop_detector.report_view import FINDING, REVIEW_CANDIDATE, Item, ReportView, build_report_view, short_path

SCHEMA = "ai-slop-report/1"
MISSING = "MISSING"
# The rules shared by every item (loop, hold_if, forbid, verify, prove) come
# from the work-order ruleset (work_order_rules), stated once in the header.


class AiReportInvalid(RuntimeError):
    """The report failed its own schema; nothing was written."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RulesetRef(_Strict):
    schema_: Literal["ai-slop-work-order-rules/2"] = Field(alias="schema")
    version: str
    sha256: str


class Measurement(_Strict):
    pattern: str
    hollow: str
    claims: str


class Claims(_Strict):
    """Docstring promises over the measured files, by state (claim_judge)."""

    extracted_claims: int
    supported: int
    delegated_in_module: int
    provided_elsewhere: int
    undecided: int
    contradicted: int
    unmeasured: int
    not_evaluated: int
    candidates: int
    merged: int
    undecided_by_reason: Dict[str, int]


class Promise(_Strict):
    """The docstring promise an item breaks (claim_findings.ClaimFinding)."""

    function: str
    line: int
    claim_kind: str
    promise: str
    promise_line: int
    basis: str
    detail: str
    looked_for: str
    why: str
    resolves: str
    same_cause_as: List[str]
    kind: Literal["claim_without_mechanism"]
    status: str


class Header(_Strict):
    schema_: Literal["ai-slop-report/1"] = Field(alias="schema")
    record: Literal["header"]
    tool: Literal["ai-slop-detector"]
    version: str
    engine: str
    target: str
    files: int
    score: Optional[float]
    status: str
    measurement: Measurement
    findings: int
    candidates: int
    severity: Dict[str, int]
    hollow_functions: int
    hollow_not_decidable: int
    claims: Claims
    emitted: int
    truncated: int
    loop: List[str]
    hold_if: List[str]
    forbid: List[str]
    verify: Dict[str, str]
    prove: Dict[str, str]
    ruleset: RulesetRef


class Record(_Strict):
    record: Literal["item"]
    id: str
    semantic_key: str
    cause_key: str
    symbol: str
    locator: str
    kind: Literal["FINDING", "REVIEW_CANDIDATE"]
    rule: str
    severity: Optional[Literal["critical", "high", "medium", "low"]]
    file: str
    line: int
    source_sha256: str
    source_origin: Literal["file_bytes", "string_utf8", "MISSING"]
    channel_state: str
    evidence: str
    fix: str
    promise: Optional[Promise] = None


def schema() -> Dict[str, Any]:
    """The JSON Schema of the two record kinds (for tooling and docs)."""
    return {"$id": SCHEMA, "header": Header.model_json_schema(), "item": Record.model_json_schema()}


def _cause_key(item: Item, rel: str) -> str:
    """The cause without the line's text: kind, rule, path, symbol, subject.
    A reworded violation (a TODO with new words) keeps it."""
    key = f"{item.kind}|{item.rule}|{rel}|{item.symbol or MODULE}|{item.subject or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _semantic_key(item: Item, rel: str) -> str:
    """What the finding is (finding_identity.semantic_part): kind, rule, path,
    symbol, subject and the text of its line."""
    key = f"{item.kind}|{item.rule}|{rel}|{semantic_part(item.symbol, item.subject, item.fingerprint, item.line)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _item_id(item: Item, rel: str) -> str:
    """The semantic key and the structural locator (which copy, in this
    snapshot). Two items with one id are a defect the report refuses
    (validate), never renumbered."""
    key = f"{_semantic_key(item, rel)}|{item.locator or ''}".encode("utf-8")
    prefix = "F" if item.kind == FINDING else "C"
    return prefix + hashlib.sha256(key).hexdigest()[:12]


def _record(item: Item, root: str, view: ReportView) -> Dict[str, Any]:
    rel = short_path(item.file, root)
    finding = item.kind == FINDING
    record = {
        "record": "item",
        "id": _item_id(item, rel),
        "semantic_key": _semantic_key(item, rel),
        "cause_key": _cause_key(item, rel),
        "symbol": item.symbol or MODULE,
        "locator": item.locator or "",
        "kind": item.kind,
        "rule": item.rule,
        "severity": item.severity if finding else None,
        "file": rel,
        "line": item.line,
        # the bytes the scan analyzed; never a later read of the file
        "source_sha256": item.source_sha256 or MISSING,
        "source_origin": item.content_origin or MISSING,
        "channel_state": _channel_state(item, view),
        "evidence": item.message or MISSING,
        "fix": item.suggestion or (MISSING if finding else "NOT-APPLICABLE: decide in VERIFY first"),
    }
    if item.promise is not None:
        record["promise"] = item.promise
    return record


def _channel_state(item: Item, view: ReportView) -> str:
    if item.kind == FINDING:
        return view.measurement
    return view.claims.state if item.rule == CLAIM_RULE else view.semantic.state


def ruleset() -> Tuple[Ruleset, str]:
    """The checked ruleset and its digest; AiReportInvalid when it cannot be trusted."""
    try:
        return load_ruleset()
    except RulesetInvalid as exc:
        raise AiReportInvalid(str(exc)) from exc


def build_records(
    view: ReportView, limit: Optional[int] = None, rules: Optional[Tuple[Ruleset, str]] = None
) -> List[Dict[str, Any]]:
    """The header and the item records (findings by severity, then
    candidates), at most `limit` items; the header says how many were left."""
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION

    root = view.target if view.is_project else str(Path(view.target).parent)
    items = view.findings + view.candidates
    kept = items if limit is None else items[: max(0, limit)]
    header = {
        "schema": SCHEMA,
        "record": "header",
        "tool": "ai-slop-detector",
        "version": __version__,
        "engine": CACHE_ENGINE_VERSION,
        "target": view.target,
        "files": view.files,
        "score": view.score,
        "status": view.status,
        "measurement": {"pattern": view.measurement, "hollow": view.semantic.state, "claims": view.claims.state},
        "findings": len(view.findings),
        "candidates": len(view.candidates),
        "severity": view.severity,
        "hollow_functions": view.semantic.functions,
        "hollow_not_decidable": view.semantic.unknown,
        "claims": dict(view.claims.counts, undecided_by_reason=dict(view.claims.undecided_by_reason)),
        "emitted": len(kept),
        "truncated": len(items) - len(kept),
        **header_fields(*(rules or ruleset())),
    }
    return [header] + [_record(i, root, view) for i in kept]


def validate(records: List[Dict[str, Any]]) -> None:
    """Every record against its model; raise AiReportInvalid on the first failure."""
    try:
        if not records:
            raise AiReportInvalid("an AI report needs its header record")
        Header.model_validate(records[0])
        for record in records[1:]:
            Record.model_validate(record)
        ids = [r["id"] for r in records[1:]]
        if len(set(ids)) != len(ids):
            raise AiReportInvalid("the AI report has two items with one id")
    except ValidationError as exc:
        raise AiReportInvalid(f"the AI report failed its schema: {exc.error_count()} error(s)") from exc


def _line(record: Dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, allow_nan=False)


def render_ai_report(result: Any, limit: Optional[int] = None) -> str:
    """The validated JSON Lines text of an analysis result."""
    records = build_records(build_report_view(result), limit)
    validate(records)
    return "\n".join(_line(r) for r in records) + "\n"


def prove_state(
    before: List[Dict[str, Any]], after: List[Dict[str, Any]], item_id: str, symbol_present: bool
) -> str:
    """PERSISTS, FIXED_CANDIDATE or HOLD for one item of `before`, from the
    item records of a re-scan. A changed id is never a fix by itself: the
    locator addresses one snapshot, the semantic key says what the finding is.
    FIXED_CANDIDATE still needs the tests (PROVE); `symbol_present` comes from
    the caller, who can see whether the item's function or class still exists."""
    if not symbol_present:
        return "HOLD"  # moved, renamed or deleted: nothing here to prove
    after_ids = {r["id"] for r in after}
    if item_id in after_ids:
        return "PERSISTS"
    same_text = _left(before, after, item_id, "semantic_key")
    if same_text in ("PERSISTS", "HOLD"):
        return same_text
    # Fewer (or no) copies of the text: provisional until the cause agrees
    # (FH-WO-006: a reworded twin keeps the cause at its count).
    same_cause = _left(before, after, item_id, "cause_key")
    if same_cause is None or same_cause == "FIXED_CANDIDATE":
        return "FIXED_CANDIDATE"
    return "HOLD"  # the cause is left as often as before (reworded), or the match is ambiguous


def _left(before: List[Dict[str, Any]], after: List[Dict[str, Any]], item_id: str, field: str) -> Optional[str]:
    """What the re-scan says about the item among the records sharing its
    `field`; None when none of them is left."""
    after_ids = {r["id"] for r in after}
    key = next(r[field] for r in before if r["id"] == item_id)
    same_before = [r["id"] for r in before if r[field] == key]
    same_after = [r for r in after if r[field] == key]
    if not same_after:
        return None
    if len(same_after) >= len(same_before):
        return "PERSISTS"  # as many as before: this one moved or was reworded
    others = set(same_before) - {item_id}
    if len(same_after) == len(same_before) - 1 and others <= after_ids:
        return "FIXED_CANDIDATE"  # every other one kept its id; this one is gone
    return "HOLD"  # fewer under new ids: which one went is not known
