"""Phantom import detection pattern and module resolution helpers."""

from __future__ import annotations

import ast
import logging
import re
import sys
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from slop_detector.ast_index import walk_nodes
from slop_detector.dependency_declarations import (
    declaration_files,
    declared_requirements,
    root_declaration_files,
)
from slop_detector.environment_resolution import environment_state, find_installed_spec
from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity
from slop_detector.project_context import fingerprint_for_roots, is_importable_directory
from slop_detector.project_resolution import (
    ProjectModuleIndex,
    discover_project_packages,
    get_module_index,
    resolution_roots,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Module resolution index (one per environment state)
# ------------------------------------------------------------------

_RESOLVABLE_MODULES_STORE: Dict[Tuple[Tuple[str, int], ...], FrozenSet[str]] = {}

# ------------------------------------------------------------------
# Project-local package discovery
# ------------------------------------------------------------------

# Both keyed by (directory or root, project-context fingerprint): a changed
# context is a new key, so a long-running process never reuses a stale answer.
_SIBLING_MODULES_CACHE: Dict[Tuple[str, str], FrozenSet[str]] = {}

_DECLARED_DEPENDENCY_SOURCES_CACHE: Dict[Tuple[str, str], Mapping[str, FrozenSet[str]]] = {}


def _discover_sibling_modules(file_path: Path, fingerprint: Optional[str] = None) -> FrozenSet[str]:
    """Names importable from the file's directory: sibling .py files and, for a
    script outside a regular package, sibling package directories (regular or
    namespace), since a script's directory is on sys.path when it runs.

    Inside a regular package `import name` is absolute, so a subpackage next
    to the module is not what it loads."""
    if fingerprint is None:
        fingerprint = fingerprint_for_roots(file_path, resolution_roots(file_path))
    key = (str(file_path.parent), fingerprint)
    if key in _SIBLING_MODULES_CACHE:
        return _SIBLING_MODULES_CACHE[key]
    script_directory = not (file_path.parent / "__init__.py").is_file()
    try:
        result: FrozenSet[str] = frozenset(
            p.stem if p.is_file() else p.name
            for p in file_path.parent.iterdir()
            if (p.suffix == ".py" and p.stem != "__init__" and p.is_file())
            or (script_directory and is_importable_directory(p))
        )
    except OSError:
        result = frozenset()
    _SIBLING_MODULES_CACHE[key] = result
    return result


_IMPORT_GUARD_EXC_NAMES: FrozenSet[str] = frozenset(
    {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
)


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


def _declaration_sources(files: Sequence[Path], label_root: Path) -> Dict[str, set[str]]:
    """Map import names to the declaration files (labelled from `label_root`)."""
    sources: Dict[str, set[str]] = {}
    for path in files:
        label = path.relative_to(label_root).as_posix()
        for dependency in declared_requirements(path):
            for import_name in _dependency_import_names(dependency):
                sources.setdefault(import_name, set()).add(label)
    return sources


def _discover_declared_dependency_sources(
    project_root: Path, fingerprint: Optional[str] = None
) -> Mapping[str, FrozenSet[str]]:
    """Map import names to the root's declaration files that justify them."""
    if fingerprint is None:
        fingerprint = fingerprint_for_roots(project_root / "_", (project_root,))
    root_key = (str(project_root), fingerprint)
    cached = _DECLARED_DEPENDENCY_SOURCES_CACHE.get(root_key)
    if cached is not None:
        return cached
    sources = _declaration_sources(root_declaration_files(project_root), project_root)
    result = {name: frozenset(locations) for name, locations in sources.items()}
    _DECLARED_DEPENDENCY_SOURCES_CACHE[root_key] = result
    return result


def _path_declarations(file: Path, nearest_root: Path) -> Mapping[str, FrozenSet[str]]:
    """Declarations in the directories between the file and its nearest root.

    Only files on the file's own path count: a declaration in another subtree
    says nothing about this file. The root itself is read by the root lookup.
    """
    directories = []
    current = file.parent
    while current != nearest_root and nearest_root in current.parents:
        directories.append(current)
        current = current.parent
    files = [path for directory in directories for path in declaration_files(directory)]
    sources = _declaration_sources(files, nearest_root)
    return {name: frozenset(locations) for name, locations in sources.items()}


def _resolves_in_project(
    indexes: Sequence[ProjectModuleIndex], dotted: str, names: Sequence[str] = ()
) -> bool:
    """Exact-path resolution under any of the project roots' module roots, no depth limit."""
    return any(index.resolves(dotted, names) for index in indexes)


def _get_resolvable_modules() -> FrozenSet[str]:
    """All top-level module names resolvable in this environment.

    Cached per environment state, so an install or uninstall in a long-lived
    process (MCP server, watch mode) is seen by the next lookup.
    """
    state = environment_state()
    if state in _RESOLVABLE_MODULES_STORE:
        return _RESOLVABLE_MODULES_STORE[state]

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

    _RESOLVABLE_MODULES_STORE.clear()
    _RESOLVABLE_MODULES_STORE[state] = frozenset(known)
    return _RESOLVABLE_MODULES_STORE[state]


def _module_exists(name: str, excluded: Sequence[Path] = ()) -> bool:
    """Return True if name is a resolvable top-level module in the analyzer's environment.

    Never from the analyzer's cwd or the `excluded` project roots (see
    slop_detector.environment_resolution). A lookup that raises is not an
    answer: it propagates, and the pattern is recorded as unmeasured for the
    file instead of reporting the module as installed.
    """
    if name in _get_resolvable_modules():
        return True
    return find_installed_spec(name, excluded) is not None


def environment_exclusions(indexes: Sequence[ProjectModuleIndex]) -> Tuple[Path, ...]:
    """The analyzed project's own roots: never evidence that a module is installed."""
    return tuple(
        path
        for index in indexes
        for path in (index.project_root, *(root.path for root in index.roots))
    )


def _merged_declarations(roots: Sequence[Path]) -> Mapping[str, FrozenSet[str]]:
    """Declaration sources of every resolution root, merged per import name."""
    merged: Dict[str, FrozenSet[str]] = {}
    for root in roots:
        for name, sources in _discover_declared_dependency_sources(root).items():
            merged[name] = merged.get(name, frozenset()) | sources
    return merged


def project_skip_context(
    file: Path, allowlist: FrozenSet[str]
) -> Tuple[FrozenSet[str], Tuple[ProjectModuleIndex, ...]]:
    """Top-level names that belong to the project (never checked as installed packages).

    Internal packages of every resolution root, sibling .py files (flat-module
    projects without pyproject.toml), and the allowlist; plus each root's module
    index for exact-path resolution.
    """
    roots = resolution_roots(file)
    skip_names = set(allowlist)
    for position, root in enumerate(roots):
        # The scan root (second) is evidence for its hard roots and exact paths only.
        skip_names |= discover_project_packages(root, hard_only=position > 0)
    skip_names |= _discover_sibling_modules(file, fingerprint_for_roots(file, roots))
    return frozenset(skip_names), tuple(get_module_index(root) for root in roots)


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
    for node in walk_nodes(tree):
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

        roots = resolution_roots(file)
        declared_sources = dict(_merged_declarations(roots))
        if roots:
            for name, sources in _path_declarations(file, roots[0]).items():
                declared_sources[name] = declared_sources.get(name, frozenset()) | sources
        has_pyproject = bool(roots and (roots[0] / "pyproject.toml").exists())
        skip_names, indexes = project_skip_context(file, self._allowlist)
        excluded = environment_exclusions(indexes)
        guarded_lines = _collect_import_guard_lines(tree)

        for node in walk_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in skip_names or _resolves_in_project(indexes, alias.name):
                        continue
                    lineno = getattr(node, "lineno", 0)
                    sources = declared_sources.get(top, frozenset())
                    if _module_exists(top, excluded):
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
                names = [alias.name for alias in node.names]
                if top in skip_names or _resolves_in_project(indexes, node.module, names):
                    continue
                lineno = getattr(node, "lineno", 0)
                sources = declared_sources.get(top, frozenset())
                if _module_exists(top, excluded):
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
