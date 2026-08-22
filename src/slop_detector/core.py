"""Core SLOP detector with improved architecture."""

from __future__ import annotations

import ast
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from slop_detector.analysis_cache import CACHE_ENGINE_VERSION, FileAnalysisCache, fingerprint_config
from slop_detector.config import Config
from slop_detector.core_project import (
    build_project_analysis,
    collect_project_scan_coverage,
    create_empty_project_analysis,
    create_error_analysis,
    discover_supported_files,
    ignore_reason,
    is_result_non_clean,
    result_ldr_score,
    result_slop_score,
    result_status_value,
    result_total_lines,
    set_analyzed_scan_counts,
    should_ignore,
)
from slop_detector.core_scoring import (
    build_metric_warnings,
    calculate_pattern_penalty,
    calculate_slop_status,
    compute_deficit_breakdown,
    compute_gqg,
)
from slop_detector.core_topology import (
    compute_coherence_vr,
    compute_coherence_vr_exact,
    compute_dcf,
    deterministic_sample_indices,
    js_divergence,
)
from slop_detector.file_role import classify_file
from slop_detector.ignore_handler import IgnoreHandler
from slop_detector.masking import FrameworkMasker
from slop_detector.metrics import DDCCalculator, InflationCalculator, LDRCalculator
from slop_detector.metrics.context_jargon import ContextJargonDetector
from slop_detector.metrics.docstring_inflation import DocstringInflationDetector
from slop_detector.metrics.hallucination_deps import HallucinationDepsDetector
from slop_detector.models import (
    FileAnalysis,
    IgnoredFunction,
    MaskedIssue,
    ProjectAnalysis,
    SlopStatus,
    SuppressionDirective,
    SuppressionLedgerEntry,
)
from slop_detector.patterns import get_all_patterns
from slop_detector.patterns.base import Issue
from slop_detector.patterns.registry import PatternRegistry
from slop_detector.prioritization import ProjectPrioritizer
from slop_detector.rust_scan import discover_project_files
from slop_detector.suppression_handler import SuppressionHandler

logger = logging.getLogger(__name__)


