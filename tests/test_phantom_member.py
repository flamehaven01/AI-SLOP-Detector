"""RED corpus for phantom_member and unverified_imports.

Contract:
- the package and the name exist (source evidence)       -> clean
- the top-level package does not exist                    -> phantom_import (unchanged)
- the package exists, the name is shown to be absent      -> phantom_member finding
- the package exists, absence cannot be shown statically  -> unverified_imports entry,
  evidence_state "unknown", score_effect "none"
The target package is never imported or executed: only its files are read.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import sys
from pathlib import Path
from typing import Dict, List

import pytest

from slop_detector.analysis_cache import CACHE_ENGINE_VERSION
from slop_detector.core import SlopDetector

UNKNOWN_KEYS = {
    "line",
    "requested_module",
    "requested_name",
    "evidence_state",
    "reason",
    "score_effect",
    "verification_basis",
}


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A fake site-packages directory on sys.path. Importing realpkg would write MARKER."""
    root = tmp_path / "site"
    marker = tmp_path / "IMPORTED"
    _write(
        root,
        "realpkg/__init__.py",
        f"open({marker.as_posix()!r}, 'w').close()\n"
        "import os\n"
        "import realpkg.extra\n"
        "from .core import Engine\n"
        "from . import helpers\n"
        "VERSION = '1'\n"
        "def make():\n    return 1\n"
        "class Widget:\n    x = 1\n"
        "alias = make\n"
        "if os.environ.get('REALPKG_FLAG'):\n    maybe_thing = 1\n"
        "try:\n    from ._speedups import fast\nexcept ImportError:\n    fast = None\n"
        "__all__ = ['Engine', 'make', 'Ghost']\n",
    )
    _write(root, "realpkg/core.py", "class Engine:\n    x = 1\n")
    _write(root, "realpkg/helpers.py", "def h():\n    return 1\n")
    _write(root, "realpkg/extra.py", "E = 1\n")
    _write(root, "realpkg/sub/__init__.py", "S = 1\n")
    _write(root, "realpkg/sub/leaf.py", "def leaf():\n    return 1\n")
    (root / "realpkg" / f"native{importlib.machinery.EXTENSION_SUFFIXES[0]}").write_bytes(b"")
    _write(root, "lazypkg/__init__.py", "def __getattr__(name):\n    return name\n")
    _write(root, "starpkg/__init__.py", "from .impl import *\n")
    _write(root, "starpkg/impl.py", "def present():\n    return 1\n")
    _write(root, "dynpkg/__init__.py", "globals()['made_up'] = 1\n")
    _write(
        root,
        "sysmodpkg/__init__.py",
        "import sys\nsys.modules[__name__ + '.virtual'] = object()\n",
    )
    _write(root, "modonly.py", "def present():\n    return 1\n")
    _write(root, "nspkg/part.py", "P = 1\n")
    monkeypatch.syspath_prepend(str(root))
    importlib.invalidate_caches()
    return {"root": root, "marker": marker}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    _write(root, "pyproject.toml", '[project]\nname = "proj"\nversion = "0"\n')
    return root


def _analyze(project: Path, source: str):
    path = _write(project, "user.py", source)
    return SlopDetector(read_only=True).analyze_file(str(path))


def _members(analysis) -> List[str]:
    return sorted(f"{i.line}" for i in analysis.pattern_issues if i.pattern_id == "phantom_member")


def _phantom_ids(analysis) -> List[str]:
    return sorted(
        i.pattern_id for i in analysis.pattern_issues if i.pattern_id.startswith("phantom")
    )


def _unknowns(analysis) -> List[Dict]:
    rows = analysis.to_dict().get("unverified_imports")
    assert isinstance(rows, list), "FileAnalysis has no unverified_imports list"
    return rows


def _outcome(project: Path, statement: str) -> str:
    """'finding', 'unknown', or 'clean' for a one-statement file."""
    analysis = _analyze(project, statement + "\n")
    ids = _phantom_ids(analysis)
    unknowns = _unknowns(analysis)
    assert "phantom_import" not in ids, f"{statement!r} raised phantom_import: {ids}"
    if "phantom_member" in ids:
        assert not unknowns, f"{statement!r} is both a finding and unknown"
        return "finding"
    return "unknown" if unknowns else "clean"


# ---------------------------------------------------------------------------
# Present names stay clean (no false findings)
# ---------------------------------------------------------------------------

