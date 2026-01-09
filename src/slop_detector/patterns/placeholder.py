"""Placeholder code detectors."""

from __future__ import annotations
import ast
import re
from typing import Optional

from slop_detector.patterns.base import ASTPattern, RegexPattern, Issue, Severity, Axis


class PassPlaceholderPattern(ASTPattern):
    """Detect functions with only pass statement."""

    id = "pass_placeholder"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Empty function with only pass - placeholder not implemented"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.FunctionDef):
            # Check if function body is only pass or docstring + pass
            body = [
                n
                for n in node.body
                if not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)
            ]

            if len(body) == 1 and isinstance(body[0], ast.Pass):
                return self.create_issue_from_node(
                    node, file, suggestion="Implement the function or remove it"
                )
        return None


class TodoCommentPattern(RegexPattern):
    """Detect TODO comments."""

    id = "todo_comment"
    severity = Severity.MEDIUM
    axis = Axis.NOISE
    message = "TODO comment - incomplete implementation"
    pattern = r"#\s*" + "TODO"

    def create_issue(self, file, line, column=0, code=None, message=None, suggestion=None):
        return super().create_issue(
            file,
            line,
            column,
            code,
            message or self.message,
            suggestion or "Complete the TODO or create a ticket",
        )


class FixmeCommentPattern(RegexPattern):
    """Detect FIXME comments."""

    id = "fixme_comment"
    severity = Severity.MEDIUM
    axis = Axis.NOISE
    message = "FIXME comment - known issue not addressed"
    pattern = r"#\s*" + "FIXME"

    def create_issue(self, file, line, column=0, code=None, message=None, suggestion=None):
        return super().create_issue(
            file,
            line,
            column,
            code,
            message or self.message,
            suggestion or "Fix the issue or create a ticket",
        )


class XXXCommentPattern(RegexPattern):
    """Detect XXX comments."""

    id = "xxx_comment"
    severity = Severity.LOW
    axis = Axis.NOISE
    message = "XXX comment - potential code smell"
    pattern = r"#\s*" + "XXX"


class HackCommentPattern(RegexPattern):
    """Detect HACK comments."""

    id = "hack_comment"
    severity = Severity.HIGH
    axis = Axis.STYLE
    message = "HACK comment - technical debt indicator"
    pattern = r"#\s*" + "HACK"

    def create_issue(self, file, line, column=0, code=None, message=None, suggestion=None):
        return super().create_issue(
            file,
            line,
            column,
            code,
            message or self.message,
            suggestion or "Refactor the hacky solution properly",
        )


class EllipsisPlaceholderPattern(ASTPattern):
    """Detect functions with only ellipsis (...)."""

    id = "ellipsis_placeholder"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Empty function with only ... - placeholder not implemented"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.FunctionDef):
            # Check if function body is only ellipsis or docstring + ellipsis
            body = [
                n
                for n in node.body
                if not (
                    isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)
                )
            ]

            if len(body) == 1:
                if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    if body[0].value.value is ...:
                        return self.create_issue_from_node(
                            node, file, suggestion="Implement the function or remove it"
                        )
        return None
