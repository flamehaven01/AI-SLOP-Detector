"""Buzzword-to-Code Ratio (BCR) calculator with context awareness."""

import ast
import logging
from pathlib import Path

from slop_detector.models import InflationResult

logger = logging.getLogger(__name__)

try:
    from radon.complexity import cc_visit

    RADON_AVAILABLE = True
except ImportError:
    RADON_AVAILABLE = False


class InflationCalculator:
    """Calculate Inflation (formerly BCR) with context-aware jargon detection."""

    JARGON = {
        # AI/ML jargon
        "ai_ml": [
            "neural",
            "deep learning",
            "transformer",
            "attention mechanism",
            "reinforcement learning",
            "policy optimization",
            "gradient descent",
            "latent space",
            "embedding",
            "semantic reasoning",
        ],
        # Architecture jargon
        "architecture": [
            "byzantine",
            "fault-tolerant",
            "fault tolerant",
            "distributed",
            "scalable",
            "enterprise-grade",
            "enterprise grade",
            "production-ready",
            "production ready",
            "mission-critical",
            "mission critical",
            "cloud-native",
            "cloud native",
            "microservices",
            "serverless",
        ],
        # Quality jargon
        "quality": [
            "robust",
            "resilient",
            "performant",
            "optimized",
            "optimization",
            "state-of-the-art",
            "cutting-edge",
            "advanced algorithm",
            "sophisticated",
            "comprehensive",
            "holistic",
        ],
        # Paper references
        "academic": [
            "neurips",
            "iclr",
            "icml",
            "cvpr",
            "equation",
            "theorem",
            "proof",
            "lemma",
            "spotlight",
        ],
    }

    # Libraries that justify jargon
    JUSTIFICATIONS = {
        "ai_ml": ["torch", "tensorflow", "keras", "jax", "transformers"],
        "architecture": ["multiprocessing", "concurrent", "asyncio", "distributed"],
        "quality": ["numba", "cython", "vectorized", "@cache", "@lru_cache"],
    }

    def __init__(self, config):
        """Initialize with config."""
        self.config = config
        self.use_radon = config.use_radon() and RADON_AVAILABLE

    def calculate(self, file_path: str, content: str, tree: ast.AST) -> InflationResult:
        """Calculate Inflation with context awareness (v2.8.0 TOE formula)."""
        lines = content.splitlines()
        logic_lines = sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))
        avg_complexity = self._calculate_avg_complexity(content, tree)
        is_config_file = self._is_config_file(file_path, tree)

        jargon_found, justified_jargon, jargon_details = self._scan_jargon(content, lines, tree)
        effective_jargon = max(0, len(jargon_found) - len(justified_jargon))
        inflation_score = self._compute_inflation_score(
            effective_jargon, logic_lines, avg_complexity, is_config_file
        )
        status = (
            "FAIL" if inflation_score > 1.0 else ("WARNING" if inflation_score > 0.5 else "PASS")
        )

        return InflationResult(
            jargon_count=len(jargon_found),
            avg_complexity=avg_complexity,
            inflation_score=inflation_score,
            status=status,
            jargon_found=jargon_found,
            jargon_details=jargon_details,
            justified_jargon=justified_jargon,
            is_config_file=is_config_file,
        )

    def _scan_jargon(self, content: str, lines: list, tree: ast.AST):
        """Scan all lines for jargon hits, returning (found, justified, details)."""
        jargon_found = []
        justified_jargon = []
        jargon_details = []
        func_scopes = self._build_function_scopes(tree, lines)

        for line_idx, line in enumerate(lines, 1):
            line_lower = line.lower()
            for category, words in self.JARGON.items():
                for word in words:
                    if word.lower() in line_lower:
                        for _ in range(line_lower.count(word.lower())):
                            jargon_found.append(word)
                            is_justified = self._is_jargon_justified_scoped(
                                category, word, content, lines, line_idx, func_scopes
                            )
                            if is_justified:
                                justified_jargon.append(word)
                            jargon_details.append(
                                {
                                    "word": word,
                                    "line": line_idx,
                                    "category": category,
                                    "justified": is_justified,
                                }
                            )
        return jargon_found, justified_jargon, jargon_details

    def _compute_inflation_score(
        self, effective_jargon: int, logic_lines: int, avg_complexity: float, is_config_file: bool
    ) -> float:
        """Compute final inflation score using v2.8.0 density × complexity formula."""
        if is_config_file and self.config.is_config_file_exception_enabled():
            return 0.0
        if logic_lines == 0:
            return float("inf") if effective_jargon > 0 else 0.0
        jargon_density = effective_jargon / logic_lines
        # complexity_modifier >= 1.0: complex code pays premium for jargon
        complexity_modifier = max(1.0, 1.0 + (avg_complexity - 3.0) / 10.0)
        return min(jargon_density * complexity_modifier * 10.0, 10.0)

    def _calculate_avg_complexity(self, content: str, tree: ast.AST) -> float:
        """Calculate average cyclomatic complexity using radon if available."""
        if self.use_radon:
            avg: float = 1.0  # safe default if radon fails
            try:
                results = cc_visit(content)
                if results:
                    avg = sum(r.complexity for r in results) / len(results)
            except Exception as exc:  # noqa: BLE001 — radon parse errors are unpredictable
                logger.debug("radon cc_visit failed, using default complexity=1.0: %s", exc)
            return avg

        # Fallback: simple AST-based complexity
        function_count = 0
        total_complexity = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_count += 1
                complexity = 1
                for child in ast.walk(node):
                    if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                        complexity += 1
                    elif isinstance(child, ast.BoolOp):
                        complexity += len(child.values) - 1
                total_complexity += complexity

        return total_complexity / function_count if function_count > 0 else 1.0

    def _build_function_scopes(self, tree: ast.AST, lines: list) -> dict:
        """Build mapping of line_number -> (func_start, func_end) for each line.

        v2.8.0: Enables function-scoped justification check.
        Returns dict: line_idx (1-based) -> (start_line, end_line) or None.
        """
        # Collect all function ranges (include decorator lines in scope start)
        func_ranges = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno + 1)
                # Extend start to first decorator so @lru_cache etc. are in scope
                if node.decorator_list:
                    true_start = min(d.lineno for d in node.decorator_list)
                else:
                    true_start = node.lineno
                func_ranges.append((true_start, end))

        # Sort by start so inner functions are found after outer
        func_ranges.sort()

        # For each line, find the innermost enclosing function
        n_lines = len(lines)
        scope_map = {}
        for line_idx in range(1, n_lines + 1):
            enclosing = None
            for start, end in func_ranges:
                if start <= line_idx <= end:
                    # Prefer innermost (latest start that still contains the line)
                    if enclosing is None or start > enclosing[0]:
                        enclosing = (start, end)
            scope_map[line_idx] = enclosing
        return scope_map

    def _is_jargon_justified_scoped(
        self,
        category: str,
        word: str,
        content: str,
        lines: list,
        line_idx: int,
        func_scopes: dict,
    ) -> bool:
        """Check if jargon is justified within its local function scope.

        v2.8.0: Function-scoped justification (TOE: measure at minimum relevant scope).
        - If jargon is inside a function: justifier must appear in that function body
        - If jargon is module-level: justifier may appear anywhere in file
        """
        if category not in self.JUSTIFICATIONS:
            return False

        justifiers = self.JUSTIFICATIONS[category]
        scope = func_scopes.get(line_idx)

        if scope is None:
            # Module-level: check full file (conservative — module-level jargon is rare)
            scope_text = content
        else:
            start, end = scope
            scope_text = "\n".join(lines[start - 1 : end])

        return any(j in scope_text for j in justifiers)

    def _is_jargon_justified(self, category: str, word: str, content: str) -> bool:
        """Legacy file-scoped justification (kept for external callers)."""
        if category not in self.JUSTIFICATIONS:
            return False
        justifiers = self.JUSTIFICATIONS[category]
        return any(j in content for j in justifiers)

    def _is_config_file(self, file_path: str, tree: ast.AST) -> bool:
        """Check if file is a configuration file."""
        # Check filename patterns
        config_patterns = self.config.get("exceptions.config_files.patterns", [])
        for pattern in config_patterns:
            if Path(file_path).match(pattern):
                # Verify no functions
                function_count = sum(
                    1
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                return function_count == 0

        return False
