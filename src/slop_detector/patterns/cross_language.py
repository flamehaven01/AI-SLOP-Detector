"""Cross-language pattern detectors - AI leaks patterns from other languages.

The method and attribute idioms (`.push`, `.equals`, `.each`, `.Length`) are
reported only when the receiver is proven to be a Python built-in: a built-in
literal, or a name bound exactly once in the same scope, by a top-level
statement before the use, to a built-in literal or an unshadowed built-in
constructor. On a built-in these members do not exist, so the call fails at
run time. Any receiver that is not proven (a parameter, an attribute, a
factory result, a name bound in a branch or rebound) is not a finding: many
real APIs are called `push` or `equals`. This is a definite-positive subset,
not type inference.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Set, Union

from slop_detector.ast_index import walk_nodes
from slop_detector.patterns.base import ASTPattern, Axis, BasePattern, Issue, Severity

# Constructors whose call returns a built-in of that type, unless the name is rebound.
_BUILTIN_CONSTRUCTORS = frozenset(
    {"list", "dict", "set", "frozenset", "tuple", "str", "bytes", "bytearray"}
)
_BUILTIN_LITERALS = (
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.JoinedStr,
)
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_NESTED_SCOPES = _DEFS + (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
Scope = Union[ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]


def _scope_nodes(scope: Scope) -> Iterator[ast.AST]:
    """Nodes evaluated in `scope` itself; nested scopes are yielded, not entered."""
    stack: List[ast.AST] = list(scope.body)
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _NESTED_SCOPES):
            stack.extend(ast.iter_child_nodes(node))


def _parameters(scope: Scope) -> List[ast.arg]:
    if not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    args = scope.args
    extra = [a for a in (args.vararg, args.kwarg) if a is not None]
    return [*args.posonlyargs, *args.args, *args.kwonlyargs, *extra]


def _binding_names(node: ast.AST) -> List[str]:
    """Names a single node binds in the scope it is evaluated in."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
        return [node.id]
    if isinstance(node, _DEFS):
        return [node.name]
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [(alias.asname or alias.name).split(".")[0] for alias in node.names]
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return list(node.names)
    if isinstance(node, ast.ExceptHandler) and node.name:
        return [node.name]
    return []


def _bindings(scope: Scope) -> Dict[str, List[ast.AST]]:
    """Every binding site of every name in `scope`, parameters and `global` included."""
    sites: Dict[str, List[ast.AST]] = defaultdict(list)
    for arg in _parameters(scope):
        sites[arg.arg].append(arg)
    for node in _scope_nodes(scope):
        for name in _binding_names(node):
            sites[name].append(node)
    return sites


def _shadowed_constructors(tree: ast.Module) -> Set[str]:
    """Constructor names bound anywhere in the module: their calls prove nothing."""
    shadowed: Set[str] = set()
    for node in walk_nodes(tree):
        names = [node.arg] if isinstance(node, ast.arg) else _binding_names(node)
        shadowed.update(n for n in names if n in _BUILTIN_CONSTRUCTORS)
    return shadowed


def _is_builtin_value(value: ast.expr, shadowed: Set[str]) -> bool:
    if isinstance(value, _BUILTIN_LITERALS):
        return True
    if isinstance(value, ast.Constant) and isinstance(value.value, (str, bytes)):
        return True
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in _BUILTIN_CONSTRUCTORS
        and value.func.id not in shadowed
    )


def _single_assignment_value(stmt: ast.stmt, site: ast.AST) -> Optional[ast.expr]:
    """The value `stmt` assigns when its only target is `site`, else None."""
    if isinstance(stmt, ast.Assign) and stmt.targets == [site]:
        return stmt.value
    if isinstance(stmt, ast.AnnAssign) and stmt.target is site:
        return stmt.value
    return None


