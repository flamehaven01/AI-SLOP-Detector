"""Function clone cluster detection pattern."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, List

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
