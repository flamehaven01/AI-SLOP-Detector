"""Operational command helpers for review, cleanup, and watch workflows."""

from __future__ import annotations

import ast
import fnmatch
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from slop_detector.analysis.cross_file import CrossFileAnalyzer
from slop_detector.ci_gate import CIGate
from slop_detector.gate.models import GateMode
from slop_detector.patterns.python_imports import _discover_project_packages, _find_project_root
from slop_detector.renderer_markdown import get_mitigation

try:
    import tomllib
except ImportError:  # pragma: no cover - py38 fallback
    import tomli as tomllib  # type: ignore[import-not-found,assignment]

try:
    from importlib.metadata import packages_distributions
except ImportError:  # pragma: no cover - py38 fallback
    packages_distributions = None

_JS_IMPORT_RE = re.compile(
    r"""(?:import\s+(?:.+?\s+from\s+)?|export\s+.+?\s+from\s+|require\()\s*['"]([^'"]+)['"]"""
)
_NODE_BUILTINS = frozenset(
    {
        "assert",
        "buffer",
        "child_process",
        "crypto",
        "events",
        "fs",
        "http",
        "https",
        "net",
        "os",
        "path",
        "stream",
        "timers",
        "url",
        "util",
        "zlib",
    }
)
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


def _run_git(args: List[str], cwd: Path) -> List[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def get_changed_files(project_path: Path, base_ref: str = "HEAD") -> List[str]:
    """Return repo-relative changed files for an audit baseline."""
    root = project_path.resolve()
    diffs = _run_git(
        ["diff", "--name-only", "--diff-filter=ACM", f"{base_ref}...HEAD"],
        cwd=root,
    )
    if diffs:
        return diffs
    diffs = _run_git(["diff", "--name-only", "--diff-filter=ACM"], cwd=root)
    return diffs


def _top_targets(result, limit: int = 10) -> List[Dict[str, Any]]:
    hotspots = list(getattr(result, "priority_hotspots", []) or [])
    if hotspots:
        return [
            {
                "file_path": h.file_path,
                "priority_score": h.priority_score,
                "deficit_score": h.deficit_score,
                "reasons": list(h.reasons),
                "coverage_ratio": h.coverage_ratio,
                "churn_count": h.churn_count,
            }
            for h in hotspots[:limit]
        ]

    file_results = sorted(
        getattr(result, "file_results", []) or [],
        key=lambda fr: getattr(fr, "deficit_score", 0.0),
        reverse=True,
    )
    targets: List[Dict[str, Any]] = []
    for fr in file_results[:limit]:
        targets.append(
            {
                "file_path": fr.file_path,
                "priority_score": float(getattr(fr, "deficit_score", 0.0)),
                "deficit_score": float(getattr(fr, "deficit_score", 0.0)),
                "reasons": ["high deficit"] if getattr(fr, "deficit_score", 0.0) >= 30 else [],
                "coverage_ratio": None,
                "churn_count": 0,
            }
        )
    return targets


def _find_findings(result, limit: int = 20) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for fr in sorted(
        getattr(result, "file_results", []) or [],
        key=lambda item: getattr(item, "deficit_score", 0.0),
        reverse=True,
    ):
        if getattr(fr, "deficit_score", 0.0) < 30 and not getattr(fr, "pattern_issues", []):
            continue
        findings.append(
            {
                "file_path": fr.file_path,
                "status": getattr(fr.status, "value", str(fr.status)),
                "deficit_score": getattr(fr, "deficit_score", 0.0),
                "introduced": False,
                "issues": [
                    getattr(issue, "pattern_id", str(issue))
                    for issue in getattr(fr, "pattern_issues", [])[:10]
                ],
            }
        )
        if len(findings) >= limit:
            break
    return findings


def _relative_project_path(file_path: str, project_path: Path) -> str:
    path_obj = Path(file_path)
    try:
        return str(path_obj.resolve().relative_to(project_path.resolve()))
    except Exception:
        return str(path_obj)


def _looks_like_dead_code(file_path: str) -> bool:
    """Return True for obvious placeholder / dead-code only files."""
    path = Path(file_path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return False

    if "TODO" in source or "FIXME" in source:
        return True

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body:
            if all(isinstance(item, (ast.Pass, ast.Expr)) for item in body):
                if any(isinstance(item, ast.Pass) for item in body):
                    return True
                if any(
                    isinstance(item, ast.Expr)
                    and isinstance(getattr(item, "value", None), ast.Constant)
                    and getattr(item.value, "value", None) in (Ellipsis, "")
                    for item in body
                ):
                    return True
    return False


def _build_hotspot_index(result) -> Dict[str, Any]:
    index: Dict[str, Any] = {}
    for hotspot in list(getattr(result, "priority_hotspots", []) or []):
        try:
            key = str(Path(hotspot.file_path).resolve())
        except Exception:
            key = str(hotspot.file_path)
        index[key] = hotspot
    return index


def _find_file_result(result, file_path: str):
    for file_result in list(getattr(result, "file_results", []) or []):
        try:
            if Path(file_result.file_path).resolve() == Path(file_path).resolve():
                return file_result
        except Exception:
            if file_result.file_path == file_path:
                return file_result
    return None


def _clamp_confidence(value: float) -> float:
    return round(max(0.05, min(0.95, value)), 2)


def _classify_action(confidence: float) -> str:
    if confidence >= 0.75:
        return "safe_review"
    if confidence >= 0.45:
        return "needs_review"
    return "unsafe_auto_remove"


def _cleanup_file_evidence(result, file_path: str) -> Dict[str, Any]:
    hotspot = _build_hotspot_index(result).get(str(Path(file_path).resolve()))
    file_result = _find_file_result(result, file_path)
    evidence = {
        "deficit_score": None,
        "churn_count": 0,
        "churn_score": 0.0,
        "coverage_ratio": None,
        "reasons": [],
    }
    if file_result is not None:
        evidence["deficit_score"] = round(float(getattr(file_result, "deficit_score", 0.0)), 4)
    if hotspot is not None:
        evidence["deficit_score"] = round(float(getattr(hotspot, "deficit_score", 0.0)), 4)
        evidence["churn_count"] = int(getattr(hotspot, "churn_count", 0) or 0)
        evidence["churn_score"] = round(float(getattr(hotspot, "churn_score", 0.0) or 0.0), 4)
        coverage_ratio = getattr(hotspot, "coverage_ratio", None)
        evidence["coverage_ratio"] = (
            None if coverage_ratio is None else round(float(coverage_ratio), 4)
        )
        evidence["reasons"] = list(getattr(hotspot, "reasons", []) or [])
    return evidence


def _canonical_dep_name(name: str) -> str:
    return name.strip().replace("-", "_").lower()


def _pep508_name(spec: str) -> str:
    cleaned = spec.strip()
    if "[" in cleaned:
        cleaned = cleaned.split("[", 1)[0]
    for marker in [";", ">=", "<=", "==", "!=", "~=", ">", "<", " "]:
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0]
    return _canonical_dep_name(cleaned)


def _module_to_distribution(module_name: str) -> str:
    canonical = _canonical_dep_name(module_name.split(".", 1)[0])
    if packages_distributions is not None:
        try:
            mapping = packages_distributions() or {}
            dists = mapping.get(module_name) or mapping.get(module_name.split(".", 1)[0]) or []
            if dists:
                return _canonical_dep_name(dists[0])
        except Exception:
            pass
    return canonical


def _scan_python_manifest_hygiene(project_path: Path, result) -> List[Dict[str, Any]]:
    pyproject = project_path / "pyproject.toml"
    if not pyproject.exists():
        return []

    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return []

    project_data = data.get("project", {})
    declared_raw = list(project_data.get("dependencies", []) or [])
    for extras in (project_data.get("optional-dependencies", {}) or {}).values():
        declared_raw.extend(list(extras or []))
    declared = {_pep508_name(spec): spec for spec in declared_raw if _pep508_name(spec)}
    if not declared:
        return []

    internal_packages = (
        _discover_project_packages(_find_project_root(project_path / "dummy.py") or project_path)
        or frozenset()
    )
    imported_modules = set()
    for fr in list(getattr(result, "file_results", []) or []):
        for imported in list(getattr(fr.ddc, "imported", []) or []):
            top_level = imported.split(".", 1)[0]
            if _canonical_dep_name(top_level) in internal_packages:
                continue
            imported_modules.add(top_level)

    imported_dists = {_module_to_distribution(name) for name in imported_modules}
    issues: List[Dict[str, Any]] = []

    unused_declared = sorted(name for name in declared if name not in imported_dists)
    for dep_name in unused_declared:
        issues.append(
            {
                "issue_type": "manifest_unused_dependency",
                "manifest": "pyproject.toml",
                "dependency": declared[dep_name],
                "confidence": 0.78,
                "action_class": "safe_review",
                "evidence": {
                    "declared_dependency": declared[dep_name],
                    "imported_distributions": sorted(imported_dists),
                    "reasons": ["declared in pyproject.toml but not observed in analyzed imports"],
                },
            }
        )

    undeclared = sorted(name for name in imported_dists if name and name not in declared)
    for dep_name in undeclared:
        issues.append(
            {
                "issue_type": "undeclared_import",
                "manifest": "pyproject.toml",
                "dependency": dep_name,
                "confidence": 0.72,
                "action_class": "needs_review",
                "evidence": {
                    "imported_distribution": dep_name,
                    "declared_dependencies": sorted(declared.keys()),
                    "reasons": ["import observed but dependency is not declared in pyproject.toml"],
                },
            }
        )

    return issues


def _scan_js_manifest_hygiene(project_path: Path) -> List[Dict[str, Any]]:
    package_json = project_path / "package.json"
    if not package_json.exists():
        return []

    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return []

    declared_sections = {
        "dependencies": data.get("dependencies", {}) or {},
        "devDependencies": data.get("devDependencies", {}) or {},
        "optionalDependencies": data.get("optionalDependencies", {}) or {},
        "peerDependencies": data.get("peerDependencies", {}) or {},
    }
    declared: Dict[str, str] = {}
    for section, deps in declared_sections.items():
        for name in deps:
            declared[_canonical_dep_name(name)] = section
    if not declared:
        return []

    imported_modules = set()
    for path in project_path.rglob("*"):
        if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            continue
        if any(part in {"node_modules", ".git", "dist", "build", ".venv"} for part in path.parts):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _JS_IMPORT_RE.findall(content):
            if not match or match.startswith(".") or match.startswith("/"):
                continue
            top_level = match.split("/", 1)[0]
            if top_level.startswith("@") and "/" in match:
                top_level = "/".join(match.split("/", 2)[:2])
            if top_level.startswith("node:"):
                top_level = top_level.split(":", 1)[1]
            canonical = _canonical_dep_name(top_level)
            if canonical in _NODE_BUILTINS:
                continue
            imported_modules.add(canonical)

    if not imported_modules:
        return []

    issues: List[Dict[str, Any]] = []
    unused_declared = sorted(name for name in declared if name not in imported_modules)
    for dep_name in unused_declared:
        issues.append(
            {
                "issue_type": "manifest_unused_dependency",
                "manifest": "package.json",
                "dependency": dep_name,
                "confidence": 0.78,
                "action_class": "safe_review",
                "evidence": {
                    "declared_dependency": dep_name,
                    "section": declared[dep_name],
                    "imported_modules": sorted(imported_modules),
                    "reasons": [
                        "declared in package.json but not observed in scanned JS/TS imports"
                    ],
                },
            }
        )

    undeclared = sorted(name for name in imported_modules if name not in declared)
    for dep_name in undeclared:
        issues.append(
            {
                "issue_type": "undeclared_import",
                "manifest": "package.json",
                "dependency": dep_name,
                "confidence": 0.72,
                "action_class": "needs_review",
                "evidence": {
                    "imported_module": dep_name,
                    "declared_dependencies": sorted(declared.keys()),
                    "reasons": [
                        "JS/TS import observed but dependency is not declared in package.json"
                    ],
                },
            }
        )

    return issues


def _architecture_layers_from_config(project_path: Path, config) -> List[Dict[str, Any]]:
    architecture = config.get_architecture_config() if config else {}
    if not architecture or not architecture.get("enabled"):
        return []

    layers = architecture.get("layers") or []
    if layers:
        normalized = []
        for layer in layers:
            if not isinstance(layer, dict):
                continue
            name = str(layer.get("name") or "").strip()
            patterns = [str(item) for item in (layer.get("patterns") or []) if str(item).strip()]
            if name and patterns:
                normalized.append(
                    {
                        "name": name,
                        "patterns": patterns,
                        "can_import": [str(item) for item in (layer.get("can_import") or [])],
                        "cannot_import": [str(item) for item in (layer.get("cannot_import") or [])],
                    }
                )
        if normalized:
            return normalized

    preset = str(architecture.get("preset") or "none").strip().lower()
    if preset == "layered":
        return list(_LAYERED_PRESET)
    return []


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
        try:
            importer_rel = str(Path(importer).resolve().relative_to(project_path.resolve()))
        except Exception:
            importer_rel = str(importer)
        importer_layer, importer_pattern = _match_architecture_layer_with_pattern(
            importer_rel, layers
        )
        if importer_layer is None:
            continue

        for imported in imported_items:
            try:
                imported_rel = str(Path(imported).resolve().relative_to(project_path.resolve()))
            except Exception:
                imported_rel = str(imported)
            imported_layer, imported_pattern = _match_architecture_layer_with_pattern(
                imported_rel, layers
            )
            if imported_layer is None or imported_layer == importer_layer:
                continue
            allowed_imports = layer_rules.get(importer_layer, set())
            forbidden_imports = layer_forbidden.get(importer_layer, set())
            is_forbidden = imported_layer in forbidden_imports
            is_not_allowed = bool(allowed_imports) and imported_layer not in allowed_imports
            if is_forbidden or is_not_allowed:
                violation_reason = (
                    f"{importer_layer} -> {imported_layer} is explicitly forbidden"
                    if is_forbidden
                    else f"{importer_layer} -> {imported_layer} is not in the allowed import set"
                )
                issues.append(
                    {
                        "issue_type": "layer_boundary_violation",
                        "importer": importer_rel,
                        "importee": imported_rel,
                        "importer_layer": importer_layer,
                        "importee_layer": imported_layer,
                        "display": (
                            f"{importer_rel} ({importer_layer}) depends on "
                            f"{imported_rel} ({imported_layer})"
                        ),
                        "confidence": 0.42,
                        "action_class": "unsafe_auto_remove",
                        "evidence": {
                            "preset": str(config.get_architecture_config().get("preset", "custom")),
                            "rule": "layer imports must satisfy configured architecture rules",
                            "reasons": [
                                "import crosses configured architecture layer order",
                                violation_reason,
                            ],
                            "allowed_imports": sorted(allowed_imports),
                            "forbidden_imports": sorted(forbidden_imports),
                            "matched_importer_pattern": importer_pattern,
                            "matched_importee_pattern": imported_pattern,
                        },
                    }
                )
    return issues


def _score_dead_code_confidence(
    result, file_path: str, pattern_count: int, placeholder: bool
) -> Dict[str, Any]:
    evidence = _cleanup_file_evidence(result, file_path)
    confidence = 0.45

    deficit_score = float(evidence["deficit_score"] or 0.0)
    churn_score = float(evidence["churn_score"] or 0.0)
    coverage_ratio = evidence["coverage_ratio"]

    if placeholder:
        confidence += 0.15
    if pattern_count > 0:
        confidence += 0.10
    if deficit_score >= 60:
        confidence += 0.10
    elif deficit_score >= 30:
        confidence += 0.05

    if churn_score >= 0.60:
        confidence -= 0.30
    elif churn_score >= 0.30:
        confidence -= 0.15
    elif churn_score == 0.0:
        confidence += 0.10

    if coverage_ratio is not None and coverage_ratio <= 0.10:
        confidence += 0.15
    elif coverage_ratio is not None and coverage_ratio <= 0.30:
        confidence += 0.10
    elif coverage_ratio is not None and coverage_ratio >= 0.60:
        confidence -= 0.15

    confidence = _clamp_confidence(confidence)
    evidence["rule_inputs"] = {
        "pattern_count": pattern_count,
        "placeholder": placeholder,
    }
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": evidence,
    }


