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
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from slop_detector import __version__
from slop_detector.report_view import FINDING, REVIEW_CANDIDATE, Item, ReportView, build_report_view, short_path

SCHEMA = "ai-slop-report/1"
MISSING = "MISSING"
LOOP = ["VERIFY", "ACK_OR_REJECT", "FIX", "PROVE", "REPORT"]
HOLD_IF = [
    "the file's SHA-256 differs from source_sha256",
    "the item's channel state is not MEASURED or COMPLETE",
]
FORBID = [
    "a suppression comment or a noqa / pragma marker",
    "a threshold, weight or config change",
    "deleting or renaming the function to make the item vanish",
]
# Rules shared by every item, stated once in the header. `prove` is a
# suggestion for a person or an approved test profile, not a command to run.
PROVE = {
    "suggestion": "re-scan the item's file with the same configuration",
    "expect": "the item's id is absent, no new item appears, the project's tests pass",
}
_VERIFY = {
    FINDING: "check the evidence at file:line; ACK and fix, or REJECT with the reason it does not apply",
    REVIEW_CANDIDATE: (
        "decide whether a real effect or use is expected here; if yes fix, if no REJECT with the reason"
    ),
}


class AiReportInvalid(RuntimeError):
    """The report failed its own schema; nothing was written."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Measurement(_Strict):
    pattern: str
    hollow: str


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
    emitted: int
    truncated: int
    loop: List[str]
    hold_if: List[str]
    forbid: List[str]
    verify: Dict[str, str]
    prove: Dict[str, str]


class Record(_Strict):
    record: Literal["item"]
    id: str
    kind: Literal["FINDING", "REVIEW_CANDIDATE"]
    rule: str
    severity: Optional[Literal["critical", "high", "medium", "low"]]
    file: str
    line: int
    source_sha256: str
    channel_state: str
    evidence: str
    fix: str


def schema() -> Dict[str, Any]:
    """The JSON Schema of the two record kinds (for tooling and docs)."""
    return {"$id": SCHEMA, "header": Header.model_json_schema(), "item": Record.model_json_schema()}


def _sha256(path: str) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return MISSING


def _item_id(item: Item, rel: str) -> str:
    """Stable across runs of the same source: kind, rule, path and line."""
    key = f"{item.kind}|{item.rule}|{rel}|{item.line}".encode("utf-8")
    prefix = "F" if item.kind == FINDING else "C"
    return prefix + hashlib.sha256(key).hexdigest()[:12]


def _record(item: Item, root: str, view: ReportView, digests: Dict[str, str]) -> Dict[str, Any]:
    rel = short_path(item.file, root)
    if item.file not in digests:
        digests[item.file] = _sha256(item.file)
    finding = item.kind == FINDING
    return {
        "record": "item",
        "id": _item_id(item, rel),
        "kind": item.kind,
        "rule": item.rule,
        "severity": item.severity if finding else None,
        "file": rel,
        "line": item.line,
        "source_sha256": digests[item.file],
        "channel_state": view.measurement if finding else view.semantic.state,
        "evidence": item.message or MISSING,
        "fix": item.suggestion or (MISSING if finding else "NOT-APPLICABLE: decide in VERIFY first"),
    }


def build_records(view: ReportView, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """The header and the item records (findings by severity, then
    candidates), at most `limit` items; the header says how many were left."""
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION

    root = view.target if view.is_project else str(Path(view.target).parent)
    items = view.findings + view.candidates
    kept = items if limit is None else items[: max(0, limit)]
    digests: Dict[str, str] = {}
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
        "measurement": {"pattern": view.measurement, "hollow": view.semantic.state},
        "findings": len(view.findings),
        "candidates": len(view.candidates),
        "severity": view.severity,
        "hollow_functions": view.semantic.functions,
        "hollow_not_decidable": view.semantic.unknown,
        "emitted": len(kept),
        "truncated": len(items) - len(kept),
        "loop": LOOP,
        "hold_if": HOLD_IF,
        "forbid": FORBID,
        "verify": _VERIFY,
        "prove": PROVE,
    }
    return [header] + [_record(i, root, view, digests) for i in kept]


def validate(records: List[Dict[str, Any]]) -> None:
    """Every record against its model; raise AiReportInvalid on the first failure."""
    try:
        if not records:
            raise AiReportInvalid("an AI report needs its header record")
        Header.model_validate(records[0])
        for record in records[1:]:
            Record.model_validate(record)
    except ValidationError as exc:
        raise AiReportInvalid(f"the AI report failed its schema: {exc.error_count()} error(s)") from exc


def _line(record: Dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, allow_nan=False)


def render_ai_report(result: Any, limit: Optional[int] = None) -> str:
    """The validated JSON Lines text of an analysis result."""
    records = build_records(build_report_view(result), limit)
    validate(records)
    return "\n".join(_line(r) for r in records) + "\n"
