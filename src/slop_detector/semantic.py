"""Static semantic facts read from a module's closed call graph.

A single-function rule sees `save(record)` read `record` when it passes it on
to `self._write(record)`; whether `_write` uses it is a fact about the call
graph. Two facts are reported, both about functions the module defines:

- input_never_used: a parameter the function reads only to pass it to module
  functions that drop it, so it reaches no result and no effect, in a function
  that returns a value (one it never reads is ignored_parameter's finding);
- success_without_effect: a function whose every return is `True`, a short
  success string, or the answer of a module function that only reports
  success, that calls module functions to do its work, and whose calls all
  resolve to module functions with no effect (log lines aside).

A call the module does not define is an open edge: it may read its arguments
and may have an effect, so it counts as both and the channel abstains. The
findings are evidence beside the score; they never change deficit_score.
Each carries a status: DOCUMENTED_PROMISE when the docstring names a dropped
input (the function promises to use it), REVIEW_CANDIDATE otherwise (no
effect was seen, but nothing states that one is owed).
"""

from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Union

from slop_detector.patterns.declared_intent import declared_intent
from slop_detector.patterns.ignored_parameter import _documented_as_kept, fixed_signature
from slop_detector.patterns.placeholder import (
    _PURE_BUILTINS,
    _SUCCESS_KEYWORDS,
    SUCCESS_CLAIM,
    _is_log_call,
    _literal_argument,
    _success_mark,
    constant_success_marks,
)

FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_IMPLICIT = frozenset({"self", "cls"})
_SUCCESS_TEXT_LIMIT = 40  # longer literals are content (a prompt, a template)
_STATUS_KEYS = frozenset({"status", "state", "result"})  # dict keys whose value names the outcome
_ERROR_KEYS = frozenset({"error", "errors", "exception"})  # a dict carrying one reports a failure


@dataclass
class SemanticFinding:
    function: str
    kind: str
    line: int
    inputs: List[str] = field(default_factory=list)
    evidence: str = ""
    status: str = "REVIEW_CANDIDATE"
    # The line's fingerprint for a finding inside the body (finding_identity),
    # set at scan time; None at the function's def line.
    fingerprint: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "function": self.function,
            "kind": self.kind,
            "line": self.line,
            "inputs": list(self.inputs),
            "evidence": self.evidence,
            "status": self.status,
            "fingerprint": self.fingerprint,
        }


_TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _reachable(statements: list) -> list:
    """A statement list up to its first return / raise / break / continue."""
    for index, statement in enumerate(statements):
        if isinstance(statement, _TERMINATORS):
            return statements[: index + 1]
    return statements


def _own_nodes(function: FunctionNode) -> List[ast.AST]:
    """Reachable nodes of the function body; the bodies of nested functions,
    lambdas and classes are left out (the nested node itself is kept).
    Computed once per function node (several analyses walk the same body)."""
    cached = getattr(function, "_slop_own_nodes", None)
    if cached is not None:
        return cached
    nodes: List[ast.AST] = []
    positions: Dict[int, int] = {}
    stack: List[Tuple[ast.AST, int]] = [(s, i) for i, s in enumerate(_reachable(function.body))]
    while stack:
        node, position = stack.pop()
        nodes.append(node)
        positions[id(node)] = position
        if isinstance(node, _NESTED_SCOPES):
            continue
        for _, value in ast.iter_fields(node):
            if isinstance(value, list):
                if value and all(isinstance(item, ast.stmt) for item in value):
                    value = _reachable(value)
                stack.extend((item, position) for item in value if isinstance(item, ast.AST))
            elif isinstance(value, ast.AST):
                stack.append((value, position))
    setattr(function, "_slop_own_nodes", nodes)
    setattr(function, "_slop_own_positions", positions)
    return nodes


def _own_positions(function: FunctionNode) -> Dict[int, int]:
    """id of each own node -> the index of the top-level body statement it
    belongs to."""
    _own_nodes(function)
    return getattr(function, "_slop_own_positions")


def _positional(function: FunctionNode) -> List[str]:
    args = function.args
    return [a.arg for a in args.posonlyargs + args.args]


def _named(function: FunctionNode) -> Set[str]:
    args = function.args
    return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}


# The node types `_binds` can return a name for: parameters, assignment, loop,
# with and except targets, imports, nested defs and classes, comprehension,
# lambda and match variables (MatchAs / MatchStar: 3.10+), and `global` /
# `nonlocal` declarations.
_BINDING_NODES = (
    ast.Name, ast.arg, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler,
    ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal,
) + tuple(getattr(ast, n) for n in ("MatchAs", "MatchStar") if hasattr(ast, n))


def _binds(node: ast.AST) -> Set[str]:
    """The names one node binds by itself."""
    if isinstance(node, ast.Name):
        return {node.id} if isinstance(node.ctx, (ast.Store, ast.Del)) else set()
    if isinstance(node, ast.arg):
        return {node.arg}
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler)):
        return {node.name} if node.name else set()
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return set(node.names)
    name = getattr(node, "name", None)  # MatchAs / MatchStar (Python 3.10+)
    return {name} if type(node).__name__ in ("MatchAs", "MatchStar") and name else set()


