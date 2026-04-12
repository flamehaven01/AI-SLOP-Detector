"""LEDA injection surface for SPAR-adjacent review."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from slop_detector.config import Config
from slop_detector.history import HistoryTracker
from slop_detector.ml.self_calibrator import SelfCalibrator


def build_leda_injection(
    result: Any,
    *,
    path: str,
    config_path: str | None = None,
    profile: str = "restricted",
) -> dict[str, Any]:
    """Build a YAML-serializable LEDA injection payload from live code analysis."""
    project_root = _resolve_project_root(path)
    config = Config(config_path=config_path)
    tracker = HistoryTracker()
    calibrator = SelfCalibrator(db_path=tracker.db_path)
    calibration = calibrator.calibrate(current_weights=config.get_weights())

    payload = {
        "version": "0.1",
        "project": {
            "name": project_root.name,
            "root": str(project_root),
            "type": _detect_project_type(project_root),
        },
        "source": {
            "analyzer": "LEDA",
            "generated_at": _utc_now(),
            "config_path": str(Path(config_path).resolve()) if config_path else None,
            "history_db": str(tracker.db_path),
        },
        "security": {
            "classification": profile,
            "shareable": profile == "public",
            "warning": "Raw LEDA injection may expose implementation weaknesses and should be treated as sensitive review context.",
        },
        "analysis": _build_analysis_summary(result),
        "calibration": _build_calibration_summary(calibration, tracker),
        "claim_risk": _build_claim_risk(result, calibration, config),
        "maturity": _build_maturity_summary(result, calibration),
        "overrides": _build_override_summary(config, profile=profile),
        "spar_review_hints": _build_spar_hints(result, calibration, config),
    }
    return redact_leda_injection(payload, profile=profile)


def write_leda_injection(output_path: str | Path, payload: dict[str, Any]) -> Path:
    """Write LEDA injection YAML to disk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )
    return path.resolve()


def redact_leda_injection(payload: dict[str, Any], *, profile: str) -> dict[str, Any]:
    """Redact LEDA payload according to a sharing profile."""
    if profile not in {"internal", "restricted", "public"}:
        raise ValueError("profile must be one of: internal, restricted, public")

    if profile == "internal":
        payload.setdefault("security", {})
        payload["security"]["classification"] = "internal"
        payload["security"]["ingestible_by_spar"] = True
        return payload

    redacted = deepcopy(payload)
    redacted.setdefault("security", {})
    redacted["security"]["classification"] = profile
    redacted["security"]["ingestible_by_spar"] = profile != "public"
    redacted["project"].pop("root", None)
    redacted["source"]["config_path"] = None
    redacted["source"]["history_db"] = None

    if profile == "restricted":
        for risk in redacted.get("claim_risk", []):
            risk.pop("evidence", None)
        return redacted

    # public profile
    total_risks = len(redacted.get("claim_risk", []))
    high_risks = sum(1 for risk in redacted.get("claim_risk", []) if risk.get("severity") == "high")
    redacted["claim_risk"] = []
    redacted["claim_risk_summary"] = {
        "total": total_risks,
        "high_severity": high_risks,
    }
    redacted["analysis"].pop("file_path", None)
    redacted["analysis"].pop("total_files", None)
    redacted["analysis"].pop("deficit_files", None)
    redacted["analysis"].pop("clean_files", None)
    redacted["calibration"] = {
        "status": redacted.get("calibration", {}).get("status"),
        "history_records": redacted.get("calibration", {}).get("history_records", 0),
    }
    redacted["maturity"] = {
        "suggested_current": redacted.get("maturity", {}).get("suggested_current")
    }
    redacted["overrides"] = {
        "configured_override_count": redacted.get("overrides", {}).get(
            "configured_override_count", 0
        ),
    }
    redacted["spar_review_hints"] = {
        "preferred_layers": [],
        "registry_candidates": [],
        "notes": ["Public LEDA payloads are publication-safe summaries, not review inputs."],
    }
    return redacted


def _resolve_project_root(path: str) -> Path:
    candidate = Path(path).resolve()
    return candidate if candidate.is_dir() else candidate.parent


def _detect_project_type(path: Path) -> str:
    if (path / "package.json").exists():
        return "javascript"
    if (path / "go.mod").exists():
        return "go"
    return "python"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_analysis_summary(result: Any) -> dict[str, Any]:
    if hasattr(result, "project_path"):
        return {
            "mode": "project",
            "status": str(getattr(result.overall_status, "value", result.overall_status)),
            "total_files": getattr(result, "total_files", 0),
            "deficit_files": getattr(result, "deficit_files", 0),
            "clean_files": getattr(result, "clean_files", 0),
            "avg_deficit_score": round(getattr(result, "avg_deficit_score", 0.0), 2),
            "weighted_deficit_score": round(getattr(result, "weighted_deficit_score", 0.0), 2),
        }
    return {
        "mode": "file",
        "status": str(getattr(result.status, "value", result.status)),
        "deficit_score": round(getattr(result, "deficit_score", 0.0), 2),
        "file_path": getattr(result, "file_path", ""),
    }