def _score_duplicate_confidence(
    result, file_a: str, file_b: str, similarity: float
) -> Dict[str, Any]:
    evidence_a = _cleanup_file_evidence(result, file_a)
    evidence_b = _cleanup_file_evidence(result, file_b)
    max_churn = max(
        float(evidence_a["churn_score"] or 0.0), float(evidence_b["churn_score"] or 0.0)
    )
    coverage_values = [
        value
        for value in [evidence_a["coverage_ratio"], evidence_b["coverage_ratio"]]
        if value is not None
    ]
    min_coverage = min(coverage_values) if coverage_values else None

    confidence = 0.55
    if similarity >= 0.99:
        confidence += 0.15
    elif similarity >= 0.90:
        confidence += 0.10

    if max_churn >= 0.60:
        confidence -= 0.25
    elif max_churn >= 0.30:
        confidence -= 0.10
    elif max_churn == 0.0:
        confidence += 0.05

    if min_coverage is not None and min_coverage <= 0.30:
        confidence += 0.05

    confidence = _clamp_confidence(confidence)
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": {
            "similarity": round(similarity, 4),
            "file_a": evidence_a,
            "file_b": evidence_b,
        },
    }


def _score_unused_dep_confidence(
    result, file_path: str, unused_count: int, usage_ratio: float
) -> Dict[str, Any]:
    evidence = _cleanup_file_evidence(result, file_path)
    confidence = 0.55
    if unused_count >= 3:
        confidence += 0.10
    if usage_ratio <= 0.50:
        confidence += 0.10

    churn_score = float(evidence["churn_score"] or 0.0)
    coverage_ratio = evidence["coverage_ratio"]
    if churn_score >= 0.60:
        confidence -= 0.20
    elif churn_score >= 0.30:
        confidence -= 0.10

    if coverage_ratio is not None and coverage_ratio <= 0.30:
        confidence += 0.05

    confidence = _clamp_confidence(confidence)
    evidence["rule_inputs"] = {
        "unused_count": unused_count,
        "usage_ratio": round(float(usage_ratio), 4),
    }
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": evidence,
    }


