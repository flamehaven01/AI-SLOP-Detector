"""Structural anti-pattern detectors."""

from __future__ import annotations

import ast
from typing import Optional

from slop_detector.patterns.base import ASTPattern, Axis, Issue, Severity


class BareExceptPattern(ASTPattern):
    """Detect bare except clauses that catch everything."""

    id = "bare_except"
    severity = Severity.CRITICAL
    axis = Axis.STRUCTURE
    message = "Bare except catches everything including SystemExit and KeyboardInterrupt"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:  # except: (no exception type)
                # The bare handler is reported here only (empty_except leaves it).
                swallows = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
                return self.create_issue_from_node(
                    node,
                    file,
                    message=(
                        "Bare except with only pass swallows all exceptions, including "
                        "SystemExit and KeyboardInterrupt"
                        if swallows
                        else None
                    ),
                    suggestion="Catch specific exceptions: except ValueError as e:",
                )
        return None


class MutableDefaultArgPattern(ASTPattern):
    """Detect mutable default arguments (lists, dicts, sets)."""

    id = "mutable_default_arg"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Mutable default argument - shared state bug"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if not isinstance(node, ast.FunctionDef):
            return None
        positional = node.args.posonlyargs + node.args.args
        defaults = node.args.defaults
        names = {
            param.arg
            for param, default in zip(positional[len(positional) - len(defaults) :], defaults)
            if isinstance(default, (ast.List, ast.Dict, ast.Set))
        }
        if not names:
            return None
        shared = _shares_default(node, names)
        return self.create_issue(
            file=file,
            line=node.lineno,
            column=node.col_offset,
            message=(
                None
                if shared
                else "Mutable default argument (not mutated here) - shared if ever mutated"
            ),
            suggestion="Use None as default: def func(items=None):\n    if items is None:\n        items = []",
            severity_override=None if shared else Severity.HIGH,
        )


# Calls that change a list, dict or set in place.
_MUTATING_METHODS = frozenset(
    {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "sort",
        "reverse",
        "update",
        "setdefault",
        "popitem",
        "add",
        "discard",
    }
)


def _shares_default(function: ast.FunctionDef, names: set) -> bool:
    """Evidence that a mutable default is shared state: the function mutates it
    (mutating method, item or attribute assignment, augmented assignment,
    deletion) or lets it escape (return, yield, alias).
    """

    def is_param(node: ast.AST) -> bool:
        return isinstance(node, ast.Name) and node.id in names

    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if is_param(node.func.value) and node.func.attr in _MUTATING_METHODS:
                return True
        elif isinstance(node, (ast.Assign, ast.Delete)):
            if any(
                isinstance(target, (ast.Subscript, ast.Attribute)) and is_param(target.value)
                for target in node.targets
            ):
                return True
            if isinstance(node, ast.Assign) and is_param(node.value):
                return True  # aliased: the alias may be mutated or kept
        elif isinstance(node, ast.AugAssign):
            target = node.target
            if is_param(target) or (
                isinstance(target, (ast.Subscript, ast.Attribute)) and is_param(target.value)
            ):
                return True
        elif isinstance(node, (ast.Return, ast.Yield)) and node.value is not None:
            if is_param(node.value):
                return True
    return False


class StarImportPattern(ASTPattern):
    """Detect star imports (from module import *)."""

    id = "star_import"
    severity = Severity.HIGH
    axis = Axis.STRUCTURE
    message = "Star import pollutes namespace and hides dependencies"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Import specific names: from module import SpecificClass",
                    )
        return None


class GlobalStatementPattern(ASTPattern):
    """Detect global statement abuse."""

    id = "global_statement"
    severity = Severity.HIGH
    axis = Axis.STRUCTURE
    message = "Global statement makes code harder to test and reason about"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Global):
            return self.create_issue_from_node(
                node, file, suggestion="Pass variables as arguments or use class attributes"
            )
        return None
