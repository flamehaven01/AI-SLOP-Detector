"""Context-Based Jargon Detection - Cross-validates jargon claims with evidence."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class JargonEvidence:
    """Evidence for or against a jargon claim."""

    jargon: str
    category: str
    line: int
    required_evidence: List[str]  # What evidence should exist
    found_evidence: List[str]  # What evidence was actually found
    missing_evidence: List[str]  # What's missing
    evidence_ratio: float  # found / required
    is_justified: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jargon": self.jargon,
            "category": self.category,
            "line": self.line,
            "required_evidence": self.required_evidence,
            "found_evidence": self.found_evidence,
            "missing_evidence": self.missing_evidence,
            "evidence_ratio": self.evidence_ratio,
            "is_justified": self.is_justified,
        }


@dataclass
class ContextJargonResult:
    """Result of context-based jargon analysis."""

    total_jargon: int
    justified_jargon: int
    unjustified_jargon: int
    evidence_details: List[JargonEvidence]
    worst_offenders: List[str]  # Jargon with 0 evidence
    justification_ratio: float  # justified / total
    status: str  # "PASS", "WARNING", "CRITICAL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_jargon": self.total_jargon,
            "justified_jargon": self.justified_jargon,
            "unjustified_jargon": self.unjustified_jargon,
            "evidence_details": [e.to_dict() for e in self.evidence_details],
            "worst_offenders": self.worst_offenders,
            "justification_ratio": self.justification_ratio,
            "status": self.status,
        }


class ContextJargonDetector:
    """Cross-validate jargon claims with actual codebase evidence."""

    # Evidence requirements for each jargon category
    # Integration test detection constants
    INTEGRATION_PATH_PARTS = {"integration", "integration_tests", "e2e", "it"}
    INTEGRATION_NAME_HINTS = ("integration_test", "test_integration", "it_")
    INTEGRATION_MARKERS = ("@pytest.mark.integration", "@pytest.mark.e2e")
    INTEGRATION_RUNTIME_SIGNALS = (
        "testcontainers",
        "docker-compose",
        "TestClient",  # FastAPI/Starlette
        "httpx.AsyncClient",
        "requests.Session",
    )

    EVIDENCE_REQUIREMENTS = {
        "production-ready": [
            "error_handling",
            "logging",
            "tests_unit",
            "tests_integration",
            "input_validation",
            "config_management",
        ],
        "production ready": [
            "error_handling",
            "logging",
            "tests_unit",
            "tests_integration",
            "input_validation",
            "config_management",
        ],
        "enterprise-grade": [
            "error_handling",
            "logging",
            "tests_unit",
            "tests_integration",
            "monitoring",
            "documentation",
            "security",
        ],
        "enterprise grade": [
            "error_handling",
            "logging",
            "tests_unit",
            "tests_integration",
            "monitoring",
            "documentation",
            "security",
        ],
        "scalable": [
            "caching",
            "async_support",
            "connection_pooling",
            "rate_limiting",
            "tests_integration",
        ],
        "fault-tolerant": [
            "error_handling",
            "retry_logic",
            "circuit_breaker",
            "fallback",
            "tests_integration",
        ],
        "fault tolerant": [
            "error_handling",
            "retry_logic",
            "circuit_breaker",
            "fallback",
            "tests_integration",
        ],
        "robust": ["error_handling", "input_validation", "tests_unit"],
        "resilient": ["error_handling", "retry_logic", "fallback"],
        "performant": ["caching", "async_support", "optimization", "profiling"],
        "optimized": ["caching", "memoization", "lazy_loading", "algorithmic_efficiency"],
        "comprehensive": ["documentation", "tests_unit", "error_messages"],
        "sophisticated": ["design_patterns", "abstraction", "modularity"],
        "advanced": ["design_patterns", "advanced_algorithms", "optimization"],
    }

    def __init__(self, config):
        """Initialize detector."""
        self.config = config

    def analyze(
        self, file_path: str, content: str, tree: ast.AST, inflation_result: Any
    ) -> ContextJargonResult:
        """Analyze jargon with context-based evidence validation."""
        # Get jargon from inflation result
        if not hasattr(inflation_result, "jargon_details"):
            return self._empty_result()

        jargon_details = inflation_result.jargon_details

        # Collect codebase evidence
        evidence = self._collect_evidence(content, tree, file_path)

        # Validate each jargon claim
        evidence_results = []
        justified_count = 0
        unjustified_count = 0

        for jargon_detail in jargon_details:
            jargon = jargon_detail["word"].lower()
            category = jargon_detail.get("category", "unknown")
            line = jargon_detail.get("line", 0)

            # Check if this jargon requires evidence
            if jargon not in self.EVIDENCE_REQUIREMENTS:
                continue

            required_evidence = self.EVIDENCE_REQUIREMENTS[jargon]
            found_evidence = [e for e in required_evidence if evidence.get(e, False)]
            missing_evidence = [e for e in required_evidence if not evidence.get(e, False)]

            evidence_ratio = (
                len(found_evidence) / len(required_evidence) if required_evidence else 0
            )
            is_justified = evidence_ratio >= 0.5  # At least 50% evidence required

            if is_justified:
                justified_count += 1
            else:
                unjustified_count += 1

            evidence_results.append(
                JargonEvidence(
                    jargon=jargon,
                    category=category,
                    line=line,
                    required_evidence=required_evidence,
                    found_evidence=found_evidence,
                    missing_evidence=missing_evidence,
                    evidence_ratio=evidence_ratio,
                    is_justified=is_justified,
                )
            )

        # Identify worst offenders (0 evidence)
        worst_offenders = [e.jargon for e in evidence_results if e.evidence_ratio == 0]

        # Calculate justification ratio
        total = justified_count + unjustified_count
        justification_ratio = justified_count / total if total > 0 else 1.0

        # Determine status
        if justification_ratio < 0.3:
            status = "CRITICAL"
        elif justification_ratio < 0.6:
            status = "WARNING"
        else:
            status = "PASS"

        return ContextJargonResult(
            total_jargon=total,
            justified_jargon=justified_count,
            unjustified_jargon=unjustified_count,
            evidence_details=sorted(evidence_results, key=lambda e: e.evidence_ratio),
            worst_offenders=worst_offenders[:5],
            justification_ratio=justification_ratio,
            status=status,
        )

    def _collect_evidence(self, content: str, tree: ast.AST, file_path: str) -> Dict[str, bool]:
        """Collect evidence from the codebase."""
        evidence = {}

        # Error handling
        evidence["error_handling"] = self._has_error_handling(tree)

        # Logging
        evidence["logging"] = self._has_logging(tree, content)

        # Tests (DEPRECATED - kept for backward compatibility)
        evidence["tests"] = self._has_tests(file_path, tree)

        # NEW: Split tests into unit and integration
        evidence["tests_unit"] = self._has_unit_tests(file_path, tree)
        evidence["tests_integration"] = self._has_integration_tests(file_path, tree, content)

        # Input validation
        evidence["input_validation"] = self._has_input_validation(tree, content)

        # Config management
        evidence["config_management"] = self._has_config_management(tree, content)

        # Monitoring
        evidence["monitoring"] = self._has_monitoring(tree, content)

        # Documentation
        evidence["documentation"] = self._has_documentation(tree)

        # Security
        evidence["security"] = self._has_security(tree, content)

        # Caching
        evidence["caching"] = self._has_caching(tree, content)

        # Async support
        evidence["async_support"] = self._has_async_support(tree)

        # Retry logic
        evidence["retry_logic"] = self._has_retry_logic(tree, content)

        # Design patterns
        evidence["design_patterns"] = self._has_design_patterns(tree)

        # Advanced algorithms
        evidence["advanced_algorithms"] = self._has_advanced_algorithms(tree)

        # Optimization
        evidence["optimization"] = self._has_optimization(tree, content)

        return evidence

    def _has_error_handling(self, tree: ast.AST) -> bool:
        """Check for error handling (try/except blocks)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) and node.handlers:
                # Check it's not empty except
                for handler in node.handlers:
                    if handler.body and not (
                        len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)
                    ):
                        return True
        return False

    def _has_logging(self, tree: ast.AST, content: str) -> bool:
        """Check for logging usage."""
        # Check imports
        if "import logging" in content or "from logging" in content:
            # Check actual usage
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute):
                        if func.attr in ("debug", "info", "warning", "error", "critical"):
                            return True
        return False

    def _has_tests(self, file_path: str, tree: ast.AST) -> bool:
        """Check for test presence."""
        # Check if this is a test file
        if "test_" in str(file_path) or "_test" in str(file_path):
            return True

        # Check for test functions
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name.startswith("test_"):
                    return True

        # Check for test directory
        path = Path(file_path)
        if path.parent.name in ("tests", "test"):
            return True

        return False

    def _has_unit_tests(self, file_path: str, tree: ast.AST) -> bool:
        """Detect unit tests (fast, isolated tests)."""
        path = Path(str(file_path))

        # Exclude integration/e2e directories from unit tests
        if any(p in self.INTEGRATION_PATH_PARTS for p in path.parts):
            return False

        # Reuse existing tests detection logic
        return self._has_tests(file_path, tree)

    def _has_integration_tests(self, file_path: str, tree: ast.AST, content: str) -> bool:
        """Detect integration tests (tests that hit real deps)."""
        path = Path(str(file_path))

        # 1) Path-based detection
        if any(p in self.INTEGRATION_PATH_PARTS for p in path.parts):
            return self._is_real_test_file(tree)

        # 2) File name-based detection
        if any(hint in path.name for hint in self.INTEGRATION_NAME_HINTS):
            return self._is_real_test_file(tree)

        # 3) Pytest marker-based detection
        if any(m in content for m in self.INTEGRATION_MARKERS):
            return self._is_real_test_file(tree)

        # 4) Runtime signal-based detection
        if self._has_integration_runtime_signals(content):
            # Runtime signals + test file = integration test
            return self._has_tests(file_path, tree) and self._is_real_test_file(tree)

        return False

    def _has_integration_runtime_signals(self, content: str) -> bool:
        """Detect runtime signals of integration testing."""
        return any(sig in content for sig in self.INTEGRATION_RUNTIME_SIGNALS)

    def _is_real_test_file(self, tree: ast.AST) -> bool:
        """
        Check if file contains actual test functions.
        Prevents false positives from helper files like integration_utils.py
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                return True
        return False

    def _has_input_validation(self, tree: ast.AST, content: str) -> bool:
        """Check for input validation."""
        # Look for validation patterns
        validation_keywords = ["isinstance", "type(", "assert", "ValueError", "TypeError"]
        for keyword in validation_keywords:
            if keyword in content:
                return True
        return False

    def _has_config_management(self, tree: ast.AST, content: str) -> bool:
        """Check for config management."""
        config_patterns = ["config", "settings", ".env", "yaml", "toml", "json"]
        for pattern in config_patterns:
            if pattern in content.lower():
                return True
        return False

    def _has_monitoring(self, tree: ast.AST, content: str) -> bool:
        """Check for monitoring/metrics."""
        monitoring_keywords = ["metric", "prometheus", "statsd", "datadog", "sentry"]
        for keyword in monitoring_keywords:
            if keyword in content.lower():
                return True
        return False

    def _has_documentation(self, tree: ast.AST) -> bool:
        """Check for meaningful documentation."""
        docstring_count = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node)
                if doc and len(doc) > 20:  # Meaningful docstrings
                    docstring_count += 1
        return docstring_count >= 2

    def _has_security(self, tree: ast.AST, content: str) -> bool:
        """Check for security measures."""
        security_keywords = ["auth", "token", "encrypt", "hash", "permission", "sanitize"]
        for keyword in security_keywords:
            if keyword in content.lower():
                return True
        return False

    def _has_caching(self, tree: ast.AST, content: str) -> bool:
        """Check for caching."""
        caching_keywords = ["@cache", "@lru_cache", "redis", "memcache", "cache"]
        for keyword in caching_keywords:
            if keyword in content:
                return True
        return False

    def _has_async_support(self, tree: ast.AST) -> bool:
        """Check for async/await usage."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
                return True
        return False

    def _has_retry_logic(self, tree: ast.AST, content: str) -> bool:
        """Check for retry logic."""
        retry_keywords = ["retry", "@retry", "tenacity", "backoff", "while True"]
        for keyword in retry_keywords:
            if keyword in content:
                return True
        return False

    def _has_design_patterns(self, tree: ast.AST) -> bool:
        """Check for design patterns."""
        # Look for common patterns: Factory, Singleton, Observer, etc.
        class_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_names.add(node.name.lower())

        pattern_indicators = ["factory", "singleton", "observer", "strategy", "adapter", "proxy"]
        return any(pattern in " ".join(class_names) for pattern in pattern_indicators)

    def _has_advanced_algorithms(self, tree: ast.AST) -> bool:
        """Check for advanced algorithms."""
        # Look for complex logic indicating advanced algorithms
        max_complexity = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                complexity = self._calculate_complexity(node)
                max_complexity = max(max_complexity, complexity)

        return max_complexity >= 10  # High complexity suggests advanced logic

    def _has_optimization(self, tree: ast.AST, content: str) -> bool:
        """Check for optimization techniques."""
        optimization_keywords = ["@cache", "vectorize", "numba", "cython", "optimize"]
        for keyword in optimization_keywords:
            if keyword in content.lower():
                return True
        return False

    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """Simple cyclomatic complexity calculation."""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    def _empty_result(self) -> ContextJargonResult:
        """Return empty result when no jargon detected."""
        return ContextJargonResult(
            total_jargon=0,
            justified_jargon=0,
            unjustified_jargon=0,
            evidence_details=[],
            worst_offenders=[],
            justification_ratio=1.0,
            status="PASS",
        )
