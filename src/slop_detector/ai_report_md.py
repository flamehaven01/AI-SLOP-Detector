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
from slop_detector.report_view import build_report_view
from slop_detector.work_order_rules import MODES, Ruleset
from slop_detector.work_order_rules import SCHEMA as RULESET_SCHEMA

FORMAT = "ai-slop-report/1 markdown work order"
SNIPPET_LINES = 20  # code shown per item; the full span is named so the agent can read the rest
_RANK = {
    "critical": 0,
    "high": 1,
    None: 2,
    "medium": 3,
    "low": 4,
}  # report_view._PRIORITY, candidates third


def _one_line(value: Any) -> str:
    """Text from the analyzed repository on one Markdown line (S5-G2): a line
    break is shown as a visible backslash-n, so it can never open a section
    or an item block. Code excerpts need no such step: each of their lines
    starts with its line number, and a fence closes only on a line that
    starts with backticks."""
    text = str(value).replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10))
    return text.replace(chr(10), chr(92) + "n")


def _claim_question(promise: Dict[str, Any], rules: Ruleset) -> str:
    return rules.claim.question.format(
        looked_for=_one_line(promise["looked_for"]),
        why=_one_line(promise["why"]),
        resolves=_one_line(promise["resolves"]),
    )


def _rules(items: List[Dict[str, Any]], rules: Ruleset) -> List[str]:
    """The VERIFY question of every rule present, stated once (from the ruleset)."""
    seen = sorted({(r["rule"], r["kind"]) for r in items})
    out = ["## RULES [NORM]", "VERIFY question per rule (an item block names its rule):"]
    for rule, kind in seen:
        line = (
            rules.claim.rules_line
            if rule == "claim_without_mechanism"
            else rules.question(rule, kind)
        )
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


def _shown(start: int, end: int, line: int, tier: str) -> List[int]:
    """The lines of the span an excerpt shows: all of them (T1, `full`), the
    signature and the evidence line with its neighbours (T2, `evidence`), or
    the first SNIPPET_LINES and the evidence (`capped`, no budget given)."""
    if tier == "full":
        return list(range(start, end + 1))
    if tier == "evidence":
        return sorted({start} | set(range(max(start, line - 1), min(end, line + 1) + 1)))
    shown = list(range(start, min(end, start + SNIPPET_LINES - 1) + 1))
    if line not in shown:
        shown += list(range(max(line - 2, shown[-1] + 1), min(line + 2, end) + 1))
    return shown


def _code(text: Optional[str], line: int, rel: str, tier: str = "capped") -> List[str]:
    if text is None:
        return ["code [FACT]: MISSING (file not readable)"]
    lines = text.splitlines()
    start, end, name = _span(text, line)
    shown = _shown(start, end, line, tier)
    width = len(str(end))
    out = [
        f"span [FACT]: {_one_line(rel)}:{start}-{end}" + (f" `{name}`" if name else ""),
        "```python",
    ]
    previous = None
    for n in shown:
        if previous is not None and n != previous + 1:
            out.append(f"{'':>{width}}| ... lines {previous + 1}-{n - 1} not shown")
        out.append(f"{n:>{width}}| {lines[n - 1] if n <= len(lines) else ''}")
        previous = n
    if shown[-1] < end:
        out.append(
            f"{'':>{width}}| ... lines {shown[-1] + 1}-{end} not shown (read {rel}:{start}-{end})"
        )
    elif tier == "evidence" and len(shown) < end - start + 1:
        out.append(
            f"{'':>{width}}| ... the rest of {start}-{end} not shown (read {rel}:{start}-{end})"
        )
    out.append("```")
    return out


