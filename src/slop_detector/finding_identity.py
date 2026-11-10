"""Which finding an item is, independent of where its line happens to sit.

Computed at scan time from the content the AST was built from (never from a
later read of the file):

- `symbol`: the innermost function or class holding the line.
- `fingerprint`: for a finding inside a body, the stripped text of its line
  and of the line before and after it; none for a finding reported at its
  symbol's own def line, which the symbol names already.

With the rule and the structured subject a pattern names (`Issue.subject`:
the parameter, the imported module, the clone group), they key an item; a line
number enters the key only when nothing else locates it. Two items with one
key are not told apart by numbering: the report refuses to emit them.
"""

from __future__ import annotations

import ast
import hashlib
from typing import Any, Dict, List, Optional, Tuple

from slop_detector.claims import _qualname

MODULE = "<module>"
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _spans(tree: ast.AST) -> List[Tuple[int, int, str]]:
    """(def line, end line, qualname) of every function and class."""
    parents: Dict[ast.AST, ast.AST] = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    return [
        (n.lineno, getattr(n, "end_lineno", None) or n.lineno, _qualname(parents, n))
        for n in ast.walk(tree)
        if isinstance(n, _SCOPES)
    ]


def _holder(spans: List[Tuple[int, int, str]], line: int) -> Optional[Tuple[int, int, str]]:
    holding = [s for s in spans if s[0] <= line <= s[1]]
    return min(holding, key=lambda s: s[1] - s[0]) if holding else None


def fingerprint(lines: List[str], line: int) -> Optional[str]:
    """SHA-256 (16 hex) of the stripped text of `line` and its two
    neighbours; None outside the content."""
    if not 1 <= line <= len(lines):
        return None
    window = [lines[n - 1].strip() if 1 <= n <= len(lines) else "" for n in (line - 1, line, line + 1)]
    return hashlib.sha256(chr(10).join(window).encode("utf-8")).hexdigest()[:16]


def locate(findings: List[Any], tree: ast.AST, content: str, name_symbol: bool = True) -> None:
    """Set `fingerprint` (and `symbol` when `name_symbol`) on each finding of
    the module; a finding that names its symbol already keeps it."""
    if not findings:
        return
    spans = _spans(tree)
    lines = content.splitlines()
    for finding in findings:
        line = int(finding.line or 0)
        holder = _holder(spans, line)
        if name_symbol:
            finding.symbol = holder[2] if holder else MODULE
        at_def = holder is not None and holder[0] == line
        finding.fingerprint = None if at_def else fingerprint(lines, line)


def locus(symbol: Optional[str], subject: Optional[str], fingerprint_: Optional[str], line: int) -> str:
    """The part of an item key that says where it is: the symbol, the subject
    and the line fingerprint; the line number only without symbol and fingerprint."""
    where = fingerprint_ or ("" if symbol else f"L{line}")
    return f"{symbol or MODULE}|{subject or ''}|{where}"