PRESENT = [
    "from realpkg import Engine",  # from .core import Engine
    "from realpkg import helpers",  # from . import helpers
    "from realpkg import extra",  # import realpkg.extra binds it
    "from realpkg import sub",  # package directory
    "from realpkg import core",  # module file
    "from realpkg import VERSION, make, Widget, alias",
    "from realpkg import native",  # extension module exists
    "import realpkg.sub.leaf",
    "from realpkg.sub.leaf import leaf",
    "from realpkg.core import Engine",
    "import modonly",
    "from modonly import present",
    "from nspkg import part",
    "import nspkg.part",
    "from json import loads, JSONDecodeError",
    "import json.decoder",
    "import os.path",  # os registers it with sys.modules['os.path'] = path
    "import sysmodpkg",
]


@pytest.mark.parametrize("statement", PRESENT)
def test_present_names_are_clean(site, project, statement):
    assert _outcome(project, statement) == "clean"


# ---------------------------------------------------------------------------
# Absence shown by source evidence -> phantom_member
# ---------------------------------------------------------------------------

ABSENT = [
    "from realpkg import invented",
    "import realpkg.invented",
    "from realpkg.sub import invented",
    "import realpkg.sub.invented",
    "from realpkg.core import Invented",
    "from modonly import invented",
    "import modonly.child",  # a module is not a package
    "from json import TotallyInventedAIOptimizer",
    "import json.this_api_does_not_exist",
]


@pytest.mark.parametrize("statement", ABSENT)
def test_absent_names_are_phantom_member(site, project, statement):
    assert _outcome(project, statement) == "finding"


def test_phantom_member_issue_shape(site, project):
    analysis = _analyze(project, "x = 1\nfrom realpkg import invented\n")
    issues = [i for i in analysis.pattern_issues if i.pattern_id == "phantom_member"]
    assert len(issues) == 1, [i.pattern_id for i in analysis.pattern_issues]
    issue = issues[0]
    assert issue.line == 2
    assert issue.severity.value == "high"
    assert "invented" in issue.message and "realpkg" in issue.message


# ---------------------------------------------------------------------------
# Absence cannot be shown -> unknown, never a finding
# ---------------------------------------------------------------------------

UNKNOWN = {
    "from realpkg import maybe_thing": "conditional_definition",
    "from realpkg import fast": "conditional_definition",
    "from realpkg import Ghost": "declared_in_all_only",
    "from lazypkg import anything": "module_getattr",
    "from starpkg import anything": "star_reexport",
    "from dynpkg import made_up": "dynamic_namespace",
    "import sysmodpkg.virtual": "dynamic_namespace",
    "from realpkg.native import Thing": "no_python_source",
    "from math import invented": "no_python_source",
    "from os.path import quantum_join": "runtime_dependent_alias",
    # Namespace packages are open: another distribution can add the portion.
    "from nspkg import invented": "namespace_portion_not_installed",
    "import nspkg.invented": "namespace_portion_not_installed",
    "from nspkg.missing.deep import thing": "namespace_portion_not_installed",
}


@pytest.mark.parametrize("statement", sorted(UNKNOWN))
def test_unverifiable_names_are_unknown_with_a_reason(site, project, statement):
    analysis = _analyze(project, statement + "\n")
    assert "phantom_member" not in _phantom_ids(analysis), statement
    rows = _unknowns(analysis)
    assert len(rows) == 1, rows
    row = rows[0]
    assert set(row) >= UNKNOWN_KEYS, sorted(set(row))
    assert row["evidence_state"] == "unknown"
    assert row["score_effect"] == "none"
    assert row["verification_basis"] == "source_static_analysis"
    assert row["reason"] == UNKNOWN[statement]
    assert row["line"] == 1


def test_unknowns_do_not_score(site, project):
    unknown = _analyze(project, "from lazypkg import anything\n")
    assert _unknowns(unknown)
    assert unknown.deficit_breakdown["pattern_hits"] == pytest.approx(0.0)


def test_type_checking_only_absence_is_unknown(site, project):
    source = (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from realpkg import invented\n"
    )
    analysis = _analyze(project, source)
    assert "phantom_member" not in _phantom_ids(analysis)
    assert [r["reason"] for r in _unknowns(analysis)] == ["type_checking_only"]


def test_fallback_import_in_an_except_branch_is_skipped(site, project):
    """Version-compatibility fallback: the except branch imports the old location."""
    source = (
        "try:\n    from realpkg import make\n"
        "except Exception:\n    from realpkg.old_location import make\n"
    )
    analysis = _analyze(project, source)
    assert "phantom_member" not in _phantom_ids(analysis)
    assert _unknowns(analysis) == []


def test_unguarded_absence_outside_try_is_still_a_finding(site, project):
    """Acceptance for the two skips above: the same import unguarded is a finding."""
    analysis = _analyze(project, "from realpkg.old_location import make\n")
    assert _phantom_ids(analysis) == ["phantom_member"]