def _measurement(header: Dict[str, Any], view: Any) -> List[str]:
    sem, claims, m = view.semantic, header["claims"], header["measurement"]
    sev = " ".join(f"{k} {v}" for k, v in header["severity"].items())
    undecided = ", ".join(
        f"{k} {v}" for k, v in sorted(claims["undecided_by_reason"].items(), key=lambda kv: -kv[1])
    )
    unknown = ", ".join(
        f"{k} {v}" for k, v in sorted(sem.unknown_reasons.items(), key=lambda kv: -kv[1])
    )
    rows = [
        "| channel | state | denominator |",
        "|---|---|---|",
        f"| pattern | {m['pattern']} | {header['files']} files; {header['findings']} findings ({sev}) |",
        f"| hollow | {m['hollow']} | {sem.functions} functions; {sem.unknown} not decidable"
        + (f" ({unknown})" if unknown else "")
        + " |",
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
            nulls.append(
                f"[NULL] {name} channel {state}: its items are HOLD; 0 there means NOT-MEASURED"
            )
    return rows + [""] + nulls


def _mode_lines(rules: Ruleset, mode: str) -> List[str]:
    """What this reader is for and may do (the ruleset's mode); an agent's
    preconditions start NOT-MEASURED, so the document alone never lets it act."""
    spec = getattr(rules.modes, mode)
    out = ["## AUTHORITY [NORM]", f"purpose: {spec.purpose}", f"authority: {spec.authority}", ""]
    if mode == "agent":
        out += [
            "## PRECONDITIONS [NORM]",
            *[f"{line} NOT-MEASURED" for line in spec.preconditions],
            f"rule: {spec.precondition_rule}",
            "",
        ]
    return out


def _contract(header: Dict[str, Any], rules: Ruleset, mode: str) -> List[str]:
    """The contract, every line from the ruleset (the header carries the same
    loop, hold_if, forbid and prove); what differs by mode is its authority,
    its preconditions, its allowed actions and its limits."""
    spec = getattr(rules.modes, mode)
    hold = [f"{rule} -> HOLD the item" for rule in header["hold_if"]] + list(rules.hard_stop)
    limits = (
        ["## LIMITS [FACT]", *[f"- {line}" for line in spec.limits], ""]
        if mode == "auditor"
        else []
    )
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
        *_mode_lines(rules, mode),
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
        *spec.allowed,
        "",
        *limits,
    ]


def _agent_read(
    text: Optional[str], record: Dict[str, Any], rules: Ruleset, current: str
) -> List[str]:
    """No code for an agent: the span to open in the target and the recheck
    it must pass first (a VOID or MISSING item is HOLD before any read)."""
    if text is None:
        return [f"read [NORM]: HOLD: {current}"]
    start, end, name = _span(text, record["line"])
    rel = _one_line(record["file"])
    return [
        f"span [FACT]: {rel}:{start}-{end}" + (f" `{name}`" if name else ""),
        f"read [NORM]: {rules.modes.agent.read.format(file=rel, span=f'{start}-{end}')}",
    ]


def _block(
    n: int,
    record: Dict[str, Any],
    root: Path,
    rules: Ruleset,
    mode: str,
    tier: str = "capped",
    sources: Optional[Dict[str, Tuple[Optional[str], str]]] = None,
) -> List[str]:
    if sources is not None and record["file"] in sources:
        text, sha = sources[record["file"]]
    else:
        text, sha = _source(root, record["file"])
        if sources is not None:
            sources[record["file"]] = (text, sha)
    bound = record["source_sha256"]
    # Code is shown only from the content the scan analyzed. A file that changed
    # after the scan, or a result with no scan-time hash, gets no code and no
    # verdict from this block: it is HOLD until re-scanned.
    if bound == MISSING:
        current, text = "MISSING: no scan-time hash; HOLD, re-scan", None
    elif sha != bound:
        current, text = (
            f"VOID: the file changed after the scan (now {sha[:16]}); HOLD, re-scan",
            None,
        )
    else:
        current = "the file is the content the scan analyzed"
    severity = record["severity"] or "review"
    out = [
        f"### W{n:02d} {record['id']} {record['kind']} {record['rule']} {severity}",
        f"at [FACT]: {_one_line(record['file'])}:{record['line']}",
        f"locator [FACT]: {record['locator'] or '(the symbol itself)'} semantic_key={record['semantic_key']}",
        f"bound_to [FACT]: sha256:{record['source_sha256']} ({current})",
        f"channel [FACT]: {record['channel_state']}",
        f"evidence [FACT]: {_one_line(record['evidence'])}",
    ]
    promise = record.get("promise")
    if promise:
        out.append(
            f"promise [FACT]: \"{_one_line(promise['promise'])}\" (docstring line {promise['promise_line']}, "
            f"{promise['claim_kind']}; basis {promise['basis']}"
            + (f": {_one_line(promise['detail'])}" if promise["detail"] else "")
            + ")"
        )
        out.append(f"verify [NORM]: {_claim_question(promise, rules)}")
    if mode == "agent":
        out += _agent_read(text, record, rules, current)
    else:
        out += (
            _code(text, record["line"], record["file"], tier)
            if text is not None
            else ["code [FACT]: NOT-APPLICABLE: HOLD"]
        )
    out += [f"fix [DERIVED]: {_one_line(record['fix'])}", ""]
    return out


