"""Data models for SLOP detection."""

import logging as _logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

_logger = _logging.getLogger(__name__)


class SlopStatus(str, Enum):
    """Detection status."""

    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    INFLATED_SIGNAL = "inflated_signal"
    DEPENDENCY_NOISE = "dependency_noise"
    CRITICAL_DEFICIT = "critical_deficit"


@dataclass
class LDRResult:
    """Logic Density Ratio result."""

    total_lines: int
    logic_lines: int
    empty_lines: int
    ldr_score: float
    grade: str
    is_abc_interface: bool = False
    is_type_stub: bool = False
    is_packaging_init: bool = False  # empty __init__.py — Python packaging convention

    def __post_init__(self) -> None:
        if not (0.0 <= self.ldr_score <= 1.0):
            _logger.warning("LDRResult.ldr_score %.4f out of [0,1] — clamped", self.ldr_score)
            self.ldr_score = max(0.0, min(1.0, self.ldr_score))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_lines": self.total_lines,
            "logic_lines": self.logic_lines,
            "empty_lines": self.empty_lines,
            "ldr_score": self.ldr_score,
            "grade": self.grade,
            "is_abc_interface": self.is_abc_interface,
            "is_type_stub": self.is_type_stub,
            "is_packaging_init": self.is_packaging_init,
        }


@dataclass
class InflationResult:
    """Inflation-to-Code Ratio result (formerly BCR)."""

    jargon_count: int
    avg_complexity: float
    inflation_score: float
    status: str
    jargon_found: List[str]
    jargon_details: List[Dict[str, Any]] = field(default_factory=list)
    justified_jargon: List[str] = field(default_factory=list)
    is_config_file: bool = False

    def __post_init__(self) -> None:
        if self.inflation_score < 0.0:
            _logger.warning(
                "InflationResult.inflation_score %.4f below 0 — clamped", self.inflation_score
            )
            self.inflation_score = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jargon_count": self.jargon_count,
            "avg_complexity": self.avg_complexity,
            "inflation_score": self.inflation_score,
            "status": self.status,
            "jargon_found": self.jargon_found[:10],
            "jargon_details": self.jargon_details,
            "justified_jargon": self.justified_jargon[:10],
            "is_config_file": self.is_config_file,
        }


@dataclass
class DDCResult:
    """Deep Dependency Check result."""

    imported: List[str]
    actually_used: List[str]
    unused: List[str]
    fake_imports: List[str]
    type_checking_imports: List[str]
    usage_ratio: float
    grade: str

    def __post_init__(self) -> None:
        if not (0.0 <= self.usage_ratio <= 1.0):
            _logger.warning("DDCResult.usage_ratio %.4f out of [0,1] — clamped", self.usage_ratio)
            self.usage_ratio = max(0.0, min(1.0, self.usage_ratio))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "imported": self.imported,
            "actually_used": self.actually_used,
            "unused": self.unused,
            "fake_imports": self.fake_imports,
            "type_checking_imports": self.type_checking_imports,
            "usage_ratio": self.usage_ratio,
            "grade": self.grade,
        }


@dataclass
class IgnoredFunction:
    """Function marked with @slop.ignore decorator (v2.6.3)."""

    name: str
    reason: str
    rules: List[str] = field(default_factory=list)
    lineno: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "reason": self.reason,
            "rules": self.rules,
            "lineno": self.lineno,
        }


@dataclass
class SuppressionDirective:
    """Inline comment suppression directive."""

    scope: str
    action: str
    lineno: int
    rules: List[str] = field(default_factory=list)
    source: str = "comment"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "action": self.action,
            "lineno": self.lineno,
            "rules": self.rules,
            "source": self.source,
        }