def _statement_targets(node: ast.stmt) -> Set[str]:
    """Names one top-level statement binds (not inside a function or class body)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    targets = [getattr(node, "target", None)] + list(getattr(node, "targets", []))
    targets += [item.optional_vars for item in getattr(node, "items", [])]
    return {n.id for t in targets if t is not None for n in ast.walk(t) if isinstance(n, ast.Name)}


def _module_binding_counts(tree: ast.AST) -> Dict[str, int]:
    """How often the module binds each name at top level (inside `if` / `try`
    blocks too), counting a function that declares it `global` and assigns it."""
    counts: Dict[str, int] = {}
    pending: List[ast.stmt] = list(getattr(tree, "body", []))
    while pending:
        node = pending.pop()
        for name in _statement_targets(node):
            counts[name] = counts.get(name, 0) + 1
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            pending.extend(n for n in ast.iter_child_nodes(node) if isinstance(n, ast.stmt))
    if not any(isinstance(node, ast.Global) for node in ast.walk(tree)):
        return counts  # most modules: no function walk needed
    for function in ast.walk(tree):
        if isinstance(function, _FUNCTIONS):
            declared = {n for g in ast.walk(function) if isinstance(g, ast.Global) for n in g.names}
            for name in declared:
                counts[name] = counts.get(name, 0) + 1
    return counts


# Why an open call's target is unknown (coverage `open_call_details`).
EXTERNAL = "external"
DYNAMIC = "dynamic"
AMBIGUOUS = "ambiguous"
MODULE_DEFINED_UNRESOLVED = "module_defined_unresolved"
UNCLASSIFIED = "unclassified"
_OPEN_CALL_DETAILS = (AMBIGUOUS, DYNAMIC, EXTERNAL, MODULE_DEFINED_UNRESOLVED, UNCLASSIFIED)
_BUILTIN_NAMES = frozenset(dir(builtins))
# Expressions whose result, made at run time, is the receiver: `(a or b).close()`.
_RUNTIME_ROOTS = (ast.BinOp, ast.BoolOp, ast.Await, ast.Compare, ast.IfExp, ast.UnaryOp, ast.NamedExpr)
# Literals whose type is a builtin: a method on one is a builtin's (`{...}.get`).
_BUILTIN_LITERALS = (
    ast.Constant, ast.Dict, ast.List, ast.Set, ast.Tuple, ast.JoinedStr, ast.ListComp, ast.SetComp, ast.DictComp,
)
_VALUE = "value"  # a name the function binds to a value made at run time
# Decorators that keep a method's first parameter the instance, by origin.
_INSTANCE_DECORATORS = frozenset(
    {"functools.cached_property", "abc.abstractmethod", "typing.override", "typing_extensions.override"}
)
_PROPERTY_PARTS = frozenset({"setter", "getter", "deleter"})
# The one class decorator that keeps a class's own methods as written, by origin.
_STANDARD_DATACLASS = "dataclasses.dataclass"


def _import_sources(tree: ast.AST) -> Dict[str, Set[str]]:
    """Where each top-level import binds its name from (inside `if` / `try` /
    `except` too: `except ImportError: from scipy import ndimage`):
    `import abc` -> abc, `import a.b as c` -> a.b, `from functools import
    cached_property as cp` -> functools.cached_property."""
    sources: Dict[str, Set[str]] = {}
    for node in _top_statements(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                origin = a.name if a.asname else a.name.split(".")[0]
                sources.setdefault(a.asname or origin, set()).add(origin)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for a in node.names:
                sources.setdefault(a.asname or a.name, set()).add(module + "." + a.name)
    return sources


def _top_statements(tree: ast.AST):
    """The module's top-level statements, those inside `if` / `try` /
    `except` / `with` / loop blocks too; a def's or a class's body is not
    entered (the def or class itself is yielded)."""
    pending: List[ast.stmt] = list(getattr(tree, "body", []))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ExceptHandler):  # `except ImportError: class Layout: ...`
                pending.extend(child.body)
            elif isinstance(child, ast.stmt):
                pending.append(child)


def _value_bindings(tree: ast.AST) -> Set[str]:
    """Names the module binds at top level (inside `if` / `try` too) other
    than by an import: a def, a class, a plain-name store (`name.attr = ...`
    stores into the object, it does not bind `name`), or a `global`
    declaration in a function."""
    names: Set[str] = set()
    for node in _top_statements(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif not isinstance(node, (ast.Import, ast.ImportFrom)):
            targets = [getattr(node, "target", None)] + list(getattr(node, "targets", []))
            targets += [item.optional_vars for item in getattr(node, "items", [])]
            names |= {
                n.id for t in targets if t is not None
                for n in ast.walk(t) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
            }
    return names | {n for g in ast.walk(tree) if isinstance(g, ast.Global) for n in g.names}


def _all_params(function: FunctionNode) -> Set[str]:
    """Every parameter name, `*args` and `**kwargs` included."""
    args = function.args
    extra = [a for a in (args.vararg, args.kwarg) if a is not None]
    return {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs + extra}


def _class_rebinds(klass: ast.ClassDef) -> Set[str]:
    """Members a class binds more than once: two defs, a class-level assignment
    beside a def, or an instance attribute (`self._write = writer`)."""
    seen: Dict[str, int] = {}
    for node in klass.body:
        for name in _statement_targets(node):
            seen[name] = seen.get(name, 0) + 1
    rebound = {name for name, count in seen.items() if count > 1}
    for node in ast.walk(klass):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, (ast.Store, ast.Del))
            and isinstance(node.value, ast.Name)
            and node.value.id in _IMPLICIT
        ):
            rebound.add(node.attr)
    return rebound


def _real_bases(klass: ast.ClassDef) -> List[ast.expr]:
    """A class's bases, `object` aside (it adds no method)."""
    return [b for b in klass.bases if not (isinstance(b, ast.Name) and b.id == "object")]


