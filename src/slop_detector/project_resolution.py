"""Project module-root discovery and module location, shared by patterns and analysis.

One source of truth for "what is an internal module". Roots carry an authority
tier (docs/IMPORT_GRAPH.md):

    E1 DECLARED      [tool.setuptools.packages.find] where = [...]
    E2 CONVENTIONAL  <project>/src with Python sources and no src/__init__.py
    E3 FLAT_LAYOUT   the project root, when no E1/E2 root exists
    E4 CONDITIONAL   first-level children holding regular packages, and the
                     project root when it is not E3

E1-E3 locations are hard. E4 locations exist on disk but are importable only
under a particular runtime sys.path, so callers must treat them as conditional.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

SKIP_LAYOUT_DIRS: FrozenSet[str] = frozenset(
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

PROJECT_MARKERS: Tuple[str, ...] = (
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    ".git",
)

HARD_AUTHORITIES: FrozenSet[str] = frozenset({"E1", "E2", "E3"})

_PROJECT_PACKAGES_CACHE: Dict[str, FrozenSet[str]] = {}


@dataclass(frozen=True)
class ModuleRoot:
    path: Path
    authority: str  # "E1" | "E2" | "E3" | "E4"


@dataclass(frozen=True)
class ModuleLocation:
    path: Path  # module file, package __init__.py, or namespace directory
    kind: str  # "module" | "package" | "namespace_package"
    root: ModuleRoot


def find_project_root(file_path: Path) -> Optional[Path]:
    """Walk up the directory tree to find the project root by standard markers."""
    current = file_path.parent
    for _ in range(12):
        if any((current / m).exists() for m in PROJECT_MARKERS):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def load_pyproject(project_root: Path) -> Dict[str, Any]:
    """Parse <project_root>/pyproject.toml; {} when absent, unparsable, or no TOML reader."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    toml_mod: Any = None
    try:
        import tomllib  # type: ignore[import-not-found]

        toml_mod = tomllib
    except ImportError:
        try:
            import tomli  # type: ignore[import-not-found,import]

            toml_mod = tomli
        except ImportError:
            # Not silent: declared module roots (E1) are lost without a reader.
            logger.warning("No TOML reader (tomllib/tomli); %s was not read", pyproject)
            return {}
    try:
        with open(pyproject, "rb") as fh:
            return dict(toml_mod.load(fh))
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse %s: %s", pyproject, exc)
        return {}


def declared_package_roots(project_root: Path) -> List[Path]:
    """Return directories declared by [tool.setuptools.packages.find] where."""
    node: Any = load_pyproject(project_root)
    # Parsing is not shape: `[tool.setuptools] packages = [...]` is a list, not a
    # table, so every level is checked before it is indexed.
    for key in ("tool", "setuptools", "packages", "find", "where"):
        node = node.get(key) if isinstance(node, dict) else None
    where = node if isinstance(node, list) else []
    return [project_root / str(entry) for entry in where if (project_root / str(entry)).is_dir()]


def _is_layout_candidate(path: Path) -> bool:
    return path.is_dir() and path.name not in SKIP_LAYOUT_DIRS and not path.name.startswith(".")


def is_regular_package(path: Path) -> bool:
    return _is_layout_candidate(path) and (path / "__init__.py").is_file()


def _holds_python_sources(directory: Path) -> bool:
    """True if a .py file exists anywhere below `directory` (no depth limit).

    Skip and hidden directories are pruned; the walk stops at the first .py file.
    """
    for _current, dirs, files in os.walk(directory):
        if any(name.endswith(".py") for name in files):
            return True
        dirs[:] = [d for d in dirs if d not in SKIP_LAYOUT_DIRS and not d.startswith(".")]
    return False


def is_namespace_package(path: Path) -> bool:
    """PEP 420: a directory without __init__.py that contains Python sources."""
    return (
        _is_layout_candidate(path)
        and path.name.isidentifier()
        and not (path / "__init__.py").exists()
        and _holds_python_sources(path)
    )


def _subdirs(path: Path) -> List[Path]:
    try:
        return sorted(p for p in path.iterdir() if p.is_dir())
    except OSError:
        return []


def _conventional_src(project_root: Path) -> Optional[Path]:
    """<project>/src counts as E2 only without src/__init__.py (else `src` is a package)."""
    src = project_root / "src"
    if src.is_dir() and not (src / "__init__.py").exists() and _holds_python_sources(src):
        return src
    return None


def _conditional_children(project_root: Path) -> List[Path]:
    """First-level directories that hold a regular package (monorepo `backend/app`)."""
    return [
        child
        for child in _subdirs(project_root)
        if _is_layout_candidate(child) and any(is_regular_package(c) for c in _subdirs(child))
    ]


def discover_module_roots(project_root: Path) -> Tuple[ModuleRoot, ...]:
    """Return module roots in resolution order, each tagged with its authority."""
    roots: List[ModuleRoot] = []
    seen: set = set()

    def add(path: Path, authority: str) -> None:
        resolved = path.resolve()
        if resolved not in seen and resolved.is_dir():
            seen.add(resolved)
            roots.append(ModuleRoot(resolved, authority))

    for declared in declared_package_roots(project_root):
        add(declared, "E1")
    src = _conventional_src(project_root)
    if src is not None:
        add(src, "E2")
    if not roots:
        add(project_root, "E3")
    for child in _conditional_children(project_root):
        add(child, "E4")
    add(project_root, "E4")
    return tuple(roots)