def test_import_error_guard_is_neither_finding_nor_unknown(site, project):
    source = "try:\n    from realpkg import invented\nexcept ImportError:\n    invented = None\n"
    analysis = _analyze(project, source)
    assert "phantom_member" not in _phantom_ids(analysis)
    assert _unknowns(analysis) == []


# ---------------------------------------------------------------------------
# Boundaries with existing behaviour
# ---------------------------------------------------------------------------


def test_nonexistent_package_stays_phantom_import_only(site, project):
    analysis = _analyze(project, "from no_such_pkg_xyz import thing\n")
    assert _phantom_ids(analysis) == ["phantom_import"]
    assert _unknowns(analysis) == []


def test_internal_and_relative_imports_are_not_checked(site, project):
    _write(project, "mypkg/__init__.py", "")
    _write(project, "mypkg/a.py", "from . import nothing_here\nfrom mypkg import also_nothing\n")
    analysis = SlopDetector(read_only=True).analyze_file(str(project / "mypkg" / "a.py"))
    assert "phantom_member" not in _phantom_ids(analysis)
    assert _unknowns(analysis) == []


def test_project_package_on_sys_path_is_still_not_checked(site, project, monkeypatch):
    """An editable install or a project root on sys.path must not turn internal names
    into phantom_member: internal imports belong to phantom_import and the import graph."""
    _write(project, "mypkg/__init__.py", "")
    _write(project, "mypkg/a.py", "from mypkg import also_nothing\n")
    monkeypatch.syspath_prepend(str(project))
    importlib.invalidate_caches()
    analysis = SlopDetector(read_only=True).analyze_file(str(project / "mypkg" / "a.py"))
    assert "phantom_member" not in _phantom_ids(analysis)
    assert _unknowns(analysis) == []


def test_flat_project_sibling_module_is_not_checked(site, tmp_path, monkeypatch):
    """No pyproject: a sibling .py is project code even when its directory is on sys.path."""
    flat = tmp_path / "flat"
    _write(flat, "helper.py", "def present():\n    return 1\n")
    path = _write(flat, "user.py", "from helper import nope\n")
    monkeypatch.syspath_prepend(str(flat))
    importlib.invalidate_caches()
    analysis = SlopDetector(read_only=True).analyze_file(str(path))
    assert "phantom_member" not in _phantom_ids(analysis)
    assert _unknowns(analysis) == []


def test_allowlisted_package_is_not_checked(site, project):
    path = _write(project, "user.py", "from realpkg import invented\n")
    config = _write(project, "c.yaml", "phantom_import_allowlist:\n  - realpkg\n")
    analysis = SlopDetector(config_path=str(config), read_only=True).analyze_file(str(path))
    assert "phantom_member" not in _phantom_ids(analysis)


def test_lookup_follows_sys_path_changes(tmp_path, project, monkeypatch):
    """Same package name, different installation: a long-running process must not reuse
    the first lookup after sys.path changes."""
    first, second = tmp_path / "first", tmp_path / "second"
    _write(first, "swappkg/__init__.py", "def old():\n    return 1\n")
    _write(second, "swappkg/__init__.py", "def new():\n    return 1\n")
    monkeypatch.syspath_prepend(str(first))
    importlib.invalidate_caches()
    assert _outcome(project, "from swappkg import new") == "finding"
    monkeypatch.syspath_prepend(str(second))
    importlib.invalidate_caches()
    assert _outcome(project, "from swappkg import new") == "clean"


def test_target_package_is_never_imported(site, project):
    for statement in PRESENT + ABSENT + sorted(UNKNOWN):
        _analyze(project, statement + "\n")
    assert not site["marker"].exists(), "realpkg/__init__.py was executed"
    leaked = [
        m
        for m in ("realpkg", "lazypkg", "starpkg", "dynpkg", "sysmodpkg", "modonly", "nspkg")
        if m in sys.modules
    ]
    assert leaked == [], leaked


def test_disable_turns_off_both_outputs(site, project, monkeypatch):
    path = _write(project, "user.py", "from realpkg import invented\nfrom lazypkg import x\n")
    detector = SlopDetector(read_only=True)
    detector.pattern_registry.disable("phantom_member")
    analysis = detector.analyze_file(str(path))
    assert "phantom_member" not in _phantom_ids(analysis)
    assert _unknowns(analysis) == []


def test_cache_version_moves_with_the_new_output():
    assert CACHE_ENGINE_VERSION not in {"analysis-cache-v11", "analysis-cache-v12"}
