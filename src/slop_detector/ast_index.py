"""One walk per parsed module.

Patterns and metrics each walked the whole module (`ast.walk(tree)`), about
forty walks per file; on Flamehaven-TOE that was most of a cold scan. The
node list of a module is built once and shared. It is `ast.walk` order
(breadth first), so every reader sees exactly what it saw before. Only
module roots are cached: analysis never changes a module's structure, while
function nodes are deep-copied and rewritten elsewhere (clone identity).
"""

from __future__ import annotations

import ast
from typing import List

_ATTRIBUTE = "_slop_walk_nodes"


def walk_nodes(tree: ast.AST) -> List[ast.AST]:
    """`list(ast.walk(tree))`, built once per parsed module."""
    if not isinstance(tree, ast.Module):
        return list(ast.walk(tree))
    nodes = getattr(tree, _ATTRIBUTE, None)
    if nodes is None:
        nodes = list(ast.walk(tree))
        setattr(tree, _ATTRIBUTE, nodes)
    return nodes
