"""Behavioral promises in a function's docstring (H3-1: extraction only).

A claim is a mechanism the docstring's summary sentence says this function
itself performs ("Fetch every page of a paginated collection."). Nothing here
judges the body: every claim leaves with its mechanism NOT_EVALUATED.

Precision first: only the first sentence, only English, only the function's
own action. A word that names the mechanism as a topic, as an object, under
a negation or as something another component does is not a claim; such a
match is counted by reason, so a missing claim is never read as a function
without one. Functions not analyzed are counted by reason too.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from slop_detector.patterns.declared_intent import (
    _body_without_docstring,
    _first_sentence,
    _raises_not_implemented,
    declared_intent,
)

SCOPE = "FIRST_SUMMARY_SENTENCE"
BASIS = "EXPLICIT_BEHAVIORAL_PROMISE"
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)

# The function's own action carrying the mechanism. Delegable kinds (retry,
# cache) are extracted too; judging them waits for a proven provider (H3-4).
PROMISES: Dict[str, "re.Pattern[str]"] = {
    # "pages" alone is often a document's or a site's pages: an API page needs
    # a collection, a result set or a pagination link beside it.
    "pagination": re.compile(
        r"\b(?:every|all|each) pages? of (?:a |the |an )?(?:paginated |api )?"
        r"(?:collection|results?|response|listing|endpoint|query|search)\b"
        r"|\bfollow(?:s|ing)? (?:the )?(?:pagination|next(?:[- ]page)? (?:links?|urls?|cursors?|tokens?)|\w+ link headers)\b"
        r"|\bpaginat(?:es|ing) (?:through|over)\b",
        re.I,
    ),
    "parallel": re.compile(
        r"\bin parallel\b|\bconcurrently\b|\bsimultaneously\b|\bin (?:a )?(?:thread|process|worker) pool\b", re.I
    ),
    "aggregation": re.compile(
        r"\b(?:weighted )?(?:mean|average|sum|median) (?:of|over|across) (?:the |all |its |each |every )?"
        r"(?:[\w-]+ ){0,2}[\w-]+s'?(?=\W|$)"
        r"|\bensemble of\b",
        re.I,
    ),
    "rejection": re.compile(
        r"\breject(?:s|ing)? \w+|\braises? \w*(?:Error|Exception) (?:if|when|for|on)\b"
        r"|\bonly accept(?:s|ing)?\b|\brefuses? \w+",
        re.I,
    ),
    "validation": re.compile(r"^(?:validate|validates|verify|verifies) \w+", re.I),
    # "current" and "latest" are left out: "the current phase / user", "the
    # latest checkpoint / message id" are a store's own state far more often
    # than data fetched live.
    "live_data": re.compile(
        r"^(?:fetch(?:es)?|download(?:s)?|retrieve(?:s)?|quer(?:y|ies)|get(?:s)?|load(?:s)?|read(?:s)?) "
        r"(?:the )?(?:live|real[- ]time|up[- ]to[- ]date|fresh)\b",
        re.I,
    ),
    "computed_result": re.compile(
        r"^(?:compute(?:s)?|calculate(?:s)?|estimate(?:s)?|attribute(?:s)?|derive(?:s)?) \w+"
        r"|\bwith (?:SHAP|LIME|integrated gradients|permutation importance) values\b",
        re.I,
    ),
    "retry": re.compile(
        r"\bwith (?:up to \w+ )?(?:\w+ )?retr(?:y|ies)\b"
        r"|\bretr(?:y|ies|ying) (?:up to|on|until|with|\w+ times)\b"
        r"|\b(?:with|using) (?:exponential |linear )?backoff\b",
        re.I,
    ),
    "cache": re.compile(
        r"\b(?:return(?:s)?|get(?:s)?|load(?:s)?|fetch(?:es)?) (?:the )?cached\b"
        r"|\bcaches (?:the|its|each|every) \w+|\bmemoi[sz](?:e|es|ed)\b|\b(?:is|are) cached\b",
        re.I,
    ),
}

# Why a match is not this function's own promise (checked in this order).
# The sentence says the function itself is a stand-in: "(stub -- the real
# check is in ...)", "is a placeholder", "not implemented". A stub named as
# an object ("the stub file") is not a disclosure.
_SELF_DISCLOSED = re.compile(
    r"\((?:a |an |the )?(?:stub|placeholder|no-op|dummy)\b"
    r"|\b(?:stub|placeholder|no-op)\s*(?:--|-|:|;|,)"
    r"|\b(?:is|this is) (?:a |an |only a )?(?:stub|placeholder|no-op|dummy)\b"
    # "not implemented" of the function itself, not of an object it handles
    r"|(?:^|\(|--|:)\s*not (?:yet )?implemented\b|\b(?:this|it) is not (?:yet )?implemented\b",
    re.I,
)
_TEST_DESCRIPTION = re.compile(r"^(?:tests?|check(?:s)? that|ensures? that|verif(?:y|ies) that|asserts?|regression)\b", re.I)
_PREDICATE = re.compile(r"^(?:returns? (?:true|false|whether)|whether|true if|checks? (?:if|whether))\b", re.I)
# The mechanism is another task's relation or another actor's, not this one's.
_RELATION = re.compile(
    r"\b(?:in parallel|concurrently|simultaneously) (?:with|by)\b|\bmultiple (?:processes|threads|workers)\b", re.I
)
_NEGATION = re.compile(r"\b(?:never|not|no|without|cannot|instead of)\b|n't\b", re.I)
_ELSEWHERE = re.compile(
    r"\b(?:delegat\w* to|relies on|handled by|provided by|done by|left to)\b"
    r"|\bthe (?:client|server|session|api|library|backend|framework|caller)'?s? (?:paginat|retr|cach|validat)"
    # an instruction to the overrider: the subclass does it, this default does not
    r"|^(?:overload|override|overwrite|reimplement) (?:this|me|it)\b|\bsubclass(?:es)? (?:should|must|may|can)\b",
    re.I,
)
_AS_OBJECT = re.compile(
    r"\b(?:retry|cache|cached|validation|pagination|parallel|concurrency|backoff)"
    r" (?:policy|policies|config\w*|settings?|options?|models?|keys?|layer|service|backend|helper|strategy|mode|"
    r"state|size|limit|counter|count|entry|entries|directory|dir|path|file)\b",
    re.I,
)
_OBJECT_VERBS = re.compile(
    r"^(?:clear|invalidate|reset|configure|register|update|set|build|create|evict|purge|drop|free|remove|delete)s?\b",
    re.I,
)


def _excluded(sentence: str, match: "re.Match[str]") -> Optional[str]:
    """Why a match is not a promise of this function's own behavior, or None."""
    before = sentence[: match.start()]
    if _SELF_DISCLOSED.search(sentence):
        return "self_disclosed"
    if _TEST_DESCRIPTION.search(sentence):
        return "test_description"
    if _PREDICATE.search(sentence):
        return "predicate_about_mechanism"
    if _NEGATION.search(before) or _NEGATION.search(match.group(0)):
        return "negated"
    if _ELSEWHERE.search(sentence) or _RELATION.search(sentence):
        return "attributed_elsewhere"
    if _AS_OBJECT.search(sentence) or _OBJECT_VERBS.search(sentence):
        return "mechanism_as_object"
    return None


