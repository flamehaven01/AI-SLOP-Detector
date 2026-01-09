"""Buzzword-to-Code Ratio (BCR) calculator with context awareness."""

import ast
from pathlib import Path
from typing import List, Set

from slop_detector.models import InflationResult

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

    def calculate(
        self, file_path: str, content: str, tree: ast.AST
    ) -> InflationResult:
        """Calculate Inflation with context awareness."""
        jargon_found = []
        justified_jargon = []
        jargon_details = []

        lines = content.splitlines()

        for line_idx, line in enumerate(lines, 1):
            line_lower = line.lower()
            
            for category, words in self.JARGON.items():
                for word in words:
                    # Simple check: word must be present
                    if word.lower() in line_lower:
                        # Count occurrences in this line
                        count = line_lower.count(word.lower())
                        for _ in range(count):
                            jargon_found.append(word)
                            
                            is_justified = self._is_jargon_justified(category, word, content)
                            if is_justified:
                                justified_jargon.append(word)
                            
                            jargon_details.append({
                                "word": word,
                                "line": line_idx,
                                "category": category,
                                "justified": is_justified
                            })

        jargon_count = len(jargon_found)
        justified_count = len(justified_jargon)

        # Adjust jargon count (reduce if justified)
        effective_jargon_count = max(0, jargon_count - justified_count)

        # Calculate average complexity
        avg_complexity = self._calculate_avg_complexity(content, tree)

        # Check if it's a config file
        is_config_file = self._is_config_file(file_path, tree)

        # Calculate Inflation Score
        if avg_complexity == 0:
            if is_config_file and self.config.is_config_file_exception_enabled():
                inflation_score = 0.0
            else:
                inflation_score = float("inf") if effective_jargon_count > 0 else 0.0
        else:
            inflation_raw = effective_jargon_count / (avg_complexity * 10)
            inflation_score = min(inflation_raw, 10.0)

        # Determine status
        if inflation_score > 1.0:
            status = "FAIL"
        elif inflation_score > 0.5:
            status = "WARNING"
        else:
            status = "PASS"

        return InflationResult(
            jargon_count=jargon_count,
            avg_complexity=avg_complexity,
            inflation_score=inflation_score,
            status=status,
            jargon_found=jargon_found,
            jargon_details=jargon_details,
            justified_jargon=justified_jargon,
            is_config_file=is_config_file,
        )

    def _calculate_avg_complexity(self, content: str, tree: ast.AST) -> float:
        """Calculate average cyclomatic complexity using radon if available."""
        if self.use_radon:
            try:
                results = cc_visit(content)
                if not results:
                    return 1.0
                total = sum(r.complexity for r in results)
                return total / len(results)
            except Exception:
                pass

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

    def _is_jargon_justified(self, category: str, word: str, content: str) -> bool:
        """Check if jargon is justified by actual implementation."""
        if category not in self.JUSTIFICATIONS:
            return False

        justifiers = self.JUSTIFICATIONS[category]
        for justifier in justifiers:
            if justifier in content:
                return True

        return False

    def _is_config_file(self, file_path: str, tree: ast.AST) -> bool:
        """Check if file is a configuration file."""
        file_name = Path(file_path).name.lower()

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
