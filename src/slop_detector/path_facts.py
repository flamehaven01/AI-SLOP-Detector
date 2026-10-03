"""Root-relative path facts: what a file's path says about it, decided once.

Only the part of a path below the root is a fact about the file. A `tests` or
`build` directory above the root is where the checkout lives, not a property of
the file. The root is, in order: the scan root of a project scan, the nearest
project marker of a single file (project_resolution.find_project_root), or none.
Without a root only the file name is a fact; directory facts are unknown (None).

These are path facts, not evidence: `conftest.py` is a test context file, which
says nothing about whether tests exist or run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Iterable, Optional, Tuple, Union

from slop_detector.project_resolution import find_project_root

PathLike = Union[str, PurePath]

# Directories whose files are not project source: environments, caches, build output.
DEFAULT_EXCLUDE_PARTS = frozenset(
    {
        ".claude",
        ".venv",
        "venv",
        "site-packages",
        "node_modules",
        "__pycache__",
        ".git",
        "build",
        "dist",
        ".tox",
        ".next",
        "htmlcov",
    }
)
TEST_DIRS = frozenset({"tests", "test", "__tests__"})
INTEGRATION_DIRS = frozenset({"integration", "integration_tests", "it"})
E2E_DIRS = frozenset({"e2e"})
CORPUS_DIR = "corpus"


@dataclass(frozen=True)
class PathFacts:
    """Facts a path states about a file, relative to a root.

    test_kind: unit | integration | e2e for a test file, none for a non-test
    file, unknown when the directory facts are unknown. Booleans are None when
    unknown.
    """

    name: str
    relative_path: Optional[str]
    dir_parts: Tuple[str, ...]
    root_known: bool
    is_test: Optional[bool]
    test_kind: str
    is_corpus: Optional[bool]
    exclusion_reason: Optional[str]

    def fingerprint(self) -> str:
        """Stable key for everything that path facts can change downstream."""
        return hashlib.sha256(repr(self).encode("utf-8")).hexdigest()[:16]


def resolve_root(file_path: PathLike, root: Optional[PathLike] = None) -> Optional[Path]:
    """The scan root when given, else the nearest project marker, else None."""
    if root is not None:
        return Path(root)
    return find_project_root(Path(file_path).resolve())


def relative_to_root(file_path: PathLike, root: PathLike) -> Optional[PurePath]:
    """`file_path` below `root`, or None when it is not below it."""
    path, base = PurePath(file_path), PurePath(root)
    try:
        return path.relative_to(base)
    except ValueError:
        pass
    try:
        return Path(file_path).resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return None


def default_exclusion_reason(parts: Iterable[str]) -> Optional[str]:
    """`directory:<name>` when a path part is a default-excluded directory."""
    hits = {part.lower() for part in parts} & DEFAULT_EXCLUDE_PARTS
    return f"directory:{sorted(hits)[0]}" if hits else None


def _name_is_test(name: str) -> bool:
    return name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"


def _test_kind(name: str, dir_parts: Tuple[str, ...], root_known: bool) -> str:
    stem = name.lower()
    if E2E_DIRS & set(dir_parts) or "e2e" in stem:
        return "e2e"
    if INTEGRATION_DIRS & set(dir_parts) or "integration" in stem:
        return "integration"
    return "unit" if root_known else "unknown"


def _corpus_under_tests(dir_parts: Tuple[str, ...]) -> bool:
    for index, part in enumerate(dir_parts):
        if part == CORPUS_DIR and TEST_DIRS & set(dir_parts[:index]):
            return True
    return False


def path_facts(file_path: PathLike, root: Optional[PathLike]) -> PathFacts:
    """Facts about `file_path` below `root` (no root: file-name facts only)."""
    name = PurePath(file_path).name
    relative = relative_to_root(file_path, root) if root is not None else None
    if relative is None:
        named_test = _name_is_test(name)
        return PathFacts(
            name=name,
            relative_path=None,
            dir_parts=(),
            root_known=False,
            is_test=True if named_test else None,
            test_kind=_test_kind(name, (), False) if named_test else "unknown",
            is_corpus=None,
            exclusion_reason=None,
        )
    dir_parts = tuple(part.lower() for part in relative.parts[:-1])
    is_test = _name_is_test(name) or bool(TEST_DIRS & set(dir_parts))
    return PathFacts(
        name=name,
        relative_path=relative.as_posix(),
        dir_parts=dir_parts,
        root_known=True,
        is_test=is_test,
        test_kind=_test_kind(name, dir_parts, True) if is_test else "none",
        is_corpus=_corpus_under_tests(dir_parts),
        exclusion_reason=default_exclusion_reason(dir_parts),
    )


def facts_for(file_path: PathLike, root: Optional[PathLike] = None) -> PathFacts:
    """Path facts under the root rule (scan root, then project marker, then none)."""
    return path_facts(file_path, resolve_root(file_path, root))