def _english(sentence: str) -> bool:
    """Mostly ASCII letters: other scripts are not analyzed (not 'no claim')."""
    letters = [c for c in sentence if c.isalpha()]
    if not letters:
        return False
    other = sum(1 for c in letters if ord(c) > 127)
    return other / len(letters) <= 0.2  # a stray accented name keeps English text English


@dataclass(frozen=True)
class Claim:
    kind: str
    function: str
    line: int
    text: str
    phrase: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind,
            "subject": "current_function",
            "source": {"function": self.function, "line": self.line, "text": self.text, "phrase": self.phrase},
            "extraction": {"state": "EXTRACTED", "scope": SCOPE, "confidence_basis": BASIS},
            "mechanism": {"state": "NOT_EVALUATED"},
        }


@dataclass
class ClaimExtraction:
    claims: List[Claim] = field(default_factory=list)
    functions: int = 0
    eligible: int = 0
    not_analyzed: Dict[str, int] = field(default_factory=dict)
    excluded: Dict[str, int] = field(default_factory=dict)
    out_of_scope: Dict[str, int] = field(default_factory=dict)

    def coverage(self) -> Dict[str, object]:
        """Functions and claims kept apart: one function can make several claims."""
        by_kind: Dict[str, int] = {}
        for claim in self.claims:
            by_kind[claim.kind] = by_kind.get(claim.kind, 0) + 1
        return {
            "functions": self.functions,
            "eligible_functions": self.eligible,
            "functions_with_claims": len({(c.function, c.line) for c in self.claims}),
            "extracted_claims": len(self.claims),
            "claims_by_kind": dict(sorted(by_kind.items())),
            "not_analyzed_by_reason": dict(sorted(self.not_analyzed.items())),
            "excluded_matches_by_reason": dict(sorted(self.excluded.items())),
            "out_of_scope": dict(sorted(self.out_of_scope.items())),
        }