class _Graph:
    """The module's functions and methods and the calls between them."""

    def __init__(self, tree: ast.AST) -> None:
        self.intent = declared_intent(tree)
        self.functions: Dict[Tuple[str, str], FunctionNode] = {}
        self.owner: Dict[FunctionNode, str] = {}
        counts = _module_binding_counts(tree)
        self.ambiguous: Set[Tuple[str, str]] = {("", name) for name, n in counts.items() if n > 1}
        self._bound: Dict[FunctionNode, Set[str]] = {}
        self._outer: Dict[FunctionNode, Set[str]] = {}
        self._imported: Dict[FunctionNode, Set[str]] = {}
        self.import_sources = _import_sources(tree)
        self.imported = set(self.import_sources)
        values = _value_bindings(tree)
        # Imported, and bound at top level another way too (`backend = connect()`).
        self.rebound_imports = self.imported & values
        self._module_names = self.intent.module_bindings | values | self.imported
        self.never_run: Dict[FunctionNode, List[Tuple[ast.Call, FunctionNode]]] = {}
        self._kinds: Dict[FunctionNode, Dict[str, list]] = {}
        self._class_of: Dict[FunctionNode, ast.ClassDef] = {}
        body = getattr(tree, "body", [])
        defined = {n.name for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        # Top-level classes bound once; values the module assigns at top level.
        self.classes: Dict[str, ast.ClassDef] = {
            n.name: n for n in body if isinstance(n, ast.ClassDef) and ("", n.name) not in self.ambiguous
        }
        self.module_values = self.intent.module_bindings - self.imported - defined
        for node in body:
            if isinstance(node, _FUNCTIONS):
                self._add("", node)
            elif isinstance(node, ast.ClassDef):
                self.ambiguous |= {(node.name, name) for name in _class_rebinds(node)}
                for member in node.body:
                    if isinstance(member, _FUNCTIONS):
                        self._add(node.name, member)
                        self._class_of[member] = node

    def _add(self, owner: str, node: FunctionNode) -> None:
        self.functions[(owner, node.name)] = node
        self.owner[node] = owner

    def bound_in(self, function: FunctionNode) -> Set[str]:
        """Names the function binds itself (a call through one is open)."""
        if function not in self._bound:
            self._scan(function)
        return self._bound[function]

    def outer_names(self, function: FunctionNode) -> Set[str]:
        """Names the function declares `global` / `nonlocal`: storing one
        changes state outside the call."""
        if function not in self._outer:
            self._scan(function)
        return self._outer[function]

    def imported_in(self, function: FunctionNode) -> Set[str]:
        """Names the function binds by an import."""
        if function not in self._imported:
            self._scan(function)
        return self._imported[function]

    def _scan(self, function: FunctionNode) -> None:
        """The three above in one walk of the function."""
        bound: Set[str] = set()
        outer: Set[str] = set()
        imported: Set[str] = set()
        for inner in ast.walk(function):
            if inner is not function and isinstance(inner, _BINDING_NODES):
                names = _binds(inner)
                bound |= names
                if isinstance(inner, (ast.Global, ast.Nonlocal)):
                    outer |= names
                elif isinstance(inner, (ast.Import, ast.ImportFrom)):
                    imported |= names
        self._bound[function] = bound
        self._outer[function] = outer
        self._imported[function] = imported

    def own_kinds(self, function: FunctionNode) -> Dict[str, list]:
        """How the function's own body binds each name: a nested def or class
        (the node) or a value (`_VALUE`), one entry per binding. Computed once
        per function."""
        kinds = self._kinds.get(function)
        if kinds is not None:
            return kinds
        kinds = {}
        for node in _own_nodes(function):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kinds.setdefault(node.name, []).append(node)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                kinds.setdefault(node.id, []).append(_VALUE)
            elif isinstance(node, ast.ExceptHandler) or type(node).__name__ in ("MatchAs", "MatchStar"):
                if node.name:
                    kinds.setdefault(node.name, []).append(_VALUE)
        self._kinds[function] = kinds
        return kinds

    def qualname(self, node: FunctionNode) -> str:
        owner = self.owner[node]
        return f"{owner}.{node.name}" if owner else node.name

    def resolve(self, call: ast.Call, caller: FunctionNode) -> Optional[Tuple[FunctionNode, int]]:
        """(callee, positional offset) for a call into the module, or None (open edge)."""
        return self.resolution(call, caller)[0]

    def resolution(self, call: ast.Call, caller: FunctionNode) -> Tuple[Optional[Tuple[FunctionNode, int]], str]:
        """(callee, positional offset), or (None, why the target is open).

        A call joins the closed graph only when its target is certain. Open:
        a decorated callee (the decorator may wrap it in anything); a name the
        caller binds itself (a parameter, a local, a comprehension variable)
        or the module binds twice; a `self.` call to a method a subclass in the
        module overrides (it dispatches on the instance) or the class binds
        again (an instance attribute of the same name), or in a class under a
        decorator or metaclass that may replace it.

        Why, for an open target: `external` (an imported name, a builtin, a
        method inherited only from imported bases), `dynamic` (chosen at run
        time: a parameter, a value the caller or the module assigns, an
        object's attribute, an expression's result, an overridable method),
        `ambiguous` (bound more than once, or wrapped by a decorator, the
        callee's or its class's, or by a metaclass),
        `module_defined_unresolved` (the module defines a candidate - a class,
        a nested def, a method of the class or of a module base - that the
        graph does not follow), `unclassified` (no evidence either way).
        """
        func = call.func
        if isinstance(func, ast.Name):
            found, why = self._module_function(func.id, caller)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            found, why = self._own_method(func.value.id, func.attr, caller)
        else:
            found, why = None, self._expression_target(func, caller)
        if found is not None and found[0].decorator_list:
            return None, AMBIGUOUS
        return found, why

    def _module_function(self, name: str, caller: FunctionNode):
        key = ("", name)
        callee = self.functions.get(key)
        if name in self.bound_in(caller):
            return None, self._local_binding(name, caller)
        if key in self.ambiguous:
            return None, AMBIGUOUS
        if callee is None:
            return None, self._module_name(name)
        return (callee, 0), ""

    def _own_method(self, receiver: str, name: str, caller: FunctionNode):
        if not self._own_instance(receiver, caller):
            return None, self._receiver(receiver, caller, name)
        key = (self.owner[caller], name)
        callee = self.functions.get(key)
        if key in self.ambiguous:
            return None, AMBIGUOUS
        if callee is None:
            return None, self._inherited(self.owner[caller], name)
        if self.intent.is_contract(callee) or _left_to_subclasses(callee):
            return None, DYNAMIC
        if not self._class_keeps(caller, name):
            return None, AMBIGUOUS
        return (callee, 1), ""

    def _own_instance(self, receiver: str, caller: FunctionNode) -> bool:
        """`self` / `cls` is the method's own instance or class only as its
        first parameter, never bound again in its body (`cls = type(env)`,
        `for self in items`): then `self.m()` is a method of the class."""
        if receiver not in _IMPLICIT or not self.owner.get(caller):
            return False
        positional = _positional(caller)
        return (
            bool(positional)
            and positional[0] == receiver
            and receiver not in self.own_kinds(caller)
            and self._instance_method(caller)
        )

    def _instance_method(self, caller: FunctionNode) -> bool:
        """No decorator, or only ones that keep the first parameter the
        instance, proven by origin: the builtin `property` and its setter /
        getter / deleter, and `functools.cached_property`, `abc.abstractmethod`,
        `typing(_extensions).override` by the module's imports. A staticmethod,
        a classmethod (`cls.m()` is not bound like `self.m()`) or any other
        decorator, alone or stacked, is not."""
        if not caller.decorator_list:
            return True
        klass = self.classes.get(self.owner[caller])
        if klass is None:
            return False
        local = {name for member in klass.body for name in _statement_targets(member)}
        return all(self._keeps_instance(d, klass, local) for d in caller.decorator_list)

    def _keeps_instance(self, decorator: ast.expr, klass: ast.ClassDef, local: Set[str]) -> bool:
        """One decorator of a method of `klass` (`local`: the names its body binds)."""
        if isinstance(decorator, ast.Attribute) and decorator.attr in _PROPERTY_PARTS:
            return self._is_property(klass, decorator.value, local)
        if isinstance(decorator, ast.Name) and decorator.id == "property":
            return self._builtin_property(local)
        origins = self._origins(decorator, local)
        return bool(origins) and origins <= _INSTANCE_DECORATORS

    def _origins(self, decorator: ast.expr, local: Set[str]) -> Set[str]:
        """Where `name` / `name.attr` comes from by the module's imports; none
        when `name` is bound again, by the module or in `local`."""
        root = decorator.value if isinstance(decorator, ast.Attribute) else decorator
        if not isinstance(root, ast.Name) or root.id in local or root.id in self.rebound_imports:
            return set()
        origins = self.import_sources.get(root.id, set())
        if isinstance(decorator, ast.Attribute):
            origins = {origin + "." + decorator.attr for origin in origins}
        return origins

    def _class_keeps(self, caller: FunctionNode, name: str) -> bool:
        """The class statement keeps its method `name` as written: no class
        decorator, metaclass or class keyword (any may replace a method), or
        only the standard `dataclasses.dataclass`, and then not a special
        method (`__eq__`, `__post_init__`: it may generate or call one)."""
        klass = self._class_of[caller]
        if klass.keywords:
            return False
        if not klass.decorator_list:
            return True
        special = name.startswith("__") and name.endswith("__")
        return not special and all(self._plain_dataclass(d) for d in klass.decorator_list)

    def _plain_dataclass(self, decorator: ast.expr) -> bool:
        """`@dataclass` / `@dataclasses.dataclass(frozen=True)`: the standard
        one by origin, options only as constants and none of them `slots`
        (that makes a new class object)."""
        if isinstance(decorator, ast.Call):
            options = decorator.keywords
            if decorator.args or any(k.arg == "slots" or not isinstance(k.value, ast.Constant) for k in options):
                return False
            decorator = decorator.func
        return self._origins(decorator, set()) == {_STANDARD_DATACLASS}

    def _builtin_property(self, local: Set[str]) -> bool:
        """`property` is the builtin: neither the module nor the class binds it."""
        return "property" not in self._module_names and "property" not in local

    def _is_property(self, klass: ast.ClassDef, value: ast.expr, local: Set[str]) -> bool:
        """`@size.setter`: `size` is a def of the class under the builtin `property`."""
        return isinstance(value, ast.Name) and self._builtin_property(local) and any(
            isinstance(member, _FUNCTIONS)
            and member.name == value.id
            and len(member.decorator_list) == 1
            and isinstance(member.decorator_list[0], ast.Name)
            and member.decorator_list[0].id == "property"
            for member in klass.body
        )

    def _inherited(self, owner: str, name: str) -> str:
        """`self.name(...)` where the class defines no `name`: a module base
        that defines it is a candidate; imported bases only are an outside
        definition; mixed, builtin or unknown bases, or a decorator or
        metaclass that may add the method, are not classified."""
        klass = self.classes.get(owner)
        bases = _real_bases(klass) if klass else []
        if not bases:
            return UNCLASSIFIED
        local = [self.classes[b.id] for b in bases if isinstance(b, ast.Name) and b.id in self.classes]
        why = self._from_module_bases(local, name) if len(local) == len(bases) else EXTERNAL
        if why == AMBIGUOUS:
            return why  # a module base binds it again, whatever adds methods here
        if klass.decorator_list or klass.keywords:
            return UNCLASSIFIED
        if why == EXTERNAL and not all(self._imported_root(b) for b in bases):
            return UNCLASSIFIED
        return why

    def _from_module_bases(self, local: List[ast.ClassDef], name: str) -> str:
        """The module bases and theirs: one that binds `name` again (on the
        instance) makes it ambiguous; a base anywhere on the path from outside
        the module, or a decorator or metaclass on it, may supply `name`
        first, so nothing is classified; else one that defines it is a
        candidate."""
        found, mixed, seen = False, False, set()
        while local:
            base = local.pop()
            if base.name in seen:
                continue
            seen.add(base.name)
            if (base.name, name) in self.ambiguous:
                return AMBIGUOUS
            found = found or (base.name, name) in self.functions
            parents = _real_bases(base)
            inner = [self.classes[b.id] for b in parents if isinstance(b, ast.Name) and b.id in self.classes]
            mixed = mixed or len(inner) < len(parents) or bool(base.decorator_list or base.keywords)
            local += inner
        return MODULE_DEFINED_UNRESOLVED if found and not mixed else UNCLASSIFIED

    def _imported_root(self, base: ast.expr) -> bool:
        """`Base`, `pkg.Base`, `Base[T]` with `Base` / `pkg` bound by an import only."""
        node = base.value if isinstance(base, ast.Subscript) else base
        while isinstance(node, ast.Attribute):
            node = node.value
        return isinstance(node, ast.Name) and node.id in self.imported and node.id not in self.rebound_imports

    def _local_binding(self, name: str, caller: FunctionNode, called: bool = True) -> str:
        """A name the caller binds: a parameter is the caller's choice, a
        local import an outside one, a value it assigns made at run time; a
        nested def or class called by name is a candidate the graph does not
        follow (wrapped by a decorator or bound again: ambiguous)."""
        if name in _all_params(caller):
            return DYNAMIC
        kinds = self.own_kinds(caller).get(name, [])
        if name in self.imported_in(caller):
            return AMBIGUOUS if kinds else EXTERNAL  # imported, then assigned or defined
        if not kinds:  # bound only in a nested scope, or after a return
            return UNCLASSIFIED
        if all(kind == _VALUE for kind in kinds):
            return DYNAMIC
        if len(kinds) > 1 or kinds[0].decorator_list:
            return AMBIGUOUS
        return MODULE_DEFINED_UNRESOLVED if called else UNCLASSIFIED

    def _module_name(self, name: str) -> str:
        """A name the caller does not bind and the module defines no function for."""
        if name in self.imported:
            return AMBIGUOUS if name in self.rebound_imports else EXTERNAL
        if name in _BUILTIN_NAMES and name not in self.intent.module_bindings:
            return EXTERNAL
        if name in self.classes:  # a constructor
            return AMBIGUOUS if self.classes[name].decorator_list else MODULE_DEFINED_UNRESOLVED
        if name in self.module_values:
            return DYNAMIC
        return UNCLASSIFIED  # an undefined name, or one bound inside a block

    def _receiver(self, receiver: str, caller: FunctionNode, attr: Optional[str] = None, chain: bool = False) -> str:
        """`receiver.attr(...)` with a receiver other than the caller's own
        instance (`chain`: `receiver.attr.more(...)`, `attr` its first link).
        `self` / `cls` here is a name like any other: a parameter of a
        top-level function or a value the caller assigns (a method's own
        `self.m()` resolves in `_own_method` and never reaches this)."""
        if receiver in self.bound_in(caller):
            return self._local_binding(receiver, caller, called=False)
        if receiver in self.imported:
            return AMBIGUOUS if receiver in self.rebound_imports else EXTERNAL
        if ("", receiver) in self.ambiguous:
            return AMBIGUOUS
        if receiver in self.classes:
            return self._class_member(receiver, attr, chain)
        if receiver in self.module_values:
            return DYNAMIC
        return UNCLASSIFIED

    def _class_member(self, klass: str, attr: Optional[str], chain: bool) -> str:
        """`Store.build(...)` (a method: a candidate) or `Logger.CURRENT.logkv(...)`
        (a class attribute: it holds a run-time value); an attribute of a
        method (`Store.build.cache_clear()`) or an undefined member is not
        classified; a decorated class or a member bound again is ambiguous."""
        if self.classes[klass].decorator_list or (klass, attr) in self.ambiguous:
            return AMBIGUOUS
        if (klass, attr) in self.functions:
            return UNCLASSIFIED if chain else MODULE_DEFINED_UNRESOLVED
        return DYNAMIC if chain else UNCLASSIFIED

    def _expression_target(self, func: ast.expr, caller: FunctionNode) -> str:
        """The target is an expression: a call's or a subscript's result is
        chosen at run time; an attribute chain is classified by its root (an
        operator's, a comparison's or an await's result: run time too)."""
        if isinstance(func, (ast.Call, ast.Subscript) + _RUNTIME_ROOTS):
            return DYNAMIC  # `(runner or default)(...)`, `(f if c else g)(...)`
        if not isinstance(func, ast.Attribute):
            return UNCLASSIFIED  # `(lambda: ...)()`: not classified yet
        first, root = func, func.value
        while isinstance(root, ast.Attribute):
            first, root = root, root.value
        if isinstance(root, (ast.Call, ast.Subscript) + _RUNTIME_ROOTS):
            return DYNAMIC
        if isinstance(root, _BUILTIN_LITERALS):
            return EXTERNAL  # a method of a builtin literal: `", ".join(...)`, `{...}.get(...)`
        if not isinstance(root, ast.Name):
            return UNCLASSIFIED
        if root.id in _all_params(caller):
            return DYNAMIC  # `self.db.insert(...)`, `client.session.post(...)`
        return self._receiver(root.id, caller, first.attr, chain=True)


def _left_to_subclasses(method: FunctionNode) -> bool:
    """The body ends in `raise NotImplementedError`: a subclass, possibly in
    another module, supplies the method that `self.` dispatches to."""
    body = _reachable(method.body)
    exc = body[-1].exc if body and isinstance(body[-1], ast.Raise) else None
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"


def _parents(nodes: List[ast.AST]) -> Dict[ast.AST, ast.AST]:
    return {child: node for node in nodes for child in ast.iter_child_nodes(node)}


# Expressions that only combine values: a value read inside one of them flows
# into the result of the expression and nowhere else.
_VALUE_EXPRESSIONS = (
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.JoinedStr,
    ast.FormattedValue,
    ast.Tuple,
    ast.List,
    ast.Set,
    ast.Dict,
    ast.Subscript,
    ast.Slice,
    ast.Starred,
)
# `locals()` / `vars()` build a snapshot of the frame: its value flows like any
# other. `eval` / `exec` may read any name: every input is left undecided.
_SNAPSHOT_READERS = frozenset({"locals", "vars"})
_DYNAMIC_EXECUTORS = frozenset({"eval", "exec"})
# Builtins that only build a value from their arguments.
_VALUE_BUILTINS = frozenset({"dict", "list", "tuple", "set", "frozenset", "sorted", "reversed"})


def _assigned_names(statement: ast.AST) -> Optional[List[str]]:
    """The plain names an assignment binds, or None when it stores elsewhere
    (an attribute or an item store is an effect)."""
    if not isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return None
    if isinstance(statement, ast.AnnAssign) and statement.value is None:
        return None  # `x: int` only annotates
    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
    if not all(isinstance(t, (ast.Name, ast.Tuple, ast.List)) for t in targets):
        return None
    return [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]


def _local_targets(function: FunctionNode) -> Set[str]:
    """Plain names the function assigns (`x = ...`, `a, b = ...`, `x += ...`)."""
    names: Set[str] = set()
    for node in _own_nodes(function):
        names |= set(_assigned_names(node) or [])
    return names


def _stored_in(graph: _Graph, function: FunctionNode, start: ast.AST, parents) -> Optional[Tuple[List[str], ast.AST]]:
    """(the locals a value flows into, the assignment) when the value only feeds
    an assignment to plain names (`prompt = f"Q: {question}"`), else None (any
    other use).

    A call other than a value-building builtin, an attribute read (a property
    may run code), a statement's condition and a loop all count as uses: a
    loop's input decides how often its body runs. An `if` expression's test
    only shapes the expression's value, so it flows with it.
    """
    node: ast.AST = start
    while True:
        parent = parents.get(node)
        if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            return _local_store(graph, function, node, parent)
        if not _passes_value(graph, function, node, parent):
            return None
        node = parent


def _passes_value(graph: _Graph, function: FunctionNode, node: ast.AST, parent) -> bool:
    """`parent` only combines `node` into a bigger value."""
    if isinstance(parent, ast.Call):
        return node is not parent.func and _value_builtin(graph, function, parent.func)
    return isinstance(parent, _VALUE_EXPRESSIONS + (ast.IfExp,))


def _local_store(graph: _Graph, function: FunctionNode, node: ast.AST, assignment) -> Optional[Tuple[List[str], ast.AST]]:
    """The locals an assignment stores `node` in, or None when the store is a
    use: an attribute or item target, `_ = ...` (a deliberate discard, like
    `del`) or a `global` / `nonlocal` name (state outside the call)."""
    stored = _assigned_names(assignment) if node is assignment.value else None
    if not stored or "_" in stored or set(stored) & graph.outer_names(function):
        return None
    return stored, assignment


class _Versions:
    """Which definition of a local a read sees.

    A local assigned only by top-level statements of the body (straight-line
    code) gets one version per assignment, keyed `name@index`: a read sees the
    last one before its statement, so `prompt = f"{q}"; prompt = "canned"`
    drops `q`. A parameter is versioned the same way from its entry value,
    keyed by its plain name: `question = "canned"; return question` returns a
    later version and drops the caller's value. A name also assigned inside a
    branch, loop or `with`, declared global, or read by a nested scope keeps one
    key, its name.
    """

    def __init__(self, function: FunctionNode, nodes: List[ast.AST], params: Set[str]) -> None:
        body = _reachable(function.body)
        self.index = _own_positions(function)  # every node a read or a store can be
        top: Dict[str, List[int]] = {}
        top_store_ids: Set[int] = set()
        for position, statement in enumerate(body):
            names = _assigned_names(statement)
            if names is None:
                continue
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            top_store_ids |= {id(n) for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
            for name in names:
                top.setdefault(name, []).append(position)
        self.params = set(params)
        unversioned = _unversioned(nodes, top_store_ids)
        self.defs = {name: sorted(set(found)) for name, found in top.items() if name not in unversioned}

    def keys(self, name: str) -> List[str]:
        if name not in self.defs:
            return [name]
        entry = [name] if name in self.params else []
        return entry + [f"{name}@{position}" for position in self.defs[name]]

    def defined(self, name: str, assignment: ast.AST) -> str:
        if name not in self.defs:
            return name
        return f"{name}@{self.index[id(assignment)]}"

    def seen(self, name: str, node: ast.AST) -> Optional[str]:
        """The key a read at `node` sees; None before the first definition (a
        parameter's entry value is its plain name)."""
        if name not in self.defs:
            return name
        position = self.index.get(id(node), -1)
        before = [p for p in self.defs[name] if p < position]
        if before:
            return f"{name}@{before[-1]}"
        return name if name in self.params else None


def _unversioned(nodes: List[ast.AST], top_store_ids: Set[int]) -> Set[str]:
    """Names that keep one key: read by a nested scope, declared global or
    nonlocal, or stored anywhere but a top-level assignment (`x: int` aside)."""
    names = _bound_names_in_nested(nodes)
    names |= {n for g in nodes if isinstance(g, (ast.Global, ast.Nonlocal)) for n in g.names}
    annotations = _annotation_only(nodes)
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if id(node) not in top_store_ids and id(node) not in annotations:
                names.add(node.id)
    return names


def _annotation_only(nodes: List[ast.AST]) -> Set[int]:
    """Ids of the names `x: int` annotates without assigning."""
    return {
        id(node.target)
        for node in nodes
        if isinstance(node, ast.AnnAssign) and node.value is None and isinstance(node.target, ast.Name)
    }


def _bound_names_in_nested(nodes: List[ast.AST]) -> Set[str]:
    """Names read or bound inside nested functions, lambdas and classes."""
    names: Set[str] = set()
    for node in nodes:
        if isinstance(node, _NESTED_SCOPES):
            names |= {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
    return names


def _frame_calls(graph: _Graph, function: FunctionNode, nodes: List[ast.AST]) -> Tuple[List[ast.Call], bool]:
    """(the `locals()` / `vars()` snapshots, whether `eval` / `exec` runs)."""
    snapshots: List[ast.Call] = []
    dynamic = False
    for node in nodes:
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        name = node.func.id
        if name in graph.bound_in(function) or name in graph.intent.module_bindings:
            continue
        if name in _DYNAMIC_EXECUTORS:
            dynamic = True
        elif name in _SNAPSHOT_READERS and not node.args and not node.keywords:
            snapshots.append(node)
    return snapshots, dynamic


def _param_reads(graph: _Graph, function: FunctionNode) -> Dict[str, List[Optional[Tuple]]]:
    """Per parameter and per local definition, each read: (callee, callee
    parameter) when the value is only passed to a module function, (function,
    local key) when it only flows into a local, None when it is used any other
    way (a result, a condition, an effect, an open call)."""
    nodes = _own_nodes(function)
    parents = _parents(nodes)
    params = _named(function)
    locals_ = _local_targets(function) - params
    versions = _Versions(function, nodes, params)
    reads: Dict[str, List[Optional[Tuple]]] = {}
    for name in params | locals_:
        reads.update({key: [] for key in versions.keys(name)})
    snapshots, dynamic = _frame_calls(graph, function, nodes)
    if dynamic:
        return {key: [None] for key in reads}  # eval / exec may read any of them
    for node in nodes:
        if isinstance(node, ast.Name) and (node.id in params or node.id in locals_):
            _record_read(graph, function, node, params, parents, versions, reads)
        elif isinstance(node, ast.AugAssign):
            _record_augmented(function, node, versions, reads)
    # Nested functions and lambdas may read any of these: a use.
    for name in _bound_names_in_nested(nodes) & set(reads):
        reads[name].append(None)
    for snapshot in snapshots:
        _record_snapshot(graph, function, snapshot, params | locals_, params, parents, versions, reads)
    return reads


def _record_snapshot(graph: _Graph, function: FunctionNode, snapshot: ast.Call, names, params, parents, versions, reads) -> None:
    """`locals()` reads every value the frame holds at that point into wherever
    the snapshot goes: returned or passed on is a use, dropped is not."""
    sinks = _read_sinks(graph, function, snapshot, parents, versions)
    for name in names:
        key = versions.seen(name, snapshot)
        if key is not None:
            reads[key].extend(sinks)


def _record_read(graph: _Graph, function: FunctionNode, node: ast.Name, params, parents, versions, reads) -> None:
    """A load sends the value it sees on; rebinding or deleting a parameter
    handles it on purpose (a use); an assignment to a local defines it."""
    annotation = parents.get(node)
    if isinstance(annotation, ast.AnnAssign) and annotation.value is None:
        return  # `x: int` neither reads nor assigns
    if isinstance(node.ctx, ast.Load):
        key = versions.seen(node.id, node)
        if key is not None:
            reads[key].extend(_read_sinks(graph, function, node, parents, versions))
    elif node.id in params and not (isinstance(node.ctx, ast.Store) and node.id in versions.defs):
        reads[node.id].append(None)


def _record_augmented(function: FunctionNode, node: ast.AugAssign, versions, reads) -> None:
    """`x += 1` reads the definition before it into the new one."""
    if not isinstance(node.target, ast.Name):
        return
    name = node.target.id
    if name in versions.defs:
        previous = versions.seen(name, node)
        if previous is not None:
            reads[previous].append((function, versions.defined(name, node)))


def _read_sinks(graph: _Graph, function: FunctionNode, node: ast.AST, parents, versions: "_Versions") -> List[Optional[Tuple]]:
    """Where one read sends the value: a module parameter, local definitions,
    or None (a use)."""
    if isinstance(node, ast.Name):
        passed = _passed_to(graph, function, node, parents)
        if passed is not None:
            return [passed]
    stored = _stored_in(graph, function, node, parents)
    if stored is None:
        return [None]
    names, assignment = stored
    return [(function, versions.defined(local, assignment)) for local in names]


def _passed_to(graph: _Graph, function: FunctionNode, name: ast.Name, parents) -> Optional[Tuple]:
    parent = parents.get(name)
    call = parent
    keyword = None
    if isinstance(parent, ast.keyword):
        keyword, call = parent.arg, parents.get(parent)
    if not isinstance(call, ast.Call) or name is call.func:
        return None
    resolved = graph.resolve(call, function)
    if resolved is None:
        return None
    callee, offset = resolved
    if keyword is not None:
        return (callee, keyword) if keyword in _named(callee) else None
    if any(isinstance(a, ast.Starred) for a in call.args):
        return None
    slots = [i for i, a in enumerate(call.args) if a is name]
    if not slots:
        return None
    index = slots[0] + offset
    positional = _positional(callee)
    return (callee, positional[index]) if index < len(positional) else None


def _dropped(graph: _Graph) -> Tuple[Set[Tuple[FunctionNode, str]], Dict]:
    """(values that reach nothing, the reads): the greatest fixed point of
    "every read only passes it to a module parameter, or stores it in a local,
    that is itself dropped". A local nobody reads is dropped."""
    reads = {f: _param_reads(graph, f) for f in graph.owner}
    dropped = {(f, p) for f, per in reads.items() for p in per}
    changed = True
    while changed:
        changed = False
        for f, p in list(dropped):
            if any(r is None or r not in dropped for r in reads[f][p]):
                dropped.discard((f, p))
                changed = True
    return dropped, reads


def _value_builtin(graph: _Graph, function: FunctionNode, func: ast.expr) -> bool:
    """A pure builtin or one that only builds a value (`dict`, `list`, ...)."""
    if isinstance(func, ast.Name) and func.id in _VALUE_BUILTINS:
        return func.id not in graph.intent.module_bindings and func.id not in graph.bound_in(function)
    return _pure_builtin(graph, function, func)


def _pure_builtin(graph: _Graph, function: FunctionNode, func: ast.expr) -> bool:
    """`len(...)` and friends, unless the module or the function rebinds the name."""
    return (
        isinstance(func, ast.Name)
        and func.id in _PURE_BUILTINS
        and func.id not in graph.intent.module_bindings
        and func.id not in graph.bound_in(function)
    )


EFFECT_OBSERVED = "EFFECT_OBSERVED"
EFFECT_UNKNOWN = "EFFECT_UNKNOWN"
NO_EFFECT = "NO_EFFECT_IN_CLOSED_GRAPH"
_EFFECT_RANK = {NO_EFFECT: 0, EFFECT_UNKNOWN: 1, EFFECT_OBSERVED: 2}


def _deferred_body(function: FunctionNode) -> bool:
    """Calling it only builds a coroutine or a generator: the body runs when
    that object is awaited or iterated. An unreachable `yield` counts too."""
    cached = getattr(function, "_slop_deferred", None)
    if cached is None:
        cached = isinstance(function, ast.AsyncFunctionDef) or any(
            isinstance(n, (ast.Yield, ast.YieldFrom)) for n in _block_nodes(function.body)
        )
        setattr(function, "_slop_deferred", cached)
    return cached


def _never_run(graph: _Graph, function: FunctionNode) -> List[Tuple[ast.Call, FunctionNode]]:
    """Statement calls (`self._write(record)`) to module coroutines and
    generators: the object is dropped, so the body never runs."""
    if function in graph.never_run:
        return graph.never_run[function]
    found = []
    for node in _own_nodes(function):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            resolved = graph.resolve(node.value, function)
            if resolved is not None and _deferred_body(resolved[0]):
                found.append((node.value, resolved[0]))
    graph.never_run[function] = found
    return found


def _observed_effect(node: ast.AST) -> bool:
    """`global` / `nonlocal`, a `yield`, or a store to an attribute or an item."""
    if isinstance(node, (ast.Global, ast.Nonlocal, ast.Yield, ast.YieldFrom)):
        return True
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
        targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
        return any(isinstance(t, (ast.Attribute, ast.Subscript)) for tg in targets for t in ast.walk(tg))
    return False


def _implicit_call(node: ast.AST) -> Optional[str]:
    """Why a node runs code the module does not show, without a call: a
    context manager's `__enter__` / `__exit__`, or an await on an object from
    elsewhere (`await future`, each step of `async for`)."""
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return "context_manager"
    if isinstance(node, ast.Await) and not isinstance(node.value, ast.Call):
        return "external_awaitable"
    if isinstance(node, ast.AsyncFor) or (isinstance(node, ast.comprehension) and node.is_async):
        return "external_awaitable"
    return None


def _local_effect(graph: _Graph, function: FunctionNode):
    """(the body's own effect state, the module functions whose bodies it runs,
    why the state is unknown, why its open calls are open). A store to an
    attribute, an item or an outer name is observed; an open call or code run
    implicitly (a context manager, an awaitable from elsewhere) is unknown (it
    may do anything); a log line or a value builtin is none."""
    callees: List[FunctionNode] = []
    reasons: Set[str] = set()
    details: Set[str] = set()
    dropped = {id(call) for call, _ in _never_run(graph, function)}
    local = _local_names(graph, function)
    for node in _own_nodes(function):
        if _observed_effect(node):
            return EFFECT_OBSERVED, callees, set(), set()
        implicit = _implicit_call(node)
        if implicit:
            reasons.add(implicit)
        if isinstance(node, ast.Call) and id(node) not in dropped:
            if _is_log_call(node) or _value_builtin(graph, function, node.func):
                continue
            if constant_success_marks(node, local):
                continue  # a report built from literals (`SendResult(ok=True)`) is a value
            resolved, why = graph.resolution(node, function)
            if resolved is None:
                reasons.add("open_call")
                details.add(why)
            else:
                callees.append(resolved[0])
    return (EFFECT_UNKNOWN if reasons else NO_EFFECT), callees, reasons, details


def _local_names(graph: _Graph, function: FunctionNode) -> frozenset:
    """Names whose value the function gets at run time: its parameters, its
    own bindings, `self` / `cls`."""
    return frozenset(graph.bound_in(function) | _all_params(function) | _IMPLICIT)


def _with_effect(graph: _Graph):
    """(effect state, module callees, unknown reasons, open-call details) per
    function. The state is the strongest of its own and its callees' (observed
    > unknown > none), the greatest over call cycles; a function unknown only
    through a callee has the reason `unknown_callee`."""
    local = {f: _local_effect(graph, f) for f in graph.owner}
    states = {f: own for f, (own, _, _, _) in local.items()}
    changed = True
    while changed:
        changed = False
        for f, (_, callees, _, _) in local.items():
            best = max([states[f]] + [states[c] for c in callees], key=_EFFECT_RANK.__getitem__)
            if best != states[f]:
                states[f] = best
                changed = True
    reasons = {
        f: (own_reasons or {"unknown_callee"}) if states[f] == EFFECT_UNKNOWN else set()
        for f, (_, _, own_reasons, _) in local.items()
    }
    details = {f: own if states[f] == EFFECT_UNKNOWN else set() for f, (_, _, _, own) in local.items()}
    return states, {f: callees for f, (_, callees, _, _) in local.items()}, reasons, details


def _coverage(states, reasons, details) -> Dict[str, object]:
    """What the channel decided: functions per effect state, how many stayed
    unknown for each reason, and how many have an open call of each kind (a
    function can count under several kinds, so these do not sum to a total)."""
    counts: Dict[str, int] = {}
    for found in reasons.values():
        for reason in found:
            counts[reason] = counts.get(reason, 0) + 1
    return {
        "state": "MEASURED",
        "functions": len(states),
        "effect_states": {s: sum(1 for v in states.values() if v == s) for s in sorted(_EFFECT_RANK)},
        "unknown_reasons": dict(sorted(counts.items())),
        "open_call_details": {k: sum(1 for d in details.values() if k in d) for k in _OPEN_CALL_DETAILS},
    }


def _returns(function: FunctionNode) -> List[ast.Return]:
    return [n for n in _own_nodes(function) if isinstance(n, ast.Return)]


def _success_text(value: ast.expr) -> bool:
    """`True`, or a short string that claims success (`"saved"`, `"ok"`)."""
    if not isinstance(value, ast.Constant):
        return False
    if value.value is True:
        return True
    text = value.value
    return isinstance(text, str) and len(text) <= _SUCCESS_TEXT_LIMIT and bool(SUCCESS_CLAIM.search(text))


def _is_success(value: Optional[ast.expr], local: frozenset = frozenset()) -> bool:
    """A value that says the work succeeded whatever happened: `True`, a
    success word, a success member (`Status.SUCCESS`), a dict whose success or
    status entry is such a literal (`{"status": "ok", "id": order_id}`), or a
    constructed report of literals (`SendResult(ok=True)`). `local`: the
    function's parameters and locals; a member read from one (`conn.connected`)
    is a run-time value, not a constant."""
    if value is None:
        return False
    if isinstance(value, ast.Attribute):
        return _success_mark(value) is not None and _literal_argument(value, local)
    if isinstance(value, ast.Dict):
        return _success_dict(value, local)
    return _success_text(value) or bool(constant_success_marks(value, local))


def _success_dict(value: ast.Dict, local: frozenset) -> bool:
    """Some entry under a success key (`ok`, `success`, ...) or a status key
    (`status`, `state`, `result`) holds a literal success, and no such entry
    holds anything else (a computed status is not a constant claim)."""
    claims = []
    for key, item in zip(value.keys, value.values):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        name = key.value.lower()
        if name in _ERROR_KEYS and not (isinstance(item, ast.Constant) and not item.value):
            return False  # `{"available": True, "error": str(e)}` reports a failure
        if name in _SUCCESS_KEYWORDS or name in _STATUS_KEYS:
            claims.append(_entry_claims_success(key.value, item, local))
    return bool(claims) and all(claims)


def _entry_claims_success(key: str, item: ast.expr, local: frozenset) -> bool:
    """One success or status entry: `"ok": True`, `"status": "ok"`, or a
    success member (`Status.SUCCESS`) read from no run-time value."""
    member = isinstance(item, ast.Attribute)
    if key.lower() in _SUCCESS_KEYWORDS:
        return _success_mark(item, key) is not None and (not member or _literal_argument(item, local))
    marked = member and _success_mark(item) is not None
    return _success_text(item) or (marked and _literal_argument(item, local))


def _promises(function: FunctionNode, inputs: List[str]) -> bool:
    """The docstring names one of the inputs: the function says it uses it."""
    doc = ast.get_docstring(function) or ""
    return any(re.search(r"\b" + re.escape(name) + r"\b", doc) for name in inputs)


def _returns_value(returns: List[ast.Return]) -> bool:
    return any(
        r.value is not None and not (isinstance(r.value, ast.Constant) and r.value.value is None)
        for r in returns
    )


def _unused_inputs(function: FunctionNode, dropped, reads) -> List[str]:
    """Parameters the function reads, only to pass them to module functions that
    drop them, or overwrites before any use. One it never reads or rebinds is
    ignored_parameter's finding."""
    args = function.args
    own = reads[function]
    return [
        a.arg
        for a in args.posonlyargs + args.args + args.kwonlyargs
        if a.arg not in _IMPLICIT
        and not a.arg.startswith("_")
        and (function, a.arg) in dropped
        and (own[a.arg] or any(key.startswith(a.arg + "@") for key in own))
        and not _documented_as_kept(function, a.arg)
    ]


def _success_only(graph: _Graph) -> Set[FunctionNode]:
    """Functions whose every return is a success constant, or the result of a
    module function that only reports success (`return self._write(record)`
    where `_write` returns `True`): the least fixed point."""
    returns = {f: _returns(f) for f in graph.owner}
    local = {f: _local_names(graph, f) for f in graph.owner}
    found: Set[FunctionNode] = set()
    changed = True
    while changed:
        changed = False
        for f, rs in returns.items():
            if f in found or not rs:
                continue
            if all(_is_success(r.value, local[f]) or _returns_success_call(graph, f, r.value, found) for r in rs):
                found.add(f)
                changed = True
    return found


def _returns_success_call(graph: _Graph, caller: FunctionNode, value, found) -> bool:
    if not isinstance(value, ast.Call):
        return False
    resolved = graph.resolve(value, caller)
    return resolved is not None and resolved[0] in found


def _checks_its_input(intent, function: FunctionNode) -> bool:
    """A check that looks at what it is given (`validate_record(record)`
    reads `record`), with a signature nobody else fixes: an interface
    default (`def supports(self, feature): return True`) is not one."""
    if fixed_signature(intent, function) is not None:
        return False
    params = {a.arg for a in function.args.posonlyargs + function.args.args + function.args.kwonlyargs} - _IMPLICIT
    nodes = _own_nodes(function)
    if any(isinstance(n, (ast.Assert, ast.Raise)) for n in nodes):
        return False  # it fails loudly on a bad input: the True is not unconditional
    # A read is a load: `del timeout_s` or `record = {}` does not look at the input.
    reads = any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in params for n in nodes)
    return reads and not any(_names_outside_text(r.value) & params for r in _returns(function))


def _names_outside_text(value: Optional[ast.expr]) -> Set[str]:
    """Names a returned value reads, those only shown inside an f-string left
    out (`f"Scanned {root}"` reports, it does not depend on `root`). A
    serializer (`{"ok": True, "effect": p.effect}`) depends on its input."""
    if value is None:
        return set()
    names: Set[str] = set()
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.JoinedStr):
            continue
        if isinstance(node, ast.Name):
            names.add(node.id)
        stack.extend(ast.iter_child_nodes(node))
    return names


def _reports_success(intent, function: FunctionNode, success_only: Set[FunctionNode]) -> bool:
    """Undecorated, not a dunder or a contract, and it only ever reports success."""
    if function.decorator_list or function.name.startswith("__") or intent.is_contract(function):
        return False
    return function in success_only


_TRY_NODES = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)
_CATCH_ALL = frozenset({"Exception", "BaseException"})


