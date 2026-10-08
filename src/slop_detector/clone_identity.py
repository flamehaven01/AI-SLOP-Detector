"""Canonical function-body identity for exact duplicate detection.

One definition for both reports that say "exact duplicate": the same-file
pattern (`exact_duplicate_pair`) and the cross-file duplicate list.

Identity is the body only. The leading docstring, the function name,
decorators, annotations and defaults are not part of it; parameters and local
names are canonicalized by position; operators, call targets, attributes and
constants are kept; `def` and `async def` stay distinct.

Eligibility is separate: a body counts as a duplicate candidate only with at
least MIN_SEMANTIC_NODES semantic nodes (context and operator helper nodes are
not counted, though operators remain part of the identity).
"""

from __future__ import annotations

import ast
import copy
from hashlib import sha256
from typing import Dict, List, Tuple, Union

from slop_detector.metrics.ldr import _is_docstring_stmt

FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]

# Precision-oriented eligibility floor derived from the current multi-repository
# dogfood corpus (11 codebases, 2026-10-08), not a universal constant. Bodies
# below it were leaf statements (pass, raise X, return a constant or a name) or
# a single delegating call; at 6 to 10 the set of 4-or-more-function groups was
# the same.
MIN_SEMANTIC_NODES = 8

_HELPER_NODES = (ast.expr_context, ast.operator, ast.boolop, ast.unaryop, ast.cmpop)


def _collect_local_name_mapping(func: FunctionNode) -> Dict[str, str]:
    mapping: Dict[str, str] = {}

    def _bind(name: str, prefix: str = "v") -> None:
        if name and name not in mapping:
            mapping[name] = f"{prefix}{len(mapping)}"

    all_args = []
    all_args.extend(func.args.posonlyargs)
    all_args.extend(func.args.args)
    all_args.extend(func.args.kwonlyargs)
    for arg in all_args:
        _bind(arg.arg, "a")
    if func.args.vararg:
        _bind(func.args.vararg.arg, "a")
    if func.args.kwarg:
        _bind(func.args.kwarg.arg, "a")

    for node in ast.walk(func):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            _bind(node.id, "v")
        elif isinstance(node, ast.ExceptHandler) and isinstance(node.name, str):
            _bind(node.name, "e")

    return mapping


class _LocalNameNormalizer(ast.NodeTransformer):
    def __init__(self, mapping: Dict[str, str]):
        self.mapping = mapping

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = "__func__"
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = "__func__"
        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        if node.arg in self.mapping:
            node.arg = self.mapping[node.arg]
        return self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id in self.mapping:
            node.id = self.mapping[node.id]
        return node

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.AST:
        if isinstance(node.name, str) and node.name in self.mapping:
            node.name = self.mapping[node.name]
        return self.generic_visit(node)


def function_body(func: FunctionNode) -> List[ast.stmt]:
    """The body statements without the leading docstring."""
    body = list(func.body)
    if body and _is_docstring_stmt(body[0]):
        body = body[1:]
    return body


def body_fingerprint(func: FunctionNode) -> Tuple[str, int]:
    """(identity, semantic node count) of a function body."""
    cloned = copy.deepcopy(func)
    normalized = _LocalNameNormalizer(_collect_local_name_mapping(cloned)).visit(cloned)
    body = function_body(normalized)
    kind = "async" if isinstance(func, ast.AsyncFunctionDef) else "def"
    dump = "\n".join(ast.dump(stmt, include_attributes=False) for stmt in body)
    size = sum(1 for stmt in body for node in ast.walk(stmt) if not isinstance(node, _HELPER_NODES))
    return sha256(f"{kind}\n{dump}".encode("utf-8")).hexdigest(), size