@dataclass
class SuppressionLedgerEntry:
    """A suppressed issue recorded for auditability."""

    file_path: str
    directive_line: int
    suppressed_line: int
    pattern_id: str
    scope: str
    matched_rule: str
    source: str = "comment"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "directive_line": self.directive_line,
            "suppressed_line": self.suppressed_line,
            "pattern_id": self.pattern_id,
            "scope": self.scope,
            "matched_rule": self.matched_rule,
            "source": self.source,
        }


@dataclass
class MaskedIssue:
    """A framework-aware masked issue recorded for auditability."""

    file_path: str
    masked_line: int
    pattern_id: str
    framework: str
    rule_id: str
    reason: str
    source: str = "framework_masking"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "masked_line": self.masked_line,
            "pattern_id": self.pattern_id,
            "framework": self.framework,
            "rule_id": self.rule_id,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class FileAnalysis:
    """Complete file analysis result."""

    file_path: str
    ldr: LDRResult
    inflation: InflationResult
    ddc: DDCResult
    deficit_score: float
    status: SlopStatus
    warnings: List[str] = field(default_factory=list)
    pattern_issues: List[Any] = field(default_factory=list)  # v2.1: Pattern issues
    docstring_inflation: Any = None  # v2.2: Docstring inflation analysis
    hallucination_deps: Any = None  # v2.2: Hallucinated dependencies
    context_jargon: Any = None  # v2.2: Context-based jargon validation
    ignored_functions: List[IgnoredFunction] = field(default_factory=list)  # v2.6.3
    suppression_directives: List[SuppressionDirective] = field(default_factory=list)
    suppression_ledger: List[SuppressionLedgerEntry] = field(default_factory=list)
    masked_issues: List[MaskedIssue] = field(default_factory=list)
    ml_score: Any = None  # v2.8.0: Optional ML secondary signal (MLScore | None)
    # v3.0: Distributional Code Fingerprint — P(node_type | file) over AST node types.
    # Genuine probability distribution. Used for information-theoretic slop distance (CQMS Level 2).
    dcf: Dict[str, float] = field(default_factory=dict)
    # v3.7.6 (SLOP-003): per-dimension attribution of deficit_score so users
    # can answer "why is my clean-status file not 0?" without reading findings.
    # Fields: ldr_penalty, inflation_penalty, ddc_penalty, purity_penalty,
    # pattern_hits, total. Sum of penalty fields equals total within 0.01.
    deficit_breakdown: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "file_path": self.file_path,
            "ldr": self.ldr.to_dict(),
            "inflation": self.inflation.to_dict(),
            "ddc": self.ddc.to_dict(),
            "deficit_score": self.deficit_score,
            "status": self.status.value,
            "warnings": self.warnings,
            "pattern_issues": [
                issue.to_dict() if hasattr(issue, "to_dict") else str(issue)
                for issue in self.pattern_issues
            ],
        }
        if self.docstring_inflation:
            result["docstring_inflation"] = (
                self.docstring_inflation.to_dict()
                if hasattr(self.docstring_inflation, "to_dict")
                else self.docstring_inflation
            )
        if self.hallucination_deps:
            result["hallucination_deps"] = (
                self.hallucination_deps.to_dict()
                if hasattr(self.hallucination_deps, "to_dict")
                else self.hallucination_deps
            )
        if self.context_jargon:
            result["context_jargon"] = (
                self.context_jargon.to_dict()
                if hasattr(self.context_jargon, "to_dict")
                else self.context_jargon
            )
        if self.ignored_functions:
            result["ignored_functions"] = [f.to_dict() for f in self.ignored_functions]
        if self.suppression_directives:
            result["suppression_directives"] = [d.to_dict() for d in self.suppression_directives]
        if self.suppression_ledger:
            result["suppression_ledger"] = [e.to_dict() for e in self.suppression_ledger]
        if self.masked_issues:
            result["masked_issues"] = [item.to_dict() for item in self.masked_issues]
        if self.ml_score is not None:
            result["ml_score"] = (
                self.ml_score.to_dict() if hasattr(self.ml_score, "to_dict") else self.ml_score
            )
        if self.dcf:
            result["dcf"] = self.dcf
        if self.deficit_breakdown:
            result["deficit_breakdown"] = self.deficit_breakdown
        return result


