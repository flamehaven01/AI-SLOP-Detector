"""Local repository impact tracking for repeated slop-detector use."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_id_for(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:12]


def _issue_count_from_result(result: Any) -> int:
    if hasattr(result, "file_results"):
        python_count = sum(
            len(getattr(item, "pattern_issues", []) or []) for item in result.file_results
        )
        js_count = sum(
            len(getattr(item, "issues", []) or [])
            for item in getattr(result, "js_file_results", []) or []
        )
        go_count = sum(
            len(getattr(item, "issues", []) or [])
            for item in getattr(result, "go_file_results", []) or []
        )
        return python_count + js_count + go_count
    return len(getattr(result, "pattern_issues", []) or [])


def _build_snapshot(command: str, result: Any) -> Dict[str, Any]:
    if hasattr(result, "file_results"):
        return {
            "timestamp": _utc_now(),
            "command": command,
            "total_files": int(getattr(result, "total_files", 0) or 0),
            "deficit_files": int(getattr(result, "deficit_files", 0) or 0),
            "issue_count": _issue_count_from_result(result),
            "weighted_deficit_score": round(
                float(getattr(result, "weighted_deficit_score", 0.0) or 0.0), 4
            ),
            "overall_status": getattr(
                getattr(result, "overall_status", None),
                "value",
                str(getattr(result, "overall_status", "unknown")),
            ),
        }
    return {
        "timestamp": _utc_now(),
        "command": command,
        "total_files": 1,
        "deficit_files": (
            0
            if str(
                getattr(
                    getattr(result, "status", None), "value", getattr(result, "status", "unknown")
                )
            )
            == "clean"
            else 1
        ),
        "issue_count": _issue_count_from_result(result),
        "weighted_deficit_score": round(float(getattr(result, "deficit_score", 0.0) or 0.0), 4),
        "overall_status": getattr(
            getattr(result, "status", None), "value", str(getattr(result, "status", "unknown"))
        ),
    }


@dataclass
class ImpactTracker:
    """Keep a local, gitignored record of repo-level detector impact."""

    project_root: Path
    impact_path: Optional[Path] = None
    max_runs: int = 50

    def __post_init__(self) -> None:
        self.project_root = self.project_root.resolve()
        self.impact_path = self.impact_path or self.project_root / ".slop-detector" / "impact.json"

    def _impact_path(self) -> Path:
        assert self.impact_path is not None
        return self.impact_path

    def _default_document(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "enabled": False,
            "project_id": _project_id_for(self.project_root),
            "project_root": str(self.project_root),
            "updated_at_utc": _utc_now(),
            "runs": [],
        }

    def _load(self) -> Dict[str, Any]:
        impact_path = self._impact_path()
        if not impact_path.exists():
            return self._default_document()
        try:
            return json.loads(impact_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return self._default_document()

    def _save(self, document: Dict[str, Any]) -> None:
        impact_path = self._impact_path()
        impact_path.parent.mkdir(parents=True, exist_ok=True)
        document["updated_at_utc"] = _utc_now()
        impact_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    def enable(self) -> Dict[str, Any]:
        document = self._load()
        document["enabled"] = True
        self._save(document)
        return document

    def disable(self) -> Dict[str, Any]:
        document = self._load()
        document["enabled"] = False
        self._save(document)
        return document

    def status(self) -> Dict[str, Any]:
        document = self._load()
        return {
            "enabled": bool(document.get("enabled", False)),
            "impact_path": str(self._impact_path()),
            "project_id": document.get("project_id", _project_id_for(self.project_root)),
            "runs_recorded": len(document.get("runs", []) or []),
        }

    def record(self, command: str, result: Any) -> Optional[Dict[str, Any]]:
        document = self._load()
        if not document.get("enabled", False):
            return None
        runs = list(document.get("runs", []) or [])
        runs.append(_build_snapshot(command, result))
        document["runs"] = runs[-self.max_runs :]
        self._save(document)
        return document["runs"][-1]

    def summary(self) -> Dict[str, Any]:
        document = self._load()
        runs = list(document.get("runs", []) or [])
        latest = runs[-1] if runs else None
        previous = runs[-2] if len(runs) >= 2 else None
        score_delta = None
        issue_delta = None
        direction = "stable"
        if latest and previous:
            score_delta = round(
                float(latest.get("weighted_deficit_score", 0.0))
                - float(previous.get("weighted_deficit_score", 0.0)),
                4,
            )
            issue_delta = int(latest.get("issue_count", 0)) - int(previous.get("issue_count", 0))
            if score_delta < 0:
                direction = "improved"
            elif score_delta > 0:
                direction = "degraded"
        return {
            "enabled": bool(document.get("enabled", False)),
            "impact_path": str(self._impact_path()),
            "project_id": document.get("project_id", _project_id_for(self.project_root)),
            "runs_recorded": len(runs),
            "latest_run": latest,
            "previous_run": previous,
            "score_delta": score_delta,
            "issue_delta": issue_delta,
            "direction": direction,
        }
