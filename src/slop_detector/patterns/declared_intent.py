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
- another decorator supplies the body (a `...` body under it is a signature).

Only the module is read, so a file's result never depends on other files.
"""

from __future__ import annotations

import ast
from typing import Dict, Optional, Set, Union

from slop_detector.ast_index import walk_nodes

FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]

_ABSTRACT_BASES = frozenset({"ABC", "Protocol"})
_ABSTRACT_METACLASSES = frozenset({"ABCMeta"})
_ACCESSOR_DECORATORS = frozenset({"property", "cached_property", "classmethod", "staticmethod"})
_SIGNATURE_DECORATORS = frozenset({"abstractmethod", "overload"})


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


def is_declared_body(intent: DeclaredIntent, function: FunctionNode, stmt: ast.stmt) -> bool:
    """The one-statement body `stmt` is declared intent, not an unfinished stub.

    A contract method is declared whatever its body. A `return` is declared in
    an accessor or in an override of a module base (a hook answering a
    question); a `...` body is declared under an implementing decorator. An
    override that is `pass` or raises stays a placeholder.
    """
    if intent.is_contract(function):
        return True
    if isinstance(stmt, ast.Return):
        return intent.is_accessor(function) or intent.overrides_module_base(function)
    is_ellipsis = (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and stmt.value.value is ...
    )
    return is_ellipsis and intent.has_implementing_decorator(function)
