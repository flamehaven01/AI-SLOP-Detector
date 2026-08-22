"""Phantom import detection pattern and module resolution helpers."""

from __future__ import annotations

import ast
import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional

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

_SIBLING_MODULES_CACHE: Dict[str, FrozenSet[str]] = {}

_DECLARED_DEPENDENCY_SOURCES_CACHE: Dict[str, Mapping[str, FrozenSet[str]]] = {}


def _discover_sibling_modules(file_path: Path) -> FrozenSet[str]:
    """Return stem names of .py files in the same directory (importable siblings)."""
    key = str(file_path.parent)
    if key in _SIBLING_MODULES_CACHE:
        return _SIBLING_MODULES_CACHE[key]
    try:
        result: FrozenSet[str] = frozenset(
            p.stem for p in file_path.parent.iterdir() if p.suffix == ".py" and p.stem != "__init__"
        )
    except OSError:
        result = frozenset()
    _SIBLING_MODULES_CACHE[key] = result
    return result


_SKIP_LAYOUT_DIRS: FrozenSet[str] = frozenset(
    {
        "tests",
        "test",
        "docs",
        "doc",
        "examples",
        "scripts",
        "tools",
        ".venv",
        "venv",
        "env",
        "build",
        "dist",
        ".git",
        "__pycache__",
        "node_modules",
        "site-packages",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".tox",
        "htmlcov",
    }
)

