"""Identity of the project context that import resolution reads.

phantom_import and phantom_member depend on more than the analyzed file: on
the project's dependency declarations and on its module topology. A snapshot
fingerprints exactly those inputs:

- the contents of every dependency declaration file in the tree (see
  slop_detector.dependency_declarations): a declaration between a file and
  its root is evidence for that file;
- every project-relative directory and .py path (which modules, packages and
  namespace directories exist). File contents are not part of it: editing a
  module does not change what can be imported.

Hidden directories are skipped (an import path cannot name them), as is
__pycache__. A file with no project root gets a snapshot of its directory's
.py names and importable subdirectories, which is all its sibling-module
lookup reads.

Process-local resolver caches and the persistent analysis cache are keyed by
(root, fingerprint), so a changed context is never served from a cache. Inside
a scan scope a root's snapshot is built once and stays fixed for the scan; no
process-global state is mutated.
"""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from slop_detector.dependency_declarations import is_declaration_file
from slop_detector.path_boundary import (
    LinkEntry,
    bounded_walk,
    is_inside,
    relative_label,
    walk_boundary,
)

_SKIP_DIRS = frozenset({"__pycache__"})
# Environments next to a script are not packages it imports.
_ENVIRONMENT_DIRS = frozenset({"venv", "env", "site-packages", "node_modules", "__pycache__"})


@dataclass(frozen=True)
class ProjectContextSnapshot:
    root: Path
    fingerprint: str
    # Every name a .py file or a directory leading to one could be imported as, from anywhere
    # below the root (environment directories excluded) -> those files and directories, relative
    # POSIX paths. Derived from the same walk as the fingerprint.
    module_paths: Dict[str, Tuple[str, ...]] = field(default_factory=dict, compare=False)
    # Names of links below the root whose real path leaves the boundary (not followed: what is
    # behind them is not known) -> those links, relative POSIX paths.
    blocked_paths: Dict[str, Tuple[str, ...]] = field(default_factory=dict, compare=False)
    # Aliases (links inside the boundary) the walk did not enter because their real directory
    # was already walked through MAX_ALIASES_PER_DIRECTORY links; relative POSIX paths.
    truncated_paths: Tuple[str, ...] = field(default=(), compare=False)


_SCOPE: ContextVar[Optional[Dict[Tuple[str, str], ProjectContextSnapshot]]] = ContextVar(
    "slop_project_context_scope", default=None
)


@contextmanager
def project_context_scope() -> Iterator[None]:
    """Snapshots built inside are reused until the outermost scope exits."""
    if _SCOPE.get() is not None:
        yield
        return
    token = _SCOPE.set({})
    try:
        yield
    finally:
        _SCOPE.reset(token)


def project_context(root: Path) -> ProjectContextSnapshot:
    """The snapshot of a project root: the scope's, or a fresh one outside a scope."""
    return _scoped(("project", str(root)), lambda: build_project_context_snapshot(root))


def directory_context(directory: Path) -> ProjectContextSnapshot:
    """The snapshot of a root-less file's directory (its sibling .py names)."""
    return _scoped(("directory", str(directory)), lambda: _directory_snapshot(directory))


def context_for_file(file: Path, project_root: Optional[Path]) -> ProjectContextSnapshot:
    return project_context(project_root) if project_root else directory_context(file.parent)


def fingerprint_for_roots(file: Path, roots: Sequence[Path]) -> str:
    """Identity of every project context a file's import evidence comes from."""
    if not roots:
        return directory_context(file.parent).fingerprint
    return "+".join(project_context(root).fingerprint for root in roots)


def _scoped(key: Tuple[str, str], build) -> ProjectContextSnapshot:
    scope = _SCOPE.get()
    if scope is not None and key in scope:
        return scope[key]
    snapshot = build()
    if scope is not None:
        scope[key] = snapshot
    return snapshot


def build_project_context_snapshot(root: Path) -> ProjectContextSnapshot:
    digest = hashlib.sha256()
    topology, declarations, links, truncated = _walk(root)
    for rel, path in declarations:
        digest.update(b"D\0" + rel.encode("utf-8") + b"\0")
        digest.update(_read_bytes(path))
    for kind, rel in topology:
        digest.update(f"{kind}\0{rel}\0".encode("utf-8"))
    # The project's own environment is import evidence too (slop_detector.import_providers):
    # installing or removing a distribution there is a new context.
    from slop_detector.import_providers import find_target_environment

    target = find_target_environment((root,))
    if target is not None:
        digest.update(b"T\0" + target.fingerprint.encode("utf-8"))
    return ProjectContextSnapshot(
        root,
        digest.hexdigest(),
        _module_paths(topology),
        _blocked_paths(root, links),
        tuple(sorted(path.relative_to(root).as_posix() for path in truncated)),
    )


