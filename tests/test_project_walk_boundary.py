"""S1: the project walks and module lookups that import resolution shares stay inside the
authorized scan area (3.18).

A directory link (symlink, or a junction on Windows) is followed only when its real path is
inside the boundary: the explicit scan root, or for a single-file analysis the file's project
root. A link out of it is not opened, listed or tested, and what lies behind it is not a project
module; an import only such a link could supply is unverified (`out_of_boundary`), never a
finding, since not looking is not evidence that it is missing.

Observation: a realpath-aware audit hook records every `open` / `os.scandir` / `os.listdir`
whose real path is outside. `stat` / `lstat` are not audit events, so zero recorded reads is
evidence about listings and file contents only, not full isolation; the static boundary checks
are tested on their own.
"""

from __future__ import annotations

import importlib
import os
import sys
import threading
from pathlib import Path
from typing import Dict, List

import pytest

from slop_detector.core import SlopDetector
from slop_detector.core_project import walk_project
from slop_detector.project_context import build_project_context_snapshot
from slop_detector.project_resolution import (
    ProjectModuleIndex,
    discover_project_packages,
    probe_module,
)

IMPORT_IDS = {
    "phantom_import",
    "runtime_unavailable_dependency",
    "undeclared_optional_dependency",
    "declared_outside_primary_metadata",
    "undeclared_dependency",
    "provider_conflict",
}

_WATCH: Dict[str, object] = {"root": None, "seen": []}
_BUSY = threading.local()


def _hook(event: str, args: tuple) -> None:
    if getattr(_BUSY, "on", False):
        return
    root = _WATCH["root"]
    if root is None or event not in ("open", "os.scandir", "os.listdir") or not args:
        return
    target = args[0]
    if not isinstance(target, (str, bytes, os.PathLike)):
        return
    _BUSY.on = True
    try:
        real = os.path.normcase(os.path.realpath(os.fsdecode(target)))
        if real == root or real.startswith(str(root) + os.sep):
            _WATCH["seen"].append((event, os.fsdecode(target)))  # type: ignore[union-attr]
    except Exception:  # an audit hook must never break the audited call
        pass
    finally:
        _BUSY.on = False


sys.addaudithook(_hook)


def _watch(root: Path) -> None:
    _WATCH["root"] = os.path.normcase(os.path.realpath(str(root)))
    _WATCH["seen"] = []


