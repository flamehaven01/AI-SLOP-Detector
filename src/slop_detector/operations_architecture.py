"""Architecture-layer helpers for cleanup and boundary review."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional

_LAYERED_PRESET = [
    {
        "name": "api",
        "patterns": [
            "src/api/**",
            "**/api/**",
            "**/interfaces/**",
            "**/ui/**",
            "**/routes/**",
            "**/controller/**",
            "**/controllers/**",
            "**/presentation/**",
        ],
        "can_import": ["service", "domain"],
        "cannot_import": ["data"],
    },
    {
        "name": "service",
        "patterns": [
            "src/service/**",
            "src/services/**",
            "**/service/**",
            "**/services/**",
            "**/application/**",
            "**/use_case/**",
            "**/use_cases/**",
        ],
        "can_import": ["domain", "data"],
        "cannot_import": ["api"],
    },
    {
        "name": "domain",
        "patterns": [
            "src/domain/**",
            "**/domain/**",
            "**/model/**",
            "**/models/**",
            "**/entity/**",
            "**/entities/**",
            "**/value_object/**",
            "**/value_objects/**",
        ],
        "can_import": [],
        "cannot_import": ["data", "api", "service"],
    },
    {
        "name": "data",
        "patterns": [
            "src/data/**",
            "**/data/**",
            "**/repository/**",
            "**/repositories/**",
            "**/infrastructure/**",
            "**/adapter/**",
            "**/adapters/**",
        ],
        "can_import": ["domain"],
        "cannot_import": ["api"],
    },
]


def _architecture_layers_from_config(project_path: Path, config) -> List[Dict[str, Any]]:
    architecture = config.get_architecture_config() if config else {}
    if not architecture or not architecture.get("enabled"):
        return []

    normalized = _normalize_architecture_layers(architecture.get("layers") or [])
    if normalized:
        return normalized

    preset = str(architecture.get("preset") or "none").strip().lower()
    if preset == "layered":
        return list(_LAYERED_PRESET)
    return []


def _normalize_architecture_layers(layers: List[Any]) -> List[Dict[str, Any]]:
    normalized = []
    for layer in layers:
        if not isinstance(layer, dict):
            continue
        name = str(layer.get("name") or "").strip()
        patterns = [str(item) for item in (layer.get("patterns") or []) if str(item).strip()]
        if not name or not patterns:
            continue
        normalized.append(
            {
                "name": name,
                "patterns": patterns,
                "can_import": [str(item) for item in (layer.get("can_import") or [])],
                "cannot_import": [str(item) for item in (layer.get("cannot_import") or [])],
            }
        )
    return normalized


def _match_architecture_layer(rel_path: str, layers: List[Dict[str, Any]]) -> Optional[str]:
    normalized = rel_path.replace("\\", "/")
    for layer in layers:
        for pattern in layer.get("patterns", []):
            if fnmatch.fnmatch(normalized, pattern):
                return str(layer["name"])
    return None


def _match_architecture_layer_with_pattern(
    rel_path: str, layers: List[Dict[str, Any]]
) -> tuple[Optional[str], Optional[str]]:
    normalized = rel_path.replace("\\", "/")
    for layer in layers:
        for pattern in layer.get("patterns", []):
            if fnmatch.fnmatch(normalized, pattern):
                return str(layer["name"]), str(pattern)
    return None, None


def _detect_boundary_violations(project_path: Path, cross, config) -> List[Dict[str, Any]]:
    layers = _architecture_layers_from_config(project_path, config)
    if not layers:
        return []

    layer_rules = {str(layer["name"]): set(layer.get("can_import", [])) for layer in layers}
    layer_forbidden = {str(layer["name"]): set(layer.get("cannot_import", [])) for layer in layers}
    issues: List[Dict[str, Any]] = []

    for importer, imported_items in (cross.import_graph or {}).items():
        importer_rel = _project_relative_path(importer, project_path)
        importer_layer, importer_pattern = _match_architecture_layer_with_pattern(
            importer_rel, layers
        )
        if importer_layer is None:
            continue

        for imported in imported_items:
            imported_rel = _project_relative_path(imported, project_path)
            imported_layer, imported_pattern = _match_architecture_layer_with_pattern(
                imported_rel, layers
            )
            if imported_layer is None or imported_layer == importer_layer:
                continue
            issue = _build_boundary_violation_issue(
                importer_rel,
                imported_rel,
                importer_layer,
                imported_layer,
                importer_pattern,
                imported_pattern,
                layer_rules.get(importer_layer, set()),
                layer_forbidden.get(importer_layer, set()),
                config,
            )
            if issue is not None:
                issues.append(issue)
    return issues


def _project_relative_path(path_value: str, project_path: Path) -> str:
    try:
        return str(Path(path_value).resolve().relative_to(project_path.resolve()))
    except Exception:
        return str(path_value)


def _build_boundary_violation_issue(
    importer_rel: str,
    imported_rel: str,
    importer_layer: str,
    imported_layer: str,
    importer_pattern: Optional[str],
    imported_pattern: Optional[str],
    allowed_imports: set[str],
    forbidden_imports: set[str],
    config,
) -> Optional[Dict[str, Any]]:
    is_forbidden = imported_layer in forbidden_imports
    is_not_allowed = bool(allowed_imports) and imported_layer not in allowed_imports
    if not (is_forbidden or is_not_allowed):
        return None
    violation_reason = (
        f"{importer_layer} -> {imported_layer} is explicitly forbidden"
        if is_forbidden
        else f"{importer_layer} -> {imported_layer} is not in the allowed import set"
    )
    return {
        "issue_type": "layer_boundary_violation",
        "importer": importer_rel,
        "importee": imported_rel,
        "importer_layer": importer_layer,
        "importee_layer": imported_layer,
        "display": f"{importer_rel} ({importer_layer}) depends on {imported_rel} ({imported_layer})",
        "confidence": 0.42,
        "action_class": "unsafe_auto_remove",
        "evidence": {
            "preset": str(config.get_architecture_config().get("preset", "custom")),
            "rule": "layer imports must satisfy configured architecture rules",
            "reasons": ["import crosses configured architecture layer order", violation_reason],
            "allowed_imports": sorted(allowed_imports),
            "forbidden_imports": sorted(forbidden_imports),
            "matched_importer_pattern": importer_pattern,
            "matched_importee_pattern": imported_pattern,
        },
    }


def _score_boundary_confidence(cycle: List[str]) -> Dict[str, Any]:
    return {
        "confidence": 0.4,
        "action_class": "unsafe_auto_remove",
        "evidence": {
            "cycle_length": len(cycle),
            "cycle": list(cycle),
            "reasons": ["architectural boundary violation requires structural review"],
        },
    }
