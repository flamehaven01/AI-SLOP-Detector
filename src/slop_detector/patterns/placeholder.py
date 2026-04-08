"""Placeholder code detectors."""

from __future__ import annotations

import ast
from typing import List, Optional, Union

from slop_detector.patterns.base import ASTPattern, Axis, Issue, RegexPattern, Severity

# ---------------------------------------------------------------------------
# Module-level helpers — shared by multiple pattern classes
# ---------------------------------------------------------------------------


def _strip_docstring(body: List[ast.stmt]) -> List[ast.stmt]:
    """Return body with leading docstring node removed."""
    return [
        n
        for n in body
        if not (
            isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)
            and isinstance(n.value.value, str)
        )
    ]


def _has_abstractmethod(node: ast.FunctionDef) -> bool:
    """Return True if the function has an @abstractmethod decorator."""
    return any(
        (d.id if isinstance(d, ast.Name) else d.attr if isinstance(d, ast.Attribute) else "")
        == "abstractmethod"
        for d in node.decorator_list
    )


def _empty_container_repr(value: ast.expr) -> Optional[str]:
    """Return display string if value is an empty container literal, else None."""
    if isinstance(value, ast.List) and not value.elts:
        return "[]"
    if isinstance(value, ast.Dict) and not value.keys:
        return "{}"
    if isinstance(value, ast.Tuple) and not value.elts:
        return "()"
    if isinstance(value, ast.Set) and not value.elts:
        return "set()"
    return None


def _is_placeholder_stmt(stmt: ast.stmt) -> bool:
    """Return True if a single statement is a recognised placeholder body."""
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is ...
    if isinstance(stmt, ast.Return):
        # return None / return <constant>
        if stmt.value is None or isinstance(stmt.value, ast.Constant):
            return True
        # return self / return cls  (method-chaining stub)
        if isinstance(stmt.value, ast.Name) and stmt.value.id in ("self", "cls"):
            return True
        # return empty container
        if _empty_container_repr(stmt.value) is not None:
            return True
    return False


class PassPlaceholderPattern(ASTPattern):
    """Detect functions with only pass statement."""

    id = "pass_placeholder"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Empty function with only pass - placeholder not implemented"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if not isinstance(node, ast.FunctionDef):
            return None
        if _has_abstractmethod(node):
            return None
        body = _strip_docstring(node.body)
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
        if not isinstance(node, ast.FunctionDef):
            return None
        body = _strip_docstring(node.body)
        if len(body) == 1:
            stmt = body[0]
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                if stmt.value.value is ...:
                    return self.create_issue_from_node(
                        node, file, suggestion="Implement the function or remove it"
                    )
        return None


class NotImplementedPattern(ASTPattern):
    """Detect functions that raise NotImplementedError.

    Skips @abstractmethod decorated methods — raise NotImplementedError in an
    ABC interface is the correct Python pattern, not a placeholder.
    """

    id = "not_implemented"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Function raises NotImplementedError - placeholder not implemented"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if not isinstance(node, ast.FunctionDef):
            return None
        if _has_abstractmethod(node):
            return None
        body = _strip_docstring(node.body)
        if len(body) != 1 or not isinstance(body[0], ast.Raise):
            return None
        exc = body[0].exc
        is_not_impl = (
            isinstance(exc, ast.Call)
            and isinstance(exc.func, ast.Name)
            and exc.func.id == "NotImplementedError"
        ) or (isinstance(exc, ast.Name) and exc.id == "NotImplementedError")
        if is_not_impl:
            return self.create_issue_from_node(
                node, file, suggestion="Implement the function or use ABC if intentional"
            )
        return None


class EmptyExceptPattern(ASTPattern):
    """Detect empty exception handlers (except: pass).

    Severity depends on the exception type caught:
    - Bare 'except: pass'           -> CRITICAL (swallows SystemExit, KeyboardInterrupt)
    - 'except ImportError: pass'    -> LOW      (optional dependency guard pattern)
    - 'except SomeTypedExc: pass'   -> MEDIUM   (intentional but undocumented)
    """

    id = "empty_except"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Empty exception handler - errors silently ignored"

    # Exception types that indicate optional-dependency guard pattern
    _IMPORT_GUARD_NAMES: frozenset = frozenset({"ImportError", "ModuleNotFoundError"})

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if not isinstance(node, ast.ExceptHandler):
            return None
        if not (len(node.body) == 1 and isinstance(node.body[0], ast.Pass)):
            return None

        exc_node = node.type

        if exc_node is None:
            # Bare except: pass — catches everything, including SystemExit
            return self.create_issue(
                file=file,
                line=getattr(node, "lineno", 0),
                column=getattr(node, "col_offset", 0),
                message="Bare 'except: pass' swallows all exceptions including SystemExit",
                suggestion="Catch specific exception types and log or handle them properly",
                severity_override=Severity.CRITICAL,
            )

        # Check for optional dependency guard: except ImportError / ModuleNotFoundError
        exc_names: set[str] = set()
        if isinstance(exc_node, ast.Name):
            exc_names.add(exc_node.id)
        elif isinstance(exc_node, ast.Tuple):
            for elt in exc_node.elts:
                if isinstance(elt, ast.Name):
                    exc_names.add(elt.id)

        exc_type_str = ast.unparse(exc_node)

        if exc_names and exc_names.issubset(self._IMPORT_GUARD_NAMES):
            # Optional dependency guard — common and legitimate pattern
            return self.create_issue(
                file=file,
                line=getattr(node, "lineno", 0),
                column=getattr(node, "col_offset", 0),
                message=(
                    f"'except {exc_type_str}: pass' — optional dependency guard; "
                    f"verify this is intentional"
                ),
                suggestion=(
                    "Add a comment explaining which optional package is guarded "
                    "and what fallback behaviour is active."
                ),
                severity_override=Severity.LOW,
            )

        # Typed except with pass — intentional but undocumented silence
        return self.create_issue(
            file=file,
            line=getattr(node, "lineno", 0),
            column=getattr(node, "col_offset", 0),
            message=(f"Empty handler for '{exc_type_str}' silently discards the exception"),
            suggestion=(
                "Add logging (logger.debug/warning) or a comment explaining "
                "why silence is correct here."
            ),
            severity_override=Severity.MEDIUM,
        )