def _count(table: Dict[str, int], key: str) -> None:
    table[key] = table.get(key, 0) + 1


def _qualname(parents: Dict[ast.AST, ast.AST], node: ast.AST) -> str:
    names = []
    while node is not None and not isinstance(node, ast.Module):
        if isinstance(node, _FUNCTIONS + (ast.ClassDef,)):
            names.append(node.name)
        node = parents.get(node)
    return ".".join(reversed(names))


def _not_analyzed(function, intent, is_test: Optional[bool]) -> Optional[str]:
    if is_test is True or function.name.startswith("test_"):
        return "test_code"
    if is_test is None:
        return "test_status_unknown"  # not assumed to be product code
    if intent.is_contract(function):
        return "contract_or_abstract"
    if _is_stub(function):
        return "stub_body"  # the placeholder patterns judge it
    return None


def _is_stub(function) -> bool:
    """`pass`, `...` or `raise NotImplementedError` only, after the docstring."""
    if _raises_not_implemented(function):
        return True
    body = _body_without_docstring(function)
    return all(isinstance(n, ast.Pass) or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)) for n in body)


def _docstring_line(function) -> int:
    first = function.body[0] if function.body else function
    return getattr(first, "lineno", function.lineno)


def extract_claims(tree: ast.AST, is_test: Optional[bool]) -> ClaimExtraction:
    """Claims of every function in the module (nested ones under their own
    name). `is_test`: the file is test code (True), product code (False) or
    unknown (None, e.g. no project root): only False is analyzed."""
    out = ClaimExtraction()
    intent = declared_intent(tree)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for function in (n for n in ast.walk(tree) if isinstance(n, _FUNCTIONS)):
        out.functions += 1
        doc = ast.get_docstring(function)
        if not doc:
            _count(out.not_analyzed, "no_docstring")
            continue
        reason = _not_analyzed(function, intent, is_test)
        if reason:
            _count(out.not_analyzed, reason)
            continue
        sentence = _first_sentence(doc)
        if not _english(sentence):
            _count(out.not_analyzed, "non_english")
            continue
        out.eligible += 1
        if len(" ".join(doc.split())) > len(sentence):
            _count(out.out_of_scope, "later_sentences_not_analyzed")
        out.claims += _function_claims(function, sentence, _qualname(parents, function), out.excluded)
    return out


def _function_claims(function, sentence: str, name: str, excluded: Dict[str, int]) -> List[Claim]:
    claims = []
    for kind, pattern in PROMISES.items():
        match = pattern.search(sentence)
        if not match:
            continue
        why = _excluded(sentence, match)
        if why:
            _count(excluded, why)
            continue
        claims.append(Claim(kind, name, _docstring_line(function), sentence, match.group(0)))
    return claims


def claims_for_file(tree: ast.AST, path: str, root: Optional[str] = None) -> Tuple[ClaimExtraction, Optional[bool]]:
    """Extraction with the file's test status from path facts (root rule)."""
    from slop_detector.path_facts import facts_for

    is_test = facts_for(path, root).is_test
    return extract_claims(tree, is_test), is_test
