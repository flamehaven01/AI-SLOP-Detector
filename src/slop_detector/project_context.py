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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from slop_detector.dependency_declarations import is_declaration_file

_SKIP_DIRS = frozenset({"__pycache__"})
# Environments next to a script are not packages it imports.
_ENVIRONMENT_DIRS = frozenset({"venv", "env", "site-packages", "node_modules", "__pycache__"})


@dataclass(frozen=True)
class ProjectContextSnapshot:
    root: Path
    fingerprint: str


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
    topology, declarations = _walk(root)
    for rel, path in declarations:
        digest.update(b"D\0" + rel.encode("utf-8") + b"\0")
        digest.update(_read_bytes(path))
    for kind, rel in topology:
        digest.update(f"{kind}\0{rel}\0".encode("utf-8"))
    return ProjectContextSnapshot(root, digest.hexdigest())


def is_importable_directory(path: Path) -> bool:
    """A directory `import <name>` loads from a sys.path entry: a regular
    package or a namespace package (a .py file somewhere below it)."""
    name = path.name
    if name.startswith(".") or name in _ENVIRONMENT_DIRS or not name.isidentifier():
        return False
    if not path.is_dir():
        return False
    if (path / "__init__.py").is_file():
        return True
    for _current, dirs, files in os.walk(path):
        if any(item.endswith(".py") for item in files):
            return True
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _ENVIRONMENT_DIRS]
    return False


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _walk(root: Path) -> Tuple[List[Tuple[str, str]], List[Tuple[str, Path]]]:
    """Module topology and declaration files below the root, in one walk."""
    entries: List[Tuple[str, str]] = []
    declarations: List[Tuple[str, Path]] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS)
        base = Path(current).relative_to(root)
        entries.extend(("d", (base / d).as_posix()) for d in dirs)
        entries.extend(("f", (base / f).as_posix()) for f in sorted(files) if f.endswith(".py"))
        in_requirements_dir = base.name == "requirements"
        for name in files:
            if is_declaration_file(name) or (in_requirements_dir and name.endswith(".txt")):
                declarations.append(((base / name).as_posix(), Path(current) / name))
    return sorted(entries), sorted(declarations)


def _directory_snapshot(directory: Path) -> ProjectContextSnapshot:
    try:
        names = sorted(
            p.name
            for p in directory.iterdir()
            if p.suffix == ".py" or (p.is_dir() and is_importable_directory(p))
        )
    except OSError:
        names = []
    digest = hashlib.sha256("\0".join(names).encode("utf-8")).hexdigest()
    return ProjectContextSnapshot(directory, digest)
