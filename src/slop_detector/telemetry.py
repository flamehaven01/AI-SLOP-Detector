"""Opt-in telemetry payload construction and local queueing."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _telemetry_home() -> Path:
    override = os.getenv("AI_SLOP_DETECTOR_HOME")
    if override:
        return Path(override)
    return Path.home() / ".slop-detector"


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


def _analysis_payload(command: str, result: Any, project_root: Path) -> Dict[str, Any]:
    if hasattr(result, "file_results"):
        analysis = {
            "project_mode": True,
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
            "churn_analysis_available": bool(getattr(result, "churn_analysis_available", False)),
            "coverage_analysis_available": bool(
                getattr(result, "coverage_analysis_available", False)
            ),
        }
    else:
        analysis = {
            "project_mode": False,
            "total_files": 1,
            "deficit_files": (
                0
                if str(
                    getattr(
                        getattr(result, "status", None),
                        "value",
                        getattr(result, "status", "unknown"),
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
            "churn_analysis_available": False,
            "coverage_analysis_available": False,
        }

    return {
        "schema_version": 1,
        "timestamp_utc": _utc_now(),
        "event": "analysis_run",
        "command": command,
        "project_id": _project_id_for(project_root),
        "session": {
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": platform.system().lower(),
            "ci": bool(os.getenv("CI")),
        },
        "analysis": analysis,
    }


@dataclass
class TelemetryManager:
    """Manage opt-in telemetry state and local event queue."""

    config_path: Optional[Path] = None
    queue_path: Optional[Path] = None

    def __post_init__(self) -> None:
        home = _telemetry_home()
        self.config_path = self.config_path or home / "telemetry.json"
        self.queue_path = self.queue_path or home / "telemetry-events.jsonl"

    def _default_config(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "enabled": False,
            "updated_at_utc": _utc_now(),
        }

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return self._default_config()
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return self._default_config()

    def _save_config(self, document: Dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        document["updated_at_utc"] = _utc_now()
        self.config_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    def status(self) -> Dict[str, Any]:
        config = self._load_config()
        queued_events = 0
        if self.queue_path.exists():
            try:
                queued_events = sum(
                    1 for _ in self.queue_path.read_text(encoding="utf-8").splitlines() if _.strip()
                )
            except OSError:
                queued_events = 0
        return {
            "enabled": bool(config.get("enabled", False)),
            "config_path": str(self.config_path),
            "queue_path": str(self.queue_path),
            "queued_events": queued_events,
        }

    def enable(self) -> Dict[str, Any]:
        config = self._load_config()
        config["enabled"] = True
        self._save_config(config)
        return self.status()

    def disable(self) -> Dict[str, Any]:
        config = self._load_config()
        config["enabled"] = False
        self._save_config(config)
        return self.status()

    def build_payload(self, command: str, result: Any, project_root: Path) -> Dict[str, Any]:
        return _analysis_payload(command, result, project_root)

    def example_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "event": "analysis_run",
            "command": "review",
            "project_id": "ab12cd34ef56",
            "session": {
                "python_version": "3.11.0",
                "platform": "linux",
                "ci": False,
            },
            "analysis": {
                "project_mode": True,
                "total_files": 120,
                "deficit_files": 18,
                "issue_count": 57,
                "weighted_deficit_score": 21.3478,
                "overall_status": "clean",
                "churn_analysis_available": True,
                "coverage_analysis_available": True,
            },
        }

    def capture(self, command: str, result: Any, project_root: Path) -> Optional[Dict[str, Any]]:
        payload = self.build_payload(command, result, project_root)
        if os.getenv("AI_SLOP_DETECTOR_TELEMETRY", "").strip().lower() == "inspect":
            return payload
        if not self._load_config().get("enabled", False):
            return None
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        with self.queue_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
        return payload
