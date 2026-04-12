"""Data models for the CI/CD gate module."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class GateMode(str, Enum):
    """CI gate enforcement modes."""

    SOFT = "soft"  # PR comments only, never fails
    HARD = "hard"  # Fail build on threshold
    QUARANTINE = "quarantine"  # Track repeat offenders, escalate to HARD


class GateVerdict(str, Enum):
    """Gate decision outcomes."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    QUARANTINE = "quarantine"


@dataclass
class GateThresholds:
    """Configurable thresholds for gate decisions."""

    deficit_fail: float = 70.0  # Fail if deficit score >= this
    deficit_warn: float = 30.0  # Warn if deficit score >= this
    critical_patterns_fail: int = 3  # Fail if critical patterns >= this
    high_patterns_warn: int = 5  # Warn if high patterns >= this
    inflation_fail: float = 1.5  # Fail if inflation score >= this
    ddc_fail: float = 0.5  # Fail if import usage < this


@dataclass
class QuarantineRecord:
    """Track repeat offenders for quarantine mode."""

    file_path: str
    offense_count: int = 0
    last_deficit_score: float = 0.0
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "offense_count": self.offense_count,
            "last_deficit_score": self.last_deficit_score,
            "violations": self.violations,
        }


@dataclass
class GateResult:
    """Result of CI gate evaluation."""

    verdict: GateVerdict
    mode: GateMode
    deficit_score: float
    message: str
    failed_files: List[str] = field(default_factory=list)
    warned_files: List[str] = field(default_factory=list)
    quarantined_files: List[str] = field(default_factory=list)
    should_fail_build: bool = False
    pr_comment: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "mode": self.mode.value,
            "deficit_score": self.deficit_score,
            "message": self.message,
            "failed_files": self.failed_files,
            "warned_files": self.warned_files,
            "quarantined_files": self.quarantined_files,
            "should_fail_build": self.should_fail_build,
            "pr_comment": self.pr_comment,
        }
