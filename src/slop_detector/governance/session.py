"""
CR-EP v2.7.2 compatible analysis session.

Generates .cr-ep/ evidence artifacts for each analysis run.
Artifacts: session.json, why_gate.json, scope_declaration.json,
           enforcement_log.jsonl, change_events.jsonl, review_contract.json
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CR_EP_VERSION = "2.7.2"
_SEVERITY_RISK = {"critical": 0.9, "high": 0.6, "medium": 0.3, "low": 0.1}


@dataclass
class AnalysisSession:
    """
    CR-EP-compatible session for a slop analysis run.

    Writes evidence artifacts to <project_root>/.cr-ep/ so the analysis
    session is auditable and replayable under CR-EP governance.
    """

    project_path: Path
    mode: str = "standard"  # nano | lite | standard | full
    trust_tier: str = "PEER"  # HUMAN | PEER | UNTRUSTED
    declared_why: str = "Detect AI-generated code quality issues"

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _events: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    _enforcement_log: List[Dict[str, Any]] = field(default_factory=list, repr=False)
    _gate_decisions: List[Dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.cr_ep_dir = Path(self.project_path) / ".cr-ep"
        self.cr_ep_dir.mkdir(exist_ok=True)
        self._write_session()
        self._write_why_gate()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_file_analyzed(
        self,
        file_path: str,
        slop_score: float,
        status: str,
        issues_count: int,
        gate_decision: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a file analysis event."""
        event = {
            "event_type": "file_analyzed",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "file": file_path,
            "slop_score": slop_score,
            "status": status,
            "issues_count": issues_count,
        }
        self._events.append(event)
        if gate_decision:
            self._gate_decisions.append({"file": file_path, "gate": gate_decision})

    def record_fix_applied(self, file_path: str, pattern_id: str, line: int) -> None:
        """Record an auto-fix event."""
        self._events.append(
            {
                "event_type": "fix_applied",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "file": file_path,
                "pattern_id": pattern_id,
                "line": line,
            }
        )

    def record_enforcement(self, rule: str, result: str, detail: str = "") -> None:
        """Record a governance enforcement action."""
        self._enforcement_log.append(
            {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "rule": rule,
                "result": result,
                "detail": detail,
            }
        )

    def finalize(
        self,
        files_planned: List[str],
        files_actual: List[str],
        total_issues: int,
        halt_count: int,
    ) -> Path:
        """
        Write all CR-EP artifacts and return the .cr-ep/ directory path.
        """
        self._write_scope_declaration(files_planned, files_actual)
        self._write_change_events()
        self._write_enforcement_log()
        self._write_review_contract(total_issues, halt_count)
        return self.cr_ep_dir

    # ------------------------------------------------------------------
    # Artifact writers
    # ------------------------------------------------------------------

    def _write_session(self) -> None:
        data = {
            "cr_ep_version": CR_EP_VERSION,
            "session_id": self.session_id,
            "mode": self.mode,
            "trust_tier": self.trust_tier,
            "working_path": str(self.project_path),
            "started_at_utc": self.started_at.isoformat(),
            "dm1_metric": 0.0,
            "dt3_review_threshold": 0.20,
            "mode_upgrade_history": [],
            "tool": "ai-slop-detector",
        }
        self._write_json("session.json", data)

    def _write_why_gate(self) -> None:
        data = {
            "wq_1": "Detect AI-generated code quality deficits in target project",
            "wq_2": "Run LDR/BCR/DDC metrics + pattern detection on all Python/JS files",
            "wq_3": "Produce actionable report with gate decisions and optional auto-fix",
            "q3_scaffold_used": True,
            "q3_results": {
                "approach": "hybrid_metric_pattern",
                "gate_model": "SNP_GateDecision_compatible",
                "cr_ep_profile": self.mode,
            },
            "declared_why": self.declared_why,
        }
        self._write_json("why_gate.json", data)

    def _write_scope_declaration(self, planned: List[str], actual: List[str]) -> None:
        planned_count = len(planned)
        actual_count = len(actual)
        overshoot = (actual_count - planned_count) / max(planned_count, 1)
        data = {
            "depends_on_why_gate": True,
            "why_gate_snapshot_wq1": "Detect AI-generated code quality deficits",
            "generated_after_utc": datetime.now(timezone.utc).isoformat(),
            "planned_files": planned,
            "planned_touchpoints": planned_count,
            "sd0_confirmed": True,
            "actual_files": actual,
            "actual_score": actual_count,
            "overshoot_ratio": round(overshoot, 4),
            "overshoot_formula": "(actual - planned) / max(planned, 1)",
            "overshoot_interpretation": (
                "within_bounds" if overshoot <= 0.20 else "overshoot_detected"
            ),
            "dm1_triggered": overshoot > 0.20,
        }
        self._write_json("scope_declaration.json", data)

    def _write_change_events(self) -> None:
        path = self.cr_ep_dir / "change_events.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for event in self._events:
                f.write(json.dumps(event) + "\n")

    def _write_enforcement_log(self) -> None:
        path = self.cr_ep_dir / "enforcement_log.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for entry in self._enforcement_log:
                f.write(json.dumps(entry) + "\n")

    def _write_review_contract(self, total_issues: int, halt_count: int) -> None:
        risk = min(1.0, (total_issues * 0.02) + (halt_count * 0.10))
        data = {
            "declared_why": self.declared_why,
            "risk_score": round(risk, 4),
            "scope_variance": len(self._events),
            "drift_events": [
                e for e in self._events if e.get("status") in {"suspicious", "critical_deficit"}
            ],
            "hard_line_conflicts": halt_count,
            "required_revalidation": halt_count > 0,
            "approval_required": halt_count > 5,
            "gate_decisions": self._gate_decisions,
            "session_id": self.session_id,
            "finalized_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json("review_contract.json", data)

    def _write_json(self, filename: str, data: Dict[str, Any]) -> None:
        path = self.cr_ep_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
