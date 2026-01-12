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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_lines": self.total_lines,
            "logic_lines": self.logic_lines,
            "empty_lines": self.empty_lines,
            "ldr_score": self.ldr_score,
            "grade": self.grade,
            "is_abc_interface": self.is_abc_interface,
            "is_type_stub": self.is_type_stub,
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
            "file_results": [r.to_dict() for r in self.file_results],
        }
