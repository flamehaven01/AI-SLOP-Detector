"""Manifest-hygiene helpers for cleanup operations."""

from __future__ import annotations

import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from slop_detector.patterns.python_imports import _discover_project_packages, _find_project_root

if sys.version_info >= (3, 11):
    import tomllib as _toml_loader  # type: ignore[import-not-found]
else:  # pragma: no cover - py38 fallback
    _toml_loader = importlib.import_module("tomli")

try:
    from importlib.metadata import packages_distributions
except ImportError:  # pragma: no cover - py38 fallback
    packages_distributions = None  # type: ignore[assignment]

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
            return canonical
    return canonical


def _compute_stdlib_modules() -> frozenset:
    names: set = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)
    if not getattr(sys, "stdlib_module_names", None):
        # Python 3.8/3.9 have no sys.stdlib_module_names; derive the top-level
        # names from the runtime's stdlib directory so pure-Python stdlib modules
        # (abc, collections, ast, ...) are still excluded, not just C built-ins.
        try:
            import sysconfig

            stdlib_dir = sysconfig.get_paths().get("stdlib")
            if stdlib_dir:
                stdlib_path = Path(stdlib_dir)
                if stdlib_path.is_dir():
                    for entry in stdlib_path.iterdir():
                        if entry.suffix == ".py":
                            names.add(entry.stem)
                        elif entry.is_dir() and entry.name.isidentifier():
                            names.add(entry.name)
        except Exception:
            pass
    return frozenset(names)


_STDLIB_MODULES: frozenset = _compute_stdlib_modules()


def _scan_python_manifest_hygiene(project_path: Path, result) -> List[Dict[str, Any]]:
    pyproject = project_path / "pyproject.toml"
    project_data = _load_python_project_data(pyproject)
    if not project_data:
        return []
    declared_main, declared_all = _build_python_declared_dependency_sets(project_data)
    if not declared_all:
        return []

    imported_dists = _collect_python_imported_distributions(project_path, result)
    issues: List[Dict[str, Any]] = []
    # Unused check covers main runtime dependencies only. optional-dependencies
    # (dev/test extras like black, mypy, pytest) are opt-in tools that are not
    # expected to appear in analyzed imports, so flagging them is a false positive.
    issues.extend(_build_python_unused_declared_issues(declared_main, imported_dists))
    # Undeclared check compares imports against ALL declared deps (main + optional)
    # so an import satisfied by an extra is not flagged.
    issues.extend(_build_python_undeclared_issues(declared_all, imported_dists))
    return issues


def _load_python_project_data(pyproject: Path) -> Dict[str, Any]:
    if not pyproject.exists():
        return {}
    try:
        data = _toml_loader.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return {}
    project_data = data.get("project", {})
    return project_data if isinstance(project_data, dict) else {}


def _build_python_declared_dependency_sets(
    project_data: Dict[str, Any],
) -> tuple[Dict[str, str], Dict[str, str]]:
    declared_main = {
        _pep508_name(spec): spec
        for spec in (project_data.get("dependencies", []) or [])
        if _pep508_name(spec)
    }
    declared_all = {
        _pep508_name(spec): spec
        for spec in _collect_python_declared_dependencies(project_data)
        if _pep508_name(spec)
    }
    return declared_main, declared_all


def _collect_python_declared_dependencies(project_data: Dict[str, Any]) -> List[str]:
    declared_raw = list(project_data.get("dependencies", []) or [])
    for extras in (project_data.get("optional-dependencies", {}) or {}).values():
        declared_raw.extend(list(extras or []))
    return declared_raw


def _collect_python_imported_distributions(project_path: Path, result) -> set[str]:
    internal_packages = (
        _discover_project_packages(_find_project_root(project_path / "dummy.py") or project_path)
        or frozenset()
    )
    imported_modules = set()
    for fr in list(getattr(result, "file_results", []) or []):
        for imported in list(getattr(fr.ddc, "imported", []) or []):
            top_level = imported.split(".", 1)[0]
            if top_level in _STDLIB_MODULES:
                continue
            if _canonical_dep_name(top_level) in internal_packages:
                continue
            imported_modules.add(top_level)
    return {_module_to_distribution(name) for name in imported_modules}


def _build_python_unused_declared_issues(
    declared: Dict[str, str], imported_dists: set[str]
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for dep_name in sorted(name for name in declared if name not in imported_dists):
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
    return issues


def _build_python_undeclared_issues(
    declared: Dict[str, str], imported_dists: set[str]
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for dep_name in sorted(name for name in imported_dists if name and name not in declared):
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
    data = _load_package_json_data(package_json)
    if not data:
        return []

    declared = _collect_js_declared_dependencies(data)
    if not declared:
        return []
    imported_modules = _collect_js_imported_modules(project_path)
    if not imported_modules:
        return []
    issues: List[Dict[str, Any]] = []
    issues.extend(_build_js_unused_declared_issues(declared, imported_modules))
    issues.extend(_build_js_undeclared_issues(declared, imported_modules))
    return issues


def _load_package_json_data(package_json: Path) -> Dict[str, Any]:
    if not package_json.exists():
        return {}
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _collect_js_declared_dependencies(data: Dict[str, Any]) -> Dict[str, str]:
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
    return declared


def _collect_js_imported_modules(project_path: Path) -> set[str]:
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
            canonical = _canonicalize_js_import(match)
            if canonical:
                imported_modules.add(canonical)
    return imported_modules


def _canonicalize_js_import(match: str) -> Optional[str]:
    if not match or match.startswith(".") or match.startswith("/"):
        return None
    top_level = match.split("/", 1)[0]
    if top_level.startswith("@") and "/" in match:
        top_level = "/".join(match.split("/", 2)[:2])
    if top_level.startswith("node:"):
        top_level = top_level.split(":", 1)[1]
    canonical = _canonical_dep_name(top_level)
    if canonical in _NODE_BUILTINS:
        return None
    return canonical


def _build_js_unused_declared_issues(
    declared: Dict[str, str], imported_modules: set[str]
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for dep_name in sorted(name for name in declared if name not in imported_modules):
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
    return issues


def _build_js_undeclared_issues(
    declared: Dict[str, str], imported_modules: set[str]
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for dep_name in sorted(name for name in imported_modules if name not in declared):
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