def _catches_all(handler: ast.ExceptHandler) -> bool:
    """A bare `except:` or one naming `Exception` / `BaseException`."""
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(
        (t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else "") in _CATCH_ALL
        for t in types
    )


def _does_work(statements: List[ast.stmt]) -> bool:
    """A call other than a log line: something that can fail."""
    return any(
        isinstance(node, ast.Call) and not _is_log_call(node)
        for statement in statements
        for node in ast.walk(statement)
    )


def _swallowed_failures(function: FunctionNode) -> List[ast.ExceptHandler]:
    """Catch-all handlers that neither raise nor return, around a try that is
    the function's whole work: the body is that try and a final return, a
    docstring and log lines aside. A best-effort step inside larger work
    (`try: enable_diagnostics() except Exception: log.debug(...)`) is not."""
    body = _reachable(function.body)
    if not body or not isinstance(body[-1], ast.Return):
        return []
    work = [s for s in body[:-1] if not _is_docstring(s) and not _is_log_statement(s)]
    if len(work) != 1 or not isinstance(work[0], _TRY_NODES) or not _does_work(work[0].body):
        return []
    found = []
    for handler in work[0].handlers:
        inner = _block_nodes(handler.body)
        if _catches_all(handler) and not any(isinstance(n, (ast.Raise, ast.Return)) for n in inner):
            found.append(handler)
    return found


