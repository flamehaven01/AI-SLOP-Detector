"""Rust analyzer (v1): unfinished-code markers in .rs files.

Rules (outside test code):
  rust_todo_macro           todo!() call                  high
  rust_unimplemented_macro  unimplemented!() call         high
  rust_dbg_macro            dbg!() call                   medium
  rust_todo_comment         TODO/FIXME/HACK/XXX comment   low

Two paths read a file into tokens: tree-sitter-rust (the [rust] extra,
Python 3.10+) and a token scanner (always available). Both read a string,
char or macro_rules! definition as one literal and agree on identifiers and
comments; they may split punctuation, numbers, labels and lifetimes inside
macro arguments differently, which no rule reads. One detector then works on
either stream, so both paths report the same findings.
Calls inside strings, comments and macro_rules! bodies are not calls; items
under #[cfg(test)], #[test] or an attribute path ending in ::test are test
code and not reported. A file neither path can read raises RustReadError (a
failed file in scan coverage), never a file with no findings. A file
tree-sitter reports a syntax error for is read by the token scanner, and its
result says so (ast_mode False).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from slop_detector.diagnostic_bands import classify_deficit
from slop_detector.finding_identity import bind_lines, read_source

logger = logging.getLogger(__name__)

_TS_AVAILABLE = False
try:
    import tree_sitter_rust as _tsrust
    from tree_sitter import Language as _Language
    from tree_sitter import Parser as _Parser

    _RUST_LANG = _Language(_tsrust.language())
    _TS_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the [rust] extra
    logger.debug("tree-sitter-rust unavailable - Rust analysis uses the token scanner")

# The token scanner measures every rule of this analyzer.
REGEX_FALLBACK_NOT_MEASURED: tuple = ()

# Score weights, as for Go: a stub call weighs like an empty Go function, a
# debug call like a debug print; a TODO comment is reported, not scored.
STUB_WEIGHT = 25.0
DEBUG_WEIGHT = 5.0

_RULES = {
    "todo": (
        "rust_todo_macro",
        "high",
        "todo!() left in the code: it panics when reached",
        "Implement the code path, or return an error the caller can handle",
    ),
    "unimplemented": (
        "rust_unimplemented_macro",
        "high",
        "unimplemented!() left in the code: it panics when reached",
        "Implement the code path, or return an error the caller can handle",
    ),
    "dbg": (
        "rust_dbg_macro",
        "medium",
        "dbg!() debug print left in the code",
        "Remove the debug print or use a logger",
    ),
}
_COMMENT_RULE = (
    "rust_todo_comment",
    "low",
    "Unresolved marker",
    "Resolve the marker or track it in an issue",
)
_MARKER = re.compile(r"(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
_COMMENT_LEAD = re.compile(r"^\s*(?://[/!]?|/\*[*!]?|\*+(?!/))?\s*")
_IDENT = re.compile(r"^(r#)?[^\W\d]\w*$")
_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = set(_OPEN.values())
_Spans = List[Tuple[Tuple[int, int], Tuple[int, int]]]  # ((line, col), (line, col)) ranges


class RustReadError(ValueError):
    """A Rust file the analyzer cannot tokenize (unterminated string or comment)."""


@dataclass(frozen=True)
class _Tok:
    kind: str  # ident | punct | lit | life
    text: str
    line: int  # 1-based
    col: int  # 0-based, in characters
    end_line: int


@dataclass(frozen=True)
class _Comment:
    line: int
    col: int
    text: str


@dataclass
class RustIssue:
    """A finding in a Rust file."""

    pattern_id: str
    severity: str  # critical | high | medium | low
    line: int
    column: int
    message: str
    suggestion: Optional[str] = None
    fingerprint: Optional[str] = None
    locator: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "severity": self.severity,
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "suggestion": self.suggestion,
            "fingerprint": self.fingerprint,
            "locator": self.locator,
        }


@dataclass
class RustFileAnalysis:
    """Analysis result for a .rs file."""

    file_path: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    ldr_equivalent: float
    issues: List[RustIssue] = field(default_factory=list)
    ast_mode: bool = False
    slop_score: float = 0.0
    status: str = "clean"  # clean | suspicious | critical_deficit
    source_sha256: str = ""
    content_origin: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "total_lines": self.total_lines,
            "code_lines": self.code_lines,
            "comment_lines": self.comment_lines,
            "blank_lines": self.blank_lines,
            "ldr_equivalent": round(self.ldr_equivalent, 4),
            "ast_mode": self.ast_mode,
            "slop_score": round(self.slop_score, 2),
            "status": self.status,
            "issues": [i.to_dict() for i in self.issues],
            "source_sha256": self.source_sha256,
            "content_origin": self.content_origin,
        }


class RustAnalyzer:
    """Analyzes .rs files for unfinished-code markers."""

    def analyze(self, file_path: str) -> RustFileAnalysis:
        content, digest = read_source(file_path)
        result = self._analyze_ast(file_path, content) if _TS_AVAILABLE else None
        if result is None:
            result = self._analyze_tokens(file_path, content)
        return bind_lines(result, content, digest)

    def _analyze_tokens(self, file_path: str, content: str) -> RustFileAnalysis:
        tokens, comments = _scan(content)
        return _analyze(file_path, content, tokens, comments, ast_mode=False)

    def _analyze_ast(self, file_path: str, content: str) -> Optional[RustFileAnalysis]:
        """None when tree-sitter reports a syntax error (the scanner reads it)."""
        read = _ast_tokens(content)
        if read is None:
            return None
        tokens, comments = read
        return _analyze(file_path, content, tokens, comments, ast_mode=True)


# --- token scanner -----------------------------------------------------------


def _end_quoted(content: str, k: int, line: int) -> int:
    """Index after the closing quote of a string whose body starts at k."""
    while k < len(content):
        if content[k] == "\\":
            k += 2
        elif content[k] == '"':
            return k + 1
        else:
            k += 1
    raise RustReadError(f"not readable Rust: unterminated string at line {line}")


def _end_char(content: str, k: int, line: int) -> int:
    """Index after a char literal whose opening quote is at k."""
    j = k + 1
    while j < len(content) and content[j] != "'":
        j += 2 if content[j] == "\\" else 1
        if content[j - 1] == "\n":
            break
    if j >= len(content) or content[j] != "'":
        raise RustReadError(f"not readable Rust: unterminated char literal at line {line}")
    return j + 1


def _word_end(content: str, k: int) -> int:
    while k < len(content) and (content[k].isalnum() or content[k] == "_"):
        k += 1
    return k


def _end_block_comment(content: str, k: int, line: int) -> int:
    """Index after a (nested) block comment whose `/*` is at k."""
    depth, j = 1, k + 2
    while j < len(content) and depth:
        if content.startswith("/*", j):
            depth, j = depth + 1, j + 2
        elif content.startswith("*/", j):
            depth, j = depth - 1, j + 2
        else:
            j += 1
    if depth:
        raise RustReadError(f"not readable Rust: unterminated block comment at line {line}")
    return j


def _end_raw(content: str, j: int, hashes: int, line: int) -> int:
    """Index after a raw string whose `#...#"` opener starts at j."""
    close = '"' + "#" * hashes
    end = content.find(close, j + hashes + 1)
    if end < 0:
        raise RustReadError(f"not readable Rust: unterminated raw string at line {line}")
    return end + len(close)


def _quote_token(content: str, k: int, line: int) -> Tuple[str, int]:
    """A char literal or a lifetime, at the `'` at k."""
    if content[k + 1 : k + 2] == "\\" or content[k + 2 : k + 3] == "'":
        return "lit", _end_char(content, k, line)
    return "life", _word_end(content, k + 1)


def _word_token(content: str, k: int, line: int) -> Tuple[str, int]:
    """An identifier, or a literal with a word prefix (r"..", br#".."#, b'.', c"..", r#name)."""
    j = _word_end(content, k)
    word, nxt = content[k:j], content[j : j + 1]
    if word in ("r", "br", "cr") and nxt in ('"', "#"):
        hashes = len(content[j:]) - len(content[j:].lstrip("#"))
        if content[j + hashes : j + hashes + 1] == '"':
            return "lit", _end_raw(content, j, hashes, line)
        if word == "r" and hashes == 1:  # raw identifier r#name
            return "ident", _word_end(content, j + 1)
    if word in ("b", "c") and nxt == '"':
        return "lit", _end_quoted(content, j + 1, line)
    if word == "b" and nxt == "'":
        return "lit", _end_char(content, j, line)
    return "ident", j


def _token_at(content: str, k: int, line: int) -> Tuple[str, int]:
    """(kind, end index) of the token or comment starting at k."""
    ch = content[k]
    if content.startswith("//", k):
        end = content.find("\n", k)
        return "comment", len(content) if end < 0 else end
    if content.startswith("/*", k):
        return "comment", _end_block_comment(content, k, line)
    if ch == '"':
        return "lit", _end_quoted(content, k + 1, line)
    if ch == "'":
        return _quote_token(content, k, line)
    if ch.isalpha() or ch == "_":
        return _word_token(content, k, line)
    if ch.isdigit():
        return "lit", _word_end(content, k)
    return "punct", k + (2 if content.startswith("::", k) else 1)


def _scan(content: str) -> Tuple[List[_Tok], List[_Comment]]:
    """Tokens and comments of a Rust source, without tree-sitter."""
    tokens: List[_Tok] = []
    comments: List[_Comment] = []
    i, line, line_start = 0, 1, 0
    while i < len(content):
        if content[i].isspace():
            if content[i] == "\n":
                line, line_start = line + 1, i + 1
            i += 1
            continue
        kind, end = _token_at(content, i, line)
        text = content[i:end]
        start_line, start_col = line, i - line_start
        if "\n" in text:
            line += text.count("\n")
            line_start = i + text.rfind("\n") + 1
        if kind == "comment":
            comments.append(_Comment(start_line, start_col, text))
        else:
            tokens.append(_Tok(kind, text, start_line, start_col, line))
        i = end
    return _without_macro_rules(tokens, comments)


def _match(tokens: List[_Tok], k: int) -> int:
    """Index of the delimiter closing the one opened at k (or the last token)."""
    depth = 0
    for j in range(k, len(tokens)):
        if tokens[j].kind == "punct" and tokens[j].text in _OPEN:
            depth += 1
        elif tokens[j].kind == "punct" and tokens[j].text in _CLOSE:
            depth -= 1
            if depth == 0:
                return j
    return len(tokens) - 1


def _is_macro_call(tokens: List[_Tok], k: int, gap: int = 0) -> bool:
    """tokens[k] is an identifier followed by `!` and, `gap` tokens later, an
    opening delimiter (gap 1 for macro_rules! name {...})."""
    return (
        tokens[k].kind == "ident"
        and k + 2 + gap < len(tokens)
        and tokens[k + 1].text == "!"
        and tokens[k + 2 + gap].text in _OPEN
    )


def _without_macro_rules(
    tokens: List[_Tok], comments: List[_Comment]
) -> Tuple[List[_Tok], List[_Comment]]:
    """A macro_rules! definition is one opaque unit, as tree-sitter reads it:
    its body is a pattern, not code, and its comments are not reported."""
    out: List[_Tok] = []
    spans: _Spans = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if (
            tok.text == "macro_rules"
            and _is_macro_call(tokens, i, gap=1)
            and tokens[i + 2].kind == "ident"
        ):
            end = _match(tokens, i + 3)
            last = tokens[end]
            if tokens[i + 3].text != "{" and end + 1 < len(tokens) and tokens[end + 1].text == ";":
                end, last = end + 1, tokens[end + 1]
            out.append(_Tok("lit", "macro_rules!", tok.line, tok.col, last.end_line))
            spans.append(((tok.line, tok.col), (last.end_line, last.col + len(last.text))))
            i = end + 1
            continue
        out.append(tok)
        i += 1
    kept = [c for c in comments if not _inside(spans, c.line, c.col)]
    return out, kept


# --- tree-sitter -------------------------------------------------------------

_AST_UNITS = {"string_literal": "lit", "raw_string_literal": "lit", "char_literal": "lit"}


def _ast_tokens(content: str) -> Optional[Tuple[List[_Tok], List[_Comment]]]:
    """The scanner's tokens, read by tree-sitter; None on a syntax error."""
    data = content.encode("utf-8")
    tree = _Parser(_RUST_LANG).parse(data)
    root = tree.root_node
    if root.has_error:
        return None
    byte_lines = data.split(b"\n")

    def col(row: int, byte_col: int) -> int:
        return len(byte_lines[row][:byte_col].decode("utf-8", errors="replace"))

    tokens: List[_Tok] = []
    comments: List[_Comment] = []
    stack = [root]
    while stack:
        node = stack.pop()
        kind = node.type
        text = data[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
        row, byte_col = node.start_point
        if kind in ("line_comment", "block_comment"):
            comments.append(_Comment(row + 1, col(row, byte_col), text.rstrip("\n")))
            continue
        unit = _AST_UNITS.get(kind) or (
            "life" if kind == "lifetime" else "lit" if kind == "macro_definition" else None
        )
        if unit is None and node.child_count == 0:
            unit = "ident" if _IDENT.match(text) else "lit" if text[:1].isdigit() else "punct"
        if unit is not None:
            if text:
                tokens.append(_Tok(unit, text, row + 1, col(row, byte_col), node.end_point[0] + 1))
            continue
        stack.extend(reversed(node.children))
    return tokens, comments


# --- the detector, shared by both paths --------------------------------------


def _is_test_attribute(inner: List[_Tok]) -> bool:
    """#[cfg(test)], or an attribute path ending in `test` (#[test],
    #[tokio::test], #[tokio::test(flavor = "...")])."""
    texts = [t.text for t in inner]
    if texts == ["cfg", "(", "test", ")"]:
        return True
    path = texts[: texts.index("(")] if "(" in texts else texts
    return (
        bool(path)
        and path[-1] == "test"
        and all((t == "::") == (k % 2 == 1) for k, t in enumerate(path))
    )


def _item_end(tokens: List[_Tok], k: int) -> int:
    """Index of the last token of the item starting at k: its body's closing
    brace, or the `;` / `,` that ends it, or the token before an enclosing
    closing delimiter."""
    depth = 0
    for j in range(k, len(tokens)):
        tok = tokens[j]
        if tok.kind != "punct":
            continue
        if tok.text in _OPEN:
            if tok.text == "{" and depth == 0:
                return _match(tokens, j)
            depth += 1
        elif tok.text in _CLOSE:
            if depth == 0:
                return j - 1
            depth -= 1
        elif tok.text in (";", ",") and depth == 0:
            return j
    return len(tokens) - 1


def _block_end(tokens: List[_Tok], k: int) -> int:
    """Index of the token closing the block that contains token k."""
    depth = 0
    for j in range(k, len(tokens)):
        tok = tokens[j]
        if tok.kind == "punct" and tok.text in _OPEN:
            depth += 1
        elif tok.kind == "punct" and tok.text in _CLOSE:
            if depth == 0:
                return j
            depth -= 1
    return len(tokens) - 1


def _test_spans(tokens: List[_Tok]) -> _Spans:
    """(start, end) positions of the code under a test attribute."""
    spans = []
    i = 0
    while i < len(tokens):
        if tokens[i].text != "#" or tokens[i].kind != "punct":
            i += 1
            continue
        inner_attr = i + 1 < len(tokens) and tokens[i + 1].text == "!"
        bracket = i + (2 if inner_attr else 1)
        if bracket >= len(tokens) or tokens[bracket].text != "[":
            i += 1
            continue
        close = _match(tokens, bracket)
        if _is_test_attribute(tokens[bracket + 1 : close]):
            end = _block_end(tokens, close + 1) if inner_attr else _item_end(tokens, close + 1)
            last = tokens[min(max(end, close), len(tokens) - 1)]
            spans.append(
                ((tokens[i].line, tokens[i].col), (last.end_line, last.col + len(last.text)))
            )
        i = close + 1
    return spans


def _inside(spans: _Spans, line: int, col: int) -> bool:
    return any(a <= (line, col) <= b for a, b in spans)


def _macro_issues(tokens: List[_Tok], spans: _Spans) -> List[RustIssue]:
    """todo!/unimplemented!/dbg! calls (also path-qualified) outside test code."""
    issues: List[RustIssue] = []
    for k, tok in enumerate(tokens):
        if tok.text not in _RULES or not _is_macro_call(tokens, k):
            continue
        start = k
        while start >= 2 and tokens[start - 1].text == "::" and tokens[start - 2].kind == "ident":
            start -= 2
        first = tokens[start]
        if _inside(spans, first.line, first.col):
            continue
        pattern_id, severity, message, fix = _RULES[tok.text]
        issues.append(RustIssue(pattern_id, severity, first.line, first.col, message, fix))
    return issues


def _comment_issues(comments: List[_Comment], spans: _Spans) -> List[RustIssue]:
    """TODO/FIXME/HACK/XXX markers leading a comment line, outside test code."""
    issues: List[RustIssue] = []
    for comment in comments:
        for offset, segment in enumerate(comment.text.split("\n")):
            lead = _COMMENT_LEAD.match(segment)
            rest = segment[lead.end() if lead else 0 :]
            marker = _MARKER.match(rest)
            if not marker:
                continue
            line = comment.line + offset
            column = (comment.col if offset == 0 else 0) + len(segment) - len(rest)
            if _inside(spans, line, column):
                continue
            pattern_id, severity, message, fix = _COMMENT_RULE
            issues.append(
                RustIssue(pattern_id, severity, line, column, f"{message}: {rest.strip()}", fix)
            )
    return issues


def _analyze(
    file_path: str,
    content: str,
    tokens: List[_Tok],
    comments: List[_Comment],
    ast_mode: bool,
) -> RustFileAnalysis:
    lines = content.splitlines()
    spans = _test_spans(tokens)
    calls = _macro_issues(tokens, spans)
    issues = sorted(calls + _comment_issues(comments, spans), key=lambda i: (i.line, i.column))
    stubs = sum(1 for i in calls if i.pattern_id != "rust_dbg_macro")
    debug = len(calls) - stubs

    code: Set[int] = {n for t in tokens for n in range(t.line, t.end_line + 1)}
    commented: Set[int] = {
        n for c in comments for n in range(c.line, c.line + c.text.count("\n") + 1)
    } - code
    total = len(lines)
    blank = sum(1 for n, text in enumerate(lines, 1) if not text.strip() and n not in commented)
    ldr = len(code) / total if total else 0.0
    score = 0.0
    if total:
        per_100 = 100.0 / total
        score += 40.0 if ldr < 0.20 else 20.0 if ldr < 0.40 else 0.0
        score += stubs * STUB_WEIGHT * per_100
        score += debug * DEBUG_WEIGHT * per_100
    score = min(score, 100.0)
    return RustFileAnalysis(
        file_path=file_path,
        total_lines=total,
        code_lines=len(code),
        comment_lines=len(commented),
        blank_lines=blank,
        ldr_equivalent=ldr,
        issues=issues,
        ast_mode=ast_mode,
        slop_score=score,
        status=classify_deficit(score).value,
    )
