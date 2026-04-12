"""Data models for SLOP detection."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


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
    ml_score: Any = None  # v2.8.0: Optional ML secondary signal (MLScore | None)
    # v3.0: Distributional Code Fingerprint — P(node_type | file) over AST node types.
    # Genuine probability distribution. Used for information-theoretic slop distance (CQMS Level 2).
    dcf: Dict[str, float] = field(default_factory=dict)

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
        if self.ml_score is not None:
            result["ml_score"] = (
                self.ml_score.to_dict() if hasattr(self.ml_score, "to_dict") else self.ml_score
            )
        if self.dcf:
            result["dcf"] = self.dcf
        return result


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
    # v3.0: CQMS structural coherence — max H0 persistence (MST-based) over file DCFs.
    # 1.0 = all files structurally uniform. Low = distinct structural clusters (AI/human mix signal).
    structural_coherence: float = 1.0
    coherence_level: str = "none"  # "vr_structural" | "none"

    def to_dict(self) -> Dict[str, Any]:
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
            "file_results": [r.to_dict() for r in self.file_results],
            "js_file_results": [
                r.to_dict() if hasattr(r, "to_dict") else r for r in self.js_file_results
            ],
        }
