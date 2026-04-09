"""Logic Density Ratio (LDR) calculator with improved accuracy."""

from __future__ import annotations

import ast
import re

from slop_detector.models import LDRResult


class LDRCalculator:
    """Calculate Logic Density Ratio with smart exception handling."""

    EMPTY_PATTERNS = [
        r"^\s*pass\s*$",
        r"^\s*\.\.\.\s*$",
        r"^\s*raise\s+NotImplementedError",
        r"^\s*#\s*" + "TODO",
        r"^\s*#\s*implementation\s+details",
        r"^\s*#\s*placeholder",
        r"^\s*#\s*" + "FIXME",
    ]

    def __init__(self, config):
        """Initialize with config."""
        self.config = config
        self.compiled_patterns = [re.compile(p) for p in self.EMPTY_PATTERNS]

    def calculate(self, file_path: str, content: str, tree: ast.AST) -> LDRResult:
        """Calculate LDR with improved empty function detection."""
        # P1: Empty __init__.py is a Python packaging convention, not slop.
        # Return perfect LDR so GQG is not penalised by ln(0).
        from pathlib import Path as _Path

        if _Path(file_path).name == "__init__.py":
            non_empty = [
                ln for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("#")
            ]
            if len(non_empty) == 0:
                return LDRResult(
                    total_lines=0,
                    logic_lines=0,
                    empty_lines=0,
                    ldr_score=1.0,
                    grade="N/A",
                    is_packaging_init=True,
                )

        # Check for special file types
        is_abc_interface = self._is_abc_interface(content, tree)
        is_type_stub = file_path.endswith(".pyi")

        # Identify lines belonging to truly empty functions
        empty_func_lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_truly_empty_function(node):
                    if (
                        hasattr(node, "lineno")
                        and hasattr(node, "end_lineno")
                        and node.end_lineno is not None
                    ):
                        empty_func_lines.update(range(node.lineno, node.end_lineno + 1))

        total_lines = 0
        logic_lines = 0

        # Use enumerate to get 1-based line numbers matching AST
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Skip completely empty lines and comment-only lines
            if not stripped or stripped.startswith("#"):
                continue

            total_lines += 1

            # Check if it's an empty pattern OR inside an empty function
            is_empty_pattern = any(pattern.match(stripped) for pattern in self.compiled_patterns)
            is_inside_empty_func = i in empty_func_lines

            if is_empty_pattern or is_inside_empty_func:
                # Count as empty line (do not increment logic_lines)
                pass
            else:
                logic_lines += 1

        empty_lines = total_lines - logic_lines
        ldr_score = logic_lines / total_lines if total_lines > 0 else 0.0

        # Apply penalty reduction for ABC interfaces
        if (is_abc_interface or is_type_stub) and self.config.is_abc_exception_enabled():
            penalty_reduction = self.config.get("exceptions.abc_interface.penalty_reduction", 0.5)
            adjusted_logic_lines = logic_lines + (empty_lines * penalty_reduction)
            ldr_score = adjusted_logic_lines / total_lines if total_lines > 0 else 0.0

        # Determine grade
        thresholds = self.config.get_ldr_thresholds()
        grade = "F"
        for grade_name, threshold in sorted(thresholds.items(), key=lambda x: -x[1]):
            if ldr_score >= threshold:
                grade = grade_name
                break

        return LDRResult(
            total_lines=total_lines,
            logic_lines=logic_lines,
            empty_lines=empty_lines,
            ldr_score=ldr_score,
            grade=grade,
            is_abc_interface=is_abc_interface,
            is_type_stub=is_type_stub,
        )

    @staticmethod
    def _is_abc_base(base: ast.expr) -> bool:
        """Return True if an AST base node refers to ABC."""
        if isinstance(base, ast.Attribute) and base.attr == "ABC":
            return True
        if isinstance(base, ast.Name) and base.id == "ABC":
            return True
        return False

    @staticmethod
    def _has_abstract_decorator(
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> bool:
        """Return True if the function has an @abstractmethod decorator."""
        for decorator in func_node.decorator_list:
            if isinstance(decorator, ast.Name) and decorator.id == "abstractmethod":
                return True
            if isinstance(decorator, ast.Attribute) and decorator.attr == "abstractmethod":
                return True
        return False

    def _count_abc_class_methods(self, node: ast.ClassDef) -> tuple[int, int]:
        """Count (abstract_methods, total_methods) in an ABC class body."""
        abstract_count = 0
        total_count = 0
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total_count += 1
                if self._has_abstract_decorator(item):
                    abstract_count += 1
        return abstract_count, total_count

    def _is_abc_interface(self, content: str, tree: ast.AST) -> bool:
        """Check if file is an ABC interface."""
        has_abc_import = (
            "abc.ABC" in content or "ABCMeta" in content or "from abc import" in content
        )
        if not has_abc_import:
            return False

        abstract_method_count = 0
        total_method_count = 0

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if any(self._is_abc_base(base) for base in node.bases):
                    abstract, total = self._count_abc_class_methods(node)
                    abstract_method_count += abstract
                    total_method_count += total

        # If more than 50% of methods are abstract, it's an interface
        if total_method_count > 0 and abstract_method_count / total_method_count >= 0.5:
            return True
        return False

    def _count_empty_function_lines(self, tree: ast.AST) -> int:
        """Count lines in truly empty functions (only pass/return None)."""
        empty_lines = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if self._is_truly_empty_function(node):
                    # Count lines in this function
                    if (
                        hasattr(node, "lineno")
                        and hasattr(node, "end_lineno")
                        and node.end_lineno is not None
                    ):
                        empty_lines += node.end_lineno - node.lineno + 1

        return empty_lines

    def _is_truly_empty_function(self, func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Check if function is truly empty (only pass or return None)."""
        body = [n for n in func_node.body if not isinstance(n, (ast.Pass, ast.Expr))]

        if len(body) == 0:
            return True

        if len(body) == 1:
            stmt = body[0]
            if isinstance(stmt, ast.Return):
                if stmt.value is None:
                    return True
                if isinstance(stmt.value, ast.Constant) and stmt.value.value is None:
                    return True

        return False
