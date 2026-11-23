"""Phantom import detection pattern and module resolution helpers."""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from slop_detector.ast_index import walk_nodes
from slop_detector.dependency_declarations import (
    build_requirements,
    declaration_files,
    declared_requirements,
    root_declaration_files,
    unread_declaration_links,
)
from slop_detector.environment_resolution import State, environment_state, find_installed_spec
from slop_detector.external_members import unknown_row
from slop_detector.import_providers import (
    ARTIFACT_VERIFIED,
    DEPENDS_ON_RUN_MODE,
    METADATA_DECLARED,
    NAME_CANDIDATE,
    OUT_OF_BOUNDARY,
    PROVIDER_UNKNOWN,
    SYS_PATH_MODIFIED,
    TYPE_CHECKING_ONLY,
    DeferredImports,
    ProviderKnowledge,
    Requirement,
    candidate_names,
    deferred_imports,
    evidence,
    find_target_environment,
    marker_active,
    marker_environment,
    parse_requirement,
    platform_guard_lines,
    provides,
    shipped_table,
    unread_environment_links,
)
from slop_detector.path_boundary import (
    is_inside,
    leaves,
    real_path,
    relative_label,
    walk_boundary,
)
from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity
from slop_detector.project_context import (
    fingerprint_for_roots,
    importable_state,
    is_importable_directory,
    project_context,
)
from slop_detector.project_resolution import (
    ProjectModuleIndex,
    discover_project_packages,
    get_module_index,
    has_location,
    resolution_roots,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Module resolution index (one per environment state)
# ------------------------------------------------------------------

_RESOLVABLE_MODULES_STORE: Dict[State, FrozenSet[str]] = {}

# ------------------------------------------------------------------
# Project-local package discovery
# ------------------------------------------------------------------

# Both keyed by (directory or root, project-context fingerprint): a changed
# context is a new key, so a long-running process never reuses a stale answer.
_SIBLING_MODULES_CACHE: Dict[Tuple[str, str, str], FrozenSet[str]] = {}

_ROOT_REQUIREMENTS_CACHE: Dict[Tuple[str, str], Tuple[Requirement, ...]] = {}


def _discover_sibling_modules(file_path: Path, fingerprint: Optional[str] = None) -> FrozenSet[str]:
    """Names importable from the file's directory, for a script outside a regular package:
    sibling .py files and package directories (regular or namespace), since a script's
    directory is on sys.path when it runs.

    Inside a regular package `import name` is absolute, so neither a module nor a subpackage
    next to the file is what it loads (only `from . import name` is): no sibling names there.
    A package module that also runs as a script is handled by `_run_mode_sibling`."""
    roots = resolution_roots(file_path)
    if fingerprint is None:
        fingerprint = fingerprint_for_roots(file_path, roots)
    boundary = walk_boundary(roots[-1] if roots else file_path.parent)
    key = (str(file_path.parent), fingerprint, str(boundary))
    if key in _SIBLING_MODULES_CACHE:
        return _SIBLING_MODULES_CACHE[key]
    script_directory = not (file_path.parent / "__init__.py").is_file()
    try:
        result: FrozenSet[str] = frozenset(
            p.stem if p.is_file() else p.name
            for p in file_path.parent.iterdir()
            if script_directory
            and not leaves(p, boundary)
            and (
                (p.suffix == ".py" and p.is_file())  # a script directory has no __init__.py
                or is_importable_directory(p, boundary)
            )
        )
    except OSError:
        result = frozenset()
    _SIBLING_MODULES_CACHE[key] = result
    return result


_IMPORT_GUARD_EXC_NAMES: FrozenSet[str] = frozenset(
    {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}
)


_EXTRAS_RE = re.compile(r"\[.*?\]")


def _dependency_import_names(dependency: str) -> FrozenSet[str]:
    """Likely import names for one declaration: the shipped table when it knows the
    distribution, else names derived from the declared name (rank 5 candidates)."""
    req = parse_requirement(_EXTRAS_RE.sub("", dependency), "")
    if req is None:
        return frozenset()
    return shipped_table().get(req.dist) or candidate_names(req.written)


def _add_dep_names(dep_list: List[str], packages: set) -> None:
    """Parse PEP-508 dependency strings and add likely import names.

    Strips extras specifiers (e.g. psycopg[binary]) before canonicalisation
    so that `import psycopg` matches `psycopg[binary]>=3.1.0` in optional-deps.
    """
    for dep in dep_list:
        packages.update(_dependency_import_names(dep))


def _requirements(files: Sequence[Path], label_root: Path) -> Tuple[Requirement, ...]:
    """Declared distributions of the files, each labelled with its file (from `label_root`)."""
    found: List[Requirement] = []
    for path in files:
        label = path.relative_to(label_root).as_posix()
        for dependency in declared_requirements(path):
            req = parse_requirement(_EXTRAS_RE.sub("", dependency), label)
            if req is not None:
                found.append(req)
    return tuple(found)


def _root_requirements(
    project_root: Path, fingerprint: Optional[str] = None
) -> Tuple[Requirement, ...]:
    """The root's declared distributions (cached per project-context fingerprint)."""
    if fingerprint is None:
        fingerprint = fingerprint_for_roots(project_root / "_", (project_root,))
    root_key = (str(project_root), fingerprint)
    cached = _ROOT_REQUIREMENTS_CACHE.get(root_key)
    if cached is None:
        cached = _requirements(root_declaration_files(project_root), project_root)
        _ROOT_REQUIREMENTS_CACHE[root_key] = cached
    return cached


def _path_requirements(file: Path, nearest_root: Path) -> Tuple[Requirement, ...]:
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
    return _requirements(files, nearest_root)


# (root, project-context fingerprint) -> every declaration in the project: (relative path,
# requirement, line or None, sha256 of the file). The fingerprint hashes declaration contents,
# so an edited or moved declaration is a new key.
_PROJECT_DECLARATIONS_CACHE: Dict[
    Tuple[str, str], Tuple[Tuple[str, Requirement, Optional[int], str], ...]
] = {}

# Pattern IDs that mean "not declared on this file's path": the ones a declaration elsewhere can
# inform.
_UNDECLARED_IDS = frozenset(
    {"phantom_import", "undeclared_dependency", "undeclared_optional_dependency"}
)


def _declaration_line(text: str, written: str) -> Optional[int]:
    """The line holding the name as written, when exactly one line does (else not known)."""
    name = re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(written) + r"(?![A-Za-z0-9_-])")
    hits = [n for n, line in enumerate(text.splitlines(), 1) if name.search(line)]
    return hits[0] if len(hits) == 1 else None


