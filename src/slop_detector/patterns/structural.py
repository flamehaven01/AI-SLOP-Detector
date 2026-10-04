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
                return self.create_issue_from_node(
                    node, file, suggestion="Catch specific exceptions: except ValueError as e:"
                )
        return None


class MutableDefaultArgPattern(ASTPattern):
    """Detect mutable default arguments (lists, dicts, sets)."""

    id = "mutable_default_arg"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Mutable default argument - shared state bug"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.FunctionDef):
            for arg in node.args.defaults:
                if isinstance(arg, (ast.List, ast.Dict, ast.Set)):
                    return self.create_issue_from_node(
                        node,
                        file,
                        suggestion="Use None as default: def func(items=None):\n    if items is None:\n        items = []",
                    )
        return None


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
