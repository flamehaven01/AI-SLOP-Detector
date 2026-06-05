"""Observability helpers kept separate from the scoring path."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_IMPACT_TRACKED_COMMANDS = {
    "scan",
    "review",
    "pulse",
    "dead-code",
    "dupes",
    "unused-deps",
    "stale-suppressions",
    "boundary-violations",
}


def _public_command_name(command: str) -> str:
    """Map internal command names onto public-facing command names."""
    if command == "audit":
        return "review"
    if command == "health":
        return "pulse"
    return command


def _record_optional_impact(command: str, result) -> None:
    """Record a best-effort local impact snapshot when enabled."""
    if command not in _IMPACT_TRACKED_COMMANDS:
        return
    try:
        from slop_detector.impact import ImpactTracker

        project_root = Path(getattr(result, "project_path", Path.cwd())).resolve()
        if project_root.is_file():
            project_root = project_root.parent
        ImpactTracker(project_root).record(command, result)
    except Exception:
        logging.getLogger(__name__).debug("impact record skipped", exc_info=True)


def _capture_optional_telemetry(command: str, result) -> None:
    """Capture a telemetry payload or inspect it when requested."""
    try:
        from slop_detector.telemetry import TelemetryManager

        project_root = Path(getattr(result, "project_path", Path.cwd())).resolve()
        if project_root.is_file():
            project_root = project_root.parent
        payload = TelemetryManager().capture(command, result, project_root)
        if (
            payload is not None
            and os.getenv("AI_SLOP_DETECTOR_TELEMETRY", "").strip().lower() == "inspect"
        ):
            print(json.dumps(payload, indent=2, ensure_ascii=False), file=sys.stderr)
    except Exception:
        logging.getLogger(__name__).debug("telemetry capture skipped", exc_info=True)