class SlopDetector:
    """Main SLOP detection engine with v2.1 pattern support."""

    def __init__(self, config_path: Optional[str] = None, model_path: Optional[str] = None):
        """Initialize detector with config.

        Args:
            config_path: Path to .slopconfig.yaml (optional).
            model_path:  Path to trained ML model .pkl (optional).
                         Defaults to "models/slop_classifier.pkl" if not specified.
                         ML scoring is silently disabled when the file is absent.
        """
        self.config = Config(config_path)
        self.ldr_calc = LDRCalculator(self.config)
        self.inflation_calc = InflationCalculator(self.config)
        self.ddc_calc = DDCCalculator(self.config)
        self.docstring_inflation_detector = DocstringInflationDetector(self.config)  # v2.2
        self.hallucination_deps_detector = HallucinationDepsDetector(self.config)  # v2.2
        self.context_jargon_detector = ContextJargonDetector(self.config)  # v2.2

        # v2.1: Initialize pattern registry
        self.pattern_registry = PatternRegistry()
        self.pattern_registry.register_all(
            get_all_patterns(
                god_function_config=self.config.get_god_function_config(),
                nested_complexity_config=self.config.get_nested_complexity_config(),
                phantom_import_allowlist=self.config.get_phantom_import_allowlist(),
            )
        )
        # Disable patterns from config
        disabled = self.config.get("patterns.disabled", [])
        for pattern_id in disabled:
            self.pattern_registry.disable(pattern_id)

        # Optional ML scorer: unavailable capability is carried into reports.
        from pathlib import Path as _Path

        from slop_detector.ml.scorer import MLScorer as _MLScorer

        _mp = _Path(model_path) if model_path else _Path("models/slop_classifier.pkl")
        self._ml_scorer, availability = _MLScorer.from_model_with_status(_mp)
        self._ml_scoring = availability.to_dict()

        # Phase 3b: JS/TS analyzer (lazy — only instantiated when needed)
        self._js_analyzer = None
        # Phase 3c: Go analyzer (lazy — only instantiated when needed)
        self._go_analyzer = None
        self._analysis_cache = (
            FileAnalysisCache(self.config.get_analysis_cache_db())
            if self.config.use_analysis_cache()
            else None
        )
        self.project_prioritizer = ProjectPrioritizer(self.config)

    def _get_js_analyzer(self):
        """Lazy-load JSAnalyzer (avoids import cost when not used)."""
        if self._js_analyzer is None:
            from slop_detector.languages.js_analyzer import JSAnalyzer

            self._js_analyzer = JSAnalyzer()
        return self._js_analyzer

    def _get_go_analyzer(self):
        """Lazy-load GoAnalyzer (avoids import cost when not used)."""
        if self._go_analyzer is None:
            from slop_detector.languages.go_analyzer import GoAnalyzer

            self._go_analyzer = GoAnalyzer()
        return self._go_analyzer

    @staticmethod
    def _compute_dcf(tree: ast.AST) -> Dict[str, float]:
        """Backward-compatible facade for structural fingerprint calculation."""
        return compute_dcf(tree)

    def analyze_file(self, file_path: str) -> FileAnalysis:
        """
        Analyze a single Python file.

        Improvements in v2.1:
        - Pattern-based detection alongside metrics
        - Hybrid scoring (metrics + patterns)
        """
        path_obj = Path(file_path).resolve()
        file_path = str(path_obj)
        logger.info(f"Analyzing: {file_path}")

        stat = path_obj.stat()
        try:
            raw_bytes = path_obj.read_bytes()
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            raise
        content = raw_bytes.decode("utf-8", errors="ignore")
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        if self._analysis_cache is not None:
            cached = self._analysis_cache.get(
                file_path=file_path,
                file_size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                content_hash=content_hash,
                config_fingerprint=fingerprint_config(self.config.config),
                engine_version=CACHE_ENGINE_VERSION,
            )
            if cached is not None:
                logger.debug("File analysis cache hit: %s", file_path)
                # Capability belongs to this execution environment, not the
                # cached file content. Never surface a historical ML score when
                # the current run cannot load its model.
                cached.ml_scoring = self._ml_scoring
                if self._ml_scorer is None:
                    cached.ml_score = None
                return cached

        # Parse AST once
        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {e}")
            # Return minimal analysis
            return self._create_error_analysis(file_path, str(e))

        result = self._build_file_analysis(file_path, content, tree)
        if self._analysis_cache is not None:
            self._analysis_cache.put(
                file_path=file_path,
                file_size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                content_hash=content_hash,
                config_fingerprint=fingerprint_config(self.config.config),
                result=result,
                engine_version=CACHE_ENGINE_VERSION,
            )
        return result

    def analyze_code_string(self, content: str, filename: str = "<string>") -> FileAnalysis:
        """Analyze Python source code provided as a string (no file I/O).

        Identical to analyze_file() but accepts raw source instead of a path.
        Useful for dataset pipelines, REPL usage, and API endpoints.

        Args:
            content:  Python source code as a string.
            filename: Virtual filename shown in results (default: "<string>").

        Returns:
            FileAnalysis — same structure as analyze_file().
        """
        try:
            tree = ast.parse(content, filename=filename)
        except SyntaxError as e:
            return self._create_error_analysis(filename, str(e))
        return self._build_file_analysis(filename, content, tree)

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
        scan_coverage = self._collect_project_scan_coverage(project_path_obj, ignore_patterns)

        # Rust discovery is optional acceleration, not the source of truth. Its
        # paths must agree with root-relative Python discovery before use.
        python_files = self._discover_supported_files(
            project_path_obj, [pattern], {".py"}, ignore_patterns
        )

        logger.info(f"Found {len(python_files)} Python files in {project_path}")

        # Analyze files
        results: List[FileAnalysis] = []
        for file_path in python_files:
            try:
                result = self.analyze_file(str(file_path))
                results.append(result)
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {e}")

        # Phase 3b: JS/TS analysis is independent of Python — run before early return
        js_results = self._analyze_js_files(project_path_obj, ignore_patterns)
        # Phase 3c: Go analysis is independent of Python — run before early return
        go_results = self._analyze_go_files(project_path_obj, ignore_patterns)
        if not results and not js_results and not go_results:
            logger.warning("No files analyzed")

        return build_project_analysis(
            str(project_path),
            str(project_path_obj),
            results,
            js_results,
            go_results,
            scan_coverage,
            self.config.use_weighted_analysis(),
            self._compute_coherence_vr,
            self.project_prioritizer.prioritize_project,
            self._ml_scoring,
        )

    def _build_file_analysis(self, file_path: str, content: str, tree: ast.AST) -> FileAnalysis:
        """Build a FileAnalysis from already-read source and parsed AST."""
        from slop_detector.file_role import ROLE_SKIP

        role = classify_file(file_path, content, tree)  # type: ignore[arg-type]
        skip = ROLE_SKIP[role]

        ldr = self.ldr_calc.calculate(file_path, content, tree)
        inflation = self.inflation_calc.calculate(file_path, content, tree)
        ddc = self.ddc_calc.calculate(file_path, content, tree)
        dcf = self._compute_dcf(tree)
        docstring_inflation = self.docstring_inflation_detector.analyze(file_path, content, tree)
        hallucination_deps = self.hallucination_deps_detector.analyze(file_path, content, tree, ddc)
        context_jargon = self.context_jargon_detector.analyze(file_path, content, tree, inflation)
        ignored_functions = IgnoreHandler.collect_ignored_functions(tree)
        suppression_directives = SuppressionHandler.parse_comment_suppressions(content)
        pattern_issues, suppression_ledger, masked_issues = (
            ([], [], [])
            if "patterns" in skip
            else self._run_patterns(
                tree,
                Path(file_path),
                content,
                ignored_functions,
                suppression_directives=suppression_directives,
            )
        )

        slop_score, slop_status, warnings, deficit_breakdown = self._calculate_slop_status(
            ldr, inflation, ddc, pattern_issues, skip=skip
        )

        result = FileAnalysis(
            file_path=file_path,
            ldr=ldr,
            inflation=inflation,
            ddc=ddc,
            deficit_score=slop_score,
            status=slop_status,
            warnings=warnings,
            pattern_issues=pattern_issues,
            docstring_inflation=docstring_inflation,
            hallucination_deps=hallucination_deps,
            context_jargon=context_jargon,
            ignored_functions=ignored_functions,
            suppression_directives=suppression_directives,
            suppression_ledger=suppression_ledger,
            masked_issues=masked_issues,
            dcf=dcf,
            deficit_breakdown=deficit_breakdown,
        )

        if len(suppression_ledger) >= 5 or len(suppression_directives) >= 3:
            result.warnings.append(
                "SUPPRESSIONS: high inline suppression usage — review whether rules should be fixed or narrowed"
            )

        if self._ml_scorer is not None:
            result.ml_score = self._ml_scorer.score(result)
        result.ml_scoring = self._ml_scoring

        return result

    _JS_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})

    def _discover_supported_files(
        self,
        project_path: Path,
        include_patterns: List[str],
        extensions: set[str] | frozenset[str],
        ignore_patterns: List[str],
    ) -> List[Path]:
        """Backward-compatible facade for verified source discovery."""
        return discover_supported_files(
            project_path,
            include_patterns,
            extensions,
            ignore_patterns,
            rust_discoverer=discover_project_files,
        )

    def _analyze_js_files(self, project_path_obj: Path, ignore_patterns: List[str]) -> List:
        """Scan and analyze JS/TS files in project_path_obj (Phase 3b)."""
        js_files = self._discover_supported_files(
            project_path_obj,
            [f"**/*{ext}" for ext in self._JS_EXTENSIONS],
            self._JS_EXTENSIONS,
            ignore_patterns,
        )
        if not js_files:
            return []
        analyzer = self._get_js_analyzer()
        results = []
        for fp in js_files:
            try:
                results.append(analyzer.analyze(str(fp)))
            except Exception as exc:
                logger.error(f"Error analyzing JS/TS file {fp}: {exc}")
        logger.info(f"Analyzed {len(results)} JS/TS files")
        return results

    def analyze_js_file(self, file_path: str):
        """Analyze a single JS/TS file and return JSFileAnalysis."""
        return self._get_js_analyzer().analyze(file_path)

    _GO_EXTENSIONS = frozenset({".go"})

    def _analyze_go_files(self, project_path_obj: Path, ignore_patterns: List[str]) -> List:
        """Scan and analyze Go files in project_path_obj (Phase 3c)."""
        go_files = self._discover_supported_files(
            project_path_obj,
            [f"**/*{ext}" for ext in self._GO_EXTENSIONS],
            self._GO_EXTENSIONS,
            ignore_patterns,
        )
        if not go_files:
            return []
        analyzer = self._get_go_analyzer()
        results = []
        for fp in go_files:
            try:
                results.append(analyzer.analyze(str(fp)))
            except Exception as exc:
                logger.error(f"Error analyzing Go file {fp}: {exc}")
        logger.info(f"Analyzed {len(results)} Go files")
        return results

    def analyze_go_file(self, file_path: str):
        """Analyze a single .go file and return GoFileAnalysis."""
        return self._get_go_analyzer().analyze(file_path)

    def _run_patterns(
        self,
        tree: ast.AST,
        file: Path,
        content: str,
        ignored_functions: Optional[List[IgnoredFunction]] = None,
        suppression_directives: Optional[List[SuppressionDirective]] = None,
    ) -> tuple[List[Issue], List[SuppressionLedgerEntry], List[MaskedIssue]]:
        """
        Run all enabled patterns on the file.

        v2.1: New pattern-based detection.
        v2.6.3: Filters issues from @slop.ignore decorated functions.
        """
        issues = []
        suppression_ledger: List[SuppressionLedgerEntry] = []
        masked_issues: List[MaskedIssue] = []
        ignored_functions = ignored_functions or []
        suppression_directives = suppression_directives or []
        ignored_ranges = IgnoreHandler.get_ignored_line_ranges(tree, ignored_functions)

        for pattern in self.pattern_registry.get_all():
            try:
                pattern_issues = pattern.check(tree, file, content)
                pattern_issues, pattern_masked = FrameworkMasker.apply_python_masking(
                    file, content, tree, pattern_issues
                )
                masked_issues.extend(pattern_masked)
                # v2.6.3: Filter issues in ignored functions
                for issue in pattern_issues:
                    if IgnoreHandler.is_line_in_ignored_range(issue.line, ignored_ranges):
                        continue
                    ledger_entry = SuppressionHandler.match_issue(
                        str(file), issue.line, pattern.id, suppression_directives
                    )
                    if ledger_entry is not None:
                        suppression_ledger.append(ledger_entry)
                        continue
                    issues.append(issue)
            except Exception as e:
                logger.warning(f"Pattern {pattern.id} failed: {e}")

        return issues, suppression_ledger, masked_issues

    # Backward-compat shims — delegate to IgnoreHandler
    def _collect_ignored_functions(self, tree: ast.AST) -> List[IgnoredFunction]:
        return IgnoreHandler.collect_ignored_functions(tree)

    def _get_ignored_line_ranges(
        self, tree: ast.AST, ignored_functions: List[IgnoredFunction]
    ) -> List[tuple]:
        return IgnoreHandler.get_ignored_line_ranges(tree, ignored_functions)

    def _is_line_in_ignored_range(self, line: int, ranges: List[tuple]) -> bool:
        return IgnoreHandler.is_line_in_ignored_range(line, ranges)

    def _compute_gqg(self, ldr, inflation_normalized: float, ddc, purity: float) -> float:
        """Backward-compatible facade for the geometric quality gate."""
        return compute_gqg(self.config.get_weights(), ldr, inflation_normalized, ddc, purity)

    @staticmethod
    def _build_metric_warnings(ldr, inflation, ddc, skip: frozenset = frozenset()) -> List[str]:
        """Backward-compatible facade for metric threshold warnings."""
        return build_metric_warnings(ldr, inflation, ddc, skip=skip)

    def _calculate_slop_status(
        self,
        ldr,
        inflation,
        ddc,
        pattern_issues: Optional[List[Issue]] = None,
        skip: frozenset = frozenset(),
    ) -> tuple[float, SlopStatus, List[str], Dict[str, float]]:
        """Backward-compatible facade for deterministic score calculation."""
        return calculate_slop_status(
            self.config.get_weights(), ldr, inflation, ddc, pattern_issues, skip=skip
        )

    def _compute_deficit_breakdown(
        self,
        ldr,
        inflation_normalized: float,
        ddc,
        purity: float,
        base_deficit_score: float,
        pattern_penalty: float,
        deficit_score: float,
    ) -> Dict[str, float]:
        """Backward-compatible facade for deficit attribution."""
        del pattern_penalty
        return compute_deficit_breakdown(
            self.config.get_weights(),
            ldr,
            inflation_normalized,
            ddc,
            purity,
            base_deficit_score,
            deficit_score,
        )

    def _js_divergence(self, p: List[float], q: List[float]) -> float:
        """Backward-compatible facade for Jensen-Shannon divergence."""
        return js_divergence(p, q)

    @staticmethod
    def _deterministic_sample_indices(total: int, sample_size: int) -> List[int]:
        """Backward-compatible facade for deterministic sampling."""
        return deterministic_sample_indices(total, sample_size)

    def _compute_coherence_vr_exact(self, file_dcfs) -> float:
        """Backward-compatible facade for exact coherence calculation."""
        return compute_coherence_vr_exact(file_dcfs)

    def _compute_coherence_vr(self, file_dcfs: List[Dict[str, float]]) -> tuple[float, str]:
        """Backward-compatible facade for configured coherence calculation."""
        return compute_coherence_vr(
            file_dcfs,
            self.config.get_exact_topology_ceiling(),
            self.config.get_topology_mode_above_ceiling(),
            exact_calculator=self._compute_coherence_vr_exact,
        )

    def _calculate_pattern_penalty(self, issues: List[Issue]) -> float:
        """Backward-compatible facade for pattern penalty calculation."""
        return calculate_pattern_penalty(issues)

    @staticmethod
    def _result_status_value(result: Any) -> str:
        return result_status_value(result)

    def _is_result_non_clean(self, result: Any) -> bool:
        return is_result_non_clean(result)

    @staticmethod
    def _result_slop_score(result: Any) -> float:
        return result_slop_score(result)

    @staticmethod
    def _result_total_lines(result: Any) -> int:
        return result_total_lines(result)

    @staticmethod
    def _result_ldr_score(result: Any) -> float:
        return result_ldr_score(result)

    def _should_ignore(
        self, file_path: Path, patterns: List[str], root: Optional[Path] = None
    ) -> bool:
        """Backward-compatible facade for project exclusion checks."""
        return should_ignore(file_path, patterns, root=root)

    def _ignore_reason(
        self, file_path: Path, patterns: List[str], root: Optional[Path] = None
    ) -> Optional[str]:
        """Backward-compatible facade for exclusion reporting."""
        return ignore_reason(file_path, patterns, root=root)

    def _collect_project_scan_coverage(
        self, project_path: Path, ignore_patterns: List[str]
    ) -> Dict[str, Any]:
        """Backward-compatible facade for project scope reporting."""
        return collect_project_scan_coverage(project_path, ignore_patterns)

    @staticmethod
    def _set_analyzed_scan_counts(
        scan_coverage: Dict[str, Any],
        python_results: List[Any],
        js_results: List[Any],
        go_results: List[Any],
    ) -> None:
        set_analyzed_scan_counts(scan_coverage, python_results, js_results, go_results)

    def _create_error_analysis(self, file_path: str, error: str) -> FileAnalysis:
        """Backward-compatible facade for parse-error results."""
        return create_error_analysis(file_path, error)

    def _create_empty_project_analysis(self, project_path: str) -> ProjectAnalysis:
        """Backward-compatible facade for an empty project result."""
        return create_empty_project_analysis(project_path)
