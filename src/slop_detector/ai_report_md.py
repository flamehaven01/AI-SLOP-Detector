"""The AI work order: the AI report `ai-slop-report/1` as one Markdown document
an agent reads to verify, fix or reject, prove and report every item
(docs/REPORTS.md 7). Not for people: fixed section order, exact identifiers,
the rules stated once, then one block per item with its code.

It is built from the validated records (`ai_report.build_records`), so it
cannot disagree with the JSON Lines. The contract follows the user's handoff
form: precedence, tags on every content line, explicit empty values, and a
self-falsifier per item (the file's SHA-256).
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from slop_detector.ai_report import FORBID, HOLD_IF, MISSING, build_records, validate
from slop_detector.report_view import build_report_view

FORMAT = "ai-slop-report/1 markdown work order"
SNIPPET_LINES = 20  # code shown per item; the full span is named so the agent can read the rest
_RANK = {"critical": 0, "high": 1, None: 2, "medium": 3, "low": 4}  # report_view._PRIORITY, candidates third

# What decides ACK or REJECT, by rule family. A rule outside the table gets
# the header's question for its kind.
_FAMILIES = {
    "size": (
        {"god_function", "nested_complexity", "deep_nesting"},
        "Does the function do more than one job? ACK if it splits into named steps with the same behavior; "
        "REJECT if it is one job laid out flat (a table, a dispatch, a fixed sequence).",
    ),
    "escape": (
        {"lint_escape"},
        "Is the silenced warning a real defect here? ACK: fix the cause and drop the marker; "
        "REJECT: the marker is narrow (one code) and the reason is stated beside it.",
    ),
    "placeholder": (
        {"return_constant_stub", "return_none_placeholder", "return_input_stub", "pass_placeholder",
         "ellipsis_placeholder", "not_implemented", "interface_only_class", "todo_comment", "fixme_comment",
         "hack_comment", "xxx_comment"},
        "Do callers get the behavior the name and docstring promise? ACK: implement it or say in the code what "
        "is intended; REJECT: the body is the whole contract (a declared default, a registered no-op, an "
        "abstract hook) and that is stated.",
    ),
    "exception": (
        {"empty_except", "bare_except", "failure_as_success"},
        "Can the caller tell that the operation failed? ACK: handle, re-raise or report the failure; "
        "REJECT: the failure is expected, harmless and the handler says why.",
    ),
    "dependency": (
        {"runtime_unavailable_dependency", "undeclared_optional_dependency", "declared_outside_primary_metadata",
         "phantom_import", "phantom_member"},
        "Does a clean install provide this import at runtime? ACK: declare it or guard it with the documented "
        "fallback; REJECT: name the declaration or guard that provides it (file:line).",
    ),
    "clone": (
        {"function_clone_cluster", "exact_duplicate_pair"},
        "Must the copies change together? ACK: keep one and call it; REJECT: they are meant to diverge "
        "(name the difference that will appear).",
    ),
    "input": (
        {"ignored_parameter", "input_never_used"},
        "Should the value change the result or an effect? ACK: use it or remove it from the signature with its "
        "callers; REJECT: the signature is fixed by a caller or protocol (name it).",
    ),
    "hollow": (
        {"success_without_effect", "effect_never_runs", "failure_reported_as_success",
         "finally_return_hides_failure", "success_ignores_outcome"},
        "Does the reported success reflect work that happened? ACK: perform the effect or report the real "
        "outcome; REJECT: name the effect the detector could not see (file:line).",
    ),
}


def _question(rule: str, kind: str, default: Dict[str, str]) -> str:
    for rules, question in _FAMILIES.values():
        if rule in rules:
            return question
    return default[kind]


def _claim_question(promise: Dict[str, Any]) -> str:
    return (
        f"the body needs {promise['looked_for']}; found: {promise['why']}. ACK: {promise['resolves']}; "
        "REJECT: name the mechanism the detector missed (file:line)"
    )


def _rules(items: List[Dict[str, Any]], header: Dict[str, Any]) -> List[str]:
    """The VERIFY question of every rule present, stated once."""
    seen = sorted({(r["rule"], r["kind"]) for r in items})
    out = ["## RULES [NORM]", "VERIFY question per rule (an item block names its rule):"]
    for rule, kind in seen:
        if rule == "claim_without_mechanism":
            out.append(f"- {rule}: is the docstring promise kept? The item block states what the body needs")
        else:
            out.append(f"- {rule}: {_question(rule, kind, header['verify'])}")
    return out + [""]


def _source(root: Path, rel: str) -> Tuple[Optional[str], str]:
    """(text, sha256) of the file as it is now; (None, MISSING) when unreadable."""
    try:
        data = (root / rel).read_bytes()
    except OSError:
        return None, MISSING
    return data.decode("utf-8", errors="replace"), hashlib.sha256(data).hexdigest()


def _span(text: str, line: int) -> Tuple[int, int, str]:
    """The innermost function or class holding `line`, else the line itself."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return line, line, ""
    best: Tuple[int, int, str] = (line, line, "")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            end = getattr(node, "end_lineno", None) or node.lineno
            if start <= line <= end and (not best[2] or end - start <= best[1] - best[0]):
                best = (start, end, node.name)
    return best


