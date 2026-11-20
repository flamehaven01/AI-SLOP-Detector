"""The file-system area import resolution may read (3.18, S1).

The boundary is the explicitly authorized scan root while a scan of it runs; for a single-file
analysis it is the root the caller passes (the file's project root). It is a real path: links
are resolved before anything is compared.

A directory or file link (a symlink, or on Windows a junction or other reparse point) is followed
only when its real path is inside the boundary, and a directory already visited by its real path
is not walked again. A link out of the boundary is not opened, listed or tested: what is behind
it is not known, which callers must keep apart from "missing".

Link detection: `S_ISLNK` covers symlinks everywhere; on Windows the reparse-point attribute
(`st_file_attributes`, Python 3.5+) also covers junctions, which `os.path.islink` does not report
and `os.path.isjunction` (3.12+) does not exist for on 3.8. One check serves 3.8 to 3.14.
"""

from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Iterator, List, Optional, Tuple

_AUTHORIZED_ROOT: ContextVar[Optional[Path]] = ContextVar("slop_authorized_root", default=None)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@contextmanager
def authorized_root_scope(root: Optional[Path]) -> Iterator[None]:
    """The scan root the user asked to analyze, for the duration of that scan."""
    token = _AUTHORIZED_ROOT.set(real_path(root) if root is not None else None)
    try:
        yield
    finally:
        _AUTHORIZED_ROOT.reset(token)


def real_path(path: Path) -> Path:
    return Path(os.path.realpath(str(path)))


def walk_boundary(root: Path) -> Path:
    """The boundary for reading below `root`: the authorized scan root during a scan, else
    `root` itself (real path)."""
    authorized = _AUTHORIZED_ROOT.get()
    return authorized if authorized is not None else real_path(root)


def is_inside(path: Path, boundary: Path) -> bool:
    """`path`'s real location (links resolved) is the boundary or below it."""
    real = real_path(path)
    return real == boundary or boundary in real.parents


def _is_link_stat(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)


def is_link(path: Path) -> bool:
    try:
        return _is_link_stat(os.lstat(str(path)))
    except OSError:
        return False


def leaves(path: Path, boundary: Path) -> bool:
    """`path` (whose parent is known to be inside) is a link out of the boundary. A path that is
    not a link costs one lstat; only a link is resolved."""
    return is_link(path) and not is_inside(path, boundary)


# How many links (aliases) one real directory is walked through, besides its own path, which is
# always walked. A guard, not a measurement: it keeps chains of aliases finite; an alias it stops
# is recorded in `truncated` (callers put it in the fingerprint), never dropped silently.
MAX_ALIASES_PER_DIRECTORY = 8


def entry_is_link(entry: os.DirEntry) -> bool:
    if entry.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        return _is_link_stat(entry.stat(follow_symlinks=False))  # cached from the listing
    except OSError:
        return False


@dataclass(frozen=True)
class LinkEntry:
    """A link met during a walk: where it is, and its real target when inside (None: outside,
    not followed)."""

    path: Path
    target: Optional[Path]


def bounded_walk(
    top: Path,
    boundary: Path,
    links: Optional[List[LinkEntry]] = None,
    truncated: Optional[List[Path]] = None,
) -> Iterator[Tuple[Path, List[str], List[str]]]:
    """Top-down walk like os.walk (callers may prune `dirs` in place), inside the boundary only.

    A link entry is resolved: outside the boundary it is recorded in `links` with no target and
    neither listed nor descended; inside it is listed and followed. Every logical path is
    walked (an alias and the original both keep their files); only a directory that is its own
    ancestor on the current path (a link cycle) is listed but not walked again, and one real
    directory is walked through at most MAX_ALIASES_PER_DIRECTORY links besides its own path (the
    other aliases go to `truncated`). Nothing is yielded when `top` itself is outside.
    """
    top_real = real_path(top)
    if not (top_real == boundary or boundary in top_real.parents):
        if links is not None:
            links.append(LinkEntry(top, None))
        return
    top_key = os.path.normcase(str(top_real))
    aliases: dict = {}
    stack: List[Tuple[Path, Path, FrozenSet[str]]] = [(top, top_real, frozenset({top_key}))]
    while stack:
        current, current_real, ancestors = stack.pop()
        try:
            with os.scandir(str(current)) as listing:
                entries = sorted(listing, key=lambda e: e.name)
        except OSError:
            continue
        dirs: List[str] = []
        files: List[str] = []
        reals = {}
        via_link = set()
        for entry in entries:
            link = entry_is_link(entry)
            real = real_path(Path(entry.path)) if link else current_real / entry.name
            if link:
                inside = real == boundary or boundary in real.parents
                if links is not None:
                    links.append(LinkEntry(Path(entry.path), real if inside else None))
                if not inside:
                    continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                dirs.append(entry.name)
                reals[entry.name] = real
                if link:
                    via_link.add(entry.name)
            else:
                files.append(entry.name)
        yield current, dirs, files
        walk_next: List[Tuple[Path, Path, FrozenSet[str]]] = []
        for name in dirs:  # decided in name order, so the first aliases are the ones kept
            key = os.path.normcase(str(reals[name]))
            if key in ancestors:
                continue  # a link back up the current path: a cycle
            if name in via_link:
                # only aliases count against the guard: a directory's own path is always walked
                if aliases.get(key, 0) >= MAX_ALIASES_PER_DIRECTORY:
                    if truncated is not None:
                        truncated.append(current / name)
                    continue
                aliases[key] = aliases.get(key, 0) + 1
            walk_next.append((current / name, reals[name], ancestors | {key}))
        stack.extend(reversed(walk_next))


def relative_label(path: Path, boundary: Path) -> str:
    """A POSIX path relative to the boundary for reports (`../x` when outside it)."""
    try:
        return Path(os.path.relpath(str(path), str(boundary))).as_posix()
    except ValueError:  # another drive on Windows: no relative form
        return path.as_posix()