def _score_stale_suppression_confidence(
    lineno: int, scope: str, rules: List[str], source: str
) -> Dict[str, Any]:
    confidence = _clamp_confidence(0.85)
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": {
            "lineno": lineno,
            "scope": scope,
            "rules": list(rules),
            "source": source,
            "reasons": ["suppression no longer matches any recorded finding"],
        },
    }


def _score_boundary_confidence(cycle: List[str]) -> Dict[str, Any]:
    confidence = _clamp_confidence(0.40)
    return {
        "confidence": confidence,
        "action_class": _classify_action(confidence),
        "evidence": {
            "cycle_length": len(cycle),
            "cycle": list(cycle),
            "reasons": ["architectural boundary violation requires structural review"],
        },
    }


def build_audit_payload(result, project_path: Path, base_ref: str = "HEAD") -> Dict[str, Any]:
    """Build the changed-code audit JSON contract."""
    gate_result = CIGate(mode=GateMode.HARD).evaluate(result)
    changed = set(get_changed_files(project_path, base_ref=base_ref))
    file_results = list(getattr(result, "file_results", []) or [])
    introduced = []
    inherited = []
    for fr in file_results:
        rel_path = _relative_project_path(fr.file_path, project_path)
        abs_path = str(Path(fr.file_path).resolve())
        changed_names = {Path(p).name for p in changed}
        if (
            rel_path in changed
            or abs_path in changed
            or Path(rel_path).name in changed_names
            or Path(abs_path).name in changed_names
        ):
            introduced.append(rel_path)
        else:
            inherited.append(rel_path)

    actions = [
        {
            "kind": "review",
            "file_path": item["file_path"],
            "priority_score": item["priority_score"],
            "reason": ", ".join(item["reasons"]) if item["reasons"] else "high deficit",
        }
        for item in _top_targets(result, limit=5)
    ]

    return {
        "command": "audit",
        "verdict": getattr(gate_result.verdict, "value", str(gate_result.verdict)),
        "should_fail_build": gate_result.should_fail_build,
        "attribution": {
            "introduced_files": introduced,
            "inherited_files": inherited,
            "introduced_count": len(introduced),
            "inherited_count": len(inherited),
        },
        "summary": {
            "project_path": result.project_path,
            "total_files": result.total_files,
            "deficit_files": result.deficit_files,
            "clean_files": result.clean_files,
            "avg_deficit_score": result.avg_deficit_score,
            "weighted_deficit_score": result.weighted_deficit_score,
            "overall_status": getattr(result.overall_status, "value", str(result.overall_status)),
        },
        "targets": _top_targets(result),
        "actions": actions,
        "findings": _find_findings(result),
        "gate": gate_result.to_dict(),
    }


