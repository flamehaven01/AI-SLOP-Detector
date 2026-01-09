"""
Python Language Analyzer
Implementation of LanguageAnalyzer for Python
"""

import ast
import re
from typing import List, Dict, Set, Tuple

from .base import LanguageAnalyzer, FunctionMetrics, CodeIssue, SeverityLevel, AnalysisResult


class PythonAnalyzer(LanguageAnalyzer):
    """Analyzer for Python source code using AST"""

    def analyze(self, file_path: str) -> AnalysisResult:
        """Analyze a Python file"""
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        # Parse AST
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            # Handle syntax errors gracefully
            return self._create_error_result(file_path, f"Syntax Error: {str(e)}")

        # Collect metrics
        line_counts = self._count_lines(file_path)
        functions = self._extract_functions(
            file_path
        )  # Pass file path, re-read content or optimize?
        # Optimization: _extract_functions should accept tree/content if possible.
        # But base class signature says file_path. We'll stick to signature.

        complexity = self._calculate_complexity(file_path)
        unused_imports = self._detect_unused_imports(file_path)

        # Calculate derived scores
        empty_funcs = sum(1 for f in functions if f.is_empty)
        total_funcs = len(functions)

        ldr = self._calculate_logic_density(line_counts["code"], empty_funcs, total_funcs)
        inflation = self._calculate_inflation_ratio(file_path, complexity["average"])

        # Imports analysis
        total_imports = self._count_imports(tree)
        ddc = self._calculate_dependency_score(total_imports, len(unused_imports))

        deficit_score = self._calculate_deficit_score(ldr, inflation, ddc)
        grade = self._assign_grade(deficit_score)

        issues = self._detect_issues(functions, unused_imports)

        return AnalysisResult(
            file_path=file_path,
            language="Python",
            total_lines=line_counts["total"],
            code_lines=line_counts["code"],
            comment_lines=line_counts["comment"],
            blank_lines=line_counts["blank"],
            functions=functions,
            classes_count=self._count_classes(tree),
            imports_count=total_imports,
            unused_imports=unused_imports,
            avg_complexity=complexity["average"],
            max_complexity=complexity["maximum"],
            logic_density=ldr,
            inflation_ratio=inflation,
            dependency_score=ddc,
            deficit_score=deficit_score,
            grade=grade,
            issues=issues,
        )

    def _count_lines(self, file_path: str) -> Dict[str, int]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        total = len(lines)
        blank = 0
        comment = 0
        code = 0

        for line in lines:
            line = line.strip()
            if not line:
                blank += 1
            elif line.startswith("#"):
                comment += 1
            else:
                code += 1

        return {"total": total, "blank": blank, "comment": comment, "code": code}

    def _extract_functions(self, file_path: str) -> List[FunctionMetrics]:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        metrics = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                metrics.append(self._analyze_function(node))
        return metrics

    def _analyze_function(self, node: ast.AST) -> FunctionMetrics:
        # Simple complexity calculation (Cognitive-like)
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1

        # Check empty
        is_empty = False
        body_stmts = [n for n in node.body if not isinstance(n, (ast.Expr, ast.Pass))]
        if not body_stmts:
            # Check if only pass or docstring
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                is_empty = True
            elif len(node.body) == 1 and isinstance(node.body[0], ast.Expr):
                # Docstring only
                is_empty = True
            elif not node.body:
                is_empty = True

        return FunctionMetrics(
            name=node.name,
            start_line=node.lineno,
            end_line=node.end_lineno if hasattr(node, "end_lineno") else node.lineno,
            lines_of_code=(node.end_lineno - node.lineno + 1) if hasattr(node, "end_lineno") else 1,
            cyclomatic_complexity=complexity,
            cognitive_complexity=complexity,  # Placeholder
            parameters_count=len(node.args.args),
            is_empty=is_empty,
            has_docstring=ast.get_docstring(node) is not None,
        )

    def _calculate_complexity(self, file_path: str) -> Dict[str, float]:
        functions = self._extract_functions(file_path)
        if not functions:
            return {"average": 0.0, "maximum": 0}

        complexities = [f.cyclomatic_complexity for f in functions]
        return {"average": sum(complexities) / len(complexities), "maximum": max(complexities)}

    def _detect_unused_imports(self, file_path: str) -> Set[str]:
        # Basic implementation
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return set()

        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    imported.add(n.asname or n.name)
            elif isinstance(node, ast.ImportFrom):
                for n in node.names:
                    imported.add(n.asname or n.name)

        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)

        return imported - used

    def _count_imports(self, tree: ast.AST) -> int:
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                count += 1
        return count

    def _count_classes(self, tree: ast.AST) -> int:
        return sum(1 for node in ast.walk(tree) if isinstance(node, ast.ClassDef))

    def _get_jargon(self) -> Set[str]:
        return {
            "ai",
            "ml",
            "blockchain",
            "quantum",
            "neural",
            "deep",
            "learning",
            "autonomous",
            "agentic",
            "synergy",
            "paradigm",
            "crypto",
            "hyper",
            "scale",
            "leverage",
            "robust",
        }

    def _get_empty_patterns(self) -> List[str]:
        return [r"^\s*pass\s*$", r"^\s*\.\.\.\s*$"]

    def _create_error_result(self, file_path: str, error_msg: str) -> AnalysisResult:
        # Return a zeroed result with error issue
        return AnalysisResult(
            file_path=file_path,
            language="Python",
            total_lines=0,
            code_lines=0,
            comment_lines=0,
            blank_lines=0,
            functions=[],
            classes_count=0,
            imports_count=0,
            unused_imports=set(),
            avg_complexity=0.0,
            max_complexity=0,
            logic_density=0.0,
            inflation_ratio=0.0,
            dependency_score=0.0,
            deficit_score=100.0,
            grade="F",
            issues=[CodeIssue(0, SeverityLevel.BLOCKER, "syntax_error", error_msg)],
        )