def _project_declarations(root: Path) -> Tuple[Tuple[str, Requirement, Optional[int], str], ...]:
    snapshot = project_context(root)
    key = (str(root), snapshot.fingerprint)
    cached = _PROJECT_DECLARATIONS_CACHE.get(key)
    if cached is not None:
        return cached
    found: List[Tuple[str, Requirement, Optional[int], str]] = []
    for rel in snapshot.declaration_files:
        path = root / rel
        try:
            data = path.read_bytes()
        except OSError:
            continue
        sha = hashlib.sha256(data).hexdigest()
        text = data.decode("utf-8", errors="replace")
        for dependency in declared_requirements(path):
            req = parse_requirement(_EXTRAS_RE.sub("", dependency), rel)
            if req is not None:
                found.append((rel, req, _declaration_line(text, req.written), sha))
    _PROJECT_DECLARATIONS_CACHE[key] = tuple(found)
    return _PROJECT_DECLARATIONS_CACHE[key]


def own_declaration_paths(file: Path, roots: Sequence[Path]) -> FrozenSet[str]:
    """The declaration files `file_requirements` reads for the file, relative to the outermost
    root: everything else in the project is another subtree."""
    if not roots:
        return frozenset()
    files = [p for root in roots for p in root_declaration_files(root)]
    current = file.parent
    while current != roots[0] and roots[0] in current.parents:
        files.extend(declaration_files(current))
        current = current.parent
    base = roots[-1]
    return frozenset(p.relative_to(base).as_posix() for p in files if base in p.parents)