def _success_handlers(function: FunctionNode, local: frozenset) -> List[ast.ExceptHandler]:
    """Catch-all handlers around work (a call that can fail) whose own answer
    is a constructed success report: log lines, then `return {"status": "ok"}`
    or `return SendResult(ok=True)`. The caller cannot tell the failure from
    a success, whatever the function's other returns say. A bare `True` is
    left out: in a predicate (`is_enabled`, `pid_alive`) it is a deliberate
    fail-open default far more often than a disguised failure."""
    found = []
    for node in _block_nodes(function.body):
        if not isinstance(node, _TRY_NODES) or not _does_work(node.body):
            continue
        for handler in node.handlers:
            body = [s for s in handler.body if not _is_log_statement(s)]
            if (
                _catches_all(handler)
                and len(body) == 1
                and isinstance(body[0], ast.Return)
                and not isinstance(body[0].value, ast.Constant)
                and _is_success(body[0].value, local)
            ):
                found.append(handler)
    return found


def _is_docstring(statement: ast.stmt) -> bool:
    return isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant)


def _is_log_statement(statement: ast.stmt) -> bool:
    return isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and _is_log_call(statement.value)


def _block_nodes(statements: List[ast.stmt]) -> List[ast.AST]:
    """Nodes of a statement block, the bodies of nested functions, lambdas and
    classes left out."""
    nodes: List[ast.AST] = []
    stack: List[ast.AST] = list(statements)
    while stack:
        node = stack.pop()
        nodes.append(node)
        if not isinstance(node, _NESTED_SCOPES):
            stack.extend(ast.iter_child_nodes(node))
    return nodes


