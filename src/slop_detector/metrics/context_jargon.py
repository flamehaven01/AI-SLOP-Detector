"""Context-Based Jargon Detection - Cross-validates jargon claims with evidence."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from slop_detector.metrics.inflation import cache_decorator_lines
from slop_detector.path_facts import PathFacts, facts_for

# Claims a CI gate holds to integration-test evidence; shared by every consumer.
PRODUCTION_CLAIMS: frozenset = frozenset(
    {
        "production-ready",
        "production ready",
        "enterprise-grade",
        "enterprise grade",
        "scalable",
        "fault-tolerant",
        "fault tolerant",
    }
)

EVIDENCE_STATES = ("structural", "weak", "absent", "unmeasured")
SUPPORT_LEVELS = ("structural", "weak", "unsupported", "unmeasured")
_VALIDATION_ERRORS = frozenset({"ValueError", "TypeError"})


def _state(structural: bool, weak: bool = False) -> str:
    return "structural" if structural else ("weak" if weak else "absent")


def _support_level(by_state: Dict[str, List[str]], required: int) -> str:
    """Claim-level support from per-requirement evidence states.

    structural: structural evidence covers at least half of all requirements
    (unmeasured requirements count in the denominator). weak: some structure or
    hints, but not enough. unmeasured: nothing could be measured here.
    unsupported: measured, and nothing is there.
    """
    if required and len(by_state["structural"]) / required >= 0.5:
        return "structural"
    if by_state["structural"] or by_state["weak"]:
        return "weak"
    if len(by_state["unmeasured"]) == required:
        return "unmeasured"
    return "unsupported"


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
    is_justified: bool  # structurally supported; never "the claim is true"
    support_level: str = "unsupported"  # structural | weak | unsupported | unmeasured
    weak_evidence: List[str] = field(default_factory=list)  # text or name hints only
    unmeasured_evidence: List[str] = field(default_factory=list)  # no collector here

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
            "support_level": self.support_level,
            "weak_evidence": self.weak_evidence,
            "unmeasured_evidence": self.unmeasured_evidence,
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

    # Integration test detection from file content. Path-based test identity and
    # test kind come from root-relative path facts (slop_detector.path_facts).
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
        self,
        file_path: str,
        content: str,
        tree: ast.AST,
        inflation_result: Any,
        facts: Optional[PathFacts] = None,
    ) -> ContextJargonResult:
        """Analyze jargon with context-based evidence validation."""
        # Get jargon from inflation result
        if not hasattr(inflation_result, "jargon_details"):
            return self._empty_result()

        jargon_details = inflation_result.jargon_details

        # Collect codebase evidence, one state per evidence key
        states = self.evidence_states(content, tree, file_path, facts)

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
            by_state: Dict[str, List[str]] = {state: [] for state in EVIDENCE_STATES}
            for key in required_evidence:
                by_state[states.get(key, "unmeasured")].append(key)
            found_evidence = by_state["structural"]

            evidence_ratio = (
                len(found_evidence) / len(required_evidence) if required_evidence else 0
            )
            support_level = _support_level(by_state, len(required_evidence))
            # Justified means structurally supported; it never means the claim is true.
            is_justified = support_level == "structural"

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
                    missing_evidence=by_state["absent"],
                    evidence_ratio=evidence_ratio,
                    is_justified=is_justified,
                    support_level=support_level,
                    weak_evidence=by_state["weak"],
                    unmeasured_evidence=by_state["unmeasured"],
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

    def evidence_states(
        self, content: str, tree: ast.AST, file_path: str, facts: Optional[PathFacts] = None
    ) -> Dict[str, str]:
        """State of every evidence key: structural, weak, absent, or unmeasured.

        structural: seen in code structure (AST). weak: only a text or name hint
        (a keyword in a comment or string, a class name). absent: measured and
        not there. unmeasured: no collector at this scope, including test
        evidence for a file that is not a test file (tests live elsewhere).
        Complexity is never evidence.
        """
        facts = facts if facts is not None else facts_for(file_path)
        states = {
            "error_handling": _state(self._has_error_handling(tree)),
            "logging": _state(self._has_logging(tree, content)),
            "input_validation": _state(
                self._has_validation_structure(tree), self._has_input_validation(tree, content)
            ),
            "documentation": _state(self._has_documentation(tree)),
            "async_support": _state(self._has_async_support(tree)),
            "caching": _state(bool(cache_decorator_lines(tree)), self._has_caching(tree, content)),
            "config_management": _state(False, self._has_config_management(tree, content)),
            "monitoring": _state(False, self._has_monitoring(tree, content)),
            "security": _state(False, self._has_security(tree, content)),
            "retry_logic": _state(False, self._has_retry_logic(tree, content)),
            "optimization": _state(False, self._has_optimization(tree, content)),
            "design_patterns": _state(False, self._has_design_patterns(tree)),
        }
        states.update(self._test_states(tree, content, facts))
        for requirements in self.EVIDENCE_REQUIREMENTS.values():
            for key in requirements:
                states.setdefault(key, "unmeasured")
        return states

    def _test_states(self, tree: ast.AST, content: str, facts: PathFacts) -> Dict[str, str]:
        """Test evidence is measurable only in a test file (by root-relative path facts)."""
        if not facts.is_test:
            return {key: "unmeasured" for key in ("tests", "tests_unit", "tests_integration")}
        real = self._is_real_test_file(tree)
        path_integration = facts.test_kind in ("integration", "e2e")
        integration = (
            path_integration
            or any(m in content for m in self.INTEGRATION_MARKERS)
            or self._has_integration_runtime_signals(content)
        )
        return {
            "tests": _state(real),
            "tests_unit": _state(real and not path_integration),
            "tests_integration": _state(real and integration),
        }

    def _collect_evidence(
        self, content: str, tree: ast.AST, file_path: str, facts: Optional[PathFacts] = None
    ) -> Dict[str, bool]:
        """Structural evidence per key (True only for the structural state)."""
        states = self.evidence_states(content, tree, file_path, facts)
        return {key: state == "structural" for key, state in states.items()}

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
        """Check for logging usage: `logging` imported and a log-level call made (AST)."""
        imported = any(
            (
                isinstance(node, ast.Import)
                and any(a.name.split(".")[0] == "logging" for a in node.names)
            )
            or (isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "logging")
            for node in ast.walk(tree)
        )
        if not imported:
            return False
        return any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("debug", "info", "warning", "error", "critical")
            for node in ast.walk(tree)
        )

    def _has_tests(self, file_path: str, tree: ast.AST, facts: Optional[PathFacts] = None) -> bool:
        """Check for test presence: a test file by path facts, or test functions."""
        facts = facts if facts is not None else facts_for(file_path)
        if facts.is_test:
            return True
        return self._is_real_test_file(tree)

    def _has_unit_tests(
        self, file_path: str, tree: ast.AST, facts: Optional[PathFacts] = None
    ) -> bool:
        """Detect unit tests (fast, isolated tests)."""
        facts = facts if facts is not None else facts_for(file_path)

        # Exclude integration/e2e test files from unit tests
        if facts.test_kind in ("integration", "e2e"):
            return False

        return self._has_tests(file_path, tree, facts)

    def _has_integration_tests(
        self, file_path: str, tree: ast.AST, content: str, facts: Optional[PathFacts] = None
    ) -> bool:
        """Detect integration tests (tests that hit real deps)."""
        facts = facts if facts is not None else facts_for(file_path)

        # 1) Path-based detection (directory or file name)
        if facts.test_kind in ("integration", "e2e"):
            return self._is_real_test_file(tree)

        # 2) Pytest marker-based detection
        if any(m in content for m in self.INTEGRATION_MARKERS):
            return self._is_real_test_file(tree)

        # 3) Runtime signal-based detection
        if self._has_integration_runtime_signals(content):
            # Runtime signals + test file = integration test
            return self._has_tests(file_path, tree, facts) and self._is_real_test_file(tree)

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

    def _has_validation_structure(self, tree: ast.AST) -> bool:
        """Input validation in code: isinstance/issubclass checks, assert, or
        raising ValueError/TypeError."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                return True
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("isinstance", "issubclass")
            ):
                return True
            if isinstance(node, ast.Raise) and node.exc is not None:
                target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                if isinstance(target, ast.Name) and target.id in _VALIDATION_ERRORS:
                    return True
        return False

    def _has_input_validation(self, tree: ast.AST, content: str) -> bool:
        """Text hint of input validation (a keyword anywhere, comments included)."""
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

    def _has_optimization(self, tree: ast.AST, content: str) -> bool:
        """Check for optimization techniques."""
        optimization_keywords = ["@cache", "vectorize", "numba", "cython", "optimize"]
        for keyword in optimization_keywords:
            if keyword in content.lower():
                return True
        return False

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
