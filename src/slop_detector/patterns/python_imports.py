"""Phantom import detection pattern and module resolution helpers."""

from __future__ import annotations

import ast
import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Module resolution index (built once per process)
# ------------------------------------------------------------------

_RESOLVABLE_MODULES_STORE: Dict[str, FrozenSet[str]] = {}

# ------------------------------------------------------------------
# Project-local package discovery
# ------------------------------------------------------------------

_PROJECT_PACKAGES_CACHE: Dict[str, FrozenSet[str]] = {}

_SKIP_LAYOUT_DIRS: FrozenSet[str] = frozenset(
    {
        "tests", "test", "docs", "doc", "examples", "scripts", "tools",
        ".venv", "venv", "env", "build", "dist", ".git", "__pycache__",
        "node_modules", "site-packages", ".mypy_cache", ".ruff_cache",
        ".pytest_cache", ".tox", "htmlcov",
    }
)

_IMPORT_GUARD_EXC_NAMES: FrozenSet[str] = frozenset(
    {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
)


def _find_project_root(file_path: Path) -> Optional[Path]:
    """Walk up directory tree to find project root by standard markers."""
    markers = {"pyproject.toml", "setup.py", "setup.cfg", ".git"}
    current = file_path.parent
    for _ in range(12):
        if any((current / m).exists() for m in markers):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _add_dep_names(dep_list: List[str], packages: set) -> None:
    """Parse PEP-508 dependency strings and add canonical names."""
    for dep in dep_list:
        name = re.split(r"[>=<!~;\[\s]", dep.strip())[0].strip()
        if not name:
            continue
        canon = name.replace("-", "_").lower()
        packages.add(canon)
        for prefix in ("flamehaven_", "flame_", "py", "python_"):
            if canon.startswith(prefix) and len(canon) > len(prefix) + 1:
                packages.add(canon[len(prefix):])


def _augment_from_pyproject(project_root: Any, packages: set, scan_dir_fn: Any) -> None:
    """Read pyproject.toml and augment packages with layout dirs + dep names."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return
    try:
        toml_mod: Any = None
        try:
            import tomllib  # type: ignore[import-not-found]
            toml_mod = tomllib
        except ImportError:
            try:
                import tomli  # type: ignore[import-not-found,import]
                toml_mod = tomli
            except ImportError:
                pass
        if toml_mod is None:
            return
        with open(pyproject, "rb") as fh:
            data = toml_mod.load(fh)
        find_cfg = data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
        for where in find_cfg.get("where", []):
            scan_dir_fn(project_root / where)
        dep_lists: List[List[str]] = [data.get("project", {}).get("dependencies", [])]
        for extras in data.get("project", {}).get("optional-dependencies", {}).values():
            dep_lists.append(extras)
        for dep_list in dep_lists:
            _add_dep_names(dep_list, packages)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse pyproject.toml for package augmentation: %s", exc)


def _discover_project_packages(project_root: Path) -> FrozenSet[str]:
    """Discover internal Python package names via filesystem scan (cached)."""
    root_key = str(project_root)
    if root_key in _PROJECT_PACKAGES_CACHE:
        return _PROJECT_PACKAGES_CACHE[root_key]

    packages: set[str] = set()

    def _scan_dir(search: Path) -> None:
        try:
            for item in search.iterdir():
                if (
                    item.is_dir()
                    and item.name not in _SKIP_LAYOUT_DIRS
                    and not item.name.startswith(".")
                    and (item / "__init__.py").exists()
                ):
                    packages.add(item.name)
        except OSError as exc:
            logger.debug("Cannot iterate directory %s: %s", search, exc)

    src_dir = project_root / "src"
    if src_dir.is_dir():
        _scan_dir(src_dir)
    _scan_dir(project_root)
    _augment_from_pyproject(project_root, packages, _scan_dir)

    result = frozenset(packages)
    _PROJECT_PACKAGES_CACHE[root_key] = result
    if result:
        logger.debug("Internal packages at %s: %s", project_root, result)
    return result


def _get_resolvable_modules() -> FrozenSet[str]:
    """Build the set of all top-level module names resolvable in this environment (cached)."""
    if "v" in _RESOLVABLE_MODULES_STORE:
        return _RESOLVABLE_MODULES_STORE["v"]

    known: set[str] = set()
    known.update(sys.builtin_module_names)

    if hasattr(sys, "stdlib_module_names"):
        known.update(sys.stdlib_module_names)  # type: ignore[attr-defined]

    try:
        from importlib.metadata import packages_distributions  # type: ignore[attr-defined]
        for top_level_names in packages_distributions().values():
            for name in top_level_names:
                known.add(name)
                known.add(name.replace("-", "_"))
    except (AttributeError, ImportError) as exc:
        logger.debug("packages_distributions unavailable, skipping layer 3: %s", exc)

    _RESOLVABLE_MODULES_STORE["v"] = frozenset(known)
    return _RESOLVABLE_MODULES_STORE["v"]


def _module_exists(name: str) -> bool:
    """Return True if name is a resolvable top-level module."""
    if name in _get_resolvable_modules():
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return True


def _handler_is_import_guard(handler: ast.ExceptHandler) -> bool:
    """Return True if this except handler would catch an ImportError."""
    if handler.type is None:
        return True
    exc_names: set[str] = set()
    if isinstance(handler.type, ast.Name):
        exc_names.add(handler.type.id)
    elif isinstance(handler.type, ast.Tuple):
        for elt in handler.type.elts:
            if isinstance(elt, ast.Name):
                exc_names.add(elt.id)
    return bool(exc_names & _IMPORT_GUARD_EXC_NAMES)


def _collect_import_guard_lines(tree: ast.AST) -> FrozenSet[int]:
    """Return line numbers of import statements inside try/except ImportError blocks."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if any(_handler_is_import_guard(h) for h in node.handlers):
            for stmt in node.body:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    guarded.add(stmt.lineno)
    return frozenset(guarded)


class PhantomImportPattern(BasePattern):
    """Detect imports that reference non-existent packages (phantom/hallucinated imports).

    Three-tier classification:
      CRITICAL  Unguarded unresolvable import — hard runtime crash, likely AI hallucination.
      MEDIUM    Guarded with try/except ImportError — undeclared optional dependency.
      (skip)    Internal project package or resolvable in current environment.
    """

    id = "phantom_import"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Import references a package that cannot be resolved in this environment"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []

        project_root = _find_project_root(file)
        internal_packages = (
            _discover_project_packages(project_root) if project_root else frozenset()
        )
        guarded_lines = _collect_import_guard_lines(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in internal_packages or _module_exists(top):
                        continue
                    lineno = getattr(node, "lineno", 0)
                    issues.append(
                        self._make_issue(file, lineno, getattr(node, "col_offset", 0),
                                         alias.name, lineno in guarded_lines)
                    )

            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if not node.module:
                    continue
                top = node.module.split(".")[0]
                if top in internal_packages or _module_exists(top):
                    continue
                lineno = getattr(node, "lineno", 0)
                issues.append(
                    self._make_issue(file, lineno, getattr(node, "col_offset", 0),
                                     node.module, lineno in guarded_lines)
                )

        return issues

    def _make_issue(
        self, file: Path, line: int, column: int, module_name: str, is_guarded: bool
    ) -> Issue:
        if is_guarded:
            return self.create_issue(
                file=file,
                line=line,
                column=column,
                message=(
                    f"Undeclared optional dependency: '{module_name}' is guarded with "
                    f"ImportError but not listed in [project.optional-dependencies]"
                ),
                suggestion=(
                    f"Add '{module_name}' to the appropriate "
                    f"[project.optional-dependencies.<group>] in pyproject.toml so "
                    f"users know this feature requires an extra install."
                ),
                severity_override=Severity.MEDIUM,
            )
        return self.create_issue(
            file=file,
            line=line,
            column=column,
            message=(
                f"Phantom import: '{module_name}' cannot be resolved "
                f"(not in stdlib, built-ins, or installed packages)"
            ),
            suggestion=(
                f"Verify '{module_name}' exists on PyPI and add it to "
                f"[project.dependencies] in pyproject.toml. "
                f"AI models sometimes generate plausible-looking but non-existent "
                f"package names."
            ),
            severity_override=Severity.CRITICAL,
        )
