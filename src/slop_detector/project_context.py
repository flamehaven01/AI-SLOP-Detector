"""Identity of the project context that import resolution reads.

phantom_import and phantom_member depend on more than the analyzed file: on
the project's dependency declarations and on its module topology. A snapshot
fingerprints exactly those inputs:

- the contents of pyproject.toml, requirements.txt and requirements/*.txt
  (dependencies and module-root configuration);
- every project-relative directory and .py path (which modules, packages and
  namespace directories exist). File contents are not part of it: editing a
  module does not change what can be imported.

Hidden directories are skipped (an import path cannot name them), as is
__pycache__. A file with no project root gets a snapshot of its directory's
.py names, which is all its sibling-module lookup reads.

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
from typing import Dict, Iterator, List, Optional, Tuple

DEPENDENCY_FILES = ("pyproject.toml", "requirements.txt")
_SKIP_DIRS = frozenset({"__pycache__"})


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
    for path in _dependency_files(root):
        digest.update(b"D\0" + path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(_read_bytes(path))
    for kind, rel in _topology(root):
        digest.update(f"{kind}\0{rel}\0".encode("utf-8"))
    return ProjectContextSnapshot(root, digest.hexdigest())


def _dependency_files(root: Path) -> List[Path]:
    files = [root / name for name in DEPENDENCY_FILES if (root / name).is_file()]
    requirements = root / "requirements"
    if requirements.is_dir():
        files.extend(sorted(requirements.glob("*.txt")))
    return files


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _topology(root: Path) -> List[Tuple[str, str]]:
    entries: List[Tuple[str, str]] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS)
        base = Path(current).relative_to(root)
        entries.extend(("d", (base / d).as_posix()) for d in dirs)
        entries.extend(("f", (base / f).as_posix()) for f in sorted(files) if f.endswith(".py"))
    return sorted(entries)


def _directory_snapshot(directory: Path) -> ProjectContextSnapshot:
    try:
        names = sorted(p.name for p in directory.iterdir() if p.suffix == ".py")
    except OSError:
        names = []
    digest = hashlib.sha256("\0".join(names).encode("utf-8")).hexdigest()
    return ProjectContextSnapshot(directory, digest)