def build_health_payload(result) -> Dict[str, Any]:
    """Build a health summary centered on next actions."""
    return {
        "command": "health",
        "summary": {
            "project_path": result.project_path,
            "overall_status": getattr(result.overall_status, "value", str(result.overall_status)),
            "weighted_deficit_score": result.weighted_deficit_score,
            "avg_deficit_score": result.avg_deficit_score,
            "avg_ldr": result.avg_ldr,
            "avg_inflation": result.avg_inflation,
            "avg_ddc": result.avg_ddc,
        },
        "targets": _top_targets(result),
        "signals": {
            "churn_analysis_available": getattr(result, "churn_analysis_available", False),
            "coverage_analysis_available": getattr(result, "coverage_analysis_available", False),
            "priority_hotspots": len(getattr(result, "priority_hotspots", []) or []),
        },
    }


def build_cleanup_payload(result, kind: str, config=None) -> Dict[str, Any]:
    """Build a cleanup-focused payload for a family of commands."""
    analyzer = CrossFileAnalyzer()
    project_path = Path(result.project_path)
    cross = analyzer.analyze(str(project_path), result.file_results)
    issues: List[Dict[str, Any]] = []

    if kind == "dead-code":
        for fr in result.file_results:
            placeholder = _looks_like_dead_code(fr.file_path)
            if (
                getattr(fr, "pattern_issues", [])
                or getattr(fr, "deficit_score", 0.0) >= 30
                or placeholder
            ):
                ranking = _score_dead_code_confidence(
                    result,
                    fr.file_path,
                    len(getattr(fr, "pattern_issues", [])),
                    placeholder,
                )
                issues.append(
                    {
                        "file_path": fr.file_path,
                        "deficit_score": getattr(fr, "deficit_score", 0.0),
                        "pattern_count": len(getattr(fr, "pattern_issues", [])),
                        "reason": "dead code placeholder",
                        **ranking,
                    }
                )
    elif kind == "dupes":
        for dup in cross.duplicates:
            ranking = _score_duplicate_confidence(result, dup.file_a, dup.file_b, dup.similarity)
            issues.append(
                {
                    "file_a": dup.file_a,
                    "file_b": dup.file_b,
                    "func_a": dup.func_a,
                    "func_b": dup.func_b,
                    "similarity": dup.similarity,
                    **ranking,
                }
            )
    elif kind == "unused-deps":
        for fr in result.file_results:
            if getattr(fr.ddc, "unused", []):
                ranking = _score_unused_dep_confidence(
                    result,
                    fr.file_path,
                    len(getattr(fr.ddc, "unused", [])),
                    getattr(fr.ddc, "usage_ratio", 0.0),
                )
                issues.append(
                    {
                        "file_path": fr.file_path,
                        "usage_ratio": fr.ddc.usage_ratio,
                        "unused": list(fr.ddc.unused),
                        **ranking,
                    }
                )
        issues.extend(_scan_python_manifest_hygiene(project_path, result))
        issues.extend(_scan_js_manifest_hygiene(project_path))
    elif kind == "stale-suppressions":
        ledger_entries = getattr(result, "suppression_ledger", []) or []
        directives = (
            getattr(result.file_results[0], "suppression_directives", [])
            if result.file_results
            else []
        )
        directive_lines = {entry.directive_line for entry in ledger_entries}
        for directive in directives:
            if directive.lineno not in directive_lines:
                ranking = _score_stale_suppression_confidence(
                    directive.lineno,
                    directive.scope,
                    list(directive.rules),
                    directive.source,
                )
                issues.append(
                    {
                        "lineno": directive.lineno,
                        "scope": directive.scope,
                        "rules": list(directive.rules),
                        "source": directive.source,
                        **ranking,
                    }
                )
    elif kind == "boundary-violations":
        for cycle in cross.import_cycles:
            ranking = _score_boundary_confidence(list(cycle.cycle))
            issues.append(
                {
                    "issue_type": "import_cycle",
                    "cycle": list(cycle.cycle),
                    "display": str(cycle),
                    **ranking,
                }
            )
        issues.extend(_detect_boundary_violations(project_path, cross, config))

    verdict = "fail" if issues else "pass"
    return {
        "command": kind,
        "verdict": verdict,
        "summary": {
            "project_path": result.project_path,
            "issue_count": len(issues),
            "overall_status": getattr(result.overall_status, "value", str(result.overall_status)),
        },
        "issues": issues,
    }


