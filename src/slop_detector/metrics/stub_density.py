"""
Stub Density and Function Clone Metrics (v3.1.0)

Two orthogonal measures of code structural quality derived from AST analysis:

1. stub_body_ratio: fraction of functions with trivially empty bodies.
   Extends placeholder pattern detection to the file level.
   (See also: patterns/placeholder.py ReturnConstantStubPattern)

2. function_clone_count: largest group of functions with near-identical
   AST node-type distributions, computed via Jensen-Shannon Divergence.

   Addresses the complexity_hidden_in_helpers evasion (SPAR A4):
   A god function split into N one-liner helpers evades all per-function
   pattern gates. When N functions are structurally near-identical, the
   aggregate signal is: complexity was fragmented, not eliminated.

Algorithm (adapted from Protocol-ReGenesis math_models.py, which ports
Flamehaven-TOE v4.5.0 toe/math/di2.py):
  - ast_node_histogram(func_node) -> normalized 30-dim vector
  - jsd(p, q) -> [0, 1] (0 = identical distributions)
  - clone group: set of functions where all pairwise JSD < CLONE_JSD_THRESHOLD

Zero external dependencies (pure Python + ast stdlib).
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum functions before clone detection is meaningful
_MIN_FUNCTIONS_FOR_CLONE = 5

# Two functions are "clones" if JSD of their AST vectors < this threshold
_CLONE_JSD_THRESHOLD = 0.05

# Clone group size thresholds
_CLONE_HIGH_THRESHOLD = 6  # >= 6 clones -> HIGH
_CLONE_MED_THRESHOLD = 4  # >= 4 clones -> MEDIUM

_EPS = 1e-12

# 30 representative Python AST node types for structural fingerprinting.
# Selected for discriminating power between stub and computational code.
_NODE_TYPES: List[str] = [
    # Definitions (structural)
    "FunctionDef",
    "AsyncFunctionDef",
    "ClassDef",
    # Control flow (computational)
    "For",
    "AsyncFor",
    "While",
    "If",
    "With",
    "AsyncWith",
    "Break",
    "Continue",
    "Try",
    "ExceptHandler",
    "Assert",
    # Exceptions / generators
    "Raise",
    "Yield",
    "YieldFrom",
    # Assignments (computational)
    "Assign",
    "AugAssign",
    "AnnAssign",
    # Imports
    "Import",
    "ImportFrom",
    # Expressions (computational)
    "Call",
    "Attribute",
    "Subscript",
    # Operators (computational)
    "BoolOp",
    "BinOp",
    "UnaryOp",
    "Compare",
    # Terminal / stub indicators
    "Return",
    "Pass",
    "Constant",
]
_NODE_INDEX: Dict[str, int] = {t: i for i, t in enumerate(_NODE_TYPES)}
_NDIM = len(_NODE_TYPES)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StubDensityResult:
    total_functions: int
    stub_functions: int
    stub_ratio: float  # [0, 1]
    max_clone_group: int  # largest cluster of near-identical functions
    clone_group_names: List[str]  # names in the largest clone cluster


# ---------------------------------------------------------------------------
# Core math: AST histogram + JSD
# ---------------------------------------------------------------------------


def _node_histogram(func_node: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> List[float]:
    """Normalized 30-dim AST node-type histogram for a single function body."""
    counts = [0.0] * _NDIM
    for node in ast.walk(func_node):
        idx = _NODE_INDEX.get(type(node).__name__)
        if idx is not None:
            counts[idx] += 1.0
    total = sum(counts)
    if total == 0.0:
        return counts
    return [c / total for c in counts]


def _jsd(p: List[float], q: List[float]) -> float:
    """Jensen-Shannon Divergence in [0, 1]. Pure Python (no numpy)."""
    m = [(pi + qi) * 0.5 for pi, qi in zip(p, q)]
    kl_pm = kl_qm = 0.0
    for pi, qi, mi in zip(p, q, m):
        if pi > _EPS and mi > _EPS:
            kl_pm += pi * math.log(pi / mi)
        if qi > _EPS and mi > _EPS:
            kl_qm += qi * math.log(qi / mi)
    return max(0.0, min(1.0, 0.5 * kl_pm + 0.5 * kl_qm))


# ---------------------------------------------------------------------------
# Stub body detection
# ---------------------------------------------------------------------------


def _is_stub_body(func: Union[ast.FunctionDef, ast.AsyncFunctionDef]) -> bool:
    """True if function body is a placeholder with no real computation.

    A stub is a function whose body (excluding docstring) is exactly one of:
    - pass / ...
    - return None / return <constant> / return <empty container>
    - raise <anything>
    """
    body = [
        s
        for s in func.body
        if not (
            isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Constant)
            and isinstance(s.value.value, str)
        )
    ]
    if not body:
        return True
    if len(body) != 1:
        return False
    stmt = body[0]
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return stmt.value.value is ...
    if isinstance(stmt, ast.Raise):
        return True
    if isinstance(stmt, ast.Return):
        val = stmt.value
        if val is None:
            return True
        if isinstance(val, ast.Constant):
            return True
        if isinstance(val, ast.List) and not val.elts:
            return True
        if isinstance(val, ast.Dict) and not val.keys:
            return True
        if isinstance(val, ast.Tuple) and not val.elts:
            return True
        if isinstance(val, ast.Set) and not val.elts:
            return True
    return False


# ---------------------------------------------------------------------------
# Clone group detection
# ---------------------------------------------------------------------------


def _find_largest_clone_group(
    funcs: List[Union[ast.FunctionDef, ast.AsyncFunctionDef]],
) -> Tuple[int, List[str]]:
    """Find the largest group of near-identical functions by AST JSD.

    Two functions are clones if JSD(histogram_A, histogram_B) < threshold.
    Returns (group_size, list_of_names).

    O(n^2) pairwise comparison. For typical files (< 60 functions) this is
    under 1,800 comparisons -- fast enough for per-file analysis.
    """
    n = len(funcs)
    if n < 2:
        return 0, []

    histograms = [_node_histogram(f) for f in funcs]

    # Build adjacency: clone_of[i] = set of j that are clones of i
    clone_edges: List[List[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if _jsd(histograms[i], histograms[j]) < _CLONE_JSD_THRESHOLD:
                clone_edges[i].append(j)
                clone_edges[j].append(i)

    # Find largest connected component (BFS)
    visited = [False] * n
    best_size, best_group = 0, []

    for start in range(n):
        if visited[start]:
            continue
        queue = [start]
        component = []
        while queue:
            node = queue.pop()
            if visited[node]:
                continue
            visited[node] = True
            component.append(node)
            queue.extend(clone_edges[node])
        if len(component) > best_size:
            best_size = len(component)
            best_group = component

    names = [funcs[i].name for i in best_group]
    return best_size, names


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def calculate_stub_density(source: str) -> Optional[StubDensityResult]:
    """Compute stub ratio and function clone group size for a Python source string.

    Returns None if the source cannot be parsed.
    Returns a result with total_functions=0 if there are no functions
    (not enough data to score).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    all_funcs: List[Union[ast.FunctionDef, ast.AsyncFunctionDef]] = [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    total = len(all_funcs)
    if total == 0:
        return StubDensityResult(
            total_functions=0,
            stub_functions=0,
            stub_ratio=0.0,
            max_clone_group=0,
            clone_group_names=[],
        )

    stubs = [f for f in all_funcs if _is_stub_body(f)]
    stub_ratio = len(stubs) / total

    # Clone detection only meaningful for files with >= MIN_FUNCTIONS_FOR_CLONE
    if total >= _MIN_FUNCTIONS_FOR_CLONE:
        clone_size, clone_names = _find_largest_clone_group(list(all_funcs))
    else:
        clone_size, clone_names = 0, []

    return StubDensityResult(
        total_functions=total,
        stub_functions=len(stubs),
        stub_ratio=stub_ratio,
        max_clone_group=clone_size,
        clone_group_names=clone_names,
    )
