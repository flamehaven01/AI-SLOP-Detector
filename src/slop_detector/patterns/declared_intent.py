"""Declared intent of placeholder-shaped code, read from the module itself.

A one-line body (`pass`, `...`, `raise NotImplementedError`, a constant) is
unfinished code only when nothing in the module says it is meant to be that
way. Evidence the module states:

- the class is declared abstract: an `ABC` / `Protocol` base (subscripted or
  qualified) or `metaclass=ABCMeta`;
- the method is a base contract: a subclass defined in the module overrides it;
- the method overrides a method its base (defined in the module) declares, so a
  constant answer is a hook implementation;
- a `property` / `cached_property` / `classmethod` / `staticmethod` is a
  declared accessor;
- another decorator supplies the body (a `...` body under it is a signature),
  or registers it (an empty `pass` / `return None` body under it, such as a
  `click.group`, does nothing and claims nothing);
- the class name says it is a default: a null object (`NullRenderer`,
  `NoopSink`) or a base (`BaseFeature`, `AirLLMBaseModel`), so its one-line
  bodies are the defaults; a `return` in a subclass of such a named base is a
  hook answer;
- `raise NotImplementedError` in a method of a class with a base the module
  does not define (the base fixes the interface; the method declares the
  operation unsupported), or of a class with two or more such methods (an
  interface written without `ABC`).

Only the module is read, so a file's result never depends on other files.
"""

from __future__ import annotations

import ast
import re
from typing import Dict, Optional, Set, Union

from slop_detector.ast_index import walk_nodes

FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]

_ABSTRACT_BASES = frozenset({"ABC", "Protocol"})
_ABSTRACT_METACLASSES = frozenset({"ABCMeta"})
_ACCESSOR_DECORATORS = frozenset({"property", "cached_property", "classmethod", "staticmethod"})
_SIGNATURE_DECORATORS = frozenset({"abstractmethod", "overload"})
# Class-name words declaring the class a null object or a base of defaults.
_DEFAULT_CLASS_WORDS = frozenset({"null", "noop", "base", "abstract"})


