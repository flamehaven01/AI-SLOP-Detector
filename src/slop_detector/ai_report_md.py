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

from slop_detector import ai_report
from slop_detector.ai_report import MISSING
from slop_detector.work_order_rules import SCHEMA as RULESET_SCHEMA, Ruleset
from slop_detector.report_view import build_report_view

FORMAT = "ai-slop-report/1 markdown work order"
SNIPPET_LINES = 20  # code shown per item; the full span is named so the agent can read the rest
_RANK = {"critical": 0, "high": 1, None: 2, "medium": 3, "low": 4}  # report_view._PRIORITY, candidates third

def _claim_question(promise: Dict[str, Any], rules: Ruleset) -> str:
    return rules.claim.question.format(
        looked_for=promise["looked_for"], why=promise["why"], resolves=promise["resolves"]
    )


def _rules(items: List[Dict[str, Any]], rules: Ruleset) -> List[str]:
    """The VERIFY question of every rule present, stated once (from the ruleset)."""
    seen = sorted({(r["rule"], r["kind"]) for r in items})
    out = ["## RULES [NORM]", "VERIFY question per rule (an item block names its rule):"]
    for rule, kind in seen:
        line = rules.claim.rules_line if rule == "claim_without_mechanism" else rules.question(rule, kind)
        out.append(f"- {rule}: {line}")
    return out + [""]


def _source(root: Path, rel: str) -> Tuple[Optional[str], str]:
    """(text, sha256) of the file as it is now, to compare with the scan-time
    hash; (None, MISSING) when unreadable."""
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


def _contract(header: Dict[str, Any], rules: Ruleset) -> List[str]:
    """The contract, every line from the ruleset (the header carries the same
    loop, hold_if, forbid and prove)."""
    hold = [f"{rule} -> HOLD the item" for rule in header["hold_if"]] + list(rules.hard_stop)
    return [
        "## CONTRACT [FORMAT]",
        f"precedence: {rules.precedence}",
        f"tags: {rules.tags}",
        f"empty values: {rules.empty_values}",
        f"self-falsifier: {rules.self_falsifier}",
        f"loop per item: {' -> '.join(header['loop'])}",
        f"VERIFY: {rules.verify_step}",
        f"PROVE: {header['prove']['suggestion']}; expect {header['prove']['expect']}",
        "",
        "## HARD-STOP [NORM]",
        *[f"HS-{n:02d} {line}" for n, line in enumerate(hold, 1)],
        "",
        "## FORBID [NORM]",
        *[f"- {rule}" for rule in header["forbid"]],
        "",
        "## INVARIANTS [NORM]",
        *[f"- {line}" for line in rules.invariants],
        "",
        "## ALLOWED [NORM]",
        *rules.allowed,
        "",
    ]


def _block(n: int, record: Dict[str, Any], root: Path, rules: Ruleset) -> List[str]:
    text, sha = _source(root, record["file"])
    bound = record["source_sha256"]
    # Code is shown only from the content the scan analyzed. A file that changed
    # after the scan, or a result with no scan-time hash, gets no code and no
    # verdict from this block: it is HOLD until re-scanned.
    if bound == MISSING:
        current, text = "MISSING: no scan-time hash; HOLD, re-scan", None
    elif sha != bound:
        current, text = f"VOID: the file changed after the scan (now {sha[:16]}); HOLD, re-scan", None
    else:
        current = "the file is the content the scan analyzed"
    severity = record["severity"] or "review"
    out = [
        f"### W{n:02d} {record['id']} {record['kind']} {record['rule']} {severity}",
        f"at [FACT]: {record['file']}:{record['line']}",
        f"locator [FACT]: {record['locator'] or '(the symbol itself)'} semantic_key={record['semantic_key']}",
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
        out.append(f"verify [NORM]: {_claim_question(promise, rules)}")
    out += _code(text, record["line"], record["file"]) if text is not None else ["code [FACT]: NOT-APPLICABLE: HOLD"]
    out += [f"fix [DERIVED]: {record['fix']}", ""]
    return out


def render_ai_report_md(result: Any, limit: Optional[int] = None) -> str:
    """The work order: every item in priority order; the first `limit` (all
    when None) as full blocks, the rest as one backlog line each."""
    view = build_report_view(result)
    # through the module, so the work order and the JSON Lines always run the same
    # code; one ruleset read serves the header and every contract line
    rules = ai_report.ruleset()
    records = ai_report.build_records(view, rules=rules)
    ai_report.validate(records)
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
        f"ruleset: {RULESET_SCHEMA} {rules[0].version} sha256:{rules[1]}",
        "",
        *_contract(header, rules[0]),
        "## MEASUREMENT [FACT]",
        *_measurement(header, view),
        "",
        *_rules(items, rules[0]),
        "## WORK-ORDER",
        "order: critical, high, review candidates, medium, low",
        "",
    ]
    for n, record in enumerate(blocks, 1):
        out += _block(n, record, root, rules[0])
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
