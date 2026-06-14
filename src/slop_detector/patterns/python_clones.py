"""Function clone cluster detection pattern."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from typing import Any, Dict, List, Tuple

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


def _iter_function_nodes(tree: ast.AST) -> List[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _collect_local_name_mapping(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Dict[str, str]:
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


def _normalized_function_signature(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Tuple[str, int]:
    cloned = copy.deepcopy(func)
    mapping = _collect_local_name_mapping(cloned)
    normalized = _LocalNameNormalizer(mapping).visit(cloned)
    ast.fix_missing_locations(normalized)
    normalized_dump = ast.dump(normalized, include_attributes=False)
    normalized_node_count = sum(1 for _ in ast.walk(normalized))
    return normalized_dump, normalized_node_count


def _find_exact_duplicate_groups(
    tree: ast.AST,
) -> List[Tuple[List[str], List[int]]]:
    groups: Dict[str, List[Tuple[str, int, int]]] = {}
    for func in _iter_function_nodes(tree):
        signature, node_count = _normalized_function_signature(func)
        entry = (func.name, getattr(func, "lineno", 1), node_count)
        groups.setdefault(signature, []).append(entry)

    duplicates: List[Tuple[List[str], List[int]]] = []
    for entries in groups.values():
        if len(entries) < 2:
            continue
        if max(node_count for _, _, node_count in entries) < 12:
            continue
        duplicate_names = [name for name, _, _ in entries]
        duplicate_lines = [lineno for _, lineno, _ in entries]
        duplicate_group = (duplicate_names, duplicate_lines)
        duplicates.append(duplicate_group)
    return duplicates


class ExactDuplicatePairPattern(BasePattern):
    """Detect exact same-file duplicate functions after local-name normalization."""

    id = "exact_duplicate_pair"
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

    id = "function_clone_cluster"
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

        clone_size = result.max_clone_group
        names_preview = ", ".join(result.clone_group_names[:6])
        if len(result.clone_group_names) > 6:
            names_preview += f", ... (+{len(result.clone_group_names) - 6} more)"

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