@dataclass
class PriorityHotspot:
    """Prioritized project-level file hotspot."""

    file_path: str
    deficit_score: float
    churn_count: int = 0
    churn_score: float = 0.0
    coverage_ratio: Optional[float] = None
    priority_score: float = 0.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "deficit_score": self.deficit_score,
            "churn_count": self.churn_count,
            "churn_score": self.churn_score,
            "coverage_ratio": self.coverage_ratio,
            "priority_score": self.priority_score,
            "reasons": self.reasons,
        }


@dataclass
class ProjectAnalysis:
    """Project-level analysis result."""

    project_path: str
    total_files: int
    deficit_files: int
    clean_files: int
    avg_deficit_score: float
    weighted_deficit_score: float
    avg_ldr: float
    avg_inflation: float
    avg_ddc: float
    overall_status: SlopStatus
    file_results: List[FileAnalysis] = field(default_factory=list)
    # Phase 3b: JS/TS analysis results (JSFileAnalysis objects)
    js_file_results: List[Any] = field(default_factory=list)
    # Phase 3c: Go analysis results (GoFileAnalysis objects)
    go_file_results: List[Any] = field(default_factory=list)
    # v3.0: CQMS structural coherence — max H0 persistence (MST-based) over file DCFs.
    # 1.0 = all files structurally uniform. Low = distinct structural clusters (AI/human mix signal).
    structural_coherence: float = 1.0
    coherence_level: str = "none"  # "vr_structural" | "vr_structural_approx" | "none"
    suppressed_issue_count: int = 0
    suppression_ledger: List[SuppressionLedgerEntry] = field(default_factory=list)
    priority_hotspots: List[PriorityHotspot] = field(default_factory=list)
    churn_analysis_available: bool = False
    coverage_analysis_available: bool = False

    def to_dict(self) -> Dict[str, Any]:
        # Local import keeps the data model free of presentation deps at module
        # load. next_steps / project_metric_rows are pure semantic helpers (no
        # rich/markdown) so machine consumers (JSON, agent route, MCP) receive
        # the same actionable plan and metric semantics a human reader gets.
        from slop_detector.renderer_glossary import next_steps, project_metric_rows

        return {
            "project_path": self.project_path,
            "total_files": self.total_files,
            "deficit_files": self.deficit_files,
            "clean_files": self.clean_files,
            "avg_deficit_score": self.avg_deficit_score,
            "weighted_deficit_score": self.weighted_deficit_score,
            "avg_ldr": self.avg_ldr,
            "avg_inflation": self.avg_inflation,
            "avg_ddc": self.avg_ddc,
            "overall_status": self.overall_status.value,
            "structural_coherence": round(self.structural_coherence, 4),
            "coherence_level": self.coherence_level,
            "suppressed_issue_count": self.suppressed_issue_count,
            "suppression_ledger": [e.to_dict() for e in self.suppression_ledger],
            "priority_hotspots": [h.to_dict() for h in self.priority_hotspots],
            "churn_analysis_available": self.churn_analysis_available,
            "coverage_analysis_available": self.coverage_analysis_available,
            # Machine-readable guidance (same source as the human report; OSOT):
            # next_steps = deterministic prioritized action plan,
            # metric_guide = per-metric value/healthy-direction/plain meaning.
            "next_steps": next_steps(self),
            "metric_guide": project_metric_rows(self),
            "file_results": [r.to_dict() for r in self.file_results],
            "js_file_results": [
                r.to_dict() if hasattr(r, "to_dict") else r for r in self.js_file_results
            ],
            "go_file_results": [
                r.to_dict() if hasattr(r, "to_dict") else r for r in self.go_file_results
            ],
        }