def _top_level_packages(root: ModuleRoot) -> List[str]:
    names = []
    for child in _subdirs(root.path):
        if is_regular_package(child):
            names.append(child.name)
        elif root.authority in HARD_AUTHORITIES and is_namespace_package(child):
            names.append(child.name)
    return names


def discover_project_packages(project_root: Path) -> FrozenSet[str]:
    """Top-level internal package names under every module root (cached).

    E4 roots contribute regular packages only; namespace packages are recognised
    under E1-E3 roots, so a stray directory cannot mute a real phantom import.
    """
    root_key = str(project_root)
    if root_key in _PROJECT_PACKAGES_CACHE:
        return _PROJECT_PACKAGES_CACHE[root_key]
    names: set = set()
    for root in discover_module_roots(project_root):
        names.update(_top_level_packages(root))
    result = frozenset(names)
    _PROJECT_PACKAGES_CACHE[root_key] = result
    if result:
        logger.debug("Internal packages at %s: %s", project_root, result)
    return result


def _find_spec(name: str, search: Sequence[Path]) -> Optional[Tuple[str, List[Path]]]:
    """One module name over a search path, in CPython PathFinder order.

    Per directory a regular package wins over a module file. Namespace portions
    are collected across the whole search path and used only when no directory
    provides a module or package. Any directory is a portion; no content
    or depth heuristic applies.
    """
    portions: List[Path] = []
    for directory in search:
        candidate = directory / name
        if (candidate / "__init__.py").is_file():
            return "package", [candidate / "__init__.py"]
        if (directory / f"{name}.py").is_file():
            return "module", [directory / f"{name}.py"]
        if name.isidentifier() and _is_layout_candidate(candidate):
            portions.append(candidate)
    return ("namespace_package", portions) if portions else None


def _resolve_chain(parts: Sequence[str], search: Sequence[Path]):
    """Import `a.b.c` one segment at a time; every parent must be a package.

    Returns (kind, paths) for the last segment, or None.
    """
    found: Optional[Tuple[str, List[Path]]] = None
    for part in parts:
        found = _find_spec(part, search)
        if found is None:
            return None
        kind, paths = found
        if kind == "module":
            search = []  # a module has no __path__: nothing can be imported below it
        elif kind == "package":
            search = [paths[0].parent]
        else:
            search = paths
    return found


def probe_module(base: Path, parts: List[str]) -> Optional[Tuple[Path, str]]:
    """Locate a dotted module below one directory. Returns (path, kind) or None."""
    if not parts:
        if (base / "__init__.py").is_file():
            return base / "__init__.py", "package"
        return (base, "namespace_package") if base.is_dir() else None
    found = _resolve_chain(parts, [base])
    if found is None:
        return None
    kind, paths = found
    return paths[0], kind


class ProjectModuleIndex:
    """Locate dotted module names across all module roots of one project."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.roots = discover_module_roots(self.project_root)
        self._cache: Dict[str, Tuple[ModuleLocation, ...]] = {}

    def locate(self, dotted: str) -> Tuple[ModuleLocation, ...]:
        """Locations providing `dotted`.

        Hard roots (E1-E3) form one search path, as sys.path would. Only when they
        do not provide the name is each E4 root tried on its own, so one location
        per E4 root lets the caller tell conditional from ambiguous.
        """
        if dotted in self._cache:
            return self._cache[dotted]
        parts = [p for p in dotted.split(".") if p]
        hard = [root for root in self.roots if root.authority in HARD_AUTHORITIES]
        found = self._chain_locations(parts, hard) if parts else []
        if parts and not found:
            for root in self.roots:
                if root.authority == "E4" and is_regular_package(root.path / parts[0]):
                    found.extend(self._chain_locations(parts, [root]))
        result = tuple(found)
        self._cache[dotted] = result
        return result

    @staticmethod
    def _chain_locations(parts: Sequence[str], roots: Sequence[ModuleRoot]) -> List[ModuleLocation]:
        found = _resolve_chain(parts, [root.path for root in roots])
        if found is None:
            return []
        kind, paths = found
        return [
            ModuleLocation(path, kind, next(r for r in roots if r.path in path.parents))
            for path in paths
        ]

    def is_internal_top_level(self, name: str) -> bool:
        return name in discover_project_packages(self.project_root) or any(
            (root.path / f"{name}.py").is_file()
            for root in self.roots
            if root.authority in HARD_AUTHORITIES
        )

    def is_package_dir(self, path: Path) -> bool:
        """Can `path` hold a relative import?

        A regular package, or a namespace directory strictly inside a module root.
        A module root is never a package: a relative import cannot climb out of
        the top-level package.
        """
        if (path / "__init__.py").is_file():
            return True
        resolved = path.resolve()
        root_paths = {root.path for root in self.roots}
        return resolved not in root_paths and any(r in resolved.parents for r in root_paths)

    def resolves(self, dotted: str, names: Sequence[str] = ()) -> bool:
        """Exact-path existence check for `import dotted` / `from dotted import names`."""
        locations = self.locate(dotted)
        if any(loc.kind != "namespace_package" for loc in locations):
            return True
        if locations and (not names or "*" in names):
            return True
        return any(self.locate(f"{dotted}.{name}") for name in names if name != "*")


_INDEX_CACHE: Dict[str, ProjectModuleIndex] = {}


def get_module_index(project_root: Path) -> ProjectModuleIndex:
    """Per-process cached index (same lifetime as the package-name cache)."""
    key = str(project_root)
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = ProjectModuleIndex(project_root)
    return _INDEX_CACHE[key]
