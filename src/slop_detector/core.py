"""Core SLOP detector with improved architecture."""

from __future__ import annotations

import ast
import fnmatch
import logging
import math
from collections import Counter
from math import exp, log, sqrt
from pathlib import Path
from typing import Dict, List, Optional

from slop_detector.config import Config
from slop_detector.file_role import classify_file
from slop_detector.ignore_handler import IgnoreHandler
from slop_detector.metrics import DDCCalculator, InflationCalculator, LDRCalculator
from slop_detector.metrics.context_jargon import ContextJargonDetector
from slop_detector.metrics.docstring_inflation import DocstringInflationDetector
from slop_detector.metrics.hallucination_deps import HallucinationDepsDetector
from slop_detector.models import FileAnalysis, IgnoredFunction, ProjectAnalysis, SlopStatus
from slop_detector.patterns import get_all_patterns
from slop_detector.patterns.base import Issue
from slop_detector.patterns.registry import PatternRegistry

logger = logging.getLogger(__name__)
DEFAULT_EXCLUDE_PARTS = {".venv", "venv", "site-packages", "node_modules", "__pycache__", ".git"}


class _SkipProxy:
    """Thin proxy that overrides specific metric attributes for role-based skip logic."""

    def __init__(self, wrapped, **overrides):
        self._wrapped = wrapped
        self._overrides = overrides

    def __getattr__(self, name: str):
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._wrapped, name)


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
            )
        )

        # Disable patterns from config
        disabled = self.config.get("patterns.disabled", [])
        for pattern_id in disabled:
            self.pattern_registry.disable(pattern_id)

        # v2.8.0: Optional ML scorer — loads silently, fails silently
        from pathlib import Path as _Path

        from slop_detector.ml.scorer import MLScorer as _MLScorer

        _mp = _Path(model_path) if model_path else _Path("models/slop_classifier.pkl")
        self._ml_scorer = _MLScorer.from_model(_mp)

        # Phase 3b: JS/TS analyzer (lazy — only instantiated when needed)
        self._js_analyzer = None
        # Phase 3c: Go analyzer (lazy — only instantiated when needed)
        self._go_analyzer = None

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
        """Compute DCF (Distributional Code Fingerprint) from a parsed AST.

        Returns P(node_type | file) = count(node_type) / total_nodes.
        Genuine probability distribution: values in [0,1], sum to 1.
        Used for information-theoretic slop distance (CQMS Level 2).
        """
        counts = Counter(type(node).__name__ for node in ast.walk(tree))
        total = sum(counts.values()) or 1
        return {k: v / total for k, v in counts.items()}

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

        # v3.3.0: Classify file role — suppresses false-positive checks for
        # __init__.py (INIT), re-export modules (RE_EXPORT), and corpus files (CORPUS).
        role = classify_file(file_path, content, tree)
        from slop_detector.file_role import ROLE_SKIP

        skip = ROLE_SKIP[role]

        # Calculate all metrics (using shared content and tree)
        ldr = self.ldr_calc.calculate(file_path, content, tree)
        inflation = self.inflation_calc.calculate(file_path, content, tree)
        ddc = self.ddc_calc.calculate(file_path, content, tree)

        # v3.0: Compute DCF before other analyses (reuses already-parsed tree)
        dcf = self._compute_dcf(tree)

        # v2.2: Analyze docstring inflation
        docstring_inflation = self.docstring_inflation_detector.analyze(file_path, content, tree)

        # v2.2: Analyze hallucination dependencies
        hallucination_deps = self.hallucination_deps_detector.analyze(file_path, content, tree, ddc)

        # v2.2: Analyze context-based jargon
        context_jargon = self.context_jargon_detector.analyze(file_path, content, tree, inflation)

        # v2.6.3: Collect @slop.ignore decorated functions
        ignored_functions = IgnoreHandler.collect_ignored_functions(tree)

        # v2.1: Run pattern detection (v2.6.3: filters ignored functions)
        pattern_issues = (
            []
            if "patterns" in skip
            else self._run_patterns(tree, Path(file_path), content, ignored_functions)
        )

        # Determine slop status (now includes pattern issues, respects role skip)
        slop_score, slop_status, warnings = self._calculate_slop_status(
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
            pattern_issues=pattern_issues,  # v2.1
            docstring_inflation=docstring_inflation,  # v2.2
            hallucination_deps=hallucination_deps,  # v2.2
            context_jargon=context_jargon,  # v2.2
            ignored_functions=ignored_functions,  # v2.6.3
            dcf=dcf,  # v3.0
        )

        # v2.8.0: Attach ML secondary score if model is loaded
        if self._ml_scorer is not None:
            result.ml_score = self._ml_scorer.score(result)

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

        from slop_detector.file_role import ROLE_SKIP

        role = classify_file(filename, content, tree)
        skip = ROLE_SKIP[role]

        ldr = self.ldr_calc.calculate(filename, content, tree)
        inflation = self.inflation_calc.calculate(filename, content, tree)
        ddc = self.ddc_calc.calculate(filename, content, tree)
        dcf = self._compute_dcf(tree)  # v3.0
        docstring_inflation = self.docstring_inflation_detector.analyze(filename, content, tree)
        hallucination_deps = self.hallucination_deps_detector.analyze(filename, content, tree, ddc)
        context_jargon = self.context_jargon_detector.analyze(filename, content, tree, inflation)
        ignored_functions = IgnoreHandler.collect_ignored_functions(tree)
        pattern_issues = (
            []
            if "patterns" in skip
            else self._run_patterns(tree, Path(filename), content, ignored_functions)
        )

        slop_score, slop_status, warnings = self._calculate_slop_status(
            ldr, inflation, ddc, pattern_issues, skip=skip
        )

        result = FileAnalysis(
            file_path=filename,
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
            dcf=dcf,  # v3.0
        )

        if self._ml_scorer is not None:
            result.ml_score = self._ml_scorer.score(result)

        return result

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

        # Phase 3b: JS/TS analysis is independent of Python — run before early return
        js_results = self._analyze_js_files(project_path_obj, ignore_patterns)
        # Phase 3c: Go analysis is independent of Python — run before early return
        go_results = self._analyze_go_files(project_path_obj, ignore_patterns)

        if not results:
            logger.warning("No files analyzed")
            pa = self._create_empty_project_analysis(str(project_path))
            pa.js_file_results = js_results
            pa.go_file_results = go_results
            return pa

        # Calculate aggregated metrics
        total_files = len(results)
        slop_files = sum(1 for r in results if r.status != SlopStatus.CLEAN)
        clean_files = total_files - slop_files

        # Simple average for deficit score
        avg_deficit_score = sum(r.deficit_score for r in results) / total_files

        # v2.8.0: SR9-inspired conservative LDR aggregation
        # SR9 = 0.6*min + 0.4*mean — gives more weight to worst-case file
        # Prevents bad files from being diluted by the average
        ldr_scores = [r.ldr.ldr_score for r in results]
        avg_ldr = 0.6 * min(ldr_scores) + 0.4 * (sum(ldr_scores) / total_files)
        avg_inflation = sum(
            r.inflation.inflation_score
            for r in results
            if math.isfinite(r.inflation.inflation_score)
        ) / max(1, sum(1 for r in results if math.isfinite(r.inflation.inflation_score)))
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

        # v3.0: VR structural coherence — MST H0 persistence over file DCFs
        file_dcfs = [r.dcf for r in results if r.dcf]
        if len(file_dcfs) >= 2:
            structural_coherence = self._compute_coherence_vr(file_dcfs)
            coherence_level = "vr_structural"
        else:
            structural_coherence = 1.0
            coherence_level = "none"

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
            structural_coherence=structural_coherence,
            coherence_level=coherence_level,
            js_file_results=js_results,
            go_file_results=go_results,
        )

    _JS_EXTENSIONS = frozenset({".js", ".jsx", ".ts", ".tsx"})

    def _analyze_js_files(self, project_path_obj: Path, ignore_patterns: List[str]) -> List:
        """Scan and analyze JS/TS files in project_path_obj (Phase 3b)."""
        js_files = [
            fp
            for fp in project_path_obj.rglob("*")
            if fp.suffix.lower() in self._JS_EXTENSIONS
            and not self._should_ignore(fp, ignore_patterns)
        ]
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
        go_files = [
            fp
            for fp in project_path_obj.rglob("*")
            if fp.suffix.lower() in self._GO_EXTENSIONS
            and not self._should_ignore(fp, ignore_patterns)
        ]
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
    ) -> List[Issue]:
        """
        Run all enabled patterns on the file.

        v2.1: New pattern-based detection.
        v2.6.3: Filters issues from @slop.ignore decorated functions.
        """
        issues = []
        ignored_functions = ignored_functions or []
        ignored_ranges = IgnoreHandler.get_ignored_line_ranges(tree, ignored_functions)

        for pattern in self.pattern_registry.get_all():
            try:
                pattern_issues = pattern.check(tree, file, content)
                # v2.6.3: Filter issues in ignored functions
                for issue in pattern_issues:
                    if not IgnoreHandler.is_line_in_ignored_range(issue.line, ignored_ranges):
                        issues.append(issue)
            except Exception as e:
                logger.warning(f"Pattern {pattern.id} failed: {e}")

        return issues

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
        """Geometric quality gate — weighted geometric mean of four dimensions.

        Formula: exp(sum(w_i * ln(max(1e-4, v_i))) / sum(w_i))
        Dimensions: ldr_score, 1-inflation_normalized, ddc.usage_ratio, purity.
        """
        weights = self.config.get_weights()
        w_ldr = weights.get("ldr", 0.40)
        w_inf = weights.get("inflation", 0.30)
        w_ddc = weights.get("ddc", 0.20)
        w_pur = weights.get("purity", 0.10)
        total_w = w_ldr + w_inf + w_ddc + w_pur
        return exp(
            (
                w_ldr * log(max(1e-4, ldr.ldr_score))
                + w_inf * log(max(1e-4, 1.0 - inflation_normalized))
                + w_ddc * log(max(1e-4, ddc.usage_ratio))
                + w_pur * log(max(1e-4, purity))
            )
            / total_w
        )

    @staticmethod
    def _build_metric_warnings(ldr, inflation, ddc, skip: frozenset = frozenset()) -> List[str]:
        """Generate per-metric threshold warnings for ldr, inflation, and ddc."""
        warnings: List[str] = []
        if "ldr" not in skip:
            if ldr.ldr_score < 0.30:
                warnings.append(f"CRITICAL: Logic density only {ldr.ldr_score:.2%}")
            elif ldr.ldr_score < 0.60:
                warnings.append(f"WARNING: Low logic density {ldr.ldr_score:.2%}")
        if "inflation" not in skip:
            if inflation.inflation_score > 1.0:
                warnings.append(f"CRITICAL: Inflation ratio {inflation.inflation_score:.2f}")
            elif inflation.inflation_score > 0.5:
                warnings.append(f"WARNING: High inflation ratio {inflation.inflation_score:.2f}")
        if "ddc" not in skip:
            if ddc.usage_ratio < 0.50:
                warnings.append(f"CRITICAL: Only {ddc.usage_ratio:.2%} of imports used")
            elif ddc.usage_ratio < 0.70:
                warnings.append(f"WARNING: Low import usage {ddc.usage_ratio:.2%}")
            if ddc.fake_imports:
                warnings.append(f"FAKE IMPORTS: {', '.join(ddc.fake_imports)}")
        return warnings

    def _calculate_slop_status(
        self,
        ldr,
        inflation,
        ddc,
        pattern_issues: Optional[List[Issue]] = None,
        skip: frozenset = frozenset(),
    ) -> tuple[float, SlopStatus, List[str]]:
        """
        Calculate slop score using weighted formula + pattern penalties.

        v2.1: Includes pattern-based scoring.
        v3.3.0: ``skip`` frozenset suppresses specific checks for file roles
                (e.g. INIT files skip 'ldr' and 'ddc').
        """
        pattern_issues = pattern_issues or []

        # Normalize Inflation (cap at 2.0, treat inf as 2.0)
        inflation_normalized = (
            min(inflation.inflation_score, 2.0) / 2.0
            if inflation.inflation_score != float("inf")
            else 1.0
        )
        if "inflation" in skip:
            inflation_normalized = 0.0  # treat as perfect

        # purity = exp(-0.5 * n_critical): GQG AND-gate dimension for pattern severity
        n_critical = len([i for i in pattern_issues if i.severity.value == "critical"])
        purity = exp(-0.5 * n_critical)

        # Build effective ldr/ddc scores respecting skip
        effective_ldr = _SkipProxy(ldr, ldr_score=1.0) if "ldr" in skip else ldr
        effective_ddc = _SkipProxy(ddc, usage_ratio=1.0) if "ddc" in skip else ddc

        gqg = self._compute_gqg(effective_ldr, inflation_normalized, effective_ddc, purity)
        base_deficit_score = 100 * (1 - gqg)
        pattern_penalty = self._calculate_pattern_penalty(pattern_issues)
        deficit_score = min(base_deficit_score + pattern_penalty, 100.0)

        warnings = self._build_metric_warnings(ldr, inflation, ddc, skip=skip)

        # v2.1: Add pattern warnings
        critical_patterns = [i for i in pattern_issues if i.severity.value == "critical"]
        high_patterns = [i for i in pattern_issues if i.severity.value == "high"]

        if critical_patterns:
            warnings.append(f"PATTERNS: {len(critical_patterns)} critical issues found")
        if high_patterns:
            warnings.append(f"PATTERNS: {len(high_patterns)} high-severity issues found")

        # v2.8.0: Monotonic single-axis status determination (TOE gate principle)
        # Primary axis: deficit_score is the authoritative measure.
        # Supplementary overrides are explicit, documented, and threshold-gated.
        if deficit_score >= 70:
            status = SlopStatus.CRITICAL_DEFICIT
        elif deficit_score >= 50:
            status = SlopStatus.INFLATED_SIGNAL
        elif deficit_score >= 30:
            status = SlopStatus.SUSPICIOUS
        else:
            status = SlopStatus.CLEAN

        # Supplementary override 1: extreme critical pattern density
        # 5+ critical patterns is unambiguous slop regardless of score
        if len(critical_patterns) >= 5 and status == SlopStatus.CLEAN:
            status = SlopStatus.SUSPICIOUS

        # Supplementary override 2: near-zero import usage (structural issue)
        # DEPENDENCY_NOISE applies when DDC < 20% is the *primary* failure mode.
        # GQG collapses on near-zero DDC, but the label should reflect root cause.
        # Guard: skip if critical patterns, high inflation, or role-based DDC skip.
        if (
            ddc.usage_ratio < 0.20
            and "ddc" not in skip
            and not critical_patterns
            and inflation.inflation_score <= 1.0
        ):
            status = SlopStatus.DEPENDENCY_NOISE

        return deficit_score, status, warnings

    def _js_divergence(self, p: List[float], q: List[float]) -> float:
        """Jensen-Shannon divergence between two probability vectors.

        Returns JSD in [0, 1] (log base 2 convention, then normalized to [0,1]).
        Both p and q must have equal length and sum to ~1.
        """
        m = [(pi + qi) / 2.0 for pi, qi in zip(p, q)]
        eps = 1e-12

        def kl(a: List[float], b: List[float]) -> float:
            return sum(ai * log(ai / bi) for ai, bi in zip(a, b) if ai > eps and bi > eps)

        jsd = 0.5 * kl(p, m) + 0.5 * kl(q, m)
        return max(0.0, min(1.0, jsd))

    def _compute_coherence_vr(self, file_dcfs: List[Dict[str, float]]) -> float:
        """MST H0 persistent homology coherence over file DCFs.

        coherence = 1 - max_mst_edge
        where max_mst_edge is the longest edge in the minimum spanning tree
        of pairwise sqrt-JSD distances between file DCFs.

        Properties:
        - epsilon-free (no threshold parameter)
        - 1.0: all files structurally uniform
        - 0.0: maximally distinct structural clusters
        - Equivalent to maximum H0 persistence in the Vietoris-Rips filtration
        """
        n = len(file_dcfs)
        if n <= 1:
            return 1.0

        # Build pairwise sqrt-JSD distance matrix
        dist = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1, n):
                all_keys = sorted(set(file_dcfs[i]) | set(file_dcfs[j]))
                p = [file_dcfs[i].get(k, 0.0) for k in all_keys]
                q = [file_dcfs[j].get(k, 0.0) for k in all_keys]
                jsd = self._js_divergence(p, q)
                d = sqrt(jsd)
                dist[i][j] = dist[j][i] = d

        # Prim's MST — O(n^2), ε-free
        in_mst = [False] * n
        min_edge = [float("inf")] * n
        min_edge[0] = 0.0
        mst_edge_weights: List[float] = []

        for _ in range(n):
            u = min((v for v in range(n) if not in_mst[v]), key=lambda v: min_edge[v])
            in_mst[u] = True
            if min_edge[u] > 0.0:
                mst_edge_weights.append(min_edge[u])
            for v in range(n):
                if not in_mst[v] and dist[u][v] < min_edge[v]:
                    min_edge[v] = dist[u][v]

        max_persistence = max(mst_edge_weights) if mst_edge_weights else 0.0
        return max(0.0, 1.0 - max_persistence)

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
        lowered_parts = {part.lower() for part in file_path.parts}
        if lowered_parts & DEFAULT_EXCLUDE_PARTS:
            return True

        normalized = str(file_path).replace("\\", "/")
        for pattern in patterns:
            pat = str(pattern).replace("\\", "/")
            if file_path.match(pat):
                return True
            if fnmatch.fnmatch(normalized, pat):
                return True
            if pat.startswith("**/") and fnmatch.fnmatch(normalized, pat[3:]):
                return True
        return False

    def _create_error_analysis(self, file_path: str, error: str) -> FileAnalysis:
        """Create minimal analysis for files with errors."""
        from slop_detector.models import DDCResult, InflationResult, LDRResult

        # 999.0 sentinel instead of float("inf") — inf serializes as "Infinity"
        # which violates RFC 8259 and is rejected by jq/most JSON parsers.
        return FileAnalysis(
            file_path=file_path,
            ldr=LDRResult(0, 0, 0, 0.0, "N/A"),
            inflation=InflationResult(0, 0.0, 999.0, "error", []),
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
