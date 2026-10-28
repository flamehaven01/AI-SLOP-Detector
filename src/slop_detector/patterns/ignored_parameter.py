"""A parameter the function never reads does not shape its result.

`upload(..., timeout_s=30.0)` that never applies the timeout, or
`predict_batch(..., batch_size=64)` that never batches, accepts an input its
result ignores. Reported: an option (a parameter with a default) that is never
read, and any unused parameter of a
function whose returned value depends on none of its inputs, or whose body only
builds values it discards. An unused positional parameter of a function
returning nothing (a handler, a printer) is not reported: such signatures are
usually fixed by the caller (measured: requiring only that the module calls the
function with the argument added 62-104 findings on the 14-repository replay,
mostly dispatch handlers and leftover helper arguments). Functions whose signature is fixed
elsewhere are left alone (declared intent): contracts and overrides, callbacks
registered by value, decorated functions, dunder methods, and methods of a
class with a base the module does not define.
"""

from __future__ import annotations

import ast
import re
from typing import List, Optional, Set

from slop_detector.patterns.base import Axis, Issue, Severity
from slop_detector.patterns.declared_intent import _SCOPE_NODES, _local_names
from slop_detector.patterns.placeholder import _PURE_BUILTINS, _IntentAwarePattern, _is_cosmetic

_IMPLICIT = frozenset({"self", "cls"})


def _with_defaults(args: ast.arguments) -> Set[str]:
    """Parameters that have a default value: options the function promises to honour."""
    positional = args.posonlyargs + args.args
    named = {a.arg for a in positional[len(positional) - len(args.defaults) :]}
    named |= {a.arg for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None}
    return named


def _uses(function: ast.AST) -> Set[str]:
    """Names the function body reads, a log line included.

    A read inside a nested function, lambda or comprehension that binds the same
    name itself (a parameter, a local) is that scope's own variable, not a use
    of the outer parameter.
    """
    used: Set[str] = set()
    stack: list = [(child, frozenset()) for child in function.body]  # type: ignore[attr-defined]
    while stack:
        node, shadowed = stack.pop()
        if isinstance(node, _SCOPE_NODES):
            shadowed = shadowed | frozenset(_local_names(node))
        # `del name` discards the argument on purpose; it counts as handled.
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
            if node.id not in shadowed:
                used.add(node.id)
        stack.extend((child, shadowed) for child in ast.iter_child_nodes(node))
    return used


# Docstring words that say a parameter is kept on purpose without being used.
_KEPT_WORDS = (
    "legacy",
    "compatib",
    "deprecat",
    "unused",
    "not used",
    "ignored",
    "kept for",
    "backward",
    "no longer",
    "tracking only",
)


def _documented_as_kept(function: ast.AST, name: str) -> bool:
    """A docstring line names the parameter and says it is kept or unused."""
    doc = ast.get_docstring(function) or ""  # type: ignore[arg-type]
    return any(
        name in line and any(word in line.lower() for word in _KEPT_WORDS)
        for line in doc.splitlines()
    )


def _documented(function: ast.AST, name: str) -> bool:
    """The docstring has an argument entry for the parameter: `name: ...`,
    `name (type): ...` or `name : type` at the start of a line."""
    doc = ast.get_docstring(function) or ""  # type: ignore[arg-type]
    entry = re.compile(r"^\s*[-*]?\s*" + re.escape(name) + r"\s*(\([^)]*\))?\s*:")
    return any(entry.match(line) for line in doc.splitlines())


# Defaults that inject a value (FastAPI): the framework uses the parameter.
_INJECTORS = frozenset({"Depends", "Security"})


def _injected(args: ast.arguments) -> Set[str]:
    """Parameters whose default is `Depends(...)` / `Security(...)`."""
    positional = args.posonlyargs + args.args
    pairs = list(zip(positional[len(positional) - len(args.defaults) :], args.defaults))
    pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
    found = set()
    for arg, default in pairs:
        if isinstance(default, ast.Call):
            func = default.func
            callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if callee in _INJECTORS:
                found.add(arg.arg)
    return found


def _annotated(args: ast.arguments) -> Set[str]:
    """Parameters annotated `Annotated[...]` (or `typing.Annotated[...]`)."""
    found = set()
    for arg in args.posonlyargs + args.args + args.kwonlyargs:
        ann = arg.annotation
        if isinstance(ann, ast.Subscript):
            head = ann.value
            name = head.attr if isinstance(head, ast.Attribute) else getattr(head, "id", "")
            if name == "Annotated":
                found.add(arg.arg)
    return found


def _is_stub_body(function: ast.AST) -> bool:
    """Only a docstring, `pass`, `...` or `raise NotImplementedError`: a stub, which
    the placeholder patterns report; its unused parameters say nothing more."""
    body = list(function.body)  # type: ignore[attr-defined]
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        if isinstance(stmt, ast.Raise) and "NotImplementedError" in ast.dump(stmt):
            continue
        return False
    return True


def _literal_results(function: ast.AST) -> bool:
    """Every returned value is a literal that reads no name at all (`True`, `{...}`)."""
    scopes = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
    found = False
    exit_codes = other_results = 0
    pending: list = list(function.body)  # type: ignore[attr-defined]
    while pending:
        node = pending.pop()
        if isinstance(node, scopes):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                continue
            if any(isinstance(n, ast.Name) for n in ast.walk(node.value)):
                return False
            found = True
            # An int that is not a bool is an exit code: a command handler's answer.
            if isinstance(node.value, ast.Constant) and type(node.value.value) is int:
                exit_codes += 1
            else:
                other_results += 1
        pending.extend(ast.iter_child_nodes(node))
    return found and not (exit_codes and not other_results)