def _finally_returns(function: FunctionNode) -> List[ast.Return]:
    """`return` inside `finally`: it replaces any exception the block raised."""
    found = []
    for node in _own_nodes(function):
        if isinstance(node, _TRY_NODES):
            found += [n for n in _block_nodes(node.finalbody) if isinstance(n, ast.Return)]
    return found


def _ignored_outcomes(graph: _Graph, function: FunctionNode, dropped) -> List[str]:
    """Locals that hold an open call's result (`ok = client.send(msg)`) and
    are never read."""
    nodes = _own_nodes(function)
    versions = _Versions(function, nodes, _named(function))
    names = []
    for node in nodes:
        name = _open_call_store(graph, function, node)
        if name is not None and (function, versions.defined(name, node)) in dropped:
            names.append(name)
    return names


def _open_call_store(graph: _Graph, function: FunctionNode, node: ast.AST) -> Optional[str]:
    """The name in `name = open_call(...)` (or `= await open_call(...)`); None
    for any other statement, a log line, a module or value-building call, and
    `_ = ...` (a deliberate discard)."""
    if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)):
        return None
    name = node.targets[0].id
    value = node.value.value if isinstance(node.value, ast.Await) else node.value
    if name == "_" or not isinstance(value, ast.Call) or _is_log_call(value):
        return None
    if graph.resolve(value, function) is not None or _value_builtin(graph, function, value.func):
        return None
    return name