def related_declarations(
    ctx: "_FileContext", module: str, members: Sequence[str]
) -> List[Dict[str, object]]:
    """Declarations in other subtrees of the project whose distribution could provide `module`:
    context for whoever fixes the finding, never this file's provider (CONTEXT_ONLY)."""
    if ctx.declaration_root is None:
        return []
    entries: Dict[Tuple[str, str], Dict[str, object]] = {}
    for rel, req, line, sha in _project_declarations(ctx.declaration_root):
        if rel in ctx.own_declarations or (rel, req.dist) in entries:
            continue
        view = ctx.knowledge.view(req)
        if not provides(view.names, module, list(members)):
            continue
        entry: Dict[str, object] = {"source_path": rel}
        if line is not None:
            entry["line"] = line
        entry["declared_distribution"] = req.written
        entry["match_basis"] = "SAME_NAME" if view.state == NAME_CANDIDATE else "KNOWN_PROVIDER"
        entry["provider_state"] = view.state
        if req.marker:
            entry["marker"] = req.marker
        entry["relationship"] = "OTHER_SUBTREE"
        entry["verification_state"] = "CONTEXT_ONLY"
        entry["source_sha256"] = sha
        entries[(rel, req.dist)] = entry
    return [entries[key] for key in sorted(entries)]


def unread_declarations(file: Path, roots: Sequence[Path]) -> Tuple[Path, ...]:
    """Declaration files on the file's evidence path (its roots, and the directories between it
    and its nearest root) that are links out of the scan area: not read, so its declarations
    are not fully known."""
    found = [p for root in roots for p in unread_declaration_links(root, True)]
    if roots:
        current = file.parent
        while current != roots[0] and roots[0] in current.parents:
            found.extend(unread_declaration_links(current, False))
            current = current.parent
    return tuple(dict.fromkeys(found))


def file_requirements(file: Path, roots: Sequence[Path]) -> Tuple[Requirement, ...]:
    """Every declaration that is evidence for `file`: each resolution root's and the ones on its path."""
    found = [req for root in roots for req in _root_requirements(root)]
    if roots:
        found.extend(_path_requirements(file, roots[0]))
        # A build script is evidenced by the build requirements of the pyproject.toml beside
        # it; the package's modules are not (build-time, not run-time, dependencies).
        pyproject = file.parent / "pyproject.toml"
        if file.name == "setup.py" and pyproject.is_file():
            label = (
                pyproject.relative_to(roots[0]).as_posix()
                if roots[0] in pyproject.parents
                else "pyproject.toml"
            )
            for dependency in build_requirements(pyproject):
                req = parse_requirement(_EXTRAS_RE.sub("", dependency), label)
                if req is not None:
                    found.append(req)
    return tuple(found)


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
    if has_location():
        skip_names |= _discover_sibling_modules(file, fingerprint_for_roots(file, roots))
    return frozenset(skip_names), tuple(get_module_index(root) for root in roots)


def _directory_supplies(directory: str, top: str, boundary: Path) -> Optional[bool]:
    """Whether a directory the file adds to sys.path holds a module or package `top`.

    Read only inside the boundary (path_boundary): when the directory, its entry for `top`, or
    a link deeper in a namespace package leads out of it, that part is not opened, listed or
    tested, and the answer is None: not known, never "missing".
    """
    if not is_inside(Path(directory), boundary):
        return None
    base = real_path(Path(directory))
    module, package = base / f"{top}.py", base / top
    if leaves(module, boundary) or leaves(package, boundary):
        return None
    if module.is_file():
        return True
    return importable_state(package, boundary)


