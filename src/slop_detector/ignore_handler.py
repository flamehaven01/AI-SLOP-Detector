"""Ignore-annotation handler for @slop.ignore decorated functions."""

from __future__ import annotations

import ast
from typing import List, Optional

from slop_detector.models import IgnoredFunction


class IgnoreHandler:
    """Handles collection and filtering of @slop.ignore decorated functions."""

    @staticmethod
    def collect_ignored_functions(tree: ast.AST) -> List[IgnoredFunction]:
        """Collect functions decorated with @slop.ignore.

        Detects patterns:
        - @slop.ignore(reason="...")
        - @slop_detector.decorators.ignore(reason="...")
        """
        ignored = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    ignore_info = IgnoreHandler._parse_slop_ignore_decorator(decorator)
                    if ignore_info:
                        ignored.append(
                            IgnoredFunction(
                                name=node.name,
                                reason=ignore_info["reason"],
                                rules=ignore_info["rules"],
                                lineno=node.lineno,
                            )
                        )
                        break  # Only need first match

        return ignored

    @staticmethod
    def _parse_slop_ignore_decorator(decorator: ast.expr) -> Optional[dict]:
        """Parse @slop.ignore decorator and extract reason/rules.

        Returns None if not a slop.ignore decorator.
        """
        if isinstance(decorator, ast.Call):
            func = decorator.func

            is_slop_ignore = False

            if isinstance(func, ast.Attribute):
                # @slop.ignore(...)
                if func.attr == "ignore" and isinstance(func.value, ast.Name):
                    if func.value.id in ("slop", "slop_detector"):
                        is_slop_ignore = True
            elif isinstance(func, ast.Name):
                # @ignore(...) - direct import
                if func.id == "ignore":
                    is_slop_ignore = True

            if is_slop_ignore:
                reason = ""
                rules = []

                for keyword in decorator.keywords:
                    if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
                        reason = str(keyword.value.value)
                    elif keyword.arg == "rules" and isinstance(keyword.value, ast.List):
                        rules = [
                            elt.value for elt in keyword.value.elts if isinstance(elt, ast.Constant)
                        ]

                if reason:  # reason is required
                    return {"reason": reason, "rules": rules}

        return None

    @staticmethod
    def get_ignored_line_ranges(
        tree: ast.AST, ignored_functions: List[IgnoredFunction]
    ) -> List[tuple]:
        """Get line ranges for ignored functions.

        Returns list of (start_line, end_line) tuples.
        """
        ranges = []
        ignored_names = {f.name for f in ignored_functions}

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in ignored_names:
                    end_line = node.end_lineno if hasattr(node, "end_lineno") else node.lineno
                    ranges.append((node.lineno, end_line))

        return ranges

    @staticmethod
    def is_line_in_ignored_range(line: int, ranges: List[tuple]) -> bool:
        """Check if a line number is within any ignored range."""
        for start, end in ranges:
            if start <= line <= end:
                return True
        return False
