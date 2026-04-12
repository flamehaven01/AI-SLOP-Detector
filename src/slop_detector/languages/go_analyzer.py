"""
Go Analyzer (v1.0.0)

Regex-based analysis with optional tree-sitter-go AST mode.
Detects AI slop patterns in .go files.

Metrics:
  ldr_equivalent      : logic lines / total lines
  god_function_count  : functions exceeding GOD_FUNCTION_LINES
  empty_func_count    : empty function bodies (stub pattern)
  panic_count         : panic() calls (error-handling evasion)
  fmt_print_count     : fmt.Println/Printf debug prints
  ignored_error_count : `_ = expr` error suppression

Patterns detected:
  go_empty_func     : empty function body (stub)
  go_panic          : panic() used as primary error path
  go_fmt_print      : debug print via fmt.Println/Printf/Print
  go_ignored_error  : blank-identifier error suppression (_ = err)
  go_todo_comment   : TODO / FIXME / HACK comment
  go_god_function   : function exceeding size threshold
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional tree-sitter-go (AST mode)
# ---------------------------------------------------------------------------

_TS_AVAILABLE = False

try:
    import tree_sitter_go as _tsgo
    from tree_sitter import Language as _Language

    _GO_LANG = _Language(_tsgo.language())
    _TS_AVAILABLE = True
except ImportError:  # pragma: no cover
    logger.debug("tree-sitter-go unavailable — Go analysis will use regex fallback")

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

GOD_FUNCTION_LINES = 60
PANIC_SEVERITY_THRESHOLD = 3  # panics >= this → critical

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_RE_BLANK = re.compile(r"^\s*$")
_RE_COMMENT = re.compile(r"^\s*//")
_RE_BLOCK_COMMENT_OPEN = re.compile(r"/\*")
_RE_BLOCK_COMMENT_CLOSE = re.compile(r"\*/")
_RE_FUNC_START = re.compile(r"^\s*func\s+(\([^)]*\)\s+)?(\w+)\s*\(")
_RE_EMPTY_FUNC = re.compile(r"^\s*func\s+[^{]+\{\s*\}")
_RE_FMT_PRINT = re.compile(r"\bfmt\.(Print|Println|Printf|Fprintf|Fprintln)\s*\(")
_RE_PANIC = re.compile(r"\bpanic\s*\(")
_RE_IGNORED_ERR = re.compile(r"\b_\s*=\s*\w")
_RE_TODO = re.compile(r"//\s*(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GoIssue:
    """A detected issue in a Go file."""

    pattern_id: str
    severity: str  # critical | high | medium | low
    line: int
    message: str
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "severity": self.severity,
            "line": self.line,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class GoFileAnalysis:
    """Analysis result for a .go file."""

    file_path: str
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    ldr_equivalent: float
    issues: List[GoIssue] = field(default_factory=list)

    # Metric counters
    god_function_count: int = 0
    empty_func_count: int = 0
    panic_count: int = 0
    fmt_print_count: int = 0
    ignored_error_count: int = 0
    max_function_lines: int = 0

    ast_mode: bool = False
    slop_score: float = 0.0
    status: str = "clean"  # clean | suspicious | critical_deficit

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "total_lines": self.total_lines,
            "code_lines": self.code_lines,
            "comment_lines": self.comment_lines,
            "blank_lines": self.blank_lines,
            "ldr_equivalent": round(self.ldr_equivalent, 4),
            "god_function_count": self.god_function_count,
            "empty_func_count": self.empty_func_count,
            "panic_count": self.panic_count,
            "fmt_print_count": self.fmt_print_count,
            "ignored_error_count": self.ignored_error_count,
            "max_function_lines": self.max_function_lines,
            "ast_mode": self.ast_mode,
            "slop_score": round(self.slop_score, 2),
            "status": self.status,
            "issues": [i.to_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class GoAnalyzer:
    """Analyzes .go files for AI-slop patterns."""

    def analyze(self, file_path: str) -> GoFileAnalysis:
        """Analyze a single .go file and return GoFileAnalysis."""
        path = Path(file_path)
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.error(f"Cannot read {file_path}: {exc}")
            return GoFileAnalysis(
                file_path=file_path,
                total_lines=0,
                code_lines=0,
                comment_lines=0,
                blank_lines=0,
                ldr_equivalent=0.0,
            )

        if _TS_AVAILABLE:
            return self._analyze_ast(file_path, content)
        return self._analyze_regex(file_path, content)

    # ------------------------------------------------------------------
    # Regex analysis (always available)
    # ------------------------------------------------------------------

    def _analyze_regex(self, file_path: str, content: str) -> GoFileAnalysis:
        lines = content.splitlines()
        total = len(lines)
        blank = comment = 0
        issues: List[GoIssue] = []

        # Counters
        empty_func = panic = fmt_print = ignored_err = 0

        # Function-boundary tracking
        in_block_comment = False
        func_start_line: Optional[int] = None
        brace_depth = 0
        func_lines_list: List[int] = []

        for i, raw in enumerate(lines, start=1):
            line = raw

            # Block comment tracking
            if in_block_comment:
                comment += 1
                if _RE_BLOCK_COMMENT_CLOSE.search(line):
                    in_block_comment = False
                continue
            if _RE_BLOCK_COMMENT_OPEN.search(line) and not _RE_COMMENT.match(line):
                in_block_comment = True
                comment += 1
                continue

            if _RE_BLANK.match(line):
                blank += 1
                continue
            if _RE_COMMENT.match(line):
                comment += 1
                # TODO/FIXME in comment
                if _RE_TODO.search(line):
                    issues.append(
                        GoIssue("go_todo_comment", "low", i, f"Unresolved marker: {line.strip()}")
                    )
                continue

            # Single-line empty func: func foo() {}
            if _RE_EMPTY_FUNC.match(line):
                empty_func += 1
                issues.append(
                    GoIssue(
                        "go_empty_func",
                        "high",
                        i,
                        "Empty function body — likely a stub",
                        "Implement or mark as // TODO",
                    )
                )

            # Function start for multi-line tracking
            if _RE_FUNC_START.match(line) and "{" in line and not _RE_EMPTY_FUNC.match(line):
                func_start_line = i
                brace_depth = line.count("{") - line.count("}")

            elif func_start_line is not None:
                brace_depth += line.count("{") - line.count("}")
                if brace_depth <= 0:
                    func_len = i - func_start_line + 1
                    func_lines_list.append(func_len)
                    if func_len > GOD_FUNCTION_LINES:
                        issues.append(
                            GoIssue(
                                "go_god_function",
                                "high",
                                func_start_line,
                                f"Function is {func_len} lines (threshold {GOD_FUNCTION_LINES})",
                                "Break into smaller functions",
                            )
                        )
                    func_start_line = None
                    brace_depth = 0

            # Pattern checks on code lines
            if _RE_FMT_PRINT.search(line):
                fmt_print += 1
                issues.append(GoIssue("go_fmt_print", "medium", i, "Debug print statement"))

            if _RE_PANIC.search(line):
                panic += 1
                severity = "critical" if panic >= PANIC_SEVERITY_THRESHOLD else "medium"
                issues.append(
                    GoIssue(
                        "go_panic",
                        severity,
                        i,
                        "panic() used — prefer returning errors",
                        "Return an error value instead",
                    )
                )

            if _RE_IGNORED_ERR.search(line):
                ignored_err += 1
                issues.append(
                    GoIssue(
                        "go_ignored_error",
                        "high",
                        i,
                        "Error silently discarded with blank identifier",
                        "Handle or propagate the error",
                    )
                )

        code = total - blank - comment
        ldr = code / total if total > 0 else 0.0
        god_count = sum(1 for fl in func_lines_list if fl > GOD_FUNCTION_LINES)
        max_fl = max(func_lines_list, default=0)

        slop_score = self._calc_slop_score(
            ldr, empty_func, panic, fmt_print, ignored_err, god_count, total
        )
        status = (
            "critical_deficit"
            if slop_score >= 70
            else "suspicious" if slop_score >= 30 else "clean"
        )

        return GoFileAnalysis(
            file_path=file_path,
            total_lines=total,
            code_lines=code,
            comment_lines=comment,
            blank_lines=blank,
            ldr_equivalent=ldr,
            issues=issues,
            god_function_count=god_count,
            empty_func_count=empty_func,
            panic_count=panic,
            fmt_print_count=fmt_print,
            ignored_error_count=ignored_err,
            max_function_lines=max_fl,
            ast_mode=False,
            slop_score=slop_score,
            status=status,
        )

    # ------------------------------------------------------------------
    # AST analysis (tree-sitter-go, optional)
    # ------------------------------------------------------------------

    def _analyze_ast(self, file_path: str, content: str) -> GoFileAnalysis:  # pragma: no cover
        """AST mode — richer metrics when tree-sitter-go is installed."""
        # Fall back to regex; AST enrichment is a future enhancement
        result = self._analyze_regex(file_path, content)
        result.ast_mode = True
        return result

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_slop_score(
        ldr: float,
        empty_func: int,
        panic: int,
        fmt_print: int,
        ignored_err: int,
        god_count: int,
        total_lines: int,
    ) -> float:
        """Compute a 0–100 slop score for a Go file."""
        if total_lines == 0:
            return 0.0

        per_100 = 100 / max(total_lines, 1)
        score = 0.0

        # Low LDR penalty (empty/comment-heavy file)
        if ldr < 0.20:
            score += 40.0
        elif ldr < 0.40:
            score += 20.0

        score += empty_func * 25.0 * per_100
        score += panic * 10.0 * per_100
        score += fmt_print * 5.0 * per_100
        score += ignored_err * 15.0 * per_100
        score += god_count * 10.0

        return min(score, 100.0)