def _code(text: Optional[str], line: int, rel: str) -> List[str]:
    if text is None:
        return ["code [FACT]: MISSING (file not readable)"]
    lines = text.splitlines()
    start, end, name = _span(text, line)
    shown = list(range(start, min(end, start + SNIPPET_LINES - 1) + 1))
    if line not in shown:
        shown += list(range(max(line - 2, shown[-1] + 1), min(line + 2, end) + 1))
    width = len(str(end))
    out = [f"span [FACT]: {rel}:{start}-{end}" + (f" `{name}`" if name else ""), "```python"]
    previous = None
    for n in shown:
        if previous is not None and n != previous + 1:
            out.append(f"{'':>{width}}| ... lines {previous + 1}-{n - 1} not shown")
        out.append(f"{n:>{width}}| {lines[n - 1] if n <= len(lines) else ''}")
        previous = n
    if shown[-1] < end:
        out.append(f"{'':>{width}}| ... lines {shown[-1] + 1}-{end} not shown (read {rel}:{start}-{end})")
    out.append("```")
    return out


def _measurement(header: Dict[str, Any], view: Any) -> List[str]:
    sem, claims, m = view.semantic, header["claims"], header["measurement"]
    sev = " ".join(f"{k} {v}" for k, v in header["severity"].items())
    undecided = ", ".join(f"{k} {v}" for k, v in sorted(claims["undecided_by_reason"].items(), key=lambda kv: -kv[1]))
    unknown = ", ".join(f"{k} {v}" for k, v in sorted(sem.unknown_reasons.items(), key=lambda kv: -kv[1]))
    rows = [
        "| channel | state | denominator |",
        "|---|---|---|",
        f"| pattern | {m['pattern']} | {header['files']} files; {header['findings']} findings ({sev}) |",
        f"| hollow | {m['hollow']} | {sem.functions} functions; {sem.unknown} not decidable"
        + (f" ({unknown})" if unknown else "") + " |",
        f"| claims | {m['claims']} | {claims['extracted_claims']} docstring promises; supported {claims['supported']}, "
        f"delegated {claims['delegated_in_module']}, undecided {claims['undecided']}"
        + (f" ({undecided})" if undecided else "")
        + f", contradicted {claims['contradicted']} (candidates {claims['candidates']}, merged {claims['merged']}), "
        f"not evaluated {claims['not_evaluated']}, unmeasured {claims['unmeasured']} |",
    ]
    nulls = []
    if header["candidates"] == 0:
        nulls.append("[NULL] review candidates: 0 in the measured channels")
    if claims["contradicted"] == 0 and m["claims"] in ("MEASURED", "PARTIAL"):
        nulls.append("[NULL] claims contradicted: 0; an undecided promise is not a pass")
    for name, state in m.items():
        if state not in ("COMPLETE", "MEASURED"):
            nulls.append(f"[NULL] {name} channel {state}: its items are HOLD; 0 there means NOT-MEASURED")
    return rows + [""] + nulls


def _contract(header: Dict[str, Any]) -> List[str]:
    return [
        "## CONTRACT [FORMAT]",
        "precedence: HARD-STOP > INVARIANTS > ALLOWED > WORK-ORDER > BACKLOG",
        "tags: [FACT] measured by the detector at the locator | [DERIVED] the detector's fix direction, advisory | "
        "[NORM] rule for the agent | [NULL] measured as nothing",
        "empty values: NOT-MEASURED | NOT-APPLICABLE: <why> | MISSING",
        "self-falsifier: each item is bound_to sha256 of its file; void_if sha256(file) != bound_to -> the item is "
        "VOID: HOLD it, do not repair from this document, re-scan",
        f"loop per item: {' -> '.join(header['loop'])}",
        "VERIFY: bound_to MATCH, channel COMPLETE or MEASURED, then the rule's question (RULES) on the code shown",
        f"PROVE: {header['prove']['suggestion']}; expect {header['prove']['expect']}",
        "",
        "## HARD-STOP [NORM]",
        *[f"HS-{n:02d} {rule} -> HOLD the item" for n, rule in enumerate(HOLD_IF, 1)],
        f"HS-{len(HOLD_IF) + 1:02d} the fix needs a FORBID change -> stop, REPORT HOLD",
        f"HS-{len(HOLD_IF) + 2:02d} the fix changes a public signature, a return type or code outside the item's span "
        "-> stop, needs a decision (D-*)",
        f"HS-{len(HOLD_IF) + 3:02d} running code from the analyzed repository without an approved test profile",
        f"HS-{len(HOLD_IF) + 4:02d} a REPORT field filled with placeholder text instead of NOT-MEASURED",
        "",
        "## FORBID [NORM]",
        *[f"- {rule}" for rule in FORBID],
        "",
        "## INVARIANTS [NORM]",
        "- score != review candidates: the score comes from the pattern channel only; a candidate never moves it",
        "- FINDING != proven defect; REVIEW_CANDIDATE != defect: both are decided in VERIFY",
        "- UNDECIDED != pass; NOT-MEASURED != 0",
        "- REJECT with evidence is a result, not a failure: it is the false-alarm channel",
        "",
        "## ALLOWED [NORM]",
        "A-01 read any file of the target",
        "A-02 edit inside the item's span",
        "A-03 add or change a test that proves the fix",
        "A-04 claim_without_mechanism: reword the docstring to what the function does",
        "D-01 decision first: split a function across files, merge clones across modules",
        "D-02 decision first: add or change a dependency declaration",
        "",
    ]


