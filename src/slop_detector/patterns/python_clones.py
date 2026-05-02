"""Function clone cluster detection pattern."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, List

from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity


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