def _runs_as_script(tree: ast.AST) -> bool:
    """A top-level `if __name__ == "__main__":` block: the module is also meant to run directly."""
    for node in getattr(tree, "body", []):
        test = node.test if isinstance(node, ast.If) else None
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            return True
    return False


def _run_mode_sibling(file: Path, top: str, boundary: Path) -> Optional[Path]:
    """For a module of a regular package: the sibling module or package named `top`, which an
    absolute `import top` loads only when the file runs as a script (its directory is then
    sys.path[0]), not when it is imported as part of the package."""
    parent = file.parent
    if not (parent / "__init__.py").is_file():
        return None
    for candidate in (parent / f"{top}.py", parent / top):
        if leaves(candidate, boundary):
            continue
        if candidate.suffix == ".py" and candidate.is_file():
            return candidate
        if candidate.suffix != ".py" and importable_state(candidate, boundary):
            return candidate
    return None


def _hash_into(entry: Dict[str, object], hashed: Path, kind: str, boundary: Path) -> str:
    """Put the sha256 of `hashed` into `entry` when it is a file read inside the boundary; return
    the state either way. The boundary is checked before the file is touched."""
    if kind == "namespace_package":
        return "NO_INIT"
    if leaves(hashed, boundary):
        return "OUT_OF_BOUNDARY"
    try:
        entry["sha256"] = hashlib.sha256(hashed.read_bytes()).hexdigest()
    except OSError:
        return "UNREADABLE"
    return "HASHED"


def _same_named_sibling(file: Path, top: str, ctx: "_FileContext") -> Optional[Dict[str, object]]:
    """For a file of a regular package: the module or package named `top` beside it, as context
    for a finding about the absolute `import top` (it is not what that import loads, but it may be
    what the author meant: `from . import top`). None when there is none. `hash_state` says why
    a sha256 is or is not there: HASHED, NO_INIT (a namespace package has no file standing for
    it), OUT_OF_BOUNDARY (the file links out and is not read) or UNREADABLE."""
    parent = file.parent
    if not (parent / "__init__.py").is_file():
        return None
    module, package = parent / f"{top}.py", parent / top
    if not leaves(module, ctx.boundary) and module.is_file():
        found, kind, hashed = module, "module", module
    elif not leaves(package, ctx.boundary) and importable_state(package, ctx.boundary):
        hashed = package / "__init__.py"
        regular = os.path.lexists(str(hashed))  # the entry, never its target
        found, kind = package, "package" if regular else "namespace_package"
    else:
        return None
    base = ctx.declaration_root or parent
    entry: Dict[str, object] = {
        "path": found.relative_to(base).as_posix() if base in found.parents else found.name,
        "kind": kind,
    }
    entry["hash_state"] = _hash_into(entry, hashed, kind, ctx.boundary)
    entry["relationship"] = "SIBLING_IN_PACKAGE"
    entry["verification_state"] = "CONTEXT_ONLY"
    return entry


def _blocked_sibling(file: Path, top: str, boundary: Path) -> Tuple[Path, ...]:
    """A sibling `top.py` or `top/` of the file (its directory is on sys.path when it runs as
    a script) that is, or holds only behind, a link out of the boundary."""
    parent = file.parent
    out = tuple(p for p in (parent / f"{top}.py", parent / top) if leaves(p, boundary))
    if out:
        return out
    if not (parent / "__init__.py").is_file() and importable_state(parent / top, boundary) is None:
        return (parent / top,)
    return ()


def _out_of_boundary_row(
    lineno: int, module: str, paths: Sequence[Path], boundary: Path
) -> Dict[str, object]:
    row = unknown_row(lineno, module, None, OUT_OF_BOUNDARY, basis="static_import")
    row["blocked_paths"] = sorted({relative_label(p, boundary) for p in paths})
    return row


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


