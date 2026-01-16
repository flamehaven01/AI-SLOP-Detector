"""Core SLOP detector with improved architecture."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from typing import List, Optional

from slop_detector.config import Config
from slop_detector.metrics import DDCCalculator, InflationCalculator, LDRCalculator
from slop_detector.metrics.context_jargon import ContextJargonDetector
from slop_detector.metrics.docstring_inflation import DocstringInflationDetector
from slop_detector.metrics.hallucination_deps import HallucinationDepsDetector
from slop_detector.models import FileAnalysis, IgnoredFunction, ProjectAnalysis, SlopStatus
from slop_detector.patterns import get_all_patterns
from slop_detector.patterns.base import Issue
from slop_detector.patterns.registry import PatternRegistry

logger = logging.getLogger(__name__)


class SlopDetector:
    """Main SLOP detection engine with v2.1 pattern support."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize detector with config."""
        self.config = Config(config_path)
        self.ldr_calc = LDRCalculator(self.config)
        self.inflation_calc = InflationCalculator(self.config)
        self.ddc_calc = DDCCalculator(self.config)
        self.docstring_inflation_detector = DocstringInflationDetector(self.config)  # v2.2
        self.hallucination_deps_detector = HallucinationDepsDetector(self.config)  # v2.2
        self.context_jargon_detector = ContextJargonDetector(self.config)  # v2.2

        # v2.1: Initialize pattern registry
        self.pattern_registry = PatternRegistry()
        self.pattern_registry.register_all(get_all_patterns())

        # Disable patterns from config
        disabled = self.config.get("patterns.disabled", [])
        for pattern_id in disabled:
            self.pattern_registry.disable(pattern_id)

    def analyze_file(self, file_path: str) -> FileAnalysis:
        """
        Analyze a single Python file.

        Improvements in v2.1:
        - Pattern-based detection alongside metrics
        - Hybrid scoring (metrics + patterns)
        """
        file_path = str(Path(file_path).resolve())
        logger.info(f"Analyzing: {file_path}")

        # Read file once
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            raise

        # Parse AST once
        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
            # Return minimal analysis
            return self._create_error_analysis(file_path, str(e))

        # Calculate all metrics (using shared content and tree)
        ldr = self.ldr_calc.calculate(file_path, content, tree)
        inflation = self.inflation_calc.calculate(file_path, content, tree)
        ddc = self.ddc_calc.calculate(file_path, content, tree)

        # v2.2: Analyze docstring inflation
        docstring_inflation = self.docstring_inflation_detector.analyze(file_path, content, tree)

        # v2.2: Analyze hallucination dependencies
        hallucination_deps = self.hallucination_deps_detector.analyze(file_path, content, tree, ddc)

        # v2.2: Analyze context-based jargon
        context_jargon = self.context_jargon_detector.analyze(file_path, content, tree, inflation)

        # v2.6.3: Collect @slop.ignore decorated functions
        ignored_functions = self._collect_ignored_functions(tree)

        # v2.1: Run pattern detection (v2.6.3: filters ignored functions)
        pattern_issues = self._run_patterns(tree, Path(file_path), content, ignored_functions)

        # Determine slop status (now includes pattern issues)
        slop_score, slop_status, warnings = self._calculate_slop_status(
            ldr, inflation, ddc, pattern_issues
        )

        return FileAnalysis(
            file_path=file_path,
            ldr=ldr,
            inflation=inflation,
            ddc=ddc,
            deficit_score=slop_score,
            status=slop_status,
            warnings=warnings,
            pattern_issues=pattern_issues,  # v2.1
            docstring_inflation=docstring_inflation,  # v2.2
            hallucination_deps=hallucination_deps,  # v2.2
            context_jargon=context_jargon,  # v2.2
            ignored_functions=ignored_functions,  # v2.6.3
        )

    def analyze_project(self, project_path: str, pattern: str = "**/*.py") -> ProjectAnalysis:
        """
        Analyze entire project with weighted scoring.

        v2.0 improvements:
        - Weighted by file size (LOC)
        - Respects ignore patterns
        - Parallel-ready architecture
        """
        project_path_obj = Path(project_path)
        ignore_patterns = self.config.get_ignore_patterns()

        # Find Python files
        python_files = []
        for file_path in project_path_obj.glob(pattern):
            # Check ignore patterns
            if self._should_ignore(file_path, ignore_patterns):
                continue
            python_files.append(file_path)

        logger.info(f"Found {len(python_files)} Python files in {project_path}")

        # Analyze files
        results: List[FileAnalysis] = []
        for file_path in python_files:
            try:
                result = self.analyze_file(str(file_path))
                results.append(result)
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")

        if not results:
            logger.warning("No files analyzed")
            return self._create_empty_project_analysis(str(project_path))

        # Calculate aggregated metrics
        total_files = len(results)
        slop_files = sum(1 for r in results if r.status != SlopStatus.CLEAN)
        clean_files = total_files - slop_files

        # Simple average
        avg_deficit_score = sum(r.deficit_score for r in results) / total_files
        avg_ldr = sum(r.ldr.ldr_score for r in results) / total_files
        avg_inflation = sum(
            r.inflation.inflation_score
            for r in results
            if r.inflation.inflation_score != float("inf")
        ) / max(1, sum(1 for r in results if r.inflation.inflation_score != float("inf")))
        avg_ddc = sum(r.ddc.usage_ratio for r in results) / total_files

        # Weighted average (by LOC)
        if self.config.use_weighted_analysis():
            total_loc = sum(r.ldr.total_lines for r in results)
            weighted_deficit_score = (
                sum(r.deficit_score * (r.ldr.total_lines / total_loc) for r in results)
                if total_loc > 0
                else avg_deficit_score
            )
        else:
            weighted_deficit_score = avg_deficit_score

        # Determine overall status
        if weighted_deficit_score >= 50:
            overall_status = SlopStatus.CRITICAL_DEFICIT
        elif weighted_deficit_score >= 30:
            overall_status = SlopStatus.SUSPICIOUS
        else:
            overall_status = SlopStatus.CLEAN

        return ProjectAnalysis(
            project_path=str(project_path),
            total_files=total_files,
            deficit_files=slop_files,
            clean_files=clean_files,
            avg_deficit_score=avg_deficit_score,
            weighted_deficit_score=weighted_deficit_score,
            avg_ldr=avg_ldr,
            avg_inflation=avg_inflation,
            avg_ddc=avg_ddc,
            overall_status=overall_status,
            file_results=results,
        )

    def _run_patterns(
        self,
        tree: ast.AST,
        file: Path,
        content: str,
        ignored_functions: Optional[List[IgnoredFunction]] = None,
    ) -> List[Issue]:
        """
        Run all enabled patterns on the file.

        v2.1: New pattern-based detection.
        v2.6.3: Filters issues from @slop.ignore decorated functions.
        """
        issues = []
        ignored_functions = ignored_functions or []
        ignored_ranges = self._get_ignored_line_ranges(tree, ignored_functions)

        for pattern in self.pattern_registry.get_all():
            try:
                pattern_issues = pattern.check(tree, file, content)
                # v2.6.3: Filter issues in ignored functions
                for issue in pattern_issues:
                    if not self._is_line_in_ignored_range(issue.line, ignored_ranges):
                        issues.append(issue)
            except Exception as e:
                logger.warning(f"Pattern {pattern.id} failed: {e}")

        return issues

    def _collect_ignored_functions(self, tree: ast.AST) -> List[IgnoredFunction]:
        """
        Collect functions decorated with @slop.ignore.

        v2.6.3: Consent-based complexity feature.

        Detects patterns:
        - @slop.ignore(reason="...")
        - @slop_detector.decorators.ignore(reason="...")
        """
        ignored = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    ignore_info = self._parse_slop_ignore_decorator(decorator)
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

    def _parse_slop_ignore_decorator(self, decorator: ast.expr) -> Optional[dict]:
        """
        Parse @slop.ignore decorator and extract reason/rules.

        Returns None if not a slop.ignore decorator.
        """
        # Handle @slop.ignore(reason="...") pattern
        if isinstance(decorator, ast.Call):
            func = decorator.func

            # Check for slop.ignore or ignore pattern
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

                # Extract arguments
                for keyword in decorator.keywords:
                    if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
                        reason = str(keyword.value.value)
                    elif keyword.arg == "rules" and isinstance(keyword.value, ast.List):
                        rules = [
                            elt.value
                            for elt in keyword.value.elts
                            if isinstance(elt, ast.Constant)
                        ]

                if reason:  # reason is required
                    return {"reason": reason, "rules": rules}

        return None

    def _get_ignored_line_ranges(
        self, tree: ast.AST, ignored_functions: List[IgnoredFunction]
    ) -> List[tuple]:
        """
        Get line ranges for ignored functions.

        Returns list of (start_line, end_line) tuples.
        """
        ranges = []
        ignored_names = {f.name for f in ignored_functions}

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in ignored_names:
                    # Get end line (last line of function)
                    end_line = node.end_lineno if hasattr(node, "end_lineno") else node.lineno
                    ranges.append((node.lineno, end_line))

        return ranges

    def _is_line_in_ignored_range(self, line: int, ranges: List[tuple]) -> bool:
        """Check if a line number is within any ignored range."""
        for start, end in ranges:
            if start <= line <= end:
                return True
        return False

    def _calculate_slop_status(
        self, ldr, inflation, ddc, pattern_issues: Optional[List[Issue]] = None
    ) -> tuple[float, SlopStatus, List[str]]:
        """
        Calculate slop score using weighted formula + pattern penalties.

        v2.1: Includes pattern-based scoring.
        """
        warnings = []
        pattern_issues = pattern_issues or []

        # Get weights from config
        weights = self.config.get_weights()

        # Normalize Inflation (cap at 2.0, treat inf as 2.0)
        inflation_normalized = (
            min(inflation.inflation_score, 2.0) / 2.0
            if inflation.inflation_score != float("inf")
            else 1.0
        )

        # Calculate base quality factor (0.0 = bad, 1.0 = good)
        base_quality = (
            ldr.ldr_score * weights["ldr"]
            + (1 - inflation_normalized) * weights["inflation"]
            + ddc.usage_ratio * weights["ddc"]
        )

        # Base deficit score from metrics
        base_deficit_score = 100 * (1 - base_quality)

        # v2.1: Add pattern penalties
        pattern_penalty = self._calculate_pattern_penalty(pattern_issues)

        # Final deficit score (capped at 100)
        deficit_score = min(base_deficit_score + pattern_penalty, 100.0)

        # Generate warnings
        if ldr.ldr_score < 0.30:
            warnings.append(f"CRITICAL: Logic density only {ldr.ldr_score:.2%}")
        elif ldr.ldr_score < 0.60:
            warnings.append(f"WARNING: Low logic density {ldr.ldr_score:.2%}")

        if inflation.inflation_score > 1.0:
            warnings.append(f"CRITICAL: Inflation ratio {inflation.inflation_score:.2f}")
        elif inflation.inflation_score > 0.5:
            warnings.append(f"WARNING: High inflation ratio {inflation.inflation_score:.2f}")

        if ddc.usage_ratio < 0.50:
            warnings.append(f"CRITICAL: Only {ddc.usage_ratio:.2%} of imports used")
        elif ddc.usage_ratio < 0.70:
            warnings.append(f"WARNING: Low import usage {ddc.usage_ratio:.2%}")

        if ddc.fake_imports:
            warnings.append(f"FAKE IMPORTS: {', '.join(ddc.fake_imports)}")

        # v2.1: Add pattern warnings
        critical_patterns = [i for i in pattern_issues if i.severity.value == "critical"]
        high_patterns = [i for i in pattern_issues if i.severity.value == "high"]

        if critical_patterns:
            warnings.append(f"PATTERNS: {len(critical_patterns)} critical issues found")
        if high_patterns:
            warnings.append(f"PATTERNS: {len(high_patterns)} high-severity issues found")

        # Determine status
        if deficit_score >= 70:
            status = SlopStatus.CRITICAL_DEFICIT
        elif len(critical_patterns) >= 3:  # v2.1: Multiple critical patterns
            status = SlopStatus.CRITICAL_DEFICIT
        elif inflation.inflation_score > 1.0:
            status = SlopStatus.INFLATED_SIGNAL
        elif ddc.usage_ratio < 0.50:
            status = SlopStatus.DEPENDENCY_NOISE
        elif deficit_score >= 30:
            status = SlopStatus.SUSPICIOUS
        else:
            status = SlopStatus.CLEAN

        return deficit_score, status, warnings

    def _calculate_pattern_penalty(self, issues: List[Issue]) -> float:
        """
        Calculate penalty from pattern issues.

        v2.1: Pattern-based scoring.
        """
        severity_weights = {
            "critical": 10.0,
            "high": 5.0,
            "medium": 2.0,
            "low": 1.0,
        }

        penalty = 0.0
        for issue in issues:
            weight = severity_weights.get(issue.severity.value, 1.0)
            penalty += weight

        # Cap pattern penalty at 50 points
        return min(penalty, 50.0)

    def _should_ignore(self, file_path: Path, patterns: List[str]) -> bool:
        """Check if file matches any ignore pattern."""
        for pattern in patterns:
            if file_path.match(pattern):
                return True
        return False

    def _create_error_analysis(self, file_path: str, error: str) -> FileAnalysis:
        """Create minimal analysis for files with errors."""
        from slop_detector.models import DDCResult, InflationResult, LDRResult

        return FileAnalysis(
            file_path=file_path,
            ldr=LDRResult(0, 0, 0, 0.0, "N/A"),
            inflation=InflationResult(0, 0.0, float("inf"), "error", []),
            ddc=DDCResult([], [], [], [], [], 0.0, "N/A"),
            deficit_score=100.0,  # CRITICAL: Syntax errors are severe
            status=SlopStatus.CRITICAL_DEFICIT,
            warnings=[f"Parse error: {error}"],
        )

    def _create_empty_project_analysis(self, project_path: str) -> ProjectAnalysis:
        """Create empty project analysis."""
        return ProjectAnalysis(
            project_path=project_path,
            total_files=0,
            deficit_files=0,
            clean_files=0,
            avg_deficit_score=0.0,
            weighted_deficit_score=0.0,
            avg_ldr=0.0,
            avg_inflation=0.0,
            avg_ddc=0.0,
            overall_status=SlopStatus.CLEAN,
            file_results=[],
        )
