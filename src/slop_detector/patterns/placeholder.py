"""Placeholder code detectors."""

from __future__ import annotations

import ast
from typing import Optional

from slop_detector.patterns.base import ASTPattern, Axis, Issue, RegexPattern, Severity


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


class NotImplementedPattern(ASTPattern):
    """Detect functions that raise NotImplementedError."""

    id = "not_implemented"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Function raises NotImplementedError - placeholder not implemented"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.FunctionDef):
            # Check if function body only raises NotImplementedError
            body = [
                n
                for n in node.body
                if not (
                    isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)
                )
            ]

            if len(body) == 1 and isinstance(body[0], ast.Raise):
                exc = body[0].exc
                if isinstance(exc, ast.Call):
                    if isinstance(exc.func, ast.Name) and exc.func.id == "NotImplementedError":
                        return self.create_issue_from_node(
                            node, file, suggestion="Implement the function or use ABC if intentional"
                        )
                elif isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                    return self.create_issue_from_node(
                        node, file, suggestion="Implement the function or use ABC if intentional"
                    )
        return None


class EmptyExceptPattern(ASTPattern):
    """Detect empty exception handlers (except: pass)."""

    id = "empty_except"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Empty exception handler - errors silently ignored"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.ExceptHandler):
            # Check if except body is only pass
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                exc_type = "all exceptions" if node.type is None else ast.unparse(node.type)
                return self.create_issue_from_node(
                    node,
                    file,
                    message=f"Empty exception handler for {exc_type} - errors silently ignored",
                    suggestion="Log the exception or handle it properly"
                )
        return None


class ReturnNonePlaceholderPattern(ASTPattern):
    """Detect functions that only return None."""

    id = "return_none_placeholder"
    severity = Severity.MEDIUM
    axis = Axis.QUALITY
    message = "Function only returns None - likely placeholder"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.FunctionDef):
            # Skip __init__ and other dunder methods
            if node.name.startswith("__") and node.name.endswith("__"):
                return None

            # Check if function body is only return None (or docstring + return None)
            body = [
                n
                for n in node.body
                if not (
                    isinstance(n, ast.Expr)
                    and isinstance(n.value, ast.Constant)
                    and isinstance(n.value.value, str)
                )
            ]

            if len(body) == 1 and isinstance(body[0], ast.Return):
                if body[0].value is None or (
                    isinstance(body[0].value, ast.Constant) and body[0].value.value is None
                ):
                    return self.create_issue_from_node(
                        node, file, suggestion="Implement the function or clarify intent"
                    )
        return None


class InterfaceOnlyClassPattern(ASTPattern):
    """Detect classes with only abstract methods or pass."""

    id = "interface_only_class"
    severity = Severity.MEDIUM
    axis = Axis.STYLE
    message = "Class contains only abstract methods or placeholders"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.ClassDef):
            # Get all methods
            methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

            if not methods:
                return None

            # Check if all methods are placeholders
            placeholder_methods = 0
            for method in methods:
                # Skip __init__ and other special methods
                if method.name.startswith("__") and method.name.endswith("__"):
                    continue

                # Check if method body is placeholder
                body = [
                    n
                    for n in method.body
                    if not (
                        isinstance(n, ast.Expr)
                        and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str)
                    )
                ]

                if len(body) == 1:
                    stmt = body[0]
                    # pass, ..., return None, raise NotImplementedError
                    is_placeholder = (
                        isinstance(stmt, ast.Pass)
                        or (
                            isinstance(stmt, ast.Expr)
                            and isinstance(stmt.value, ast.Constant)
                            and stmt.value.value is ...
                        )
                        or (
                            isinstance(stmt, ast.Return)
                            and (
                                stmt.value is None
                                or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
                            )
                        )
                        or isinstance(stmt, ast.Raise)
                    )
                    if is_placeholder:
                        placeholder_methods += 1

            # If most methods (>75%) are placeholders, flag the class
            if placeholder_methods >= len(methods) * 0.75 and placeholder_methods > 0:
                return self.create_issue_from_node(
                    node,
                    file,
                    message=f"Class has {placeholder_methods}/{len(methods)} placeholder methods",
                    suggestion="Use ABC (Abstract Base Class) if this is intentional, or implement methods"
                )

        return None
