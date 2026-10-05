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
from functools import lru_cache
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


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


def find_installed_spec(name: str, excluded: Iterable[Path] = ()) -> Optional[ModuleSpec]:
    """importlib.util.find_spec for a top-level name over the environment search path.

    sys.modules is not consulted: what this process happened to import is not
    evidence about the analyzed code. Nothing is imported or executed.
    """
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


_FINGERPRINTS: Dict[Tuple[str, ...], str] = {}


def environment_fingerprint() -> str:
    """Identity of the environment the import evidence comes from (cache key part).

    The interpreter, the search path (cwd excluded, so the cwd does not split
    the cache), and the top-level names in each search-path directory: that
    covers installs, uninstalls and upgrades (dist-info names carry the version)
    and plain packages added to a path directory. Not covered: editing the
    source of an already installed package in place (e.g. an editable install).
    """
    path = search_path()
    if path not in _FINGERPRINTS:
        listing = [(entry, _top_level_names(entry)) for entry in path]
        payload = repr((sys.version, sys.implementation.cache_tag, listing))
        _FINGERPRINTS[path] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return _FINGERPRINTS[path]


def _top_level_names(entry: str) -> Tuple[str, ...]:
    try:
        return tuple(sorted(os.listdir(entry)))
    except OSError:  # a zip, a missing directory: the entry string still counts
        return ()