def _path_findings(graph: _Graph, function: FunctionNode, success_only, dropped) -> List[SemanticFinding]:
    """Paths on which a failure ends in a success report."""
    name = graph.qualname(function)
    findings = [
        SemanticFinding(
            name,
            "finally_return_hides_failure",
            node.lineno,
            [],
            "a return inside finally replaces any exception the try raised",
        )
        for node in _finally_returns(function)
    ]
    findings += [
        SemanticFinding(
            name,
            "failure_reported_as_success",
            handler.lineno,
            [],
            "a catch-all handler answers success, so a caller cannot tell the failure from a success",
        )
        for handler in _success_handlers(function, _local_names(graph, function))
    ]
    if not _reports_success(graph.intent, function, success_only):
        return findings
    findings += [
        SemanticFinding(
            name,
            "failure_reported_as_success",
            handler.lineno,
            [],
            "a catch-all handler swallows the failure and the function goes on to report success",
        )
        for handler in _swallowed_failures(function)
    ]
    outcomes = _ignored_outcomes(graph, function, dropped)
    if outcomes:
        findings.append(
            SemanticFinding(
                name,
                "success_ignores_outcome",
                function.lineno,
                outcomes,
                "the operation's result is stored and never read, and the function reports success",
            )
        )
    return findings


