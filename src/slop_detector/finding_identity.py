"""Which finding an item is, computed at scan time from the content the AST
was built from (never from a later read of the file).

- `symbol`: the innermost function or class holding the line.
- `fingerprint`: the stripped text of the finding's own line; none at its
  symbol's def line, which the symbol names already.
- `locator`: the address of the finding in this snapshot's AST, relative to
  the symbol: the path of the innermost statement or handler holding the line
  (`body[2]/handlers[0]`). A comment is not an AST node: a comment line is
  addressed by the statement after it in its block (`~before`) or, at the end
  of a block, the statement before it (`~after`), with the number of comment
  lines between them. Blank lines and comments elsewhere leave it unchanged;
  a statement inserted in front of it in the same block moves it.

semantic_key (rule, path, symbol, subject, fingerprint) says what the finding
is; the locator says which copy of it. The locator is valid only for the
snapshot `source_sha256` names: a changed locator with the same semantic_key
is the same finding moved, never a fix (ai_report.prove_state).
"""

from __future__ import annotations

import ast
import hashlib
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from slop_detector.claims import _qualname

MODULE = "<module>"
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_BLOCKS = ("body", "handlers", "orelse", "finalbody", "cases")


_Span = Tuple[int, int, str, ast.AST]


def _spans(tree: ast.AST) -> List[_Span]:
    """(def line, end line, qualname, node) of every function and class."""
    parents: Dict[ast.AST, ast.AST] = {
        c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)
    }
    return [
        (n.lineno, getattr(n, "end_lineno", None) or n.lineno, _qualname(parents, n), n)
        for n in ast.walk(tree)
        if isinstance(n, _SCOPES)
    ]


def _holder(spans: List[_Span], line: int) -> Optional[_Span]:
    holding = [s for s in spans if s[0] <= line <= s[1]]
    return min(holding, key=lambda s: s[1] - s[0]) if holding else None


def _extent(node: ast.AST) -> Optional[Tuple[int, int]]:
    """Line extent of a node; a match case (no lineno) spans its pattern and body."""
    if hasattr(node, "lineno"):
        return node.lineno, getattr(node, "end_lineno", None) or node.lineno
    inner = [
        _extent(c)
        for c in [getattr(node, "pattern", None)] + list(getattr(node, "body", []) or [])
        if c
    ]
    spans = [e for e in inner if e]
    return (min(e[0] for e in spans), max(e[1] for e in spans)) if spans else None


class _Addresses:
    """Every statement, handler and case with its path inside its scope, and
    the block children of each container."""

    def __init__(self, tree: ast.AST) -> None:
        self.path: Dict[int, str] = {}
        self.children: Dict[int, List[ast.AST]] = {}
        self.in_scope: Dict[int, List[ast.AST]] = {}  # id(scope) -> its own statements
        self._walk(tree, "", tree)

    def _walk(self, node: ast.AST, prefix: str, scope: ast.AST) -> None:
        kids: List[ast.AST] = []
        for field in _BLOCKS:
            for index, child in enumerate(getattr(node, field, None) or []):
                if not isinstance(child, ast.AST):
                    continue
                kids.append(child)
                if isinstance(child, _SCOPES):  # a scope addresses its own body
                    self._walk(child, "", child)
                    continue
                address = f"{prefix}/{field}[{index}]" if prefix else f"{field}[{index}]"
                self.path[id(child)] = address
                self.in_scope.setdefault(id(scope), []).append(child)
                self._walk(child, address, scope)
        self.children[id(node)] = kids


def _innermost(nodes: List[ast.AST], line: int) -> Optional[ast.AST]:
    best, size = None, None
    for node in nodes:
        extent = _extent(node)
        if (
            extent
            and extent[0] <= line <= extent[1]
            and (size is None or extent[1] - extent[0] < size)
        ):
            best, size = node, extent[1] - extent[0]
    return best


def _comment_lines(lines: List[str], start: int, end: int) -> int:
    """Comment-only lines strictly between line `start` and line `end`."""
    return sum(
        1
        for n in range(start + 1, end)
        if 1 <= n <= len(lines) and lines[n - 1].strip().startswith("#")
    )