def _name_words(name: str) -> Set[str]:
    """`AirLLMBaseModel` -> {air, llm, base, model}; `NoOpSink` also gives noop."""
    words = {w.lower() for w in re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", name)}
    if "noop" in name.lower().replace("_", ""):
        words.add("noop")
    return words


def _body_without_docstring(function: ast.AST) -> list:
    return [
        n
        for n in getattr(function, "body", [])
        if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
    ]


_PLACEHOLDER_DOC = re.compile(
    r"\b(placeholder|stub|todo|not yet implemented|to be implemented)\b", re.I
)


def _says_placeholder(function: ast.AST) -> bool:
    """The docstring calls the body a placeholder ("Placeholder for CDA construction")."""
    doc = (
        ast.get_docstring(function)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        else None
    )
    return bool(doc and _PLACEHOLDER_DOC.search(doc))


def _raises_not_implemented(function: ast.AST) -> bool:
    """The body (after a docstring) is `raise NotImplementedError`, `pass` aside."""
    body = _body_without_docstring(function)
    if not body or not isinstance(body[-1], ast.Raise):
        return False
    exc = body[-1].exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    if not (isinstance(exc, ast.Name) and exc.id == "NotImplementedError"):
        return False
    return all(isinstance(n, ast.Pass) for n in body[:-1])


def _simple_name(node: ast.expr) -> str:
    """Last name of a base or decorator: `abc.ABC` -> ABC, `Protocol[T]` -> Protocol."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Subscript):
        node = node.value
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _methods(klass: ast.ClassDef) -> Set[str]:
    return {
        node.name
        for node in klass.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


_SCOPE_NODES = (
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.Lambda,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def _local_names(scope: ast.AST) -> Set[str]:
    """Names a function, lambda or comprehension binds itself (minus `global`s)."""
    bound: Set[str] = set()
    declared_global: Set[str] = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        args = scope.args
        for arg in args.posonlyargs + args.args + args.kwonlyargs:
            bound.add(arg.arg)
        for extra in (args.vararg, args.kwarg):
            if extra is not None:
                bound.add(extra.arg)
        roots = scope.body if isinstance(scope.body, list) else [scope.body]
    else:
        roots = list(getattr(scope, "generators", []))  # a comprehension's own bindings
    pending: list = list(roots)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
            continue
        if isinstance(node, _SCOPE_NODES):
            continue
        if isinstance(node, ast.Global):
            declared_global.update(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        pending.extend(ast.iter_child_nodes(node))
    return bound - declared_global


def _value_references(tree: ast.AST):
    """Functions read by value, and `self.`/`cls.` methods read by value.

    A name read resolves to the innermost scope that binds it (the module when
    none does); it registers the function defined in that same scope. So a
    nested callback (`def deny(...)` then `set_callback(deny)` in one function)
    counts, and a parameter or local of the same name elsewhere does not.
    Returns (set of (defining scope id, name), set of method names,
    map of function node id -> defining scope id).
    """
    called = {id(node.func) for node in walk_nodes(tree) if isinstance(node, ast.Call)}
    data_attrs = {
        node.attr
        for node in walk_nodes(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and isinstance(node.value, ast.Name)
        and node.value.id in ("self", "cls")
    }
    module_scope = 0
    refs: Set[tuple] = set()
    attrs: Set[str] = set()
    defined_in: Dict[int, int] = {}
    stack: list = [(tree, ())]
    while stack:
        node, scopes = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defined_in[id(node)] = scopes[-1][0] if scopes else module_scope
        if isinstance(node, _SCOPE_NODES):
            scopes = scopes + ((id(node), _local_names(node)),)
        if id(node) not in called and isinstance(getattr(node, "ctx", None), ast.Load):
            if isinstance(node, ast.Name):
                owner = next(
                    (sid for sid, names in reversed(scopes) if node.id in names), module_scope
                )
                refs.add((owner, node.id))
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in ("self", "cls")
                and node.attr not in data_attrs
            ):
                attrs.add(node.attr)
        stack.extend((child, scopes) for child in ast.iter_child_nodes(node))
    return refs, attrs, defined_in


def _module_bindings(tree: ast.AST) -> Set[str]:
    """Names the module binds at top level (defs, classes, imports, assignments)."""
    bound: Set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                bound.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
    return bound


class DeclaredIntent:
    """What one module declares about its classes and methods."""

    def __init__(self, tree: ast.AST) -> None:
        self._parent: Dict[ast.AST, ast.AST] = {
            child: parent for parent in walk_nodes(tree) for child in ast.iter_child_nodes(parent)
        }
        classes = [node for node in walk_nodes(tree) if isinstance(node, ast.ClassDef)]
        self._methods_by_class: Dict[str, Set[str]] = {}
        self._overridden: Dict[str, Set[str]] = {}
        for klass in classes:
            self._methods_by_class.setdefault(klass.name, set()).update(_methods(klass))
        for klass in classes:
            for base in klass.bases:
                self._overridden.setdefault(_simple_name(base), set()).update(_methods(klass))
        self._abstract: Set[ast.ClassDef] = {k for k in classes if self._declared_abstract(k)}
        self._name_refs, self._self_attr_refs, self._defined_in = _value_references(tree)
        self.module_bindings: Set[str] = _module_bindings(tree)

    @staticmethod
    def _declared_abstract(klass: ast.ClassDef) -> bool:
        if any(_simple_name(base) in _ABSTRACT_BASES for base in klass.bases):
            return True
        return any(
            keyword.arg == "metaclass" and _simple_name(keyword.value) in _ABSTRACT_METACLASSES
            for keyword in klass.keywords
        )

    def enclosing_class(self, function: FunctionNode) -> Optional[ast.ClassDef]:
        parent = self._parent.get(function)
        return parent if isinstance(parent, ast.ClassDef) else None

    def is_interface_class(self, klass: ast.ClassDef) -> bool:
        """Declared abstract, or subclassed in the module."""
        return klass in self._abstract or klass.name in self._overridden

    def is_contract(self, function: FunctionNode) -> bool:
        """A method of a declared interface, or a base method a subclass overrides."""
        klass = self.enclosing_class(function)
        if klass is None:
            return False
        return klass in self._abstract or function.name in self._overridden.get(klass.name, set())

    def overrides_module_base(self, function: FunctionNode) -> bool:
        """The method overrides a method that a base defined in the module declares."""
        klass = self.enclosing_class(function)
        if klass is None:
            return False
        return any(
            function.name in self._methods_by_class.get(_simple_name(base), set())
            for base in klass.bases
        )

    def has_outside_base(self, function: FunctionNode) -> bool:
        """A method of a class with a base the module does not define: the base may
        fix the method's signature (`forward(self, x, mask)` on `nn.Module`)."""
        klass = self.enclosing_class(function)
        if klass is None:
            return False
        return any(
            _simple_name(base) not in self._methods_by_class and _simple_name(base) != "object"
            for base in klass.bases
        )

    def is_registered_by_value(self, function: FunctionNode) -> bool:
        """The module hands the function over by value (a callback or a dispatch
        entry) instead of calling it: its fixed answer is the handler's job.

        A module function counts when its name is read, not called, where no
        enclosing function binds that name; a method when `self.` / `cls.` reads
        it and the class never assigns that attribute (then it is data).
        """
        if self.enclosing_class(function) is not None:
            return function.name in self._self_attr_refs
        scope = self._defined_in.get(id(function), 0)
        return (scope, function.name) in self._name_refs

    @staticmethod
    def is_default_class(klass: ast.ClassDef) -> bool:
        """The class name says null object or base: `NullRenderer`, `BaseFeature`."""
        return bool(_name_words(klass.name) & _DEFAULT_CLASS_WORDS)

    @staticmethod
    def has_named_base(klass: ast.ClassDef) -> bool:
        """A base whose name says it is a base: `class Qwen(AirLLMBaseModel)`."""
        return any(_name_words(_simple_name(b)) & {"base", "abstract"} for b in klass.bases)

    def declares_unsupported(self, function: FunctionNode) -> bool:
        """`raise NotImplementedError` where a base or the class itself fixes the
        interface: a class with a base the module does not define, or a class
        with two or more such methods."""
        klass = self.enclosing_class(function)
        if klass is None:
            return False
        if self.has_outside_base(function):
            return True
        siblings = [
            n
            for n in klass.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _raises_not_implemented(n)
        ]
        return len(siblings) >= 2

    @staticmethod
    def is_accessor(function: FunctionNode) -> bool:
        return any(_simple_name(d) in _ACCESSOR_DECORATORS for d in function.decorator_list)

    @staticmethod
    def has_implementing_decorator(function: FunctionNode) -> bool:
        """A decorator other than an accessor or a signature marker supplies the body."""
        return any(
            _simple_name(d) not in _ACCESSOR_DECORATORS | _SIGNATURE_DECORATORS
            for d in function.decorator_list
        )


def declared_intent(tree: ast.AST) -> DeclaredIntent:
    """The module's DeclaredIntent, built once per parsed tree."""
    cached = getattr(tree, "_slop_declared_intent", None)
    if cached is None:
        cached = DeclaredIntent(tree)
        setattr(tree, "_slop_declared_intent", cached)
    return cached


def _plain_body(function: FunctionNode, stmt: ast.stmt) -> bool:
    """`stmt` is the whole body, the docstring does not call it a placeholder, and
    it does not construct its answer (`SendResult(success=True)`)."""
    if _body_without_docstring(function) != [stmt] or _says_placeholder(function):
        return False
    return not (isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Call))