def _build_calibration_summary(calibration: Any, tracker: HistoryTracker) -> dict[str, Any]:
    return {
        "status": getattr(calibration, "status", "insufficient_data"),
        "history_records": tracker.count_total_records(),
        "unique_files": getattr(calibration, "unique_files", 0),
        "improvement_events": getattr(calibration, "improvement_events", 0),
        "fp_candidates": getattr(calibration, "fp_candidates", 0),
        "confidence_gap": getattr(calibration, "confidence_gap", 0.0),
        "current_weights": getattr(calibration, "current_weights", {}),
        "optimal_weights": getattr(calibration, "optimal_weights", {}),
    }


def _build_claim_risk(result: Any, calibration: Any, config: Config) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    status = _result_status(result)
    if status in {"critical_deficit", "suspicious", "inflated_signal", "dependency_noise"}:
        risks.append(
            {
                "id": "analysis_surface_instability",
                "severity": "high" if status == "critical_deficit" else "medium",
                "layer_hint": "Layer B/Layer C",
                "finding": "Current analysis surface indicates that implementation quality and outward-facing claims may diverge.",
                "evidence": [f"status={status}"],
                "suggested_action": "Review the claim surface before treating the model as closed or exact.",
            }
        )

    if getattr(calibration, "status", "") in {"ok", "no_change"}:
        risks.append(
            {
                "id": "adaptive_weight_surface_active",
                "severity": "medium",
                "layer_hint": "Layer C",
                "finding": "History-backed calibration is active, so effective review weighting may evolve beyond static documentation.",
                "evidence": [
                    f"calibration_status={getattr(calibration, 'status', 'unknown')}",
                    f"history_records={getattr(calibration, 'improvement_events', 0) + getattr(calibration, 'fp_candidates', 0)}",
                ],
                "suggested_action": "Treat maturity and registry state as a moving review surface, not a fixed declaration.",
            }
        )

    overrides = _configured_domain_overrides(config)
    if overrides:
        risks.append(
            {
                "id": "domain_override_surface",
                "severity": "medium",
                "layer_hint": "Layer B",
                "finding": "Domain-specific override rules are present, so generic complexity judgments are intentionally relaxed in named zones.",
                "evidence": [f"configured_overrides={len(overrides)}"],
                "suggested_action": "Carry override rationale into SPAR interpretation review.",
            }
        )

    return risks


def _build_maturity_summary(result: Any, calibration: Any) -> dict[str, Any]:
    status = _result_status(result)
    if status == "clean":
        suggested = "partial"
        confidence = 0.7
        rationale = "Stable analysis surface supports bounded confidence, but code-quality evidence alone does not justify closure."
    elif status in {"suspicious", "inflated_signal", "dependency_noise"}:
        suggested = "heuristic"
        confidence = 0.55
        rationale = "Analysis indicates unresolved claim-risk or quality drift."
    else:
        suggested = "heuristic"
        confidence = 0.4
        rationale = "Critical or deficit-heavy signals argue against stronger maturity labels."

    if getattr(calibration, "status", "") == "ok":
        confidence = min(0.85, confidence + 0.08)

    return {
        "suggested_current": suggested,
        "confidence": round(confidence, 2),
        "rationale": rationale,
    }


def _build_override_summary(config: Config, *, profile: str) -> dict[str, Any]:
    overrides = _configured_domain_overrides(config)
    if profile == "internal":
        return {
            "configured_domain_overrides": overrides,
            "configured_override_count": len(overrides),
            "suggested_domain_overrides": [],
        }
    return {
        "configured_override_count": len(overrides),
        "suggested_domain_overrides": [],
    }


def _build_spar_hints(result: Any, calibration: Any, config: Config) -> dict[str, Any]:
    preferred_layers = ["Layer C"]
    status = _result_status(result)
    if status in {"suspicious", "inflated_signal", "dependency_noise", "critical_deficit"}:
        preferred_layers.insert(0, "Layer B")
    if _configured_domain_overrides(config):
        preferred_layers.append("Layer A")

    notes = [
        "LEDA is a code-truth surface only. It does not issue final admissibility verdicts.",
        "Use this payload as optional context for SPAR review, alongside runtime result and MICA memory injection.",
    ]
    if getattr(calibration, "status", "") == "insufficient_data":
        notes.append("Calibration evidence is thin; treat maturity hints conservatively.")

    return {
        "preferred_layers": preferred_layers,
        "registry_candidates": ["heuristic", "partial", "environment_conditional"],
        "notes": notes,
    }


def _configured_domain_overrides(config: Config) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for item in config.get("patterns.god_function.domain_overrides", []) or []:
        entries.append(
            {
                "pattern": item.get("function_pattern", ""),
                "complexity_threshold": item.get("complexity_threshold"),
                "lines_threshold": item.get("lines_threshold"),
                "reason": item.get("reason", ""),
            }
        )
    for item in config.get("patterns.nested_complexity.domain_overrides", []) or []:
        entries.append(
            {
                "pattern": item.get("function_pattern", ""),
                "depth_threshold": item.get("depth_threshold"),
                "cc_threshold": item.get("cc_threshold"),
                "reason": item.get("reason", ""),
            }
        )
    return entries


def _result_status(result: Any) -> str:
    if hasattr(result, "overall_status"):
        return str(getattr(result.overall_status, "value", result.overall_status))
    return str(getattr(result.status, "value", result.status))