def build_explain_payload(identifier: str) -> Dict[str, Any]:
    """Return a mitigation-oriented explanation for a rule or target name."""
    mapping = {
        "dead-code": ("complex_logic", "Cleanup dead code and simplify branches."),
        "dupes": ("complex_logic", "Deduplicate similar blocks into a shared helper."),
        "unused-deps": ("unused_import", "Remove dependencies that are never used."),
        "stale-suppressions": ("jargon", "Remove suppressions that no longer silence findings."),
        "boundary-violations": (
            "complex_logic",
            "Refactor cross-file dependencies to restore clear boundaries.",
        ),
    }
    issue_key, summary = mapping.get(identifier, ("unknown", "Review the rule or target manually."))
    return {
        "command": "explain",
        "identifier": identifier,
        "summary": {
            "category": identifier,
            "message": summary,
            "mitigation": get_mitigation(issue_key),
        },
        "mitigation": get_mitigation(issue_key),
    }


def render_payload_text(payload: Dict[str, Any]) -> str:
    """Render a compact human-readable view for command payloads."""
    lines = [f"{payload.get('command', 'command').upper()}"]
    verdict = payload.get("verdict")
    if verdict:
        lines.append(f"Verdict: {str(verdict).upper()}")
    summary = payload.get("summary", {})
    if isinstance(summary, dict):
        for key, value in summary.items():
            lines.append(f"{key}: {value}")
    elif summary:
        lines.append(f"summary: {summary}")
    targets = payload.get("targets", [])
    if targets:
        lines.append("Targets:")
        for item in targets[:5]:
            lines.append(f"  - {item['file_path']} ({item.get('reason', 'review')})")
    issues = payload.get("issues", [])
    if issues:
        lines.append("Issues:")
        for item in issues[:5]:
            label = item.get("file_path") or item.get("display") or item.get("lineno")
            lines.append(f"  - {label}")
    return "\n".join(lines)