def render_ai_report_md(
    result: Any,
    limit: Optional[int] = None,
    mode: str = "auditor",
    token_budget: Optional[int] = None,
) -> str:
    """The work order: every item in priority order; the first `limit` (all
    when None) as full blocks, the rest as one backlog line each. `mode` is
    the reader: auditor (the default: evidence excerpts, read-only) or agent
    (no code copied; it holds until its preconditions pass). Both render the
    same records."""
    if mode not in MODES:
        raise ai_report.AiReportInvalidError(f"unknown work-order mode {mode!r}")
    view = build_report_view(result)
    # through the module, so the work order and the JSON Lines always run the same
    # code; one ruleset read serves the header and every contract line
    rules = ai_report.ruleset()
    records = ai_report.build_records(view, rules=rules)
    ai_report.validate(records)
    header, items = records[0], sorted(records[1:], key=lambda r: _RANK.get(r["severity"], 5))
    root = Path(view.target if view.is_project else str(Path(view.target).parent))
    sources: Dict[str, Tuple[Optional[str], str]] = {}
    fixed = (header, view, rules, mode, root, sources)
    if token_budget is None:
        cut = len(items) if limit is None else max(0, limit)
        return _document(fixed, items, ["capped"] * cut + [_INDEX] * (len(items) - cut), None)
    if mode != "auditor":
        raise ai_report.AiReportInvalidError(
            "--ai-token-budget bounds the auditor work order; an agent's is bounded by --ai-limit"
        )
    if limit is not None:  # FH-S4-F02: neither bound may silently override the other
        raise ai_report.AiReportInvalidError(
            "--ai-limit and --ai-token-budget bound the work order in two different ways; give one"
        )
    return _document(fixed, items, _fit(fixed, items, token_budget), token_budget)


_INDEX = "index"  # T3: one index line
_TIER_NAME = {"full": "T1", "evidence": "T2", _INDEX: "T3"}


def estimate_tokens(text: str) -> int:
    """Estimated tokens of a text: characters / 4, rounded up. No tokenizer
    is used; the document says so beside the number."""
    return (len(text) + 3) // 4


def _binding(record: Dict[str, Any], fixed) -> str:
    """MATCH when the file is still the content the scan analyzed; VOID (it
    changed or is gone) and MISSING (no scan-time hash) hold the item."""
    root, sources = fixed[4], fixed[5]
    if record["source_sha256"] == MISSING:
        return "MISSING HOLD"
    if record["file"] not in sources:
        sources[record["file"]] = _source(root, record["file"])
    return "MATCH" if sources[record["file"]][1] == record["source_sha256"] else "VOID HOLD"


def _index_line(record: Dict[str, Any], tiered: bool, fixed) -> str:
    """One line per item not drawn as a block (FH-S4-F01): the full scan-time
    hash and whether the file still holds it, so an index line never stands
    for content the scan did not analyze."""
    line = (
        f"- {record['id']} {record['severity'] or 'review'} {record['rule']} {_one_line(record['file'])}:"
        f"{record['line']} sha256:{record['source_sha256']} binding:{_binding(record, fixed)}"
    )
    return line + f" channel:{record['channel_state']} tier:3" if tiered else line