def _comment_locator(index: _Addresses, container: ast.AST, line: int, lines: List[str]) -> str:
    kids = [(k, s) for k in index.children.get(id(container), []) for s in [_extent(k)] if s]
    after = [(k, s) for k, s in kids if s[0] > line]
    if after:
        anchor, span = after[0]
        return f"{_address(index, anchor)}~before{_comment_lines(lines, line, span[0])}"
    before = [(k, s) for k, s in kids if s[1] < line]
    if before:
        anchor, span = before[-1]
        return f"{_address(index, anchor)}~after{_comment_lines(lines, span[1], line)}"
    return f"~only{_comment_lines(lines, 0, line)}"


def _address(index: _Addresses, node: ast.AST) -> str:
    """A statement's path; a nested scope is addressed by its name."""
    if isinstance(node, _SCOPES):
        return f"def:{node.name}"
    return index.path.get(id(node), "")


def _locator(scope: ast.AST, index: _Addresses, line: int, lines: List[str]) -> str:
    """The address of `line` among the statements of its own scope."""
    holding = _innermost(index.in_scope.get(id(scope), []), line)
    is_comment = 1 <= line <= len(lines) and lines[line - 1].strip().startswith("#")
    if is_comment:
        span = _extent(holding) if holding is not None else None
        container = holding if holding is not None and span and span[0] < line else scope
        return _comment_locator(index, container, line, lines)
    return _address(index, holding) if holding is not None else ""


def fingerprint(lines: List[str], line: int) -> Optional[str]:
    """SHA-256 (16 hex) of the stripped text of `line`; None outside the content."""
    if not 1 <= line <= len(lines):
        return None
    return hashlib.sha256(lines[line - 1].strip().encode("utf-8")).hexdigest()[:16]


def locate(findings: List[Any], tree: ast.AST, content: str, name_symbol: bool = True) -> None:
    """Set `fingerprint` and `locator` (and `symbol` when `name_symbol`) on
    each finding of the module; a finding that names its symbol keeps it."""
    if not findings:
        return
    spans = _spans(tree)
    index = _Addresses(tree)
    lines = content.splitlines()
    for finding in findings:
        line = int(finding.line or 0)
        holder = _holder(spans, line)
        if name_symbol:
            finding.symbol = holder[2] if holder else MODULE
        at_def = holder is not None and holder[0] == line
        finding.fingerprint = None if at_def else fingerprint(lines, line)
        finding.locator = (
            "" if at_def else _locator(holder[3] if holder else tree, index, line, lines)
        )


def read_source(path: str) -> Tuple[str, str]:
    """(text, SHA-256 of the bytes) of a file read once. The text is what
    Path.read_text(encoding="utf-8", errors="ignore") gives (universal
    newlines), so an analyzer that used it sees the same content."""
    with open(path, "rb") as handle:
        raw = handle.read()
    text = (
        raw.decode("utf-8", errors="ignore")
        .replace(chr(13) + chr(10), chr(10))
        .replace(chr(13), chr(10))
    )
    return text, hashlib.sha256(raw).hexdigest()


def bind_lines(result: Any, content: str, digest: str) -> Any:
    """Bind a JS/TS or Go result to the bytes read and address its issues by
    line text and line. These analyzers have no statement path: a line shift
    changes the locator (and the id). Findings of one rule on one line (two
    `any` types in one signature) are told apart by their column (JS/TS) or
    their order on the line (Go, which has no column); a finding alone on its
    line keeps the line locator."""
    result.source_sha256, result.content_origin = digest, "file_bytes"
    lines = content.splitlines()
    shared = Counter((issue.pattern_id, int(issue.line or 0)) for issue in result.issues)
    order: Counter = Counter()
    for issue in result.issues:
        line = int(issue.line or 0)
        issue.fingerprint = fingerprint(lines, line)
        key = (issue.pattern_id, line)
        order[key] += 1
        if shared[key] == 1:
            issue.locator = f"L{line}"
        elif getattr(issue, "column", None) is not None:
            issue.locator = f"L{line}C{issue.column}"
        else:
            issue.locator = f"L{line}#{order[key]}"
    return result


def semantic_part(
    symbol: Optional[str], subject: Optional[str], fingerprint_: Optional[str], line: int
) -> str:
    """What the finding is: symbol, subject and the line's text; the line
    number only without symbol and fingerprint."""
    where = fingerprint_ or ("" if symbol else f"L{line}")
    return f"{symbol or MODULE}|{subject or ''}|{where}"
