"""CI/CD Gate with 3-tier enforcement modes."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from slop_detector.models import FileAnalysis, ProjectAnalysis, SlopStatus


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


class CIGate:
    """CI/CD quality gate with 3-tier enforcement."""

    def __init__(
        self,
        mode: GateMode = GateMode.SOFT,
        thresholds: Optional[GateThresholds] = None,
        quarantine_db_path: Optional[str] = None,
    ):
        """Initialize CI gate."""
        self.mode = mode
        self.thresholds = thresholds or GateThresholds()
        self.quarantine_db_path = quarantine_db_path or ".slop_quarantine.json"
        self.quarantine_records: Dict[str, QuarantineRecord] = {}

        if self.mode == GateMode.QUARANTINE:
            self._load_quarantine_db()

    def evaluate(self, result: ProjectAnalysis | FileAnalysis) -> GateResult:
        """Evaluate analysis result and return gate decision."""
        is_project = isinstance(result, ProjectAnalysis)

        if is_project:
            return self._evaluate_project(result)
        else:
            return self._evaluate_file(result)

    def _evaluate_project(self, result: ProjectAnalysis) -> GateResult:
        """Evaluate project-level analysis."""
        failed_files = []
        warned_files = []
        quarantined_files = []

        # Check each file
        for file_result in result.file_results:
            file_verdict = self._check_file_thresholds(file_result)

            if file_verdict == GateVerdict.FAIL:
                failed_files.append(file_result.file_path)
            elif file_verdict == GateVerdict.WARN:
                warned_files.append(file_result.file_path)
            elif file_verdict == GateVerdict.QUARANTINE:
                quarantined_files.append(file_result.file_path)

        # Determine overall verdict
        if self.mode == GateMode.SOFT:
            verdict = GateVerdict.WARN if (failed_files or warned_files) else GateVerdict.PASS
            should_fail = False
            message = self._generate_soft_message(failed_files, warned_files)

        elif self.mode == GateMode.HARD:
            if failed_files:
                verdict = GateVerdict.FAIL
                should_fail = True
                message = f"Build FAILED: {len(failed_files)} files exceed quality thresholds"
            elif warned_files:
                verdict = GateVerdict.WARN
                should_fail = False
                message = f"Build WARNING: {len(warned_files)} files have quality issues"
            else:
                verdict = GateVerdict.PASS
                should_fail = False
                message = "Build PASSED: All files meet quality standards"

        elif self.mode == GateMode.QUARANTINE:
            # Update quarantine records
            for file_path in failed_files:
                self._update_quarantine(file_path, result)

            # Check if any files should escalate to FAIL
            escalated = [f for f in failed_files if self._should_escalate(f)]

            if escalated:
                verdict = GateVerdict.FAIL
                should_fail = True
                message = f"Build FAILED: {len(escalated)} repeat offenders exceeded thresholds"
            elif failed_files:
                verdict = GateVerdict.QUARANTINE
                should_fail = False
                message = f"Build QUARANTINE: {len(failed_files)} files flagged, tracking violations"
            elif warned_files:
                verdict = GateVerdict.WARN
                should_fail = False
                message = f"Build WARNING: {len(warned_files)} files have quality issues"
            else:
                verdict = GateVerdict.PASS
                should_fail = False
                message = "Build PASSED: All files meet quality standards"

            self._save_quarantine_db()

        else:
            verdict = GateVerdict.PASS
            should_fail = False
            message = "Unknown mode"

        # Generate PR comment
        pr_comment = self._generate_pr_comment(
            result, failed_files, warned_files, quarantined_files
        )

        return GateResult(
            verdict=verdict,
            mode=self.mode,
            deficit_score=result.weighted_deficit_score,
            message=message,
            failed_files=failed_files,
            warned_files=warned_files,
            quarantined_files=quarantined_files,
            should_fail_build=should_fail,
            pr_comment=pr_comment,
        )

    def _evaluate_file(self, result: FileAnalysis) -> GateResult:
        """Evaluate single file analysis."""
        verdict = self._check_file_thresholds(result)

        if self.mode == GateMode.SOFT:
            should_fail = False
            message = f"File quality: {verdict.value.upper()}"

        elif self.mode == GateMode.HARD:
            should_fail = verdict == GateVerdict.FAIL
            message = (
                f"File FAILED quality gate"
                if should_fail
                else f"File quality: {verdict.value.upper()}"
            )

        elif self.mode == GateMode.QUARANTINE:
            if verdict == GateVerdict.FAIL:
                self._update_quarantine(result.file_path, result)
                should_fail = self._should_escalate(result.file_path)
                message = (
                    f"File FAILED (repeat offender)"
                    if should_fail
                    else f"File QUARANTINE (violation tracked)"
                )
                self._save_quarantine_db()
            else:
                should_fail = False
                message = f"File quality: {verdict.value.upper()}"

        else:
            should_fail = False
            message = "Unknown mode"

        failed_files = [result.file_path] if verdict == GateVerdict.FAIL else []
        warned_files = [result.file_path] if verdict == GateVerdict.WARN else []
        quarantined_files = (
            [result.file_path]
            if self.mode == GateMode.QUARANTINE and verdict == GateVerdict.FAIL
            else []
        )

        pr_comment = self._generate_pr_comment(result, failed_files, warned_files, quarantined_files)

        return GateResult(
            verdict=verdict,
            mode=self.mode,
            deficit_score=result.deficit_score,
            message=message,
            failed_files=failed_files,
            warned_files=warned_files,
            quarantined_files=quarantined_files,
            should_fail_build=should_fail,
            pr_comment=pr_comment,
        )

    def _check_file_thresholds(self, file_result: FileAnalysis) -> GateVerdict:
        """Check if file exceeds thresholds."""
        # Count critical and high patterns
        critical_count = sum(
            1 for issue in file_result.pattern_issues if issue.severity.value == "critical"
        )
        high_count = sum(
            1 for issue in file_result.pattern_issues if issue.severity.value == "high"
        )

        # Check FAIL conditions
        if file_result.deficit_score >= self.thresholds.deficit_fail:
            return GateVerdict.FAIL

        if critical_count >= self.thresholds.critical_patterns_fail:
            return GateVerdict.FAIL

        if file_result.inflation.inflation_score >= self.thresholds.inflation_fail:
            return GateVerdict.FAIL

        if file_result.ddc.usage_ratio < self.thresholds.ddc_fail:
            return GateVerdict.FAIL

        # Check WARN conditions
        if file_result.deficit_score >= self.thresholds.deficit_warn:
            return GateVerdict.WARN

        if high_count >= self.thresholds.high_patterns_warn:
            return GateVerdict.WARN

        return GateVerdict.PASS

    def _update_quarantine(self, file_path: str, result: Any) -> None:
        """Update quarantine record for a file."""
        if file_path not in self.quarantine_records:
            self.quarantine_records[file_path] = QuarantineRecord(file_path=file_path)

        record = self.quarantine_records[file_path]
        record.offense_count += 1

        if isinstance(result, FileAnalysis):
            record.last_deficit_score = result.deficit_score
            record.violations.append(
                f"Deficit: {result.deficit_score:.1f}, "
                f"Patterns: {len(result.pattern_issues)}"
            )
        elif isinstance(result, ProjectAnalysis):
            # Find the specific file result
            for file_result in result.file_results:
                if file_result.file_path == file_path:
                    record.last_deficit_score = file_result.deficit_score
                    record.violations.append(
                        f"Deficit: {file_result.deficit_score:.1f}, "
                        f"Patterns: {len(file_result.pattern_issues)}"
                    )
                    break

    def _should_escalate(self, file_path: str) -> bool:
        """Check if file should escalate from quarantine to fail."""
        if file_path not in self.quarantine_records:
            return False

        record = self.quarantine_records[file_path]
        # Escalate after 3 violations
        return record.offense_count >= 3

    def _load_quarantine_db(self) -> None:
        """Load quarantine database from disk."""
        db_path = Path(self.quarantine_db_path)
        if db_path.exists():
            try:
                with open(db_path, "r") as f:
                    data = json.load(f)
                    self.quarantine_records = {
                        path: QuarantineRecord(**record) for path, record in data.items()
                    }
            except Exception:
                # If load fails, start fresh
                self.quarantine_records = {}

    def _save_quarantine_db(self) -> None:
        """Save quarantine database to disk."""
        db_path = Path(self.quarantine_db_path)
        try:
            with open(db_path, "w") as f:
                data = {path: record.to_dict() for path, record in self.quarantine_records.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save quarantine DB: {e}", file=sys.stderr)

    def _generate_soft_message(self, failed_files: List[str], warned_files: List[str]) -> str:
        """Generate message for soft mode."""
        if failed_files and warned_files:
            return f"Quality issues detected: {len(failed_files)} critical, {len(warned_files)} warnings (soft mode - informational only)"
        elif failed_files:
            return f"{len(failed_files)} files have critical quality issues (soft mode - informational only)"
        elif warned_files:
            return f"{len(warned_files)} files have quality warnings (soft mode - informational only)"
        else:
            return "All files meet quality standards"

    def _generate_pr_comment(
        self,
        result: Any,
        failed_files: List[str],
        warned_files: List[str],
        quarantined_files: List[str],
    ) -> str:
        """Generate PR comment with quality report."""
        lines = []

        # Header
        lines.append("## AI Code Quality Report")
        lines.append("")

        # Mode indicator
        mode_emoji = {"soft": "[INFO]", "hard": "[GATE]", "quarantine": "[TRACK]"}
        lines.append(f"**Mode**: {mode_emoji.get(self.mode.value, '')} {self.mode.value.upper()}")
        lines.append("")

        # Summary
        is_project = isinstance(result, ProjectAnalysis)
        if is_project:
            lines.append("### Summary")
            lines.append(
                f"- Analyzed: {result.total_files} files ({result.clean_files} clean, {result.deficit_files} with issues)"
            )
            lines.append(f"- Average Deficit Score: {result.avg_deficit_score:.1f}/100")
            lines.append("")

        # Failed files
        if failed_files:
            lines.append("### [CRITICAL] Failed Quality Checks")
            for file_path in failed_files[:10]:  # Limit to 10
                file_name = Path(file_path).name
                lines.append(f"- `{file_name}`: Exceeds critical thresholds")
            if len(failed_files) > 10:
                lines.append(f"- ... and {len(failed_files) - 10} more")
            lines.append("")

        # Quarantined files
        if quarantined_files:
            lines.append("### [TRACKING] Quarantined Files")
            for file_path in quarantined_files:
                file_name = Path(file_path).name
                if file_path in self.quarantine_records:
                    record = self.quarantine_records[file_path]
                    lines.append(
                        f"- `{file_name}`: {record.offense_count} violations "
                        f"(escalates to FAIL after 3)"
                    )
                else:
                    lines.append(f"- `{file_name}`: 1st violation")
            lines.append("")

        # Warned files
        if warned_files:
            lines.append("### [WARNING] Quality Issues")
            for file_path in warned_files[:5]:  # Limit to 5
                file_name = Path(file_path).name
                lines.append(f"- `{file_name}`: Quality concerns detected")
            if len(warned_files) > 5:
                lines.append(f"- ... and {len(warned_files) - 5} more")
            lines.append("")

        # Recommendations
        if failed_files or warned_files or quarantined_files:
            lines.append("### Recommendations")
            lines.append("Run `slop-detector <file>` locally for detailed analysis and review questions.")
            lines.append("")

        return "\n".join(lines)
