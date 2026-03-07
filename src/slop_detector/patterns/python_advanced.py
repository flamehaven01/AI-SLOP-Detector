"""
Python Advanced Structural Patterns (v2.8.0)

God function, dead code, and deep nesting detection.
Uses AST for precise analysis — no regex approximation.

Thresholds:
  GOD_FUNCTION_LINES       = 50  (lines in a single function)
  GOD_FUNCTION_COMPLEXITY  = 10  (cyclomatic complexity)
  DEEP_NESTING_THRESHOLD   = 4   (control flow nesting depth)
"""

from __future__ import annotations

import ast
from pathlib import Path

from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

GOD_FUNCTION_LINES = 50
GOD_FUNCTION_COMPLEXITY = 10
DEEP_NESTING_THRESHOLD = 4

# AST node types that contribute to cyclomatic complexity (+1 each)
_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
)

# Nodes whose body sequence we scan for dead code
_BLOCK_CONTAINER_FIELDS = ("body", "orelse", "finalbody", "handlers")

# Statement types that terminate control flow in their block
_TERMINAL_STMTS = (ast.Return, ast.Raise, ast.Break, ast.Continue)

# Compound statement types (have a nested body)
_COMPOUND_STMTS = (
    ast.If,
    ast.For,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
    ast.Try,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _cyclomatic_complexity(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Compute McCabe cyclomatic complexity of a function.

    Base complexity = 1.
    +1 for each: if, for, while, except, with, async-with, async-for.
    +1 for each additional boolean operator (and/or) in a BoolOp.
    """
    complexity = 1
    for node in ast.walk(func_node):
        if isinstance(node, _BRANCH_NODES):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            # AND / OR: each additional operand adds one branch
            complexity += len(node.values) - 1
    return complexity


def _max_nesting_depth(node: ast.AST, depth: int = 0) -> int:
    """Return maximum control-flow nesting depth within a node.

    Depth increases for: if, for, while, with, try, except.
    """
    max_d = depth
    if isinstance(
        node, (ast.If, ast.For, ast.While, ast.With, ast.AsyncWith, ast.AsyncFor, ast.Try)
    ):
        depth += 1
        max_d = depth

    for child in ast.iter_child_nodes(node):
        max_d = max(max_d, _max_nesting_depth(child, depth))

    return max_d


def _collect_dead_statements(
    stmts: list[ast.stmt],
) -> list[ast.stmt]:
    """Return statements in the block that follow a terminal statement."""
    dead: list[ast.stmt] = []
    found_terminal = False
    for stmt in stmts:
        if found_terminal:
            dead.append(stmt)
        elif isinstance(stmt, _TERMINAL_STMTS):
            found_terminal = True
    return dead


def _find_dead_code_in_tree(root: ast.AST) -> list[ast.stmt]:
    """Recursively find all unreachable statements in every block."""
    dead: list[ast.stmt] = []

    for node in ast.walk(root):
        # Check every named block field that contains a statement list
        for field_name in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field_name, None)
            if isinstance(stmts, list) and stmts:
                dead.extend(_collect_dead_statements(stmts))
        # try.handlers is a list of ExceptHandler, each with its own body
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                dead.extend(_collect_dead_statements(handler.body))

    return dead


# ------------------------------------------------------------------
# Patterns
# ------------------------------------------------------------------


class GodFunctionPattern(BasePattern):
    """Detect functions that are too large or too complex.

    A function is a 'god function' if:
      - It has more than GOD_FUNCTION_LINES non-blank lines, OR
      - Its cyclomatic complexity exceeds GOD_FUNCTION_COMPLEXITY.

    God functions are the primary carrier of slop in AI-generated code:
    they combine unrelated responsibilities and resist meaningful testing.
    """

    id = "god_function"
    severity = Severity.HIGH
    axis = Axis.STYLE
    message = "God function detected"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        lines = content.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)

            # Count non-blank logic lines within the function
            logic_lines = sum(
                1 for ln in lines[start - 1 : end] if ln.strip() and not ln.strip().startswith("#")
            )

            complexity = _cyclomatic_complexity(node)

            is_too_long = logic_lines > GOD_FUNCTION_LINES
            is_too_complex = complexity > GOD_FUNCTION_COMPLEXITY

            if is_too_long or is_too_complex:
                reasons = []
                if is_too_long:
                    reasons.append(f"{logic_lines} logic lines (limit {GOD_FUNCTION_LINES})")
                if is_too_complex:
                    reasons.append(f"complexity={complexity} (limit {GOD_FUNCTION_COMPLEXITY})")

                issues.append(
                    self.create_issue(
                        file=file,
                        line=start,
                        column=node.col_offset,
                        message=(f"God function '{node.name}': {', '.join(reasons)}"),
                        suggestion=(
                            "Break into smaller single-responsibility functions. "
                            "Each function should do one thing and fit on one screen."
                        ),
                    )
                )

        return issues


class DeadCodePattern(BasePattern):
    """Detect unreachable statements after return/raise/break/continue.

    AI-generated code frequently produces dead code when it inserts
    defensive logic after already-returned or raises, e.g.:
        return result
        print(\"done\")  # never reached
    """

    id = "dead_code"
    severity = Severity.MEDIUM
    axis = Axis.QUALITY
    message = "Unreachable code after return/raise/break/continue"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        dead_stmts = _find_dead_code_in_tree(tree)

        for stmt in dead_stmts:
            line = getattr(stmt, "lineno", 0)
            col = getattr(stmt, "col_offset", 0)
            issues.append(
                self.create_issue(
                    file=file,
                    line=line,
                    column=col,
                    message=self.message,
                    suggestion="Remove dead code. It is never executed and confuses readers.",
                )
            )

        return issues


class DeepNestingPattern(BasePattern):
    """Detect excessive control-flow nesting depth.

    Nesting depth > DEEP_NESTING_THRESHOLD in a single function is a
    strong signal of AI-generated 'defensive' code or absent abstractions.
    Each additional nesting level doubles cognitive load.
    """

    id = "deep_nesting"
    severity = Severity.HIGH
    axis = Axis.STYLE
    message = "Excessive nesting depth"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            depth = _max_nesting_depth(node)
            if depth > DEEP_NESTING_THRESHOLD:
                issues.append(
                    self.create_issue(
                        file=file,
                        line=node.lineno,
                        column=node.col_offset,
                        message=(
                            f"Function '{node.name}' has nesting depth {depth} "
                            f"(limit {DEEP_NESTING_THRESHOLD})"
                        ),
                        suggestion=(
                            "Extract nested blocks into helper functions. "
                            "Use early-return / guard clauses to reduce nesting."
                        ),
                    )
                )

        return issues
