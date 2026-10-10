"""Function clone cluster detection pattern."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from slop_detector.clone_identity import MIN_SEMANTIC_NODES, body_fingerprint, function_body
from slop_detector.clone_signals import EXACT_DUPLICATE_PAIR_ID, FUNCTION_CLONE_CLUSTER_ID
from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity


def _is_dispatcher_pattern(tree: ast.AST, clone_names: List[str]) -> bool:
    """Return True if the clone group is a recognized dispatcher pattern.

    Two signals (either is sufficient):
    1. A dict literal maps string-keyed values to names in the clone group,
       covering >= 40% of the group.  Indicates an already-implemented dispatch
       table — exactly the remediation the detector would suggest.
    2. >= 80% of clone names share a common prefix of >= 3 chars (cmd_, handle_,
       on_, get_, ...).  Indicates uniform CLI / event-handler naming, not
       copy-paste fragmentation.
    """
    if not clone_names:
        return False
    clone_set = set(clone_names)
    threshold = max(3, int(len(clone_set) * 0.4))

    # Signal 1: dispatch table
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            hits = sum(1 for v in node.values if isinstance(v, ast.Name) and v.id in clone_set)
            if hits >= threshold:
                return True

    # Signal 2: naming prefix uniformity
    if len(clone_names) >= 4:
        for prefix_len in range(3, 10):
            prefix = clone_names[0][:prefix_len]
            if not prefix:
                break
            matching = sum(1 for n in clone_names if n.startswith(prefix))
            if matching >= len(clone_names) * 0.8:
                return True

    # Signal 3: FastAPI / Flask route file — module-level `app` or `router` assignment.
    # Route handlers share structural patterns (try/except + HTTPException) by convention,
    # not copy-paste fragmentation.
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("app", "router"):
                    return True

    return False


def _is_property_accessor_cluster(tree: ast.AST, clone_names: List[str]) -> bool:
    """Return True when the clone group consists only of simple @property accessors."""
    if not clone_names:
        return False

    clone_set = set(clone_names)
    matched = 0
    for node in _iter_function_nodes(tree):
        if node.name not in clone_set:
            continue
        decorators = node.decorator_list
        if not any(isinstance(d, ast.Name) and d.id == "property" for d in decorators):
            return False

        body = [
            stmt
            for stmt in node.body
            if not (
                isinstance(stmt, ast.Expr)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
            )
        ]
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            return False
        matched += 1

    return matched == len(clone_set)


def _fragmentation_candidates(tree: ast.AST, clone_names: List[str]) -> List[str]:
    """Clone-group members that could be pieces of one fragmented operation.

    A dunder method's shape follows its protocol (`__and__`, `__or__`, ...),
    and a name the module defines more than once is one operation implemented
    in several places: an override per class (polymorphism) or the closure of
    each decorator factory. Neither is a fragment of a larger function, even
    when the clone group holds only one of its definitions.
    """
    defined = Counter(node.name for node in _iter_function_nodes(tree))
    return [
        name
        for name in clone_names
        if defined[name] == 1 and not (name.startswith("__") and name.endswith("__"))
    ]


def _iter_function_nodes(tree: ast.AST) -> List[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _qualified_clone_names(tree: ast.AST, clone_names: List[str]) -> List[str]:
    """Render clone evidence with owning classes so repeated overrides are reviewable."""
    names = set(clone_names)
    qualified: List[str] = []

    class _Collector(ast.NodeVisitor):
        def __init__(self) -> None:
            self.class_stack: List[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            if node.name in names:
                owner = ".".join(self.class_stack)
                qualified.append(f"{owner}.{node.name}" if owner else node.name)
            self.generic_visit(node)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_function(node)

    _Collector().visit(tree)
    return qualified


def _semantic_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    """Capture values erased by the coarse AST histogram without using local names."""
    tokens: List[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and child.value is not Ellipsis:
            tokens.append(f"constant:{child.value!r}")
        elif isinstance(child, ast.Attribute):
            tokens.append(f"attribute:{child.attr}")
        elif isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                tokens.append(f"call:{child.func.id}")
            elif isinstance(child.func, ast.Attribute):
                tokens.append(f"call:{child.func.attr}")
        elif isinstance(child, ast.cmpop):
            tokens.append(f"compare:{type(child).__name__}")
    return tuple(sorted(set(tokens)))


def _has_distinct_semantic_signatures(tree: ast.AST, clone_names: List[str]) -> bool:
    names = set(clone_names)
    candidates = [node for node in _iter_function_nodes(tree) if node.name in names]
    signatures = [_semantic_signature(node) for node in candidates]
    return bool(signatures) and all(signatures) and len(set(signatures)) == len(signatures)


def _method_owners(tree: ast.AST) -> Dict[int, ast.ClassDef]:
    """Map id(method) to the class whose body defines it directly."""
    return {
        id(item): node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


_VISITOR_ADAPTER_MAX_STATEMENTS = 3


def _is_visitor_adapter_group(
    funcs: List[ast.FunctionDef | ast.AsyncFunctionDef], owners: Dict[int, ast.ClassDef]
) -> bool:
    """Visitor protocol glue, not copy-paste.

    All four must hold: one owning class, every name starts with `visit_`, and
    the (shared) body is at most 3 call statements, one of them generic_visit.
    """
    owner = owners.get(id(funcs[0]))
    if owner is None or any(owners.get(id(func)) is not owner for func in funcs):
        return False
    if not all(func.name.startswith("visit_") for func in funcs):
        return False
    body = function_body(funcs[0])
    if not body or len(body) > _VISITOR_ADAPTER_MAX_STATEMENTS:
        return False
    calls = [stmt.value for stmt in body if isinstance(stmt, (ast.Expr, ast.Return))]
    if len(calls) != len(body) or not all(isinstance(call, ast.Call) for call in calls):
        return False
    return any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "generic_visit"
        for call in calls
        if isinstance(call, ast.Call)
    )


def _find_exact_duplicate_groups(
    tree: ast.AST,
) -> List[Tuple[List[str], List[int]]]:
    groups: Dict[str, List[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for func in _iter_function_nodes(tree):
        identity, size = body_fingerprint(func)
        if size >= MIN_SEMANTIC_NODES:
            groups.setdefault(identity, []).append(func)

    owners = _method_owners(tree)
    duplicates: List[Tuple[List[str], List[int]]] = []
    for funcs in groups.values():
        if len(funcs) < 2 or _is_visitor_adapter_group(funcs, owners):
            continue
        duplicates.append(
            ([func.name for func in funcs], [getattr(func, "lineno", 1) for func in funcs])
        )
    return duplicates


class ExactDuplicatePairPattern(BasePattern):
    """Detect exact same-file duplicate functions after local-name normalization."""

    id = EXACT_DUPLICATE_PAIR_ID
    severity = Severity.HIGH
    axis = Axis.STRUCTURE

    def check(self, tree: ast.AST, file: Any, content: str) -> List[Issue]:
        duplicate_groups = _find_exact_duplicate_groups(tree)
        if not duplicate_groups:
            return []

        issues: List[Issue] = []
        for names, lines in duplicate_groups:
            preview = ", ".join(names[:6])
            if len(names) > 6:
                preview += f", ... (+{len(names) - 6} more)"
            sev = Severity.CRITICAL if len(names) >= 4 else Severity.HIGH
            issues.append(
                Issue(
                    pattern_id=self.id,
                    severity=sev,
                    axis=self.axis,
                    file=Path(str(file)) if file else Path(),
                    line=min(lines) if lines else 1,
                    column=0,
                    message=(
                        f"{len(names)} exact duplicate functions detected after normalizing "
                        f"local names and parameters: {preview}. Review for copy-paste logic "
                        f"that should be extracted or consolidated."
                    ),
                    code=preview,
                    suggestion=(
                        "Extract the shared logic into one helper or keep one public function "
                        "and route aliases to it explicitly."
                    ),
                )
            )
        return issues


class FunctionClonePattern(BasePattern):
    """Detect files where many functions have near-identical AST structure.

    Algorithm: pairwise Jensen-Shannon Divergence on 30-dim AST node-type
    histograms. Functions with JSD < 0.05 form clone groups (BFS components).

    Thresholds:
      >= 6 clones: CRITICAL
      >= 4 clones: HIGH
    """

    id = FUNCTION_CLONE_CLUSTER_ID
    severity = Severity.HIGH
    axis = Axis.STRUCTURE

    def check(self, tree: ast.AST, file: Any, content: str) -> List[Issue]:
        from slop_detector.metrics.stub_density import (
            _CLONE_HIGH_THRESHOLD,
            _CLONE_MED_THRESHOLD,
            _MIN_FUNCTIONS_FOR_CLONE,
            calculate_stub_density,
        )

        result = calculate_stub_density(content)
        if result is None or result.total_functions < _MIN_FUNCTIONS_FOR_CLONE:
            return []

        if result.max_clone_group < _CLONE_MED_THRESHOLD:
            return []

        if _is_dispatcher_pattern(tree, result.clone_group_names):
            return []

        if _is_property_accessor_cluster(tree, result.clone_group_names):
            return []

        if _has_distinct_semantic_signatures(tree, result.clone_group_names):
            return []

        fragments = _fragmentation_candidates(tree, result.clone_group_names)
        if len(fragments) < _CLONE_MED_THRESHOLD:
            return []

        clone_size = len(fragments)
        qualified_names = _qualified_clone_names(tree, fragments)
        names_preview = ", ".join(qualified_names[:6])
        if len(qualified_names) > 6:
            names_preview += f", ... (+{len(qualified_names) - 6} more)"

        if clone_size >= _CLONE_HIGH_THRESHOLD:
            sev = Severity.CRITICAL
            msg = (
                f"{clone_size} structurally near-identical functions detected "
                f"(AST JSD < 0.05): {names_preview}. "
                f"Possible god function fragmented into helpers to evade per-function gates."
            )
        else:
            sev = Severity.HIGH
            msg = (
                f"{clone_size} structurally similar functions detected "
                f"(AST JSD < 0.05): {names_preview}. "
                f"Review for unnecessary decomposition."
            )

        return [
            Issue(
                pattern_id=self.id,
                severity=sev,
                axis=self.axis,
                file=Path(str(file)) if file else Path(),
                line=1,
                column=0,
                message=msg,
                suggestion=(
                    "If these functions represent a fragmented complex operation, "
                    "consider consolidating or using a data-driven dispatch table."
                ),
            )
        ]