def _blocked_paths(root: Path, links: Sequence[LinkEntry]) -> Dict[str, Tuple[str, ...]]:
    found: Dict[str, set] = {}
    for link in links:
        if link.target is None:
            name = link.path.name[: -len(".py")] if link.path.suffix == ".py" else link.path.name
            found.setdefault(name, set()).add(link.path.relative_to(root).as_posix())
    return {name: tuple(sorted(paths)) for name, paths in found.items()}


def _module_paths(topology: Sequence[Tuple[str, str]]) -> Dict[str, Tuple[str, ...]]:
    found: Dict[str, set] = {}
    for kind, rel in topology:
        parts = rel.split("/")
        if kind != "f" or any(p in _ENVIRONMENT_DIRS for p in parts):
            continue
        stem = parts[-1][: -len(".py")]
        if stem.isidentifier() and stem != "__init__":
            found.setdefault(stem, set()).add(rel)
        for depth, part in enumerate(parts[:-1]):
            if part.isidentifier():
                found.setdefault(part, set()).add("/".join(parts[: depth + 1]))
    return {name: tuple(sorted(paths)) for name, paths in found.items()}


def importable_state(path: Path, boundary: Path) -> Optional[bool]:
    """Whether `import <name>` loads this directory from a sys.path entry (a regular package, or
    a namespace package: a .py file somewhere below it). None when the answer lies behind a link
    out of the boundary, which is not followed: not known, not "no"."""
    name = path.name
    if name.startswith(".") or name in _ENVIRONMENT_DIRS or not name.isidentifier():
        return False
    if os.path.lexists(str(path)) and not is_inside(path, boundary):
        return None
    if not path.is_dir():
        return False
    links: List[LinkEntry] = []
    for _current, dirs, files in bounded_walk(path, boundary, links):
        if any(item.endswith(".py") for item in files):
            return True
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _ENVIRONMENT_DIRS]
    return None if any(link.target is None for link in links) else False


def is_importable_directory(path: Path, boundary: Optional[Path] = None) -> bool:
    """importable_state is True (boundary: the scan root, else `path` itself)."""
    return importable_state(path, boundary or walk_boundary(path)) is True


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _walk(
    root: Path,
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, Path]], List[LinkEntry], List[Path]]:
    """Module topology, declaration files, links and truncated aliases below the root, in one
    walk inside the boundary. Each link is part of the topology with its target (or OUT), so
    pointing a link elsewhere is a new context even when the names behind it are the same; which
    aliases are truncated follows from the links and the tree, so it needs no entry of its own."""
    entries: List[Tuple[str, str]] = []
    declarations: List[Tuple[str, Path]] = []
    links: List[LinkEntry] = []
    truncated: List[Path] = []
    boundary = walk_boundary(root)
    for current, dirs, files in bounded_walk(root, boundary, links, truncated):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS)
        base = Path(current).relative_to(root)
        entries.extend(("d", (base / d).as_posix()) for d in dirs)
        entries.extend(("f", (base / f).as_posix()) for f in sorted(files) if f.endswith(".py"))
        in_requirements_dir = base.name == "requirements"
        for name in files:
            if is_declaration_file(name) or (in_requirements_dir and name.endswith(".txt")):
                declarations.append(((base / name).as_posix(), Path(current) / name))
    for link in links:
        target = "OUT" if link.target is None else relative_label(link.target, boundary)
        entries.append(("l", link.path.relative_to(root).as_posix() + "\0" + target))
    return sorted(entries), sorted(declarations), links, truncated


def _directory_snapshot(directory: Path) -> ProjectContextSnapshot:
    boundary = walk_boundary(directory)
    try:
        names = sorted(
            p.name
            for p in directory.iterdir()
            if (p.suffix == ".py" and is_inside(p, boundary))
            or (p.is_dir() and is_importable_directory(p, boundary))
        )
    except OSError:
        names = []
    digest = hashlib.sha256("\0".join(names).encode("utf-8")).hexdigest()
    return ProjectContextSnapshot(directory, digest)