class ReturnNonePlaceholderPattern(ASTPattern):
    """Detect functions that only return None."""

    id = "return_none_placeholder"
    severity = Severity.MEDIUM
    axis = Axis.QUALITY
    message = "Function only returns None - likely placeholder"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if not isinstance(node, ast.FunctionDef):
            return None
        if node.name.startswith("__") and node.name.endswith("__"):
            return None
        body = _strip_docstring(node.body)
        if len(body) == 1 and isinstance(body[0], ast.Return):
            ret = body[0]
            if ret.value is None or (
                isinstance(ret.value, ast.Constant) and ret.value.value is None
            ):
                return self.create_issue_from_node(
                    node, file, suggestion="Implement the function or clarify intent"
                )
        return None


class ReturnConstantStubPattern(ASTPattern):
    """Detect functions whose entire body is a single return <constant> statement.

    Targets the adversarial ldr_gaming/stub_with_real_structure evasion:
    20 one-liner functions each returning a literal constant score high on LDR
    but carry zero semantic value.

    Excluded:
    - Dunder methods (__len__, __bool__, __hash__ etc. legitimately return constants)
    - @abstractmethod decorated functions
    - return None (covered by ReturnNonePlaceholderPattern)
    """

    id = "return_constant_stub"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Function body is a single return <constant> - likely stub"

    _DUNDER_CONSTANT_OK = frozenset(
        {
            "__len__",
            "__bool__",
            "__hash__",
            "__sizeof__",
            "__index__",
            "__int__",
            "__float__",
            "__complex__",
            "__str__",
            "__repr__",
            "__bytes__",
            "__format__",
        }
    )

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if not isinstance(node, ast.FunctionDef):
            return None

        # Skip dunder methods that legitimately return constants
        if node.name in self._DUNDER_CONSTANT_OK:
            return None

        # Skip @abstractmethod
        decorators = [
            (d.id if isinstance(d, ast.Name) else d.attr if isinstance(d, ast.Attribute) else "")
            for d in node.decorator_list
        ]
        if "abstractmethod" in decorators:
            return None

        body = _strip_docstring(node.body)
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            return None

        ret_val = body[0].value

        # return None is handled by ReturnNonePlaceholderPattern — skip
        if ret_val is None:
            return None
        if isinstance(ret_val, ast.Constant) and ret_val.value is None:
            return None

        # return <non-None constant>  (int, str, bool, float, bytes, ...)
        if isinstance(ret_val, ast.Constant):
            val_repr = repr(ret_val.value)[:40]
            return self.create_issue_from_node(
                node,
                file,
                message=f"Function '{node.name}' returns constant {val_repr} - likely stub",
                suggestion="Implement meaningful logic or remove the function",
            )

        # return <empty container>  ([], {}, (), set())
        container = _empty_container_repr(ret_val)
        if container is not None:
            return self.create_issue_from_node(
                node,
                file,
                message=f"Function '{node.name}' returns empty {container} - likely stub",
                suggestion="Implement meaningful logic or remove the function",
            )

        return None


class InterfaceOnlyClassPattern(ASTPattern):
    """Detect classes with only abstract methods or pass."""

    id = "interface_only_class"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Class contains only abstract methods or placeholders"

    def _count_placeholder_methods(
        self, methods: List[Union[ast.FunctionDef, ast.AsyncFunctionDef]]
    ) -> int:
        """Count non-dunder methods whose body is a single placeholder statement."""
        count = 0
        for method in methods:
            if method.name.startswith("__") and method.name.endswith("__"):
                continue
            body = _strip_docstring(method.body)
            if len(body) == 1 and _is_placeholder_stmt(body[0]):
                count += 1
        return count

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if not isinstance(node, ast.ClassDef):
            return None
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not methods:
            return None
        placeholder_count = self._count_placeholder_methods(methods)
        if placeholder_count >= len(methods) * 0.50 and placeholder_count > 0:
            return self.create_issue_from_node(
                node,
                file,
                message=f"Class has {placeholder_count}/{len(methods)} placeholder methods",
                suggestion="Use ABC (Abstract Base Class) if this is intentional, or implement methods",
            )
        return None