@pytest.fixture(autouse=True)
def _unwatch():
    yield
    _WATCH["root"] = None


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _link_dir(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi  # type: ignore[import-not-found]

        _winapi.CreateJunction(str(target), str(link))  # no privilege needed on Windows
    except (ImportError, OSError, AttributeError):
        pytest.skip("cannot create a directory link here")


def _unlink_dir(link: Path) -> None:
    try:
        os.unlink(str(link))
    except OSError:
        os.rmdir(str(link))  # a junction is removed as an empty directory, target untouched


@pytest.fixture
def layout(tmp_path):
    proj = tmp_path / "proj"
    outside = tmp_path / "outside"
    proj.mkdir()
    outside.mkdir()
    _write(proj, "pyproject.toml", '[project]\nname = "proj"\nversion = "0"\ndependencies = []\n')
    return proj, outside


def _analyze(path: Path):
    importlib.invalidate_caches()
    result = SlopDetector(read_only=True).analyze_file(str(path))
    issues = [i.to_dict() for i in result.pattern_issues if i.pattern_id in IMPORT_IDS]
    return issues, result.to_dict()["unverified_imports"]


def _rows(unverified: List[dict]) -> List[tuple]:
    return [(r["requested_module"], r["reason"], r.get("blocked_paths")) for r in unverified]


def test_s1a_link_out_of_the_project_injects_nothing(layout):
    """S1a. A junction (or symlink) in the project to a package outside it: the module index does
    not resolve the package, the fingerprint does not change when the outside content does, no
    outside listing or file is opened, and the import is unverified (`out_of_boundary`), not a
    finding. Today (r8): the index resolves it through the link (no finding, no row)."""
    proj, outside = layout
    _write(outside, "extpkg/__init__.py", "x = 1\n")
    _link_dir(proj / "extpkg", outside / "extpkg")
    main = _write(proj, "main.py", "import extpkg\n")
    _watch(outside)
    index = ProjectModuleIndex(proj)
    assert not index.resolves("extpkg")
    assert "extpkg" not in discover_project_packages(proj)
    before = build_project_context_snapshot(proj).fingerprint
    issues, unverified = _analyze(main)
    assert issues == [], issues
    assert _rows(unverified) == [("extpkg", "out_of_boundary", ["extpkg"])], unverified
    _write(outside, "extpkg/added.py", "")
    _watch(outside)
    assert build_project_context_snapshot(proj).fingerprint == before
    assert _WATCH["seen"] == [], _WATCH["seen"]


def test_s1b_link_inside_the_project_still_resolves(layout):
    """S1b. A link whose real path stays inside the project is followed: the package behind it
    resolves as before. Holds today; kept as a control."""
    proj, _ = layout
    _write(proj, "libs/realpkg/__init__.py", "x = 1\n")
    _link_dir(proj / "alias", proj / "libs" / "realpkg")
    main = _write(proj, "main.py", "import alias\n")
    assert ProjectModuleIndex(proj).resolves("alias")
    issues, unverified = _analyze(main)
    assert issues == [] and unverified == [], (issues, unverified)


def test_s1c_nested_link_in_a_namespace_package_is_not_followed(layout):
    """S1c / R23j. A namespace package the file puts on sys.path (inside the project) whose only
    .py is behind a deeper junction to outside: nothing outside is listed, and the import is
    unverified (`out_of_boundary`). Today (r8): the walk goes through the link and the package
    counts as provided (3 outside listings)."""
    proj, outside = layout
    _write(outside, "deep/mod.py", "")
    (proj / "app" / "vendor" / "zz_ns_s1c").mkdir(parents=True)
    _link_dir(proj / "app" / "vendor" / "zz_ns_s1c" / "sub", outside / "deep")
    main = _write(
        proj,
        "app/main.py",
        "import sys\nfrom pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).parent / "vendor"))\n'
        "import zz_ns_s1c\n",
    )
    _watch(outside)
    issues, unverified = _analyze(main)
    assert issues == [], issues
    assert [(m, r) for m, r, _ in _rows(unverified)] == [("zz_ns_s1c", "out_of_boundary")]
    assert _WATCH["seen"] == [], _WATCH["seen"]


def test_s1d_link_cycle_is_walked_once(layout):
    """S1d. A link back to an enclosing directory inside the project is not walked again: the
    walk ends and no path repeats under the link. Today (r8): the walk descends the cycle."""
    proj, _ = layout
    _write(proj, "pkg/__init__.py", "")
    _write(proj, "pkg/mod.py", "")
    _link_dir(proj / "pkg" / "loop", proj / "pkg")
    paths = build_project_context_snapshot(proj).module_paths
    assert paths.get("mod") == ("pkg/mod.py",), paths.get("mod")
    assert "loop" not in paths, paths.get("loop")


def test_s1e_retargeted_link_changes_the_fingerprint(layout):
    """S1e. Pointing a link inside the project at another directory with the same file names
    changes the fingerprint, so a cached analysis is not reused. Today (r8): equal
    fingerprints (only the names below the link are hashed)."""
    proj, _ = layout
    _write(proj, "libs/a/x.py", "")
    _write(proj, "libs/b/x.py", "")
    _link_dir(proj / "alias", proj / "libs" / "a")
    first = build_project_context_snapshot(proj).fingerprint
    _unlink_dir(proj / "alias")
    _link_dir(proj / "alias", proj / "libs" / "b")
    assert build_project_context_snapshot(proj).fingerprint != first


def test_s1f_direct_lookups_refuse_a_link_out_of_the_project(layout):
    """S1f. The direct lookups (probe_module, a package's __init__.py, the top-level name test)
    do not accept what a link out of the project leads to. Today (r8): probe_module finds it."""
    proj, outside = layout
    _write(outside, "extpkg/__init__.py", "")
    _link_dir(proj / "extpkg", outside / "extpkg")
    _watch(outside)
    assert probe_module(proj, ["extpkg"]) is None
    index = ProjectModuleIndex(proj)
    assert index.locate("extpkg") == ()
    assert not index.is_internal_top_level("extpkg")
    assert _WATCH["seen"] == [], _WATCH["seen"]


def test_s1f_file_link_out_of_the_project_is_not_a_module(layout):
    """S1f, file: `extmod.py` in the project is a symlink to a file outside: not a project
    module, unverified (`out_of_boundary`). Needs file-symlink rights; skipped without them."""
    proj, outside = layout
    target = _write(outside, "extmod.py", "")
    try:
        os.symlink(str(target), str(proj / "extmod.py"))
    except (OSError, NotImplementedError):
        pytest.skip("cannot create a file symlink here")
    main = _write(proj, "main.py", "import extmod\n")
    assert not ProjectModuleIndex(proj).is_internal_top_level("extmod")
    issues, unverified = _analyze(main)
    assert issues == [], issues
    assert [(m, r) for m, r, _ in _rows(unverified)] == [("extmod", "out_of_boundary")]


def test_s1g_sibling_link_out_of_the_project_is_not_a_module(layout):
    """S1g. A script's sibling directory (its directory is on sys.path when it runs) that is a
    link out of the project: not a sibling module, unverified (`out_of_boundary`). Today (r8):
    the sibling counts as the project's (no finding, no row)."""
    proj, outside = layout
    _write(outside, "extsib/__init__.py", "")
    _link_dir(proj / "scripts" / "extsib", outside / "extsib")
    run = _write(proj, "scripts/run.py", "import extsib\n")
    _watch(outside)
    issues, unverified = _analyze(run)
    assert issues == [], issues
    assert [(m, r) for m, r, _ in _rows(unverified)] == [("extsib", "out_of_boundary")]
    assert _WATCH["seen"] == [], _WATCH["seen"]


def test_s1h_declarations_behind_a_link_out_are_unread_not_absent(layout):
    """S1h. The project's requirements/ directory is a link out of the project: it is not read,
    and an import it might declare is unverified (`out_of_boundary`, naming the link), not a
    finding. Today (r8): the file outside is read as a declaration."""
    proj, outside = layout
    _write(outside, "reqs/base.txt", "zz-decl-s1h\n")
    _link_dir(proj / "requirements", outside / "reqs")
    main = _write(proj, "main.py", "import zz_decl_s1h\n")
    _watch(outside)
    issues, unverified = _analyze(main)
    assert issues == [], issues
    assert _rows(unverified) == [("zz_decl_s1h", "out_of_boundary", ["requirements"])], unverified
    assert _WATCH["seen"] == [], _WATCH["seen"]


def test_s1i_environment_behind_a_link_out_is_unread_not_absent(layout):
    """S1i. The project's `.venv` is a junction (or symlink) to an environment outside: it is not
    read (its pyvenv.cfg and site-packages stay unopened), and an import that environment might
    provide is unverified (`out_of_boundary`), not a finding. Today (r8): the environment
    outside is read as the project's and decides presence."""
    proj, outside = layout
    env = outside / "venv"
    _write(env, "pyvenv.cfg", "home = x\nversion = 3.12.0\n")
    _write(env, "Lib/site-packages/zz_venv_s1i/__init__.py", "")
    _write(env, "lib/python3.12/site-packages/zz_venv_s1i/__init__.py", "")
    _link_dir(proj / ".venv", env)
    main = _write(proj, "main.py", "import zz_venv_s1i\n")
    _watch(outside)
    issues, unverified = _analyze(main)
    assert issues == [], issues
    assert _rows(unverified) == [("zz_venv_s1i", "out_of_boundary", [".venv"])], unverified
    assert _WATCH["seen"] == [], _WATCH["seen"]


def test_s1j_two_aliases_keep_every_logical_path(layout):
    """S1j. Two links inside the project to one real package: the original path and both alias
    paths keep their modules (nested ones too), every import path resolves, and the
    fingerprint is the same on a second build. Today (r9): the first alias in name order hides
    the other alias and the original directory (one shared visited set)."""
    proj, _ = layout
    _write(proj, "libs/realpkg/__init__.py", "")
    _write(proj, "libs/realpkg/sub/__init__.py", "")
    _write(proj, "libs/realpkg/sub/mod.py", "")
    _link_dir(proj / "alias_a", proj / "libs" / "realpkg")
    _link_dir(proj / "alias_b", proj / "libs" / "realpkg")
    snapshot = build_project_context_snapshot(proj)
    assert snapshot.module_paths.get("mod") == (
        "alias_a/sub/mod.py",
        "alias_b/sub/mod.py",
        "libs/realpkg/sub/mod.py",
    ), snapshot.module_paths.get("mod")
    assert build_project_context_snapshot(proj).fingerprint == snapshot.fingerprint
    index = ProjectModuleIndex(proj)
    for dotted in ("alias_a.sub.mod", "alias_b.sub.mod", "libs.realpkg.sub.mod"):
        assert index.resolves(dotted), dotted
    main = _write(proj, "main.py", "import alias_a.sub.mod\nimport alias_b.sub.mod\n")
    issues, unverified = _analyze(main)
    assert issues == [] and unverified == [], (issues, unverified)


def test_s2a_file_collector_does_not_enter_a_link_out(layout):
    """S2a. The scan's file collector (coverage, and the analyzed files when no compiled walker
    is available) neither lists nor collects what a link out of the scan root leads to. Today
    (r9): it walks into the junction and collects the files outside."""
    proj, outside = layout
    _write(outside, "ext/__init__.py", "x = 1\n")
    _write(outside, "ext/mod.py", "")
    _link_dir(proj / "ext", outside / "ext")
    _write(proj, "main.py", "")
    _watch(outside)
    relatives = [item.relative for item in walk_project(proj)]
    assert "main.py" in relatives and not any(r.startswith("ext/") for r in relatives), relatives
    assert _WATCH["seen"] == [], _WATCH["seen"]


def test_s2b_file_collector_keeps_its_inside_link_policy(layout):
    """S2b. A link inside the scan root is treated as before: a directory symlink is not
    followed (the collector's rule), a Windows junction is (as before S2). Holds today; kept as a
    control so the boundary fix changes nothing inside the project."""
    proj, _ = layout
    _write(proj, "libs/a/x.py", "")
    _link_dir(proj / "alias", proj / "libs" / "a")
    relatives = {item.relative for item in walk_project(proj)}
    expected = {"pyproject.toml", "libs/a/x.py"}
    if not os.path.islink(str(proj / "alias")):  # a junction: followed, as it was
        expected.add("alias/x.py")
    assert relatives == expected, relatives


def test_s1k_alias_guard_never_cuts_a_directory_own_path(layout):
    """S1k. Nine links to one package, all before it in name order: the guard stops the ninth
    alias, records it (snapshot.truncated_paths), and the package's own path is still walked.
    Today (r10 draft): every walk of the real directory counted, so its own path was cut and the
    cut went unrecorded."""
    proj, _ = layout
    _write(proj, "libs/pkg/__init__.py", "")
    _write(proj, "libs/pkg/mod.py", "")
    for i in range(9):
        _link_dir(proj / f"a{i}", proj / "libs" / "pkg")
    snapshot = build_project_context_snapshot(proj)
    paths = snapshot.module_paths.get("mod", ())
    assert "libs/pkg/mod.py" in paths, paths
    assert len(paths) == 9, paths  # the package's own path and eight aliases
    assert snapshot.truncated_paths == ("a8",), snapshot.truncated_paths


def test_s1l_truncated_alias_stays_a_local_candidate(layout):
    """S1l. An alias the guard did not walk is still a name the project has: an import of it after
    a sys.path change not known statically stays unverified (`sys_path_modified`, the alias in
    `local_candidates`), not a finding. Today (e9295bf): the truncated alias is missing from the
    project's module names, so the import is reported as a phantom (flagged)."""
    proj, _ = layout
    _write(proj, "libs/pkg/__init__.py", "")
    for i in range(9):
        _link_dir(proj / "tools" / f"a{i}", proj / "libs" / "pkg")
    assert build_project_context_snapshot(proj).truncated_paths == ("tools/a8",)
    run = _write(proj, "scripts/run.py", 'import sys\nsys.path.append("../tools")\nimport a8\n')
    issues, unverified = _analyze(run)
    assert issues == [], issues
    rows = [(r["requested_module"], r["reason"], r.get("local_candidates")) for r in unverified]
    assert rows == [("a8", "sys_path_modified", ["tools/a8"])], rows


def test_r24g_declarations_behind_a_link_out_are_not_context(layout):
    """R24g (P1). Another subtree's requirements behind a junction out of the project are not
    read and not listed as related declarations."""
    proj, outside = layout
    _write(outside, "reqs/requirements.txt", "zz-rel-g\n")
    _link_dir(proj / "tools" / "ext", outside / "reqs")
    main = _write(proj, "main.py", "import zz_rel_g\n")
    _watch(outside)
    issues, _ = _analyze(main)
    assert [i["pattern_id"] for i in issues] == ["phantom_import"], issues
    assert "related_declarations" not in (issues[0].get("evidence") or {}), issues[0]
    assert _WATCH["seen"] == [], _WATCH["seen"]


def test_s1l_truncated_alias_on_a_module_root_resolves_by_direct_lookup(layout):
    """S1l, direct lookup: the alias guard limits walks, not lookups. A truncated alias at the
    project root is found by the module index itself (`_find_spec`), so the import is the
    project's own: no finding and no unverified row, and the walk's truncation record is the
    only trace. Kept apart from the walk-based local candidates of the test above."""
    proj, _ = layout
    _write(proj, "libs/pkg/__init__.py", "")
    for i in range(9):
        _link_dir(proj / f"a{i}", proj / "libs" / "pkg")
    assert build_project_context_snapshot(proj).truncated_paths == ("a8",)
    assert ProjectModuleIndex(proj).resolves("a8")
    main = _write(proj, "main.py", "import a8\n")
    issues, unverified = _analyze(main)
    assert issues == [] and unverified == [], (issues, unverified)
