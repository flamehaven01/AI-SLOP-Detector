"""Complexity-related Python patterns: GodFunction, DeadCode, DeepNesting, NestedComplexity."""

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity

GOD_FUNCTION_LINES = 50
GOD_FUNCTION_COMPLEXITY = 10
DEEP_NESTING_THRESHOLD = 4

_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
)

_BLOCK_CONTAINER_FIELDS = ("body", "orelse", "finalbody", "handlers")

_TERMINAL_STMTS = (ast.Return, ast.Raise, ast.Break, ast.Continue)

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

_NESTED_CC_THRESHOLD = 5
_NESTED_DEPTH_THRESHOLD = 4


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
            complexity += len(node.values) - 1
    return complexity


def _max_nesting_depth(node: ast.AST, depth: int = 0) -> int:
    """Return maximum control-flow nesting depth within a node."""
    max_d = depth
    if isinstance(
        node, (ast.If, ast.For, ast.While, ast.With, ast.AsyncWith, ast.AsyncFor, ast.Try)
    ):
        depth += 1
        max_d = depth

    for child in ast.iter_child_nodes(node):
        max_d = max(max_d, _max_nesting_depth(child, depth))

    return max_d


def _collect_dead_statements(stmts: list[ast.stmt]) -> list[ast.stmt]:
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
        for field_name in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field_name, None)
            if isinstance(stmts, list) and stmts:
                dead.extend(_collect_dead_statements(stmts))
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                dead.extend(_collect_dead_statements(handler.body))

    return dead


# ------------------------------------------------------------------
# Patterns
# ------------------------------------------------------------------


class GodFunctionPattern(BasePattern):
    """Detect functions that are too large or too complex."""

    id = "god_function"
    severity = Severity.HIGH
    axis = Axis.STYLE
    message = "God function detected"

    def __init__(
        self,
        complexity_threshold: int = GOD_FUNCTION_COMPLEXITY,
        lines_threshold: int = GOD_FUNCTION_LINES,
        domain_overrides: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__()
        self.complexity_threshold = complexity_threshold
        self.lines_threshold = lines_threshold
        self.domain_overrides: List[Dict[str, Any]] = domain_overrides or []

    def _thresholds_for(self, func_name: str) -> tuple[int, int]:
        for override in self.domain_overrides:
            pattern = override.get("function_pattern", "")
            if pattern and fnmatch.fnmatch(func_name, pattern):
                cc = int(override.get("complexity_threshold", self.complexity_threshold))
                ln = int(override.get("lines_threshold", self.lines_threshold))
                return cc, ln
        return self.complexity_threshold, self.lines_threshold

    def _make_god_issue(
        self,
        file: Path,
        node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
        start: int,
        logic_lines: int,
        complexity: int,
        ln_limit: int,
        cc_limit: int,
        is_too_long: bool,
        is_too_complex: bool,
    ) -> Issue:
        reasons = []
        if is_too_long:
            reasons.append(f"{logic_lines} logic lines (limit {ln_limit})")
        if is_too_complex:
            reasons.append(f"complexity={complexity} (limit {cc_limit})")
        if is_too_complex:
            sev = Severity.HIGH
        elif is_too_long and complexity <= 5:
            sev = Severity.LOW
        else:
            sev = Severity.MEDIUM
        return self.create_issue(
            file=file,
            line=start,
            column=node.col_offset,
            message=f"God function '{node.name}': {', '.join(reasons)}",
            suggestion=(
                "Break into smaller single-responsibility functions. "
                "Each function should do one thing and fit on one screen."
            ),
            severity_override=sev,
        )

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        lines = content.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)

            logic_lines = sum(
                1 for ln in lines[start - 1 : end] if ln.strip() and not ln.strip().startswith("#")
            )

            complexity = _cyclomatic_complexity(node)
            cc_limit, ln_limit = self._thresholds_for(node.name)

            is_too_long = logic_lines > ln_limit
            is_too_complex = complexity > cc_limit

            if is_too_long or is_too_complex:
                issues.append(
                    self._make_god_issue(
                        file,
                        node,
                        start,
                        logic_lines,
                        complexity,
                        ln_limit,
                        cc_limit,
                        is_too_long,
                        is_too_complex,
                    )
                )

        return issues


class DeadCodePattern(BasePattern):
    """Detect unreachable statements after return/raise/break/continue."""

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
    """Detect excessive control-flow nesting depth."""

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


class NestedComplexityPattern(BasePattern):
    """Detect functions that combine deep nesting with moderate cyclomatic complexity."""

    id = "nested_complexity"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY

    def __init__(
        self,
        depth_threshold: int = _NESTED_DEPTH_THRESHOLD,
        cc_threshold: int = _NESTED_CC_THRESHOLD,
        domain_overrides: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__()
        self.depth_threshold = depth_threshold
        self.cc_threshold = cc_threshold
        self.domain_overrides: List[Dict[str, Any]] = domain_overrides or []

    def _thresholds_for(self, func_name: str) -> tuple[int, int]:
        for override in self.domain_overrides:
            pattern = override.get("function_pattern", "")
            if pattern and fnmatch.fnmatch(func_name, pattern):
                depth = int(override.get("depth_threshold", self.depth_threshold))
                cc = int(override.get("cc_threshold", self.cc_threshold))
                return depth, cc
        return self.depth_threshold, self.cc_threshold

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            depth = _max_nesting_depth(node)
            cc = _cyclomatic_complexity(node)
            depth_limit, cc_limit = self._thresholds_for(node.name)
            if depth >= depth_limit and cc >= cc_limit:
                issues.append(
                    self.create_issue(
                        file=file,
                        line=node.lineno,
                        column=node.col_offset,
                        message=(
                            f"Function '{node.name}' has both deep nesting (depth={depth}) "
                            f"and high cyclomatic complexity (cc={cc}) "
                            f"-- structural complexity composite"
                        ),
                        suggestion=(
                            "Extract nested blocks into named helper functions. "
                            "Use early-return / guard clauses and reduce branch count."
                        ),
                    )
                )
        return issues
