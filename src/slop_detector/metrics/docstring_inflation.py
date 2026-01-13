"""Docstring Inflation Detector - Detects excessive documentation relative to implementation."""

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TypeAlias, Union, cast

DocstringNode: TypeAlias = Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]


@dataclass
class DocstringInflationDetail:
    """Details about a single inflated docstring."""

    name: str  # Function/class/module name
    type: str  # "function", "class", "module"
    line: int  # Line number
    docstring_lines: int  # Lines in docstring
    implementation_lines: int  # Actual code lines
    inflation_ratio: float  # docstring_lines / implementation_lines
    severity: str  # "critical", "warning", "info"
    docstring_preview: str  # First 100 chars of docstring

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "line": self.line,
            "docstring_lines": self.docstring_lines,
            "implementation_lines": self.implementation_lines,
            "inflation_ratio": self.inflation_ratio,
            "severity": self.severity,
            "docstring_preview": self.docstring_preview,
        }


@dataclass
class DocstringInflationResult:
    """Result of docstring inflation analysis."""

    total_docstrings: int
    inflated_count: int
    avg_inflation_ratio: float
    max_inflation_ratio: float
    total_docstring_lines: int
    total_implementation_lines: int
    overall_ratio: float
    status: str  # "PASS", "WARNING", "FAIL"
    details: List[DocstringInflationDetail] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_docstrings": self.total_docstrings,
            "inflated_count": self.inflated_count,
            "avg_inflation_ratio": self.avg_inflation_ratio,
            "max_inflation_ratio": self.max_inflation_ratio,
            "total_docstring_lines": self.total_docstring_lines,
            "total_implementation_lines": self.total_implementation_lines,
            "overall_ratio": self.overall_ratio,
            "status": self.status,
            "details": [d.to_dict() for d in self.details],
        }