def _relative_fallbacks(tree: ast.AST) -> FrozenSet[Tuple[int, str]]:
    """(line, name) of absolute imports in an `except ImportError` handler whose try body imports
    the same name relatively (`try: from .x import f / except ImportError: from x import f`). The
    fallback runs when the relative import fails: when the file runs directly (a sibling x is then
    what it loads), or when x itself fails to import inside a package (that cause is x's own
    import, reported in x; a missing member f is not checked: HOLD2-F3)."""
    found: set = set()
    for node in walk_nodes(tree):
        if not isinstance(node, ast.Try):
            continue
        relative = set()
        for stmt in node.body:
            if isinstance(stmt, ast.ImportFrom) and stmt.level:
                if stmt.module:
                    relative.add(stmt.module.split(".")[0])
                else:
                    relative.update(alias.name for alias in stmt.names)
        if not relative:
            continue
        for handler in node.handlers:
            if not _handler_is_import_guard(handler):
                continue
            for stmt in handler.body:
                if isinstance(stmt, ast.Import):
                    tops = [alias.name.split(".")[0] for alias in stmt.names]
                elif isinstance(stmt, ast.ImportFrom) and stmt.module and not stmt.level:
                    tops = [stmt.module.split(".")[0]]
                else:
                    continue
                found.update((stmt.lineno, top) for top in tops if top in relative)
    return frozenset(found)


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


def _no_context_row(line: int, module: str) -> Dict[str, object]:
    return unknown_row(line, module, None, "no_project_context", basis="environment_only")