def _block(n: int, record: Dict[str, Any], root: Path) -> List[str]:
    text, sha = _source(root, record["file"])
    # The code below is shown only from the bound content: a file that changed
    # since its record was made is marked VOID (no verdict from this block).
    current = "code below read from this content" if sha == record["source_sha256"] else f"VOID: now {sha[:16]}"
    severity = record["severity"] or "review"
    out = [
        f"### W{n:02d} {record['id']} {record['kind']} {record['rule']} {severity}",
        f"at [FACT]: {record['file']}:{record['line']}",
        f"bound_to [FACT]: sha256:{record['source_sha256']} ({current})",
        f"channel [FACT]: {record['channel_state']}",
        f"evidence [FACT]: {record['evidence']}",
    ]
    promise = record.get("promise")
    if promise:
        out.append(
            f"promise [FACT]: \"{promise['promise']}\" (docstring line {promise['promise_line']}, "
            f"{promise['claim_kind']}; basis {promise['basis']}"
            + (f": {promise['detail']}" if promise["detail"] else "") + ")"
        )
        out.append(f"verify [NORM]: {_claim_question(promise)}")
    out += _code(text, record["line"], record["file"])
    out += [f"fix [DERIVED]: {record['fix']}", ""]
    return out


def render_ai_report_md(result: Any, limit: Optional[int] = None) -> str:
    """The work order: every item in priority order; the first `limit` (all
    when None) as full blocks, the rest as one backlog line each."""
    view = build_report_view(result)
    records = build_records(view)
    validate(records)
    header, items = records[0], sorted(records[1:], key=lambda r: _RANK.get(r["severity"], 5))
    root = Path(view.target if view.is_project else str(Path(view.target).parent))
    blocks = items if limit is None else items[: max(0, limit)]
    backlog = items[len(blocks):]
    score = "NOT-MEASURED" if header["score"] is None else f"{header['score']:.1f}"
    out = [
        "# AI-SLOP WORK ORDER",
        f"format: {FORMAT} | tool {header['tool']} {header['version']} | engine {header['engine']}",
        f"target: {Path(view.target).name} | files {header['files']} | score {score} {header['status']} "
        "(pattern channel only)",
        f"items: {len(items)} | work order {len(blocks)} | backlog {len(backlog)}",
        "",
        *_contract(header),
        "## MEASUREMENT [FACT]",
        *_measurement(header, view),
        "",
        *_rules(items, header),
        "## WORK-ORDER",
        "order: critical, high, review candidates, medium, low",
        "",
    ]
    for n, record in enumerate(blocks, 1):
        out += _block(n, record, root)
    out += ["## BACKLOG", "same contract; open the file and work the item as a WORK-ORDER block"]
    if backlog:
        out += [
            f"- {r['id']} {r['severity'] or 'review'} {r['rule']} {r['file']}:{r['line']} sha256:{r['source_sha256'][:16]}"
            for r in backlog
        ]
    else:
        out.append("NOT-APPLICABLE: every item is in the work order")
    out += [
        "",
        "## RESPONSE-FORM [FORMAT]",
        "one line per item worked, in order, then one summary line:",
        "`<id> ACK|REJECT|HOLD verify=PASS|FAIL fix=<one line|NOT-APPLICABLE: why> "
        "prove=PASS|FAIL|NOT-MEASURED evidence=<file:line or test name>`",
        "`SUMMARY worked=<n> ack=<n> reject=<n> hold=<n> proved=<n> not_worked=<n>`",
        "",
    ]
    return "\n".join(out)
