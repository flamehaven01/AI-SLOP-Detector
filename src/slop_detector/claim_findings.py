"""Claim channel output (H3-3): a CONTRADICTED claim becomes a review
candidate `claim_without_mechanism`; every other state is only counted.

Never scored. One candidate per contradicted claim, unless a pattern finding
on the same function already reports the same evidence: then the claim is
attached to that finding (`same_cause_as`) instead of standing beside it.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from slop_detector.claim_judge import CONTRADICTED, UNMEASURED, judge_claims
from slop_detector.claims import _docstring_line

RULE = "claim_without_mechanism"

# What the judge looked for, by claim kind (claim_judge.RULES).
LOOKED_FOR = {
    "live_data": "an I/O call by import origin, or an open call that could fetch",
    "computed_result": "a value computed from the inputs, or an open call that could compute it",
    "validation": "a raise or assert, an outcome read from the input, or two different outcomes",
    "rejection": "a raise or assert, an outcome read from the input, or two different outcomes",
    "aggregation": "a loop, comprehension or reduction over the members",
    "pagination": "a loop that calls, yield from a call, or recursion",
    "parallel": "a concurrent call (pool, thread, process, task) or an await",
}
# Why the bounded scope cannot hold it, by verdict basis.
WHY = {
    "literal_result": "every return is a literal",
    "single_outcome": "every path gives the same outcome",
    "single_member_read": "only one member is read",
    "single_request": "one request, never repeated",
    "no_request": "no request at all; every return is a literal",
    "no_concurrent_call": "no call that could run concurrently",
}
RESOLVES = "implement the mechanism, or change the docstring to what the function does"
# A pattern rule that fires only on a body whose one statement (after logging)
# is a constant return reports the evidence of these bases: a literal result,
# one outcome, no request (patterns/placeholder.py ReturnConstantStubPattern,
# ReturnNonePlaceholderPattern; both report at the def line).
SAME_EVIDENCE = {
    "literal_result": frozenset({"return_constant_stub", "return_none_placeholder"}),
    "single_outcome": frozenset({"return_constant_stub", "return_none_placeholder"}),
    "no_request": frozenset({"return_constant_stub", "return_none_placeholder"}),
}


@dataclass
class ClaimFinding:
    function: str
    line: int
    claim_kind: str
    promise: str
    promise_line: int
    basis: str
    detail: str
    looked_for: str
    why: str
    resolves: str = RESOLVES
    same_cause_as: List[str] = field(default_factory=list)
    kind: str = RULE
    status: str = "REVIEW_CANDIDATE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "function": self.function,
            "line": self.line,
            "claim_kind": self.claim_kind,
            "promise": self.promise,
            "promise_line": self.promise_line,
            "basis": self.basis,
            "detail": self.detail,
            "looked_for": self.looked_for,
            "why": self.why,
            "resolves": self.resolves,
            "same_cause_as": list(self.same_cause_as),
            "kind": self.kind,
            "status": self.status,
        }

    @property
    def evidence(self) -> str:
        detail = f" ({self.detail})" if self.detail else ""
        return f'promises "{self.promise}" ({self.claim_kind}); {self.why}{detail}'


def _def_lines(tree: ast.AST) -> Dict[int, int]:
    """Docstring line -> def line (a claim is keyed by its docstring line)."""
    return {
        _docstring_line(n): n.lineno
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _same_cause(basis: str, line: int, issues: List[Any]) -> List[str]:
    rules = SAME_EVIDENCE.get(basis, frozenset())
    return sorted(
        {i.pattern_id for i in issues if i.pattern_id in rules and int(i.line or 0) == line}
    )


def claim_analysis(
    tree: ast.AST, is_test: Optional[bool], issues: List[Any]
) -> Tuple[List[ClaimFinding], Dict[str, Any]]:
    """(candidates, coverage). `issues` are the file's pattern findings."""
    judgment = judge_claims(tree, is_test)
    defs = _def_lines(tree)
    findings = []
    for claim, verdict in judgment.verdicts:
        if verdict.state != CONTRADICTED:
            continue
        line = defs.get(claim.line, claim.line)
        findings.append(
            ClaimFinding(
                function=claim.function,
                line=line,
                claim_kind=claim.kind,
                promise=claim.text,
                promise_line=claim.line,
                basis=verdict.basis,
                detail=verdict.detail,
                looked_for=LOOKED_FOR[claim.kind],
                why=WHY[verdict.basis],
                same_cause_as=_same_cause(verdict.basis, line, issues),
            )
        )
    coverage = judgment.coverage()
    coverage["state"] = "MEASURED"
    candidates = sum(1 for f in findings if not f.same_cause_as)
    coverage["candidates"] = candidates
    coverage["merged"] = len(findings) - candidates
    return findings, coverage


def fully_measured(coverage: Dict[str, Any]) -> bool:
    """False when the channel or one of its judgments failed (not cached)."""
    return coverage.get("state") != UNMEASURED and not coverage.get("unmeasured")
