"""CI/CD Gate with 3-tier enforcement modes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from slop_detector.gate.models import (
    GateMode,
    GateResult,
    GateThresholds,
    GateVerdict,
    QuarantineRecord,
)
from slop_detector.models import FileAnalysis, ProjectAnalysis


class CIGate:
    """CI/CD quality gate with 3-tier enforcement."""

    def __init__(
        self,
        mode: GateMode = GateMode.SOFT,
        thresholds: Optional[GateThresholds] = None,
        quarantine_db_path: Optional[str] = None,
        claims_strict: bool = False,
    ):
        """Initialize CI gate.

        Args:
            mode: Gate enforcement mode (soft/hard/quarantine)
            thresholds: Configurable thresholds for gate decisions
            quarantine_db_path: Path to quarantine database
            claims_strict: Enable claim-based enforcement (v2.6.2)
        """
        self.mode = mode
        self.thresholds = thresholds or GateThresholds()
        self.quarantine_db_path = quarantine_db_path or ".slop_quarantine.json"
        self.claims_strict = claims_strict
        self.quarantine_records: Dict[str, QuarantineRecord] = {}

        if self.mode == GateMode.QUARANTINE:
            self._load_quarantine_db()

    def evaluate(self, result: ProjectAnalysis | FileAnalysis) -> GateResult:
        """Evaluate analysis result and return gate decision."""
        is_project = isinstance(result, ProjectAnalysis)

        if is_project:
            return self._evaluate_project(cast(ProjectAnalysis, result))
        return self._evaluate_file(cast(FileAnalysis, result))

    def _classify_files(self, result: ProjectAnalysis) -> tuple[List[str], List[str], List[str]]:
        """Classify file results into (failed, warned, quarantined) lists."""
        failed, warned, quarantined = [], [], []
        for file_result in result.file_results:
            v = self._check_file_thresholds(file_result)
            if v == GateVerdict.FAIL:
                failed.append(file_result.file_path)
            elif v == GateVerdict.WARN:
                warned.append(file_result.file_path)
            elif v == GateVerdict.QUARANTINE:
                quarantined.append(file_result.file_path)
        return failed, warned, quarantined

    def _verdict_soft(
        self, failed_files: List[str], warned_files: List[str]
    ) -> tuple[GateVerdict, bool, str]:
        verdict = GateVerdict.WARN if (failed_files or warned_files) else GateVerdict.PASS
        return verdict, False, self._generate_soft_message(failed_files, warned_files)

    def _verdict_hard(
        self, failed_files: List[str], warned_files: List[str]
    ) -> tuple[GateVerdict, bool, str]:
        if failed_files:
            return (
                GateVerdict.FAIL,
                True,
                f"Build FAILED: {len(failed_files)} files exceed quality thresholds",
            )
        if warned_files:
            return (
                GateVerdict.WARN,
                False,
                f"Build WARNING: {len(warned_files)} files have quality issues",
            )
        return GateVerdict.PASS, False, "Build PASSED: All files meet quality standards"

    def _verdict_quarantine(
        self, result: ProjectAnalysis, failed_files: List[str], warned_files: List[str]
    ) -> tuple[GateVerdict, bool, str]:
        for file_path in failed_files:
            self._update_quarantine(file_path, result)
        escalated = [f for f in failed_files if self._should_escalate(f)]
        if escalated:
            return (
                GateVerdict.FAIL,
                True,
                f"Build FAILED: {len(escalated)} repeat offenders exceeded thresholds",
            )
        if failed_files:
            return (
                GateVerdict.QUARANTINE,
                False,
                f"Build QUARANTINE: {len(failed_files)} files flagged, tracking violations",
            )
        if warned_files:
            return (
                GateVerdict.WARN,
                False,
                f"Build WARNING: {len(warned_files)} files have quality issues",
            )
        return GateVerdict.PASS, False, "Build PASSED: All files meet quality standards"

    def _evaluate_project(self, result: ProjectAnalysis) -> GateResult:
        """Evaluate project-level analysis."""
        failed_files, warned_files, quarantined_files = self._classify_files(result)
        mode_dispatch = {
            GateMode.SOFT: lambda: self._verdict_soft(failed_files, warned_files),
            GateMode.HARD: lambda: self._verdict_hard(failed_files, warned_files),
            GateMode.QUARANTINE: lambda: self._verdict_quarantine(
                result, failed_files, warned_files
            ),
        }
        dispatch_fn = mode_dispatch.get(self.mode)
        if dispatch_fn:
            verdict, should_fail, message = dispatch_fn()
        else:
            verdict, should_fail, message = GateVerdict.PASS, False, "Unknown mode"
        if self.mode == GateMode.QUARANTINE:
            self._save_quarantine_db()
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

    def _evaluate_file_quarantine(
        self, result: FileAnalysis, verdict: GateVerdict
    ) -> tuple[bool, str]:
        """Handle quarantine-mode evaluation for a single file."""
        if verdict != GateVerdict.FAIL:
            return False, f"File quality: {verdict.value.upper()}"
        self._update_quarantine(result.file_path, result)
        should_fail = self._should_escalate(result.file_path)
        self._save_quarantine_db()
        message = (
            "File FAILED (repeat offender)"
            if should_fail
            else "File QUARANTINE (violation tracked)"
        )
        return should_fail, message

    def _evaluate_file(self, result: FileAnalysis) -> GateResult:
        """Evaluate single file analysis."""
        verdict = self._check_file_thresholds(result)
        if self.mode == GateMode.SOFT:
            should_fail, message = False, f"File quality: {verdict.value.upper()}"
        elif self.mode == GateMode.HARD:
            should_fail = verdict == GateVerdict.FAIL
            message = (
                "File FAILED quality gate"
                if should_fail
                else f"File quality: {verdict.value.upper()}"
            )
        elif self.mode == GateMode.QUARANTINE:
            should_fail, message = self._evaluate_file_quarantine(result, verdict)
        else:
            should_fail, message = False, "Unknown mode"
        failed_files = [result.file_path] if verdict == GateVerdict.FAIL else []
        warned_files = [result.file_path] if verdict == GateVerdict.WARN else []
        quarantined_files = (
            [result.file_path]
            if self.mode == GateMode.QUARANTINE and verdict == GateVerdict.FAIL
            else []
        )
        pr_comment = self._generate_pr_comment(
            result, failed_files, warned_files, quarantined_files
        )
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

    _PRODUCTION_CLAIMS: frozenset = frozenset(
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

    def _has_uncovered_production_claims(self, ctx_jargon: Any) -> bool:
        """Return True if any production claim lacks integration test evidence."""
        if not hasattr(ctx_jargon, "evidence_details"):
            return False
        for evidence in ctx_jargon.evidence_details:
            if evidence.jargon.lower() in self._PRODUCTION_CLAIMS:
                if "tests_integration" in evidence.missing_evidence:
                    return True
        return False

    def _check_claims_evidence(self, file_result: FileAnalysis) -> Optional[GateVerdict]:
        """Check if production claims have required integration test evidence (v2.6.2)."""
        if not self.claims_strict:
            return None
        ctx_jargon = getattr(file_result, "context_jargon", None)
        if not ctx_jargon:
            return None
        if self._has_uncovered_production_claims(ctx_jargon):
            return GateVerdict.FAIL
        return None

    def _check_file_thresholds(self, file_result: FileAnalysis) -> GateVerdict:
        """Check if file exceeds thresholds."""
        # Check claim-based enforcement first (v2.6.2)
        claims_verdict = self._check_claims_evidence(file_result)
        if claims_verdict == GateVerdict.FAIL:
            return GateVerdict.FAIL

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
                f"Deficit: {result.deficit_score:.1f}, Patterns: {len(result.pattern_issues)}"
            )
        elif isinstance(result, ProjectAnalysis):
            file_result = next(
                (fr for fr in result.file_results if fr.file_path == file_path), None
            )
            if file_result:
                record.last_deficit_score = file_result.deficit_score
                record.violations.append(
                    f"Deficit: {file_result.deficit_score:.1f}, "
                    f"Patterns: {len(file_result.pattern_issues)}"
                )

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
                with open(db_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.quarantine_records = {
                        path: QuarantineRecord(**record) for path, record in data.items()
                    }
            except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
                # If load fails, start fresh
                print(f"Warning: Failed to load quarantine DB: {e}", file=sys.stderr)
                self.quarantine_records = {}

    def _save_quarantine_db(self) -> None:
        """Save quarantine database to disk."""
        db_path = Path(self.quarantine_db_path)
        try:
            with open(db_path, "w", encoding="utf-8") as f:
                data = {path: record.to_dict() for path, record in self.quarantine_records.items()}
                json.dump(data, f, indent=2)
        except (OSError, TypeError) as e:
            print(f"Warning: Failed to save quarantine DB: {e}", file=sys.stderr)

    def _generate_soft_message(self, failed_files: List[str], warned_files: List[str]) -> str:
        """Generate message for soft mode."""
        if failed_files and warned_files:
            return f"Quality issues detected: {len(failed_files)} critical, {len(warned_files)} warnings (soft mode - informational only)"
        elif failed_files:
            return f"{len(failed_files)} files have critical quality issues (soft mode - informational only)"
        elif warned_files:
            return (
                f"{len(warned_files)} files have quality warnings (soft mode - informational only)"
            )
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
            lines.append(
                "Run `slop-detector <file>` locally for detailed analysis and review questions."
            )
            lines.append("")

        return "\n".join(lines)