def _is_empty(stmt: ast.stmt) -> bool:
    """`pass`, `return` or `return None`."""
    if isinstance(stmt, ast.Pass):
        return True
    if not isinstance(stmt, ast.Return):
        return False
    return stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)


def _named_default(intent: DeclaredIntent, function: FunctionNode, stmt: ast.stmt) -> bool:
    """A default the class name or its interface declares; plain bodies only, so a
    log line in front or a "placeholder" docstring keeps a stub reported."""
    klass = intent.enclosing_class(function)
    if klass is None or not _plain_body(function, stmt):
        return False
    if intent.is_default_class(klass):
        return True
    if isinstance(stmt, ast.Return):
        return intent.has_named_base(klass)
    return isinstance(stmt, ast.Raise) and intent.declares_unsupported(function)


def is_declared_body(intent: DeclaredIntent, function: FunctionNode, stmt: ast.stmt) -> bool:
    """The one-statement body `stmt` is declared intent, not an unfinished stub.

    A contract method is declared whatever its body. A `return` is declared in
    an accessor or in an override of a module base (a hook answering a
    question); a `...` body is declared under an implementing decorator, an
    empty one under any registering decorator. An override that is `pass` or
    raises stays a placeholder unless its class name or interface declares it
    (`_named_default`).
    """
    if intent.is_contract(function) or _named_default(intent, function, stmt):
        return True
    if _is_empty(stmt) and intent.has_implementing_decorator(function):
        return True
    if isinstance(stmt, ast.Return):
        return intent.is_accessor(function) or intent.overrides_module_base(function)
    is_ellipsis = (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is ...
    )
    return is_ellipsis and intent.has_implementing_decorator(function)