_IMPORT_GUARD_EXC_NAMES: FrozenSet[str] = frozenset(
    {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
)


def _find_project_root(file_path: Path) -> Optional[Path]:
    """Walk up directory tree to find project root by standard markers."""
    markers = {"pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", ".git"}
    current = file_path.parent
    for _ in range(12):
        if any((current / m).exists() for m in markers):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


_EXTRAS_RE = re.compile(r"\[.*?\]")

_PACKAGE_IMPORT_ALIASES: Dict[str, FrozenSet[str]] = {
    "grpcio": frozenset({"grpc"}),
    "pyyaml": frozenset({"yaml"}),
}


def _dependency_import_names(dependency: str) -> FrozenSet[str]:
    """Return likely import names for a dependency declaration."""
    dependency = dependency.split("#", 1)[0].strip()
    if not dependency or dependency.startswith(("-", "git+", "http://", "https://")):
        return frozenset()
    name = re.split(r"[>=<!~;\s]", _EXTRAS_RE.sub("", dependency).strip())[0].strip()
    if not name:
        return frozenset()
    canon = name.replace("-", "_").lower()
    names = {canon}
    names.update(_PACKAGE_IMPORT_ALIASES.get(canon, frozenset()))
    for prefix in ("flamehaven_", "flame_", "py", "python_"):
        if canon.startswith(prefix) and len(canon) > len(prefix) + 1:
            names.add(canon[len(prefix) :])
    return frozenset(names)


def _add_dep_names(dep_list: List[str], packages: set) -> None:
    """Parse PEP-508 dependency strings and add likely import names.

    Strips extras specifiers (e.g. psycopg[binary]) before canonicalisation
    so that `import psycopg` matches `psycopg[binary]>=3.1.0` in optional-deps.
    """
    for dep in dep_list:
        packages.update(_dependency_import_names(dep))


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
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse pyproject.toml for package augmentation: %s", exc)


def _load_pyproject_dependency_lists(project_root: Path) -> List[List[str]]:
    """Load project and optional dependency lists without making tomllib mandatory."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return []
    try:
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            import tomli as tomllib  # type: ignore[import-not-found,import]
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
        project = data.get("project", {})
        dependency_lists = [project.get("dependencies", [])]
        dependency_lists.extend(project.get("optional-dependencies", {}).values())
        return [list(items) for items in dependency_lists if isinstance(items, list)]
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse dependency declarations in pyproject.toml: %s", exc)
        return []


def _read_requirements_file(requirements: Path) -> List[str]:
    """Read direct requirements entries; nested includes are intentionally not followed."""
    try:
        return requirements.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.debug("Cannot read requirements file %s: %s", requirements, exc)
        return []


def _discover_declared_dependency_sources(project_root: Path) -> Mapping[str, FrozenSet[str]]:
    """Map import names to the declaration files that justify them."""
    root_key = str(project_root)
    cached = _DECLARED_DEPENDENCY_SOURCES_CACHE.get(root_key)
    if cached is not None:
        return cached

    sources: Dict[str, set[str]] = {}

    def _record(dependencies: List[str], source: str) -> None:
        for dependency in dependencies:
            for import_name in _dependency_import_names(dependency):
                sources.setdefault(import_name, set()).add(source)

    for dependency_list in _load_pyproject_dependency_lists(project_root):
        _record(dependency_list, "pyproject.toml")
    requirement_files = [project_root / "requirements.txt"]
    requirements_dir = project_root / "requirements"
    if requirements_dir.is_dir():
        requirement_files.extend(sorted(requirements_dir.glob("*.txt")))
    for requirements in requirement_files:
        if requirements.exists():
            _record(
                _read_requirements_file(requirements), str(requirements.relative_to(project_root))
            )

    result = {name: frozenset(locations) for name, locations in sources.items()}
    _DECLARED_DEPENDENCY_SOURCES_CACHE[root_key] = result
    return result


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
    try:
        for child in project_root.iterdir():
            if (
                child.is_dir()
                and child.name not in _SKIP_LAYOUT_DIRS
                and not child.name.startswith(".")
            ):
                _scan_dir(child)
    except OSError as exc:
        logger.debug("Cannot iterate project root %s: %s", project_root, exc)
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
    """Classify unresolved imports without confusing runtime and metadata evidence.

    `phantom_import` is reserved for imports with no local declaration and no
    runtime resolution. Declared-but-unavailable imports and requirements-only
    declarations use distinct pattern IDs so they can be reviewed separately.
    """

    id = "phantom_import"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Import references a package that cannot be resolved in this environment"

    def __init__(self, allowlist: Optional[List[str]] = None) -> None:
        self._allowlist: FrozenSet[str] = frozenset(allowlist or [])

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []

        project_root = _find_project_root(file)
        internal_packages = (
            _discover_project_packages(project_root) if project_root else frozenset()
        )
        declared_sources = (
            _discover_declared_dependency_sources(project_root) if project_root else {}
        )
        has_pyproject = bool(project_root and (project_root / "pyproject.toml").exists())
        # Always include sibling .py files — handles flat-module projects without pyproject.toml
        sibling_modules = _discover_sibling_modules(file)
        skip_names = internal_packages | sibling_modules | self._allowlist
        guarded_lines = _collect_import_guard_lines(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in skip_names:
                        continue
                    lineno = getattr(node, "lineno", 0)
                    sources = declared_sources.get(top, frozenset())
                    if _module_exists(top):
                        continue
                    if self._is_requirements_only_metadata_gap(sources, has_pyproject):
                        issues.append(
                            self._make_metadata_gap_issue(
                                file, lineno, getattr(node, "col_offset", 0), alias.name, sources
                            )
                        )
                    else:
                        issues.append(
                            self._make_issue(
                                file,
                                lineno,
                                getattr(node, "col_offset", 0),
                                alias.name,
                                lineno in guarded_lines,
                                sources,
                            )
                        )

            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if not node.module:
                    continue
                top = node.module.split(".")[0]
                if top in skip_names:
                    continue
                lineno = getattr(node, "lineno", 0)
                sources = declared_sources.get(top, frozenset())
                if _module_exists(top):
                    continue
                if self._is_requirements_only_metadata_gap(sources, has_pyproject):
                    issues.append(
                        self._make_metadata_gap_issue(
                            file, lineno, getattr(node, "col_offset", 0), node.module, sources
                        )
                    )
                else:
                    issues.append(
                        self._make_issue(
                            file,
                            lineno,
                            getattr(node, "col_offset", 0),
                            node.module,
                            lineno in guarded_lines,
                            sources,
                        )
                    )

        return issues

    def _make_issue(
        self,
        file: Path,
        line: int,
        column: int,
        module_name: str,
        is_guarded: bool,
        declared_sources: FrozenSet[str],
    ) -> Issue:
        if declared_sources:
            locations = ", ".join(sorted(declared_sources))
            return Issue(
                pattern_id="runtime_unavailable_dependency",
                severity=Severity.MEDIUM,
                axis=self.axis,
                file=file,
                line=line,
                column=column,
                message=(
                    f"Declared dependency '{module_name}' is unavailable in the analyzer runtime "
                    f"(declared in {locations})."
                ),
                suggestion=(
                    "Install the declared dependency in the analysis environment, then rerun. "
                    "This is environment evidence, not proof of a phantom package."
                ),
            )
        if is_guarded:
            return Issue(
                pattern_id="undeclared_optional_dependency",
                severity=Severity.MEDIUM,
                axis=self.axis,
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

    @staticmethod
    def _is_requirements_only_metadata_gap(
        declared_sources: FrozenSet[str], has_pyproject: bool
    ) -> bool:
        return has_pyproject and bool(declared_sources) and "pyproject.toml" not in declared_sources

    def _make_metadata_gap_issue(
        self,
        file: Path,
        line: int,
        column: int,
        module_name: str,
        declared_sources: FrozenSet[str],
    ) -> Issue:
        locations = ", ".join(sorted(declared_sources))
        return Issue(
            pattern_id="declared_outside_primary_metadata",
            severity=Severity.LOW,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=(
                f"Dependency '{module_name}' is declared in {locations} but not in "
                "pyproject.toml project metadata."
            ),
            suggestion=(
                "Keep dependency declarations aligned with pyproject.toml so package "
                "installation and analysis use the same contract."
            ),
        )