def _proven_builtin(
    scope: Scope,
    receiver: ast.expr,
    use: ast.AST,
    sites: Dict[str, List[ast.AST]],
    shadowed: Set[str],
) -> bool:
    """Is `receiver` a built-in at `use`? Only straight-line, single-binding proof counts."""
    if _is_builtin_value(receiver, shadowed):
        return True
    if not isinstance(receiver, ast.Name) or len(sites.get(receiver.id, ())) != 1:
        return False
    site = sites[receiver.id][0]
    for stmt in scope.body:  # top-level statements only: a binding in a branch proves nothing
        value = _single_assignment_value(stmt, site)
        if value is None:
            continue
        end = (getattr(stmt, "end_lineno", stmt.lineno), getattr(stmt, "end_col_offset", 0))
        before = end <= (getattr(use, "lineno", 0), getattr(use, "col_offset", 0))
        return before and _is_builtin_value(value, shadowed)
    return False


class _BuiltinReceiverPattern(BasePattern):
    """A foreign-language member used on a value proven to be a Python built-in."""

    member = ""
    called = True  # `.member(...)`; False for an attribute such as `.Length`
    suggestion = ""

    def _receiver(self, node: ast.AST) -> Optional[ast.expr]:
        if self.called:
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                return node.func.value if node.func.attr == self.member else None
            return None
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            return node.value if node.attr == self.member else None
        return None

    def check(self, tree: ast.AST, file, content: str) -> List[Issue]:
        if not isinstance(tree, ast.Module):
            return []
        # Every finding needs `.member` somewhere in the module; most modules
        # have none, and then the scope analysis below cannot find anything.
        if not any(
            isinstance(node, ast.Attribute) and node.attr == self.member
            for node in walk_nodes(tree)
        ):
            return []
        shadowed = _shadowed_constructors(tree)
        scopes: List[Scope] = [tree]
        scopes.extend(node for node in walk_nodes(tree) if isinstance(node, _DEFS))
        issues: List[Issue] = []
        for scope in scopes:
            sites: Optional[Dict[str, List[ast.AST]]] = None
            for node in _scope_nodes(scope):
                receiver = self._receiver(node)
                if receiver is None:
                    continue
                sites = sites if sites is not None else _bindings(scope)
                if _proven_builtin(scope, receiver, node, sites, shadowed):
                    issues.append(
                        self.create_issue_from_node(node, file, suggestion=self.suggestion)
                    )
        return issues


class JavaScriptPushPattern(_BuiltinReceiverPattern):
    """Detect .push() on a built-in instead of .append() (JavaScript pattern)."""

    id = "js_push"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "JavaScript pattern: use .append() instead of .push()"
    member = "push"
    suggestion = "Use Python's .append() method"


class JavaEqualsPattern(_BuiltinReceiverPattern):
    """Detect .equals() on a built-in instead of == (Java pattern)."""

    id = "java_equals"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Java pattern: use == instead of .equals()"
    member = "equals"
    suggestion = "Use == for comparison in Python"


class RubyEachPattern(_BuiltinReceiverPattern):
    """Detect .each on a built-in instead of a for loop (Ruby pattern)."""

    id = "ruby_each"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Ruby pattern: use for loop instead of .each"
    member = "each"
    suggestion = "Use 'for item in collection:' in Python"


class GoPrintPattern(ASTPattern):
    """Detect fmt.Println() instead of print() (Go pattern)."""

    id = "go_println"
    severity = Severity.MEDIUM
    axis = Axis.QUALITY
    message = "Go pattern: use print() instead of fmt.Println()"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "Println":
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id == "fmt":
                            return self.create_issue_from_node(
                                node, file, suggestion="Use Python's print() function"
                            )
        return None


class CSharpLengthPattern(_BuiltinReceiverPattern):
    """Detect .Length (capitalized) on a built-in instead of len() (C# pattern)."""

    id = "csharp_length"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "C# pattern: use len() instead of .Length"
    member = "Length"
    called = False
    suggestion = "Use Python's len(object) function"


class PHPStrlenPattern(ASTPattern):
    """Detect strlen() instead of len() (PHP pattern)."""

    id = "php_strlen"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "PHP pattern: use len() instead of strlen()"

    def check_node(self, node: ast.AST, file, content) -> Optional[Issue]:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id == "strlen":
                    return self.create_issue_from_node(
                        node, file, suggestion="Use Python's len() function"
                    )
        return None
