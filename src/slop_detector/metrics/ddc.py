"""Deep Dependency Check (DDC) calculator with type hint awareness."""

from __future__ import annotations

import ast
from typing import Set

from slop_detector.models import DDCResult

# Modules that exist purely for type annotations and are never referenced at
# runtime (with PEP-563 `from __future__ import annotations` in effect all
# annotations are lazily evaluated strings, so their imports are invisible to
# a runtime usage scan).  Treating these like TYPE_CHECKING-guarded imports
# eliminates a systematic false-positive in the DDC usage ratio.
_ANNOTATION_ONLY_MODULES: frozenset[str] = frozenset(
    {
        "__future__",  # from __future__ import annotations
        "typing",  # Optional, Dict, List, Tuple, Any, Union, ...
        "typing_extensions",  # Annotated, Protocol, TypeAlias, ...
    }
)


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
        """Calculate DDC with type hint, noqa, __all__, and TYPE_CHECKING awareness."""
        # Collect imports (alias -> library)
        imports_map, type_checking_imports = self._collect_imports(tree, content)

        # noqa: F401 imports — treat as intentional re-exports, never flag unused
        noqa_libs = self._collect_noqa_imports(content, imports_map)
        type_checking_imports |= noqa_libs

        # __all__ members — if imported name is re-exported via __all__, treat as used
        all_exported = self._collect_all_members(tree, imports_map)
        type_checking_imports |= all_exported

        # All imported libraries
        all_imported_libs = set(imports_map.values())

        # Collect actual usage + annotation-only usage
        used_names, annotation_names = self._collect_usage(tree)

        # Annotation-only libs: imported and used only in type hints
        annotation_only_libs: Set[str] = set()
        for name in annotation_names:
            if name in imports_map:
                lib = imports_map[name]
                # Only exclude if NOT also used at runtime
                if lib not in {imports_map.get(n) for n in used_names}:
                    annotation_only_libs.add(lib)

        # Determine actually used libraries based on used aliases
        actually_used = set()
        for name in used_names:
            if name in imports_map:
                actually_used.add(imports_map[name])

        # Calculate metrics
        actually_used_list = sorted(list(actually_used))
        excluded = type_checking_imports | annotation_only_libs
        unused = sorted(all_imported_libs - set(actually_used_list) - excluded)
        fake_imports = sorted(self.HEAVYWEIGHT_LIBS & all_imported_libs - set(actually_used_list))

        # usage_ratio: fraction of runtime-expected imports that are actually used.
        # Imports that are excluded (type-checking / annotation-only / noqa / __all__)
        # are excluded from BOTH numerator and denominator — they are not "unused",
        # they are simply not expected to have a runtime footprint.
        runtime_imports = all_imported_libs - excluded
        total_runtime = len(runtime_imports)
        usage_ratio = len(actually_used) / total_runtime if total_runtime > 0 else 1.0

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
            actually_used=actually_used_list,
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
                    if lib in _ANNOTATION_ONLY_MODULES:
                        type_checking_imports.add(lib)
                        continue
                    name_to_use = alias.asname or alias.name.split(".")[0]

                    if lib not in type_checking_imports:
                        imports_map[name_to_use] = lib

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    lib = node.module.split(".")[0]
                    if lib in _ANNOTATION_ONLY_MODULES:
                        type_checking_imports.add(lib)
                    else:
                        for alias in node.names:
                            name_to_use = alias.asname or alias.name
                            if lib not in type_checking_imports:
                                imports_map[name_to_use] = lib

        return imports_map, type_checking_imports

    @staticmethod
    def _collect_noqa_imports(content: str, imports_map: dict[str, str]) -> Set[str]:
        """Return libs whose import line has '# noqa: F401' — treated as intentional re-exports."""
        noqa_libs: Set[str] = set()
        name_to_lib = {alias: lib for alias, lib in imports_map.items()}
        for line in content.splitlines():
            if "# noqa" not in line or "F401" not in line:
                continue
            # extract imported name(s) from the line
            stripped = line.split("#")[0].strip()
            if stripped.startswith("from ") and " import " in stripped:
                # from module import X, Y  # noqa: F401
                names_part = stripped.split(" import ", 1)[1]
                for part in names_part.split(","):
                    name = part.strip().split(" as ")[-1].strip()
                    if name in name_to_lib:
                        noqa_libs.add(name_to_lib[name])
            elif stripped.startswith("import "):
                # import X  # noqa: F401
                name = stripped[len("import ") :].strip().split(" as ")[-1].strip()
                lib = name.split(".")[0]
                if lib in imports_map.values():
                    noqa_libs.add(lib)
        return noqa_libs

    @staticmethod
    def _collect_all_members(tree: ast.AST, imports_map: dict[str, str]) -> Set[str]:
        """Return libs whose alias is listed in __all__ — treated as used (re-exported)."""
        all_names: Set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_names.add(elt.value)
        return {imports_map[n] for n in all_names if n in imports_map}

    def _collect_usage(self, tree: ast.AST) -> tuple[Set[str], Set[str]]:
        """Collect actual library usage and annotation-only usage.

        Returns:
            (used, annotation_used) — names used at runtime vs only in annotations.
        """
        visitor = UsageCollector()
        visitor.visit(tree)
        return visitor.used, visitor.annotation_used


class UsageCollector(ast.NodeVisitor):
    """Visitor to collect name usage excluding type annotations."""

    def __init__(self):
        self.used = set()
        self.annotation_used: Set[str] = set()  # names used only in annotations
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

    def visit_AsyncFunctionDef(self, node):  # noqa: N815
        """Visit async function definition (same as regular function)."""
        return self.visit_FunctionDef(node)

    def visit_AnnAssign(self, node):
        # Skip annotation, visit value only
        old_annotation = self.in_annotation
        self.in_annotation = True
        self.visit(node.annotation)
        self.in_annotation = old_annotation

        if node.value:
            self.visit(node.value)

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Load, ast.Store)):
            if self.in_annotation:
                self.annotation_used.add(node.id)
            else:
                self.used.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name):
            if self.in_annotation:
                self.annotation_used.add(node.value.id)
            else:
                self.used.add(node.value.id)
        self.generic_visit(node)

    def visit_Call(self, node):
        # Always count function calls as usage
        if isinstance(node.func, ast.Name):
            self.used.add(node.func.id)
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            self.used.add(node.func.value.id)
        self.generic_visit(node)