def semantic_findings(tree: ast.AST) -> List[SemanticFinding]:
    return semantic_analysis(tree)[0]


def semantic_analysis(tree: ast.AST) -> Tuple[List[SemanticFinding], Dict[str, object]]:
    """(findings, coverage) for the module."""
    graph = _Graph(tree)
    effects, callees, reasons, details = _with_effect(graph)
    coverage = _coverage(effects, reasons, details)
    if not graph.owner:
        return [], coverage
    intent = graph.intent
    dropped, reads = _dropped(graph)
    success_only = _success_only(graph)
    findings: List[SemanticFinding] = []
    for function in graph.owner:
        name = graph.qualname(function)
        returns = _returns(function)
        inputs = (
            _unused_inputs(function, dropped, reads)
            if fixed_signature(intent, function) is None and _returns_value(returns)
            else []
        )
        if inputs:
            findings.append(
                SemanticFinding(
                    name,
                    "input_never_used",
                    function.lineno,
                    inputs,
                    "the value reaches no result and no effect, here or in the module "
                    "functions it is passed to",
                    "DOCUMENTED_PROMISE" if _promises(function, inputs) else "REVIEW_CANDIDATE",
                )
            )
        work = callees[function]
        checks = not work and _checks_its_input(intent, function)
        if (work or checks) and effects[function] == NO_EFFECT and _reports_success(intent, function, success_only):
            evidence = (
                "reports success, and every call it makes resolves to module functions "
                "with no effect: " + ", ".join(sorted({graph.qualname(c) for c in work}))
                if work
                else "reads its input and reports success whatever it finds, with no effect"
            )
            findings.append(SemanticFinding(name, "success_without_effect", function.lineno, [], evidence))
        findings += [
            SemanticFinding(
                name,
                "effect_never_runs",
                call.lineno,
                [graph.qualname(callee)],
                "the call only builds a coroutine or generator and drops it, so the body never runs",
            )
            for call, callee in _never_run(graph, function)
        ]
        findings += _path_findings(graph, function, success_only, dropped)
    return sorted(findings, key=lambda f: (f.line, f.kind)), coverage
