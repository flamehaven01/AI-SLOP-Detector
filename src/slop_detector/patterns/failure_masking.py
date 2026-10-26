"""A catch-all handler that returns what the success path returns hides the failure.

When the handler answers with the same result as the `try` body's only return,
the caller cannot tell a failure from a success: the result does not depend on
whether the work happened. Only handlers that catch everything are read; a
narrow exception with a fallback is a decision about that error.

Left alone, because an external replay found them to be deliberate: a `try`
with several returns answering errors with its default, `except Exception:
return True` after a `try` that returns something else (fail-open / fail-closed
decisions), and a catch-all beside a handler that reports failure.
"""

from __future__ import annotations

import ast
from typing import List, Optional, Set

from slop_detector.patterns.base import ASTPattern, Axis, Issue, Severity
from slop_detector.patterns.placeholder import _is_cosmetic

_CATCH_ALL = frozenset({"Exception", "BaseException"})
_STATUS_KEYS = frozenset({"status", "state", "ok", "success", "healthy", "result"})
# Status values that say the work succeeded; the same one on both paths hides a failure.
_SUCCESS_STATUSES = frozenset({"up", "ok", "healthy", "success", "succeeded", "running", True})


def _catches_everything(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return True
    names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    for name in names:
        simple = name.attr if isinstance(name, ast.Attribute) else getattr(name, "id", "")
        if simple in _CATCH_ALL:
            return True
    return False


_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
_MUTATORS = frozenset(
    {"append", "extend", "insert", "update", "add", "setdefault", "pop", "remove", "clear"}
)


def _returns(statements: List[ast.stmt]) -> List[ast.Return]:
    """`return` statements of these statements, not counting nested functions or classes."""
    found: List[ast.Return] = []
    pending: List[ast.AST] = list(statements)
    while pending:
        node = pending.pop()
        if isinstance(node, _SCOPES):
            continue
        if isinstance(node, ast.Return):
            found.append(node)
        pending.extend(ast.iter_child_nodes(node))
    return found


def _success_return(node: ast.Try) -> Optional[ast.expr]:
    """The one result the success path can produce.

    Only a try body (with its else) holding a single `return` has one: with
    several, the last is usually the default answer ("not found", "deny"), and
    answering an error with the same default is a decision, not a mask.
    """
    returns = _returns(node.body + node.orelse)
    if len(returns) != 1 or returns[0].value is None:
        return None
    # It must end the success path; one early exit inside the try is a branch.
    block = node.orelse or node.body
    if block[-1] is not returns[0]:
        return None
    return returns[0].value


def _changed(statements: List[ast.stmt]) -> Set[str]:
    """Names the try body rebinds or fills (`x = ...`, `x[k] = ...`, `x.append(...)`)."""
    changed: Set[str] = set()
    for stmt in statements:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                changed.add(node.id)
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, (ast.Store, ast.Del))
                and isinstance(node.value, ast.Name)
            ):
                changed.add(node.value.id)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _MUTATORS
                and isinstance(node.func.value, ast.Name)
            ):
                changed.add(node.func.value.id)
    return changed


def _reports_failure(handler: ast.ExceptHandler) -> bool:
    """The handler raises or answers with a failure value."""
    final = handler.body[-1] if handler.body else None
    if isinstance(final, ast.Raise):
        return True
    return isinstance(final, ast.Return) and (final.value is None or _is_failure_value(final.value))


def _is_failure_value(value: ast.expr) -> bool:
    """None, False, 0, "" and empty containers say that nothing succeeded; so do a
    tuple holding False or None (`(False, reason)`) and a call passing a False
    keyword (`Usage(available=False)`)."""
    if isinstance(value, ast.Constant):
        return not value.value
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        if not value.elts:
            return True
        return isinstance(value, ast.Tuple) and any(
            isinstance(e, ast.Constant) and (e.value is False or e.value is None)
            for e in value.elts
        )
    if isinstance(value, ast.Dict):
        return not value.keys
    if isinstance(value, ast.Call):
        return any(
            isinstance(k.value, ast.Constant) and k.value.value is False for k in value.keywords
        )
    return False


def _success_statuses(value: ast.expr) -> set:
    if not isinstance(value, ast.Dict):
        return set()
    return {
        (key.value, item.value)
        for key, item in zip(value.keys, value.values)
        if isinstance(key, ast.Constant)
        and key.value in _STATUS_KEYS
        and isinstance(item, ast.Constant)
        and item.value in _SUCCESS_STATUSES
    }


def _same_result(value: ast.expr, success: ast.expr, reassigned: Set[str]) -> bool:
    """`value` is the success path's result, whatever happened in the try body."""
    if _is_failure_value(value):
        return False
    shared = _success_statuses(value) & _success_statuses(success)
    if shared:
        return True
    if ast.dump(value) != ast.dump(success):
        return False
    # The same expression is the same result only over names the try left alone.
    names = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
    return not names & reassigned


class FailureAsSuccessPattern(ASTPattern):
    """Detect catch-all handlers that return the success path's result."""

    id = "failure_as_success"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Catch-all handler returns the same result as the success path"

    def check_node(self, node: ast.AST, file, content) -> Optional[List[Issue]]:
        if not isinstance(node, ast.Try):
            return None
        success = _success_return(node)
        if success is None:
            return None
        # A sibling handler that reports failure means the try classifies its
        # errors; the catch-all's answer is then a deliberate one.
        if any(_reports_failure(h) for h in node.handlers if not _catches_everything(h)):
            return None
        reassigned = _changed(node.body + node.orelse)
        issues = []
        for handler in node.handlers:
            if not _catches_everything(handler) or not handler.body:
                continue
            final = handler.body[-1]
            if not isinstance(final, ast.Return) or final.value is None:
                continue
            if not all(_is_cosmetic(stmt) for stmt in handler.body[:-1]):
                continue
            if not _same_result(final.value, success, reassigned):
                continue
            shown = ast.unparse(final.value)[:60] if hasattr(ast, "unparse") else "it"
            issues.append(
                self.create_issue_from_node(
                    handler,
                    file,
                    message=(
                        f"Catch-all handler returns the same result as the success path "
                        f"({shown}) - the caller cannot tell the failure apart"
                    ),
                    suggestion="Return or raise a failure the caller can see",
                )
            )
        return issues or None