def _fit(fixed, items: List[Dict[str, Any]], budget: int) -> List[str]:
    """The deepest tier per item, in priority order, that keeps the whole
    document within `budget`; every item keeps at least its index line."""
    tiers = [_INDEX] * len(items)
    if estimate_tokens(_document(fixed, items, tiers, budget)) > budget:
        # The document states its budget, so the floor grows with the budget's
        # digits: report the least budget that holds itself, not a guess.
        least = budget
        while estimate_tokens(_document(fixed, items, tiers, least)) > least:
            least = estimate_tokens(_document(fixed, items, tiers, least))
        raise ai_report.AiReportInvalidError(
            f"BUDGET_UNSATISFIABLE: the index of every item needs at least {least} estimated tokens; "
            f"the budget is {budget}"
        )
    header, view, rules, mode, root, sources = fixed
    room = budget * 4 - len(_document(fixed, items, tiers, budget))

    def cost(i: int, tier: str) -> int:
        """Characters a tier adds over the item's index line."""
        block = _block(i + 1, items[i], root, rules[0], mode, tier, sources)
        return len("\n".join(block)) + 1 - (len(_index_line(items[i], True, fixed)) + 1)

    # Breadth first (S4-D1): every item gets its evidence (T2) before any item
    # gets its whole body (T1). Both passes go in priority order and stop at
    # the first item that does not fit, so a lower item never gets more than
    # a higher one.
    for i in range(len(items)):
        need = cost(i, "evidence")
        if need > room:
            break
        tiers[i], room = "evidence", room - need
    for i in range(len(items)):
        if tiers[i] != "evidence":
            break
        need = cost(i, "full") - cost(i, "evidence")
        if need > room:
            break
        tiers[i], room = "full", room - need
    # The estimate above ignores small layout effects (block numbers, counts);
    # the rendered document is the check, and the last drawn item gives way.
    while estimate_tokens(_document(fixed, items, tiers, budget)) > budget:
        drawn = [i for i, tier in enumerate(tiers) if tier != _INDEX]
        last = drawn[-1]
        tiers[last] = "evidence" if tiers[last] == "full" else _INDEX
    return tiers


def _document(fixed, items: List[Dict[str, Any]], tiers: List[str], budget: Optional[int]) -> str:
    header, view, rules, mode, root, sources = fixed
    drawn = [(r, t) for r, t in zip(items, tiers) if t != _INDEX]
    listed = [r for r, t in zip(items, tiers) if t == _INDEX]
    score = "NOT-MEASURED" if header["score"] is None else f"{header['score']:.1f}"
    out = [
        "# AI-SLOP WORK ORDER",
        f"format: {FORMAT} | tool {header['tool']} {header['version']} | engine {header['engine']}",
        f"target: {_one_line(Path(view.target).name)} | files {header['files']} | score {score} {header['status']} "
        "(pattern channel only)",
        f"items: {len(items)} | work order {len(drawn)} | backlog {len(listed)}",
        f"ruleset: {RULESET_SCHEMA} {rules[0].version} sha256:{rules[1]}",
        f"mode: {mode}",
    ]
    if budget is not None:
        counts = {
            name: sum(1 for t in tiers if _TIER_NAME[t] == name) for name in ("T1", "T2", "T3")
        }
        out.append(
            f"budget: {budget} estimated tokens (characters / 4, not a tokenizer count) | tiers T1 {counts['T1']}, "
            f"T2 {counts['T2']}, T3 {counts['T3']} (T1 whole function, T2 signature, evidence and the range to "
            "read, T3 index line)"
        )
    out += [
        "",
        *_contract(header, rules[0], mode),
        "## MEASUREMENT [FACT]",
        *_measurement(header, view),
        "",
        *_rules(items, rules[0]),
        "## WORK-ORDER",
        "order: critical, high, review candidates, medium, low",
        "",
    ]
    for n, (record, tier) in enumerate(drawn, 1):
        out += _block(n, record, root, rules[0], mode, tier, sources)
    out += ["## BACKLOG", "same contract; open the file and work the item as a WORK-ORDER block"]
    if listed:
        out += [_index_line(r, budget is not None, fixed) for r in listed]
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
