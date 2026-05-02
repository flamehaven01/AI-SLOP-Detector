"""Placeholder variable naming detection pattern."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, List, Union

from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity

_PLACEHOLDER_PARAM_THRESHOLD = 5
_NUMBERED_SEQ_HIGH = 8
_NUMBERED_SEQ_MED = 4


def _collect_numbered_vars(
    node: Union[ast.FunctionDef, ast.AsyncFunctionDef],
) -> dict:
    """Return {prefix: [nums]} for all numbered assignment targets in node."""
    numbered: dict = {}
    for stmt in ast.walk(node):
        if not isinstance(stmt, ast.Assign):
            continue
        for target in stmt.targets:
            if not isinstance(target, ast.Name):
                continue
            m = re.match(r"^([a-zA-Z_][a-zA-Z_]*)(\d+)$", target.id)
            if m:
                prefix, num = m.group(1), int(m.group(2))
                numbered.setdefault(prefix, []).append(num)
    return numbered


def _max_consecutive_run(nums: list) -> int:
    """Length of the longest consecutive integer run in a sorted list."""
    if not nums:
        return 0
    best = cur = 1
    for i in range(1, len(nums)):
        if nums[i] == nums[i - 1] + 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


class PlaceholderVariableNamingPattern(BasePattern):
    """Detect systematic placeholder variable naming in function bodies.

    Two sub-checks:
      1. High single-letter parameter count (>= 5, excluding self/cls/_)
      2. Sequential numbered variable pattern (r1,r2,r3... / x1,x2,x3...)
    """

    id = "placeholder_variable_naming"
    severity = Severity.HIGH
    axis = Axis.QUALITY

    def check(self, tree: ast.AST, file: Any, content: str) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                issues.extend(self._check_function(node, file))
        return issues

    def _check_function(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef], file: Any
    ) -> List[Issue]:
        found: List[Issue] = []

        all_args = (
            [a.arg for a in node.args.args]
            + [a.arg for a in node.args.posonlyargs]
            + [a.arg for a in node.args.kwonlyargs]
        )
        semantic_args = [a for a in all_args if a not in ("self", "cls", "_")]
        single_letter = [a for a in semantic_args if len(a) == 1]

        if len(single_letter) >= _PLACEHOLDER_PARAM_THRESHOLD:
            preview = ", ".join(single_letter[:8])
            found.append(
                self.create_issue_from_node(
                    node,
                    file,
                    message=(
                        f"Function '{node.name}' has {len(single_letter)} single-letter "
                        f"parameters ({preview}) -- placeholder naming pattern"
                    ),
                    suggestion=(
                        "Use semantic parameter names that describe the data they represent. "
                        "For math/science code, suppress with domain_overrides in .slopconfig.yaml."
                    ),
                )
            )

        numbered = _collect_numbered_vars(node)

        for prefix, nums in numbered.items():
            run = _max_consecutive_run(sorted(set(nums)))
            if run < _NUMBERED_SEQ_MED:
                continue
            sev = Severity.HIGH if run >= _NUMBERED_SEQ_HIGH else Severity.MEDIUM
            found.append(
                self.create_issue(
                    file=file,
                    line=getattr(node, "lineno", 0),
                    column=getattr(node, "col_offset", 0),
                    message=(
                        f"Function '{node.name}' uses {run} sequential numbered variables "
                        f"({prefix}1..{prefix}{run}) -- placeholder naming pattern"
                    ),
                    suggestion=(
                        "Use descriptive variable names instead of numbered sequences. "
                        "Consider a list or dict if you need indexed values."
                    ),
                    severity_override=sev,
                )
            )
            break

        return found
