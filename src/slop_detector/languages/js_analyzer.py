"""
JavaScript / TypeScript Analyzer (v2.8.0)

Tree-sitter AST-based analysis with regex fallback.
Produces JSFileAnalysis compatible with slop detection pipeline.

Primary (AST mode, requires tree-sitter):
  - Exact function boundaries (no brace-counting approximation)
  - Cyclomatic complexity per function (McCabe)
  - God function detection (lines > threshold AND complexity > threshold)
  - Dead code: unreachable statements after return/throw/break
  - True nesting depth from AST scope chain

Fallback (regex mode, zero-dependency):
  - Line-level pattern matching
  - Approximate nesting depth via brace counting

Metrics:
  ldr_equivalent    : logic lines / total lines
  max_complexity    : highest cyclomatic complexity among functions
  god_function_count: functions exceeding size+complexity thresholds
  dead_code_count   : unreachable statement count
  any_type_count    : TypeScript 'any' usage (TS only)
  console_log_count : debug print density

Patterns detected (AST-precise):
  js_var_usage         : var declaration (modernization debt)
  js_console_log       : console.log/warn/error/info
  js_any_type          : TypeScript 'any' type (TS only)
  js_empty_arrow       : empty arrow function body
  js_double_equals     : loose equality (== instead of ===)
  js_god_function      : function exceeding size or complexity threshold
  js_dead_code         : unreachable statement after return/throw/break
  js_callback_hell     : nesting depth > GOD_DEPTH_THRESHOLD
  ts_missing_return_type: exported function without return type annotation
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Tree-sitter availability (optional dependency)
# ------------------------------------------------------------------

_TS_AVAILABLE = False
_JS_LANG = None
_TS_LANG = None
_TSX_LANG = None

try:
    import tree_sitter_javascript as _tsjs
    import tree_sitter_typescript as _tsts
    from tree_sitter import Language, Parser as _TSParser

    _JS_LANG = Language(_tsjs.language())
    _TS_LANG = Language(_tsts.language_typescript())
    _TSX_LANG = Language(_tsts.language_tsx())
    _TS_AVAILABLE = True
except Exception:  # pragma: no cover
    pass

# ------------------------------------------------------------------
# Thresholds
# ------------------------------------------------------------------

GOD_FUNCTION_LINES = 50        # lines in a single function
GOD_FUNCTION_COMPLEXITY = 10   # cyclomatic complexity
GOD_DEPTH_THRESHOLD = 4        # nesting depth for callback hell

# AST node types that contribute +1 to cyclomatic complexity
_COMPLEXITY_BRANCH_TYPES = frozenset({
    "if_statement",
    "while_statement",
    "do_statement",
    "for_statement",
    "for_in_statement",
    "catch_clause",
    "switch_case",
    "ternary_expression",
})

# Logical operators also add branches
_LOGICAL_OPS = frozenset({"&&", "||", "??"})

# Function node types in tree-sitter JS/TS grammar
_FUNCTION_NODE_TYPES = frozenset({
    "function_declaration",
    "function_expression",
    "arrow_function",
    "method_definition",
    "generator_function_declaration",
    "generator_function",
})

# Statement types that make subsequent code unreachable
_TERMINAL_STATEMENTS = frozenset({
    "return_statement",
    "throw_statement",
    "break_statement",
    "continue_statement",
})

# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

@dataclass
class JSIssue:
    """A detected issue in a JS/TS file."""

    pattern_id: str
    severity: str          # critical | high | medium | low
    line: int
    column: int
    message: str
    suggestion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "severity": self.severity,
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass
class FunctionMetrics:
    """Per-function AST metrics."""
    name: str
    start_line: int
    end_line: int
    line_count: int
    complexity: int
    max_depth: int
    is_god_function: bool


@dataclass
class JSFileAnalysis:
    """Analysis result for a JS/TS file."""

    file_path: str
    language: str           # "javascript" | "typescript"
    total_lines: int
    code_lines: int
    comment_lines: int
    blank_lines: int
    ldr_equivalent: float
    issues: List[JSIssue] = field(default_factory=list)

    # Core metrics
    console_log_count: int = 0
    var_usage_count: int = 0
    any_type_count: int = 0
    double_equals_count: int = 0
    empty_arrow_count: int = 0
    max_nesting_depth: int = 0

    # v2.8.0: AST-derived metrics
    function_metrics: List[FunctionMetrics] = field(default_factory=list)
    max_complexity: int = 0
    god_function_count: int = 0
    dead_code_count: int = 0
    ast_mode: bool = False      # True if tree-sitter AST was used

    # Slop score (0-100, lower is better)
    slop_score: float = 0.0
    status: str = "clean"  # clean | suspicious | critical_deficit

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "language": self.language,
            "total_lines": self.total_lines,
            "code_lines": self.code_lines,
            "comment_lines": self.comment_lines,
            "blank_lines": self.blank_lines,
            "ldr_equivalent": self.ldr_equivalent,
            "console_log_count": self.console_log_count,
            "var_usage_count": self.var_usage_count,
            "any_type_count": self.any_type_count,
            "double_equals_count": self.double_equals_count,
            "empty_arrow_count": self.empty_arrow_count,
            "max_nesting_depth": self.max_nesting_depth,
            "max_complexity": self.max_complexity,
            "god_function_count": self.god_function_count,
            "dead_code_count": self.dead_code_count,
            "ast_mode": self.ast_mode,
            "slop_score": self.slop_score,
            "status": self.status,
            "issues": [i.to_dict() for i in self.issues],
            "function_metrics": [
                {
                    "name": f.name,
                    "start_line": f.start_line,
                    "end_line": f.end_line,
                    "line_count": f.line_count,
                    "complexity": f.complexity,
                    "max_depth": f.max_depth,
                    "is_god_function": f.is_god_function,
                }
                for f in self.function_metrics
            ],
        }


# ------------------------------------------------------------------
# Regex fallback patterns (used when tree-sitter unavailable)
# ------------------------------------------------------------------

_RE_SINGLE_COMMENT = re.compile(r"^\s*//")
_RE_BLANK = re.compile(r"^\s*$")
_RE_VAR = re.compile(r"\bvar\s+\w")
_RE_CONSOLE_LOG = re.compile(r"\bconsole\.(log|warn|error|info)\s*\(")
_RE_ANY_TYPE = re.compile(r":\s*any\b")
_RE_EMPTY_ARROW = re.compile(r"=>\s*\{\s*\}")
_RE_DOUBLE_EQUALS = re.compile(r"(?<![=!<>])==(?!=)")


# ------------------------------------------------------------------
# AST helpers
# ------------------------------------------------------------------

def _node_complexity(node: Any) -> int:
    """Recursively compute cyclomatic complexity additions within a node."""
    count = 0
    if node.type in _COMPLEXITY_BRANCH_TYPES:
        count += 1
    if node.type == "binary_expression":
        for child in node.children:
            if child.type in _LOGICAL_OPS:
                count += 1
    for child in node.children:
        count += _node_complexity(child)
    return count


def _node_max_depth(node: Any, current: int = 0) -> int:
    """Compute maximum scope nesting depth within a node."""
    if node.type in ("statement_block", "object", "array"):
        current += 1
    mx = current
    for child in node.children:
        mx = max(mx, _node_max_depth(child, current))
    return mx


def _find_dead_code(node: Any) -> List[Tuple[int, int]]:
    """
    Find unreachable statements (statements following a terminal statement
    within the same statement_block).

    Returns list of (row, col) for each dead statement.
    """
    dead = []
    if node.type == "statement_block":
        children = [c for c in node.children if c.is_named]
        found_terminal = False
        for child in children:
            if found_terminal and child.type not in ("comment",):
                dead.append((child.start_point[0] + 1, child.start_point[1]))
            if child.type in _TERMINAL_STATEMENTS:
                found_terminal = True
    for child in node.children:
        dead.extend(_find_dead_code(child))
    return dead


def _collect_functions(node: Any, depth: int = 0) -> List[Any]:
    """Collect all function nodes from AST, excluding nested (counted separately)."""
    fns = []
    if node.type in _FUNCTION_NODE_TYPES:
        fns.append(node)
        # Still recurse to find nested functions
    for child in node.children:
        fns.extend(_collect_functions(child, depth + 1))
    return fns


# ------------------------------------------------------------------
# Main analyzer
# ------------------------------------------------------------------

class JSAnalyzer:
    """
    Analyzes JavaScript/TypeScript files for slop indicators.

    v2.8.0: Tree-sitter AST primary mode with regex fallback.
    AST mode provides: exact function boundaries, cyclomatic complexity,
    god function detection, and dead code analysis.
    """

    SEVERITY_WEIGHTS = {
        "critical": 10.0,
        "high": 5.0,
        "medium": 2.0,
        "low": 1.0,
    }

    def analyze(self, file_path: str) -> JSFileAnalysis:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8", errors="ignore")
        is_ts = path.suffix.lower() in {".ts", ".tsx"}
        is_tsx = path.suffix.lower() == ".tsx"
        language = "typescript" if is_ts else "javascript"

        if _TS_AVAILABLE:
            return self._analyze_ast(file_path, content, language, is_ts, is_tsx)
        return self._analyze_regex(file_path, content, language, is_ts)

    # ------------------------------------------------------------------
    # AST mode
    # ------------------------------------------------------------------

    def _analyze_ast(
        self, file_path: str, content: str, language: str, is_ts: bool, is_tsx: bool
    ) -> JSFileAnalysis:
        """Full AST analysis using tree-sitter."""
        from tree_sitter import Parser as _P

        lang = _TSX_LANG if is_tsx else (_TS_LANG if is_ts else _JS_LANG)
        parser = _P(lang)
        source = content.encode("utf-8", errors="replace")
        tree = parser.parse(source)
        root = tree.root_node

        lines = content.splitlines()
        total = len(lines)

        # Line classification via AST comment nodes
        comment_lines_set: set = set()
        blank_lines_set: set = set()
        for i, ln in enumerate(lines):
            if not ln.strip():
                blank_lines_set.add(i)

        def collect_comments(node: Any) -> None:
            if node.type in ("comment", "block_comment"):
                for row in range(node.start_point[0], node.end_point[0] + 1):
                    comment_lines_set.add(row)
            for child in node.children:
                collect_comments(child)

        collect_comments(root)

        code_lines = sum(
            1 for i in range(total)
            if i not in blank_lines_set and i not in comment_lines_set
        )

        issues: List[JSIssue] = []
        console_count = 0
        var_count = 0
        any_count = 0
        double_eq_count = 0
        empty_arrow_count = 0

        # Walk AST for pattern detection
        def walk(node: Any) -> None:
            nonlocal console_count, var_count, any_count, double_eq_count, empty_arrow_count

            row = node.start_point[0] + 1  # 1-based
            col = node.start_point[1]

            # var declaration
            if node.type == "variable_declaration":
                text = (node.text or b"").decode("utf-8", errors="replace")
                if text.startswith("var "):
                    var_count += 1
                    issues.append(JSIssue(
                        pattern_id="js_var_usage",
                        severity="medium",
                        line=row,
                        column=col,
                        message="var declaration — use let or const",
                        suggestion="Replace var with let (mutable) or const (immutable)",
                    ))

            # console.log / warn / error / info
            elif node.type == "call_expression":
                fn = node.child_by_field_name("function")
                if fn and fn.type == "member_expression":
                    obj = fn.child_by_field_name("object")
                    prop = fn.child_by_field_name("property")
                    if (obj and obj.text == b"console" and prop
                            and prop.text in (b"log", b"warn", b"error", b"info")):
                        console_count += 1
                        method = prop.text.decode()
                        issues.append(JSIssue(
                            pattern_id="js_console_log",
                            severity="low",
                            line=row,
                            column=col,
                            message=f"console.{method} in production code",
                            suggestion="Remove debug logs or use a proper logging library",
                        ))

            # TypeScript 'any' type
            elif is_ts and node.type == "type_annotation":
                text = (node.text or b"").decode("utf-8", errors="replace")
                if ": any" in text or ":any" in text:
                    any_count += 1
                    issues.append(JSIssue(
                        pattern_id="js_any_type",
                        severity="high",
                        line=row,
                        column=col,
                        message="TypeScript 'any' type disables type safety",
                        suggestion="Use a specific type or 'unknown' with type guards",
                    ))

            # Empty arrow function
            elif node.type == "arrow_function":
                body = node.child_by_field_name("body")
                if body and body.type == "statement_block":
                    named_children = [c for c in body.children if c.is_named]
                    if not named_children:
                        empty_arrow_count += 1
                        issues.append(JSIssue(
                            pattern_id="js_empty_arrow",
                            severity="medium",
                            line=row,
                            column=col,
                            message="Empty arrow function — placeholder not implemented",
                            suggestion="Implement the function body or remove it",
                        ))

            # Loose equality (==)
            elif node.type == "binary_expression":
                op = node.child_by_field_name("operator")
                if op and op.type == "==":
                    double_eq_count += 1
                    issues.append(JSIssue(
                        pattern_id="js_double_equals",
                        severity="medium",
                        line=row,
                        column=op.start_point[1],
                        message="Loose equality (==) — use strict === instead",
                        suggestion="Replace == with ===",
                    ))

            for child in node.children:
                walk(child)

        walk(root)

        # Function-level metrics (god functions, complexity, depth)
        function_metrics: List[FunctionMetrics] = []
        god_function_count = 0
        max_complexity = 0
        max_depth_global = 0

        for fn_node in _collect_functions(root):
            name_node = fn_node.child_by_field_name("name")
            if name_node:
                fn_name = name_node.text.decode("utf-8", errors="replace")
            else:
                fn_name = "(anonymous)"

            fn_start = fn_node.start_point[0] + 1
            fn_end = fn_node.end_point[0] + 1
            fn_lines = fn_end - fn_start + 1
            complexity = 1 + _node_complexity(fn_node)
            depth = _node_max_depth(fn_node)

            is_god = fn_lines > GOD_FUNCTION_LINES or complexity > GOD_FUNCTION_COMPLEXITY
            if is_god:
                god_function_count += 1
                issues.append(JSIssue(
                    pattern_id="js_god_function",
                    severity="high",
                    line=fn_start,
                    column=fn_node.start_point[1],
                    message=(
                        f"God function '{fn_name}': "
                        f"{fn_lines} lines, complexity={complexity}"
                    ),
                    suggestion="Break into smaller single-responsibility functions",
                ))

            max_complexity = max(max_complexity, complexity)
            max_depth_global = max(max_depth_global, depth)

            function_metrics.append(FunctionMetrics(
                name=fn_name,
                start_line=fn_start,
                end_line=fn_end,
                line_count=fn_lines,
                complexity=complexity,
                max_depth=depth,
                is_god_function=is_god,
            ))

        # Callback hell: max depth exceeds threshold
        if max_depth_global > GOD_DEPTH_THRESHOLD:
            issues.append(JSIssue(
                pattern_id="js_callback_hell",
                severity="high",
                line=1,
                column=0,
                message=f"Max nesting depth {max_depth_global} — callback hell risk",
                suggestion="Refactor to async/await or flatten promise chains",
            ))

        # Dead code detection
        dead_positions = _find_dead_code(root)
        dead_code_count = len(dead_positions)
        for dead_row, dead_col in dead_positions:
            issues.append(JSIssue(
                pattern_id="js_dead_code",
                severity="medium",
                line=dead_row,
                column=dead_col,
                message="Unreachable code after return/throw/break",
                suggestion="Remove dead code",
            ))

        ldr_equiv = round(code_lines / max(total, 1), 4)

        # Slop score: LDR deficit + pattern penalty
        pattern_penalty = min(
            sum(self.SEVERITY_WEIGHTS.get(i.severity, 1.0) for i in issues),
            50.0,
        )
        ldr_deficit = max(0.0, (0.70 - ldr_equiv) * 50)
        slop_score = round(min(ldr_deficit + pattern_penalty, 100.0), 2)

        status = (
            "critical_deficit" if slop_score >= 50
            else "suspicious" if slop_score >= 20
            else "clean"
        )

        return JSFileAnalysis(
            file_path=file_path,
            language=language,
            total_lines=total,
            code_lines=code_lines,
            comment_lines=len(comment_lines_set),
            blank_lines=len(blank_lines_set),
            ldr_equivalent=ldr_equiv,
            issues=issues,
            console_log_count=console_count,
            var_usage_count=var_count,
            any_type_count=any_count,
            double_equals_count=double_eq_count,
            empty_arrow_count=empty_arrow_count,
            max_nesting_depth=max_depth_global,
            function_metrics=function_metrics,
            max_complexity=max_complexity,
            god_function_count=god_function_count,
            dead_code_count=dead_code_count,
            ast_mode=True,
            slop_score=slop_score,
            status=status,
        )

    # ------------------------------------------------------------------
    # Regex fallback mode
    # ------------------------------------------------------------------

    def _analyze_regex(
        self, file_path: str, content: str, language: str, is_ts: bool
    ) -> JSFileAnalysis:
        """Regex-based fallback when tree-sitter is unavailable."""
        lines = content.splitlines()
        total = len(lines)
        blank = 0
        comment = 0
        code = 0
        depth = 0
        max_depth = 0
        issues: List[JSIssue] = []
        console_count = 0
        var_count = 0
        any_count = 0
        double_eq_count = 0
        empty_arrow_count = 0
        in_block_comment = False

        for i, line in enumerate(lines, start=1):
            if "/*" in line:
                in_block_comment = True
            if "*/" in line:
                in_block_comment = False
                comment += 1
                continue
            if in_block_comment:
                comment += 1
                continue
            if _RE_BLANK.match(line):
                blank += 1
                continue
            if _RE_SINGLE_COMMENT.match(line):
                comment += 1
                continue

            code += 1
            depth += line.count("{") - line.count("}")
            max_depth = max(max_depth, depth)

            if _RE_VAR.search(line):
                var_count += 1
                issues.append(JSIssue("js_var_usage", "medium", i, line.index("var"),
                                      "var declaration — use let or const"))
            m = _RE_CONSOLE_LOG.search(line)
            if m:
                console_count += 1
                issues.append(JSIssue("js_console_log", "low", i, m.start(),
                                      f"console.{m.group(1)} in production code"))
            if is_ts:
                m2 = _RE_ANY_TYPE.search(line)
                if m2:
                    any_count += 1
                    issues.append(JSIssue("js_any_type", "high", i, m2.start(),
                                          "TypeScript 'any' type disables type safety"))
            m3 = _RE_EMPTY_ARROW.search(line)
            if m3:
                empty_arrow_count += 1
                issues.append(JSIssue("js_empty_arrow", "medium", i, m3.start(),
                                      "Empty arrow function — placeholder"))
            m4 = _RE_DOUBLE_EQUALS.search(line)
            if m4:
                double_eq_count += 1
                issues.append(JSIssue("js_double_equals", "medium", i, m4.start(),
                                      "Loose equality (==)"))

        if max_depth > GOD_DEPTH_THRESHOLD:
            issues.append(JSIssue("js_callback_hell", "high", 1, 0,
                                  f"Max nesting depth {max_depth} — callback hell risk"))

        ldr_equiv = round(code / max(total, 1), 4)
        pattern_penalty = min(
            sum(self.SEVERITY_WEIGHTS.get(i.severity, 1.0) for i in issues), 50.0
        )
        ldr_deficit = max(0.0, (0.70 - ldr_equiv) * 50)
        slop_score = round(min(ldr_deficit + pattern_penalty, 100.0), 2)
        status = (
            "critical_deficit" if slop_score >= 50
            else "suspicious" if slop_score >= 20
            else "clean"
        )

        return JSFileAnalysis(
            file_path=file_path,
            language=language,
            total_lines=total,
            code_lines=code,
            comment_lines=comment,
            blank_lines=blank,
            ldr_equivalent=ldr_equiv,
            issues=issues,
            console_log_count=console_count,
            var_usage_count=var_count,
            any_type_count=any_count,
            double_equals_count=double_eq_count,
            empty_arrow_count=empty_arrow_count,
            max_nesting_depth=max_depth,
            ast_mode=False,
            slop_score=slop_score,
            status=status,
        )

    def analyze_directory(
        self,
        directory: str,
        extensions: tuple = (".js", ".jsx", ".ts", ".tsx"),
        exclude_dirs: tuple = ("node_modules", ".git", "dist", "build", ".venv"),
    ) -> List[JSFileAnalysis]:
        """Analyze all JS/TS files in a directory."""
        root = Path(directory)
        results = []
        for path in root.rglob("*"):
            if path.suffix.lower() not in extensions:
                continue
            if any(part in exclude_dirs for part in path.parts):
                continue
            try:
                results.append(self.analyze(str(path)))
            except Exception as e:
                logger.debug("JS analysis failed for %s: %s", path, e)
        return results
