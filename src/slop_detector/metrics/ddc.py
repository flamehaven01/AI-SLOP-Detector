"""Deep Dependency Check (DDC) calculator with type hint awareness."""

from __future__ import annotations

import ast
from typing import Set

from slop_detector.models import DDCResult


class DDCCalculator:
    """Calculate DDC with improved usage detection."""

    HEAVYWEIGHT_LIBS = {
        "torch",
        "tensorflow",
        "keras",
        "jax",
        "transformers",
        "sklearn",
        "scipy",
        "pandas",
        "numpy",
        "cv2",
        "PIL",
    }

    def __init__(self, config):
        """Initialize with config."""
        self.config = config

    def calculate(self, file_path: str, content: str, tree: ast.AST) -> DDCResult:
        """Calculate DDC with type hint and TYPE_CHECKING awareness."""
        # Collect imports (alias -> library)
        imports_map, type_checking_imports = self._collect_imports(tree, content)

        # All imported libraries
        all_imported_libs = set(imports_map.values())

        # Collect actual usage (excluding type hints)
        used_names = self._collect_usage(tree)

        # Determine actually used libraries based on used aliases
        actually_used = set()
        for name in used_names:
            if name in imports_map:
                actually_used.add(imports_map[name])

        # Calculate metrics
        actually_used = sorted(actually_used)
        unused = sorted(all_imported_libs - set(actually_used) - type_checking_imports)
        fake_imports = sorted(self.HEAVYWEIGHT_LIBS & all_imported_libs - set(actually_used))

        # Type checking imports are not counted as unused
        total_imports = len(all_imported_libs)

        usage_ratio = len(actually_used) / total_imports if total_imports > 0 else 1.0

        # Determine grade
        if usage_ratio >= 0.90:
            grade = "EXCELLENT"
        elif usage_ratio >= 0.70:
            grade = "GOOD"
        elif usage_ratio >= 0.50:
            grade = "ACCEPTABLE"
        else:
            grade = "SUSPICIOUS"

        return DDCResult(
            imported=sorted(list(all_imported_libs)),
            actually_used=actually_used,
            unused=unused,
            fake_imports=fake_imports,
            type_checking_imports=sorted(list(type_checking_imports)),
            usage_ratio=usage_ratio,
            grade=grade,
        )

    def _collect_imports(self, tree: ast.AST, content: str) -> tuple[dict[str, str], Set[str]]:
        """Collect imports mapping alias->lib, separating TYPE_CHECKING imports."""
        imports_map = {}
        type_checking_imports = set()

        # Check if we're inside TYPE_CHECKING block
        for node in ast.walk(tree):
            # Detect TYPE_CHECKING block
            if isinstance(node, ast.If):
                if isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
                    # Collect imports from TYPE_CHECKING block
                    for item in ast.walk(node):
                        if isinstance(item, ast.Import):
                            for alias in item.names:
                                type_checking_imports.add(alias.name.split(".")[0])
                        elif isinstance(item, ast.ImportFrom):
                            if item.module:
                                type_checking_imports.add(item.module.split(".")[0])
                    continue

            # Regular imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    lib = alias.name.split(".")[0]
                    name_to_use = alias.asname or alias.name.split(".")[0]

                    if lib not in type_checking_imports:
                        imports_map[name_to_use] = lib

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    lib = node.module.split(".")[0]
                    for alias in node.names:
                        name_to_use = alias.asname or alias.name
                        if lib not in type_checking_imports:
                            imports_map[name_to_use] = lib

        return imports_map, type_checking_imports

    def _collect_usage(self, tree: ast.AST) -> Set[str]:
        """Collect actual library usage (excluding type annotations)."""
        visitor = UsageCollector()
        visitor.visit(tree)
        return visitor.used


class UsageCollector(ast.NodeVisitor):
    """Visitor to collect name usage excluding type annotations."""

    def __init__(self):
        self.used = set()
        self.in_annotation = False

    def visit_FunctionDef(self, node):
        # Visit function body but skip annotations
        old_annotation = self.in_annotation

        # Skip return annotation
        if node.returns:
            self.in_annotation = True
            self.visit(node.returns)
            self.in_annotation = old_annotation

        # Skip argument annotations
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            if arg.annotation:
                self.in_annotation = True
                self.visit(arg.annotation)
                self.in_annotation = old_annotation

        if node.args.vararg and node.args.vararg.annotation:
            self.in_annotation = True
            self.visit(node.args.vararg.annotation)
            self.in_annotation = old_annotation

        if node.args.kwarg and node.args.kwarg.annotation:
            self.in_annotation = True
            self.visit(node.args.kwarg.annotation)
            self.in_annotation = old_annotation

        # Visit decorators and body
        for decorator in node.decorator_list:
            self.visit(decorator)
        for stmt in node.body:
            self.visit(stmt)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_AnnAssign(self, node):
        # Skip annotation, visit value only
        old_annotation = self.in_annotation
        self.in_annotation = True
        self.visit(node.annotation)
        self.in_annotation = old_annotation

        if node.value:
            self.visit(node.value)

    def visit_Name(self, node):
        if not self.in_annotation and isinstance(node.ctx, (ast.Load, ast.Store)):
            self.used.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if not self.in_annotation and isinstance(node.value, ast.Name):
            self.used.add(node.value.id)
        self.generic_visit(node)

    def visit_Call(self, node):
        # Always count function calls as usage
        if isinstance(node.func, ast.Name):
            self.used.add(node.func.id)
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            self.used.add(node.func.value.id)
        self.generic_visit(node)