class PhantomImportPattern(BasePattern):
    """Classify unresolved imports without confusing runtime and metadata evidence.

    `phantom_import` is reserved for imports with no local declaration and no
    runtime resolution. Declared-but-unavailable imports and requirements-only
    declarations use distinct pattern IDs so they can be reviewed separately.
    """

    id = "phantom_import"
    # 3.18: at most HIGH. "No provider known" is not proof that no package exists; CRITICAL
    # would need execution evidence the static analysis does not have.
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Import references a package that cannot be resolved in this environment"

    def __init__(self, allowlist: Optional[List[str]] = None) -> None:
        self._allowlist: FrozenSet[str] = frozenset(allowlist or [])
        self._unknowns: Dict[str, Tuple[Dict[str, object], ...]] = {}

    def take_unknowns(self, file: Path) -> List[Dict[str, object]]:
        """Imports the last check of `file` could not judge (removed once taken)."""
        return list(self._unknowns.pop(str(file), ()))

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        # A source with no location: an import the environment cannot resolve may
        # be local code nobody showed us, so it is unverified, not a finding.
        unknowns: list[Dict[str, object]] = []
        located = has_location()

        roots = resolution_roots(file)
        skip_names, indexes = project_skip_context(file, self._allowlist)
        target = find_target_environment(roots) if located else None
        env = marker_environment(target)
        inactive, undecided = platform_guard_lines(tree, env)
        ctx = _FileContext(
            excluded=environment_exclusions(indexes),
            guarded=_collect_import_guard_lines(tree),
            inactive=inactive,
            undecided=undecided,
            deferred=deferred_imports(tree, file),
            local_paths=project_context(roots[-1]).module_paths if roots else {},
            boundary=walk_boundary(roots[-1] if roots else file.parent),
            knowledge=ProviderKnowledge(target),
            requirements=file_requirements(file, roots),
            declaration_root=roots[-1] if roots else None,
            own_declarations=own_declaration_paths(file, roots),
            runs_as_script=_runs_as_script(tree),
            relative_fallbacks=_relative_fallbacks(tree),
            unread=unread_declarations(file, roots)
            + (unread_environment_links(roots) if located and target is None else ()),
            has_pyproject=bool(roots and (roots[0] / "pyproject.toml").exists()),
            marker_env=env,
        )

        for node in walk_nodes(tree):
            requests: List[Tuple[str, List[str]]] = []
            if isinstance(node, ast.Import):
                requests = [(alias.name, []) for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                requests = [(node.module, [alias.name for alias in node.names])]
            for module, members in requests:
                top = module.split(".")[0]
                if top in skip_names or _resolves_in_project(indexes, module, members):
                    continue
                lineno = getattr(node, "lineno", 0)
                blocked = [p for index in indexes for p in index.blocked_paths(module)]
                if located and not blocked:
                    blocked = list(_blocked_sibling(file, top, ctx.boundary))
                if blocked:
                    # only a link out of the boundary could supply it: not read, so not known
                    unknowns.append(_out_of_boundary_row(lineno, module, blocked, ctx.boundary))
                    continue
                if lineno in ctx.inactive:
                    continue  # does not run on the target platform
                if self._resolved(top, ctx):
                    continue
                if not located:
                    unknowns.append(_no_context_row(lineno, module))
                    continue
                if lineno in ctx.undecided:
                    # under a platform test the target environment does not decide: whether
                    # this import runs where the code runs is not known, so it is no finding
                    unknowns.append(
                        unknown_row(
                            lineno,
                            module,
                            None,
                            "platform_guard_undecided",
                            basis="target_platform",
                        )
                    )
                    continue
                if lineno in ctx.deferred.type_checking:
                    # does not run, so whether it would resolve is no finding
                    unknowns.append(
                        unknown_row(lineno, module, None, TYPE_CHECKING_ONLY, basis="static_import")
                    )
                    continue
                two_modes = ctx.runs_as_script or (lineno, top) in ctx.relative_fallbacks
                sibling = _run_mode_sibling(file, top, ctx.boundary) if two_modes else None
                if sibling is not None:
                    # imported, the package module loads the distribution; run as a script, the
                    # sibling: which one is not known statically
                    row = unknown_row(
                        lineno, module, None, DEPENDS_ON_RUN_MODE, basis="static_import"
                    )
                    base = ctx.declaration_root or file.parent
                    row["local_candidates"] = [
                        (
                            sibling.relative_to(base).as_posix()
                            if base in sibling.parents
                            else sibling.name
                        )
                    ]
                    unknowns.append(row)
                    continue
                added = ctx.deferred.added_paths.get(lineno, ())
                states = [(d, _directory_supplies(d, top, ctx.boundary)) for d in added if d]
                if any(state is True for _, state in states):
                    continue  # provided by a directory the file itself puts on sys.path
                outside = [Path(d) for d, state in states if state is None]
                if outside:
                    unknowns.append(_out_of_boundary_row(lineno, module, outside, ctx.boundary))
                    continue
                unresolved = None in added
                # the project walk never enters a link out of the boundary, so every candidate
                # is inside it
                candidates = list(ctx.local_paths.get(top, ())) if unresolved else []
                if candidates:
                    # a directory not known statically comes first, and the project has a module
                    # of this name it could be: unverified, with those files as the evidence
                    row = unknown_row(
                        lineno, module, None, SYS_PATH_MODIFIED, basis="static_import"
                    )
                    row["local_candidates"] = candidates
                    unknowns.append(row)
                    continue
                if ctx.unread:
                    # every verdict from here on rests on declarations a link out of the scan
                    # area holds unread: not known, so no finding
                    unknowns.append(_out_of_boundary_row(lineno, module, ctx.unread, ctx.boundary))
                    continue
                issue = self._verdict(file, node, module, members, ctx)
                if unresolved:
                    # a directory added before this import is not known (or not readable): the
                    # verdict stands, but the search path it rests on was not fully seen
                    issue.evidence = {**(issue.evidence or {}), "sys_path_unresolved": True}
                sibling_context = _same_named_sibling(file, top, ctx)
                if sibling_context is not None:
                    issue.evidence = {
                        **(issue.evidence or {}),
                        "same_named_sibling": sibling_context,
                    }
                if issue.pattern_id in _UNDECLARED_IDS:
                    related = related_declarations(ctx, module, members)
                    if related:
                        issue.evidence = {**(issue.evidence or {}), "related_declarations": related}
                issues.append(issue)

        self._unknowns[str(file)] = tuple(unknowns)
        return issues

    @staticmethod
    def _resolved(top: str, ctx: "_FileContext") -> bool:
        """Resolvable where the code runs: the target environment when there is one, else the
        analyzer's. With a target, only its site-packages and the standard library are
        searched (find_installed_spec with target_sites), on every Python version: the
        analyzer's installed packages are not evidence about the target."""
        target = ctx.knowledge.target
        if target is None:
            return _module_exists(top, ctx.excluded)
        if top in getattr(sys, "stdlib_module_names", ()) or target.has_module(top):
            return True
        sites = tuple(str(site) for site in target.sites)
        return find_installed_spec(top, ctx.excluded, target_sites=sites) is not None

    def _verdict(
        self, file: Path, node: ast.AST, module: str, members: List[str], ctx: "_FileContext"
    ) -> Issue:
        line, column = getattr(node, "lineno", 0), getattr(node, "col_offset", 0)
        knowledge = ctx.knowledge
        matching = []
        for req in ctx.requirements:
            view = knowledge.view(req)
            if provides(view.names, module, members):
                matching.append((req, view))
        if matching:
            states = [marker_active(m[0].marker, ctx.marker_env) for m in matching]
            active = [m for m, s in zip(matching, states) if s is not False]
            req, view = (active or matching)[0]
            sources = frozenset(r.label for r, _ in matching)
            ev = evidence(module, req.written, view.state, knowledge.environment)
            if view.mapping_audit is not None:
                ev["mapping_audit"] = view.mapping_audit
            if req.marker:
                state_of_req = states[matching.index((req, view))]
                ev["marker_evaluation"] = {True: "ACTIVE", False: "INACTIVE", None: "UNKNOWN"}[
                    state_of_req
                ]
            if self._is_requirements_only_metadata_gap(sources, ctx.has_pyproject):
                issue = self._make_metadata_gap_issue(file, line, column, module, sources)
            else:
                inactive_marker = None if active else req.marker
                issue = self._declared_unavailable(
                    file, line, column, module, sources, req, knowledge, inactive_marker
                )
        else:
            known = knowledge.known_providers(module, members)
            # A provider is named only when exactly one distribution is known to supply the
            # name; several candidates and nothing that selects one: named nowhere.
            provider, state = known[0] if len(known) == 1 else (None, PROVIDER_UNKNOWN)
            ev = evidence(module, provider, state, knowledge.environment)
            audit = knowledge.mapping_audit_of(provider)
            if audit is not None:
                ev["mapping_audit"] = audit
            if len(known) > 1:
                ev["candidates"] = [name for name, _ in known]
            if line in ctx.guarded:
                issue = self._undeclared_optional(file, line, column, module)
            elif known:
                issue = self._undeclared_known(file, line, column, module, provider, state, known)
            else:
                issue = self._unknown_provider(file, line, column, module)
        issue.subject = module  # one import line can name several modules
        ev["target_platform"] = knowledge.target.platform if knowledge.target is not None else None
        issue.evidence = ev
        return issue

    def _declared_unavailable(
        self,
        file: Path,
        line: int,
        column: int,
        module: str,
        sources: FrozenSet[str],
        req: Requirement,
        knowledge: ProviderKnowledge,
        inactive_marker: Optional[str],
    ) -> Issue:
        locations = ", ".join(sorted(sources))
        if knowledge.target is not None:
            where = f"the target environment ({knowledge.target.path.name})"
        else:
            where = "the analyzer runtime"
        same_name = req.written.replace("-", "_").lower() == module.split(".")[0].lower()
        provider = "" if same_name else f" (provided by '{req.written}')"
        note = ""
        if inactive_marker:
            note = f"; that declaration applies only where {inactive_marker}, and this import runs here"
        return Issue(
            pattern_id="runtime_unavailable_dependency",
            severity=Severity.MEDIUM,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=(
                f"Declared dependency '{module}'{provider} is unavailable in {where} "
                f"(declared in {locations}){note}."
            ),
            suggestion=(
                "Install the declared dependency in the analysis environment, then rerun. "
                "This is environment evidence, not proof of a phantom package."
            ),
        )

    def _undeclared_optional(self, file: Path, line: int, column: int, module: str) -> Issue:
        return Issue(
            pattern_id="undeclared_optional_dependency",
            severity=Severity.MEDIUM,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=(
                f"Undeclared optional dependency: '{module}' is guarded with "
                f"ImportError but not listed in [project.optional-dependencies]"
            ),
            suggestion=(
                f"Add '{module}' to the appropriate "
                f"[project.optional-dependencies.<group>] in pyproject.toml so "
                f"users know this feature requires an extra install."
            ),
        )

    def _undeclared_known(
        self,
        file: Path,
        line: int,
        column: int,
        module: str,
        provider: Optional[str],
        state: str,
        known: List[Tuple[str, str]],
    ) -> Issue:
        """HIGH only when one provider is identified from the target environment's own files
        or metadata; a provider known from mapping knowledge (the shipped table, the analyzer's
        installs) or several candidates are review candidates: MEDIUM."""
        identified = provider is not None and state in (ARTIFACT_VERIFIED, METADATA_DECLARED)
        if provider is not None:
            whom = f"the distribution '{provider}'"
            confirm = f"Confirm that '{provider}' is the package this code means, then declare it. "
        else:
            whom = "one of " + ", ".join(f"'{name}'" for name, _ in known)
            confirm = "Several distributions provide this name; confirm which one is meant. "
        return Issue(
            pattern_id="undeclared_dependency",
            severity=Severity.HIGH if identified else Severity.MEDIUM,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=(
                f"Undeclared dependency: '{module}' is provided by {whom}, "
                "which no dependency declaration on this file's path names"
            ),
            suggestion=(
                confirm
                + "Do not install or declare a package on the strength of this finding alone."
            ),
        )

    def _unknown_provider(self, file: Path, line: int, column: int, module: str) -> Issue:
        return self.create_issue(
            file=file,
            line=line,
            column=column,
            message=(
                f"Phantom import: no installed distribution, dependency declaration or known "
                f"provider supplies '{module}'"
            ),
            suggestion=(
                f"Confirm which package '{module}' was meant to come from before installing or "
                "declaring anything: a name that can be found on a package index is not proof "
                "that it is the intended package. AI models sometimes generate plausible-looking "
                "package names."
            ),
            severity_override=Severity.HIGH,
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
        issue = Issue(
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
            subject=module_name,
        )
        return issue


@dataclass(frozen=True)
class _FileContext:
    """What one file's import verdicts read."""

    excluded: Tuple[Path, ...]
    guarded: FrozenSet[int]
    inactive: FrozenSet[int]  # under a platform test that is false in the target environment
    undecided: FrozenSet[int]  # under a platform test the target environment does not decide
    deferred: DeferredImports  # TYPE_CHECKING-only lines; directories added to sys.path
    local_paths: Dict[str, Tuple[str, ...]]  # module names anywhere in the project -> paths
    boundary: Path  # path_boundary: links out of it are not followed or read
    knowledge: ProviderKnowledge
    requirements: Tuple[Requirement, ...]
    declaration_root: Optional[Path]  # the root `related_declarations` paths are relative to
    own_declarations: FrozenSet[str]  # the declaration files on this file's path
    runs_as_script: bool  # a top-level `if __name__ == "__main__":` block
    relative_fallbacks: FrozenSet[Tuple[int, str]]  # absolute fallbacks of relative imports
    unread: Tuple[Path, ...]  # declarations / an environment behind a link out of the scan area
    has_pyproject: bool
    marker_env: Dict[str, str]  # marker variables the target environment establishes