def _pure_value(value: ast.expr) -> bool:
    """Builds a value without acting: literals, names, operators, pure builtins and
    methods of a literal (`"...".strip()`)."""
    for node in ast.walk(value):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in _PURE_BUILTINS:
            continue
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Constant):
            continue
        return False
    return True


def _discarded_locals(function: ast.AST) -> List[str]:
    """Locals the body only builds and drops, when that is all it does.

    Every statement after the docstring is `pass`, a log line, or an assignment
    of a pure value to a plain name the function never reads, and nothing is
    returned: `def prompt_fn(question): TEMPLATE = "...".strip()`.
    """
    body = list(function.body)  # type: ignore[attr-defined]
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    used = _uses(function)
    dropped: List[str] = []
    for stmt in body:
        if _is_cosmetic(stmt):
            continue
        names = _dead_store(stmt, used)
        if not names:
            return []
        dropped += names
    return dropped


def _dead_store(stmt: ast.stmt, used: Set[str]) -> List[str]:
    """The names a pure assignment binds when none is read later (public names
    only: `_x = ...` is a deliberate discard); [] otherwise."""
    if not (isinstance(stmt, ast.Assign) and _pure_value(stmt.value)):
        return []
    names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
    if len(names) != len(stmt.targets) or any(n in used or n.startswith("_") for n in names):
        return []
    return names


def _parameter_names(function: ast.AST) -> List[str]:
    args = function.args  # type: ignore[attr-defined]
    return [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]


class IgnoredParameterPattern(_IntentAwarePattern):
    """Detect parameters that do not affect the function's result."""

    id = "ignored_parameter"
    severity = Severity.MEDIUM
    axis = Axis.QUALITY
    message = "Parameter is never used - it does not affect the result"

    def _fixed_signature(self, node) -> Optional[str]:
        """Why the signature is fixed elsewhere, or None.

        "fixed": declared by the module (dunder, decorator, contract, override,
        callback) or by a base the module does not define ("outside base").
        "family": sibling methods take the same arguments (see _family).
        """
        intent = self._intent
        if intent is None:
            return "fixed"
        if node.name.startswith("__") or node.decorator_list:
            return "fixed"
        if (
            intent.is_contract(node)
            or intent.overrides_module_base(node)
            or intent.is_registered_by_value(node)
        ):
            return "fixed"
        # Methods of one class taking the same arguments form an interface
        # (handlers dispatched by name): their arguments are fixed by the family.
        klass = intent.enclosing_class(node)
        if klass is not None:
            mine = set(_parameter_names(node))
            if any(
                isinstance(other, (ast.FunctionDef, ast.AsyncFunctionDef))
                and other is not node
                and set(_parameter_names(other)) == mine
                for other in klass.body
            ):
                return "family"
        return "outside base" if intent.has_outside_base(node) else None

    def _family(self, node) -> list:
        klass = self._intent.enclosing_class(node) if self._intent else None
        mine = set(_parameter_names(node))
        return [
            other
            for other in (klass.body if klass is not None else [])
            if isinstance(other, (ast.FunctionDef, ast.AsyncFunctionDef))
            and other is not node
            and set(_parameter_names(other)) == mine
        ]

    _top_level: frozenset = frozenset()

    def check(self, tree: ast.AST, file, content) -> List[Issue]:
        # Top-level functions only: nested ones and methods are hooks of their scope.
        self._top_level = frozenset(
            node
            for node in getattr(tree, "body", [])
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        try:
            return super().check(tree, file, content)
        finally:
            self._top_level = frozenset()

    def _result_ignores_inputs(self, node) -> tuple:
        """(whether a module function's result reads no input, the locals it only
        builds and drops)."""
        if node not in self._top_level:
            return False, []
        dropped = _discarded_locals(node)
        return bool(dropped) or _literal_results(node), dropped

    @staticmethod
    def _evidence(dropped: List[str]) -> str:
        """What the body does instead of using its input, for the message."""
        if dropped:
            return f"; the body only builds {', '.join(dropped)} and discards it"
        return ""

    def check_node(self, node: ast.AST, file, content) -> Optional[List[Issue]]:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return None
        fixed = self._fixed_signature(node)
        if fixed in ("fixed", "outside base"):
            return None
        args = node.args
        names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
        names = [n for n in names if n not in _IMPLICIT and not n.startswith("_")]
        names = [n for n in names if n not in _injected(args)]
        # A docstring entry is the function's own promise about the argument.
        # `Annotated[...]` arguments are a framework's schema (tool or route
        # parameters), whatever their description says.
        documented = {n for n in names if _documented(node, n) and n not in _annotated(args)}
        if fixed == "family":
            # In a family the argument is fixed by convention, unless a sibling
            # reads it: then it means something, and this method ignores it.
            siblings = self._family(node)
            names = [n for n in names if n in documented and any(n in _uses(s) for s in siblings)]
        if not names:
            return None
        if _is_stub_body(node):
            return None
        used = _uses(node)
        options = _with_defaults(args)
        # A positional parameter left unused is reported only when a module
        # function answers with a literal that reads no input at all or only
        # builds values it discards; handlers, printers and class hooks take
        # fixed arguments.
        result_ignores_inputs, dropped = self._result_ignores_inputs(node)
        issues = []
        for name in names:
            if name in used or _documented_as_kept(node, name):
                continue
            if name not in options and name not in documented and not result_ignores_inputs:
                continue
            evidence = self._evidence(dropped)
            issues.append(
                self.create_issue_from_node(
                    node,
                    file,
                    message=(
                        f"Parameter '{name}' of '{node.name}' is never used{evidence} - it does "
                        "not affect the result"
                    ),
                    suggestion=f"Use '{name}' as the function promises, or remove it",
                )
            )
        return issues or None