def render_payload_markdown(payload: Dict[str, Any]) -> str:
    """Render a compact markdown view for command payloads."""
    lines = [f"# {payload.get('command', 'command').title()} Report", ""]
    if payload.get("verdict"):
        lines += [f"**Verdict**: `{str(payload['verdict']).upper()}`", ""]
    summary = payload.get("summary", {})
    if summary:
        lines += ["## Summary", ""]
        if isinstance(summary, dict):
            for key, value in summary.items():
                lines.append(f"- **{key}**: `{value}`")
        else:
            lines.append(f"- `{summary}`")
        lines.append("")
    targets = payload.get("targets", [])
    if targets:
        lines += ["## Targets", "", "| File | Priority | Reason |", "| :--- | :--- | :--- |"]
        for item in targets[:10]:
            lines.append(
                f"| `{Path(item['file_path']).name}` | {item.get('priority_score', 0):.1f} | "
                f"{', '.join(item.get('reasons', [])) or 'review'} |"
            )
        lines.append("")
    issues = payload.get("issues", [])
    if issues:
        lines += ["## Issues", "", "| Item | Details |", "| :--- | :--- |"]
        for item in issues[:10]:
            detail = item.get("display") or item.get("reason") or item.get("file_path") or ""
            lines.append(f"| `{item.get('file_path', item.get('lineno', 'item'))}` | {detail} |")
        lines.append("")
    return "\n".join(lines)


def watch_project(result_factory, interval: float = 2.0, follow: bool = False) -> int:
    """Poll a project scan periodically. `result_factory` returns a fresh payload."""
    try:
        while True:
            payload = result_factory()
            print(render_payload_text(payload))
            if not follow:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        return 130