class DocstringInflationDetector:
    """Detects when docstrings are disproportionately long compared to implementation."""

    # Thresholds for individual functions/classes
    CRITICAL_RATIO = 2.0  # Docstring 2x longer than implementation
    WARNING_RATIO = 1.0  # Docstring longer than implementation
    INFO_RATIO = 0.5  # Substantial docstring

    # Thresholds for overall file
    FILE_CRITICAL_RATIO = 1.5
    FILE_WARNING_RATIO = 0.8

    def __init__(self, config):
        """Initialize with config."""
        self.config = config

    def analyze(self, file_path: str, content: str, tree: ast.AST) -> DocstringInflationResult:
        """Analyze docstring inflation in a file."""
        details = []
        total_docstring_lines = 0
        total_implementation_lines = 0

        # Check module docstring
        module = cast(ast.Module, tree)
        module_doc = ast.get_docstring(module)
        if module_doc:
            module_doc_lines = len(module_doc.splitlines())
            module_impl_lines = self._count_module_implementation_lines(module, content)
            total_docstring_lines += module_doc_lines
            total_implementation_lines += module_impl_lines

            if module_impl_lines > 0:
                ratio = module_doc_lines / module_impl_lines
                if ratio >= self.INFO_RATIO:
                    details.append(
                        DocstringInflationDetail(
                            name="<module>",
                            type="module",
                            line=1,
                            docstring_lines=module_doc_lines,
                            implementation_lines=module_impl_lines,
                            inflation_ratio=ratio,
                            severity=self._get_severity(ratio),
                            docstring_preview=module_doc[:100].replace("\n", " "),
                        )
                    )

        # Check functions and classes
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                detail = self._analyze_node(node, content)
                if detail:
                    details.append(detail)
                    total_docstring_lines += detail.docstring_lines
                    total_implementation_lines += detail.implementation_lines

        # Calculate overall metrics
        total_docstrings = len(details)
        inflated_count = sum(1 for d in details if d.severity in ("critical", "warning"))

        if total_docstrings > 0:
            avg_inflation_ratio = sum(d.inflation_ratio for d in details) / total_docstrings
            max_inflation_ratio = max(d.inflation_ratio for d in details)
        else:
            avg_inflation_ratio = 0.0
            max_inflation_ratio = 0.0

        overall_ratio = (
            total_docstring_lines / total_implementation_lines
            if total_implementation_lines > 0
            else 0.0
        )

        # Determine overall status
        status = self._get_file_status(overall_ratio, inflated_count, total_docstrings)

        return DocstringInflationResult(
            total_docstrings=total_docstrings,
            inflated_count=inflated_count,
            avg_inflation_ratio=avg_inflation_ratio,
            max_inflation_ratio=max_inflation_ratio,
            total_docstring_lines=total_docstring_lines,
            total_implementation_lines=total_implementation_lines,
            overall_ratio=overall_ratio,
            status=status,
            details=sorted(details, key=lambda d: d.inflation_ratio, reverse=True)[:10],
        )

    def _analyze_node(
        self, node: DocstringNode, content: str
    ) -> Optional[DocstringInflationDetail]:
        """Analyze a function or class for docstring inflation."""
        docstring = ast.get_docstring(node)
        if not docstring:
            return None

        docstring_lines = len(docstring.splitlines())

        # Count implementation lines (excluding docstring)
        impl_lines = self._count_implementation_lines(node, docstring)

        if impl_lines == 0:
            # Special case: interface-only (handled by placeholder patterns)
            return None

        ratio = docstring_lines / impl_lines

        # Only report if ratio is significant
        if ratio < self.INFO_RATIO:
            return None

        name = node.name
        node_type = "class" if isinstance(node, ast.ClassDef) else "function"

        return DocstringInflationDetail(
            name=name,
            type=node_type,
            line=node.lineno,
            docstring_lines=docstring_lines,
            implementation_lines=impl_lines,
            inflation_ratio=ratio,
            severity=self._get_severity(ratio),
            docstring_preview=docstring[:100].replace("\n", " "),
        )

    def _count_implementation_lines(self, node: DocstringNode, docstring: str) -> int:
        """Count actual implementation lines (excluding docstring and empty lines)."""
        # For functions/classes, count non-trivial body lines
        body = node.body if hasattr(node, "body") else []

        # Identify docstring node (it's always the first statement if present)
        docstring_node = None
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstring_node = body[0]

        impl_lines = 0
        for item in body:
            # Skip the docstring node
            if item is docstring_node:
                continue

            # Count this as an implementation line
            # For multi-line statements, count end_lineno - lineno + 1
            if hasattr(item, "end_lineno") and hasattr(item, "lineno"):
                impl_lines += item.end_lineno - item.lineno + 1
            else:
                impl_lines += 1

        # If class, subtract lines from nested docstrings (count only direct implementation)
        if isinstance(node, ast.ClassDef):
            for item in body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested_doc = ast.get_docstring(item)
                    if nested_doc:
                        impl_lines -= len(nested_doc.splitlines())

        return max(impl_lines, 1)  # At least 1 to avoid division by zero

    def _count_module_implementation_lines(self, tree: ast.Module, content: str) -> int:
        """Count module-level implementation lines."""
        lines = content.splitlines()
        total_lines = len(lines)

        # Count docstring lines to subtract
        module_doc = ast.get_docstring(tree)
        docstring_lines = len(module_doc.splitlines()) if module_doc else 0

        # Subtract import lines, empty lines, comments
        import_lines = 0
        empty_lines = 0
        comment_lines = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                empty_lines += 1
            elif stripped.startswith("#"):
                comment_lines += 1
            elif stripped.startswith(("import ", "from ")):
                import_lines += 1

        impl_lines = total_lines - docstring_lines - import_lines - empty_lines - comment_lines

        return max(impl_lines, 1)

    def _get_severity(self, ratio: float) -> str:
        """Determine severity based on ratio."""
        if ratio >= self.CRITICAL_RATIO:
            return "critical"
        elif ratio >= self.WARNING_RATIO:
            return "warning"
        else:
            return "info"

    def _get_file_status(self, overall_ratio: float, inflated_count: int, total_count: int) -> str:
        """Determine overall file status."""
        if overall_ratio >= self.FILE_CRITICAL_RATIO:
            return "FAIL"
        elif overall_ratio >= self.FILE_WARNING_RATIO:
            return "WARNING"
        elif inflated_count > 0 and (inflated_count / total_count) > 0.3:
            # More than 30% of docstrings are inflated
            return "WARNING"
        else:
            return "PASS"
