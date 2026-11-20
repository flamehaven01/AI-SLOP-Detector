"""Where installed (external) modules are looked up, for phantom_import and phantom_member.

Evidence that a module is installed comes from the analyzer's environment: the
meta-path finders and the sys.path entries. Two kinds of sys.path entry are
not that environment and are left out:

- the analyzer's working directory ("" or the cwd itself, which `python -m`
  and the pre-commit hooks put on sys.path): a `models/` directory next to
  where the analyzer runs says nothing about the analyzed project;
- the analyzed project's own roots: what is project code is decided by
  ProjectModuleIndex, not by whether the project happens to be on sys.path.

Entries are compared as exact directories, so an environment inside one of
them (a `.venv` under the project or the cwd) is still searched.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import os
import sys
import sysconfig
import time
from functools import lru_cache
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@lru_cache(maxsize=4096)
def _key(entry: str, cwd: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.join(cwd, entry)))


_SEARCH_PATHS: Dict[Tuple[Tuple[object, ...], str, Tuple[str, ...]], Tuple[str, ...]] = {}


def search_path(excluded: Iterable[Path] = ()) -> Tuple[str, ...]:
    """sys.path without the cwd and without the `excluded` directories."""
    cwd = os.getcwd()
    dropped = tuple(str(path) for path in excluded)
    memo = (tuple(sys.path), cwd, dropped)
    if memo not in _SEARCH_PATHS:
        drop = {_key("", cwd)} | {_key(path, cwd) for path in dropped}
        _SEARCH_PATHS[memo] = tuple(
            entry for entry in sys.path if isinstance(entry, str) and _key(entry, cwd) not in drop
        )
    return _SEARCH_PATHS[memo]


def stdlib_paths() -> Tuple[str, ...]:
    """The analyzer interpreter's standard-library directories (no site-packages)."""
    paths = sysconfig.get_paths()
    found = [paths.get("stdlib"), paths.get("platstdlib")]
    dynload = os.path.join(sys.base_prefix, "DLLs") if os.name == "nt" else None
    if paths.get("platstdlib"):
        found.append(os.path.join(paths["platstdlib"], "lib-dynload"))
    found.append(dynload)
    return tuple(dict.fromkeys(p for p in found if p and os.path.isdir(p)))


def find_installed_spec(
    name: str, excluded: Iterable[Path] = (), target_sites: Sequence[str] = ()
) -> Optional[ModuleSpec]:
    """importlib.util.find_spec for a top-level name over the environment search path.

    `target_sites`: a target environment's site-packages. When given, the module is looked
    up there and in the standard library only: the analyzer's installed packages are not
    evidence about the target. sys.modules is not consulted: what this process happened to
    import is not evidence about the analyzed code. Nothing is imported or executed.
    """
    if target_sites:
        if name in sys.builtin_module_names:
            return importlib.machinery.BuiltinImporter.find_spec(name)
        return importlib.machinery.PathFinder.find_spec(
            name, list(target_sites) + list(stdlib_paths())
        )
    path: List[str] = list(search_path(excluded))
    for finder in sys.meta_path:
        if finder is importlib.machinery.PathFinder:
            spec = importlib.machinery.PathFinder.find_spec(name, path)
        else:
            find_spec = getattr(finder, "find_spec", None)
            spec = find_spec(name, None) if find_spec is not None else None
        if spec is not None:
            return spec
    return None


# A directory changed this recently may change again within the same mtime tick
# (on Windows an uninstall right after the last look left the mtime unchanged in
# 182 of 300 tries): its mtime alone does not identify its contents, so it is
# identified by its listing as well. 2 s covers coarse timestamp file systems
# (FAT, 2 s); after that a change gives a later mtime.
RACY_NS = 2_000_000_000

State = Tuple[Tuple[object, ...], ...]


def environment_state() -> State:
    """(entry, directory mtime[, listing]) for each search-path entry.

    An install, uninstall or upgrade adds or removes a top-level entry in a
    search-path directory, which changes that directory's mtime; caches keyed
    by this state follow the environment inside one long-lived process. A
    directory modified within RACY_NS of now is also identified by its
    listing, since a second change in the same tick keeps the mtime. Not
    covered: a tool that sets a directory's mtime back to an older value.
    """
    now = time.time_ns()
    state: List[Tuple[object, ...]] = []
    for entry in search_path():
        try:
            mtime = os.stat(entry).st_mtime_ns
        except OSError:  # a zip, a missing directory: the entry string still counts
            state.append((entry, -1))
            continue
        if mtime >= now - RACY_NS:
            state.append((entry, mtime, _top_level_names(entry)))
        else:
            state.append((entry, mtime))
    return tuple(state)


_FINGERPRINTS: Dict[State, str] = {}


def environment_fingerprint() -> str:
    """Identity of the environment the import evidence comes from (cache key part).

    The interpreter, the search path (cwd excluded, so the cwd does not split
    the cache), and the top-level names in each search-path directory: that
    covers installs, uninstalls and upgrades (dist-info names carry the version)
    and plain packages added to a path directory. Not covered: editing the
    source of an already installed package in place (e.g. an editable install).
    """
    state = environment_state()
    if state not in _FINGERPRINTS:
        listing = [(item[0], _top_level_names(str(item[0]))) for item in state]
        payload = repr((sys.version, sys.implementation.cache_tag, listing))
        _FINGERPRINTS.clear()
        _FINGERPRINTS[state] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return _FINGERPRINTS[state]


def _top_level_names(entry: str) -> Tuple[str, ...]:
    try:
        return tuple(sorted(os.listdir(entry)))
    except OSError:  # a zip, a missing directory: the entry string still counts
        return ()
