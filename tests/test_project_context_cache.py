"""A file's result follows its project's current resolution context, cached or not.

phantom_import and phantom_member read more than the file: the dependency
declarations (pyproject.toml, requirements.txt, requirements/*.txt) and the
project's module topology (which directories and .py files exist). Changing
those used to leave stale results in two places:

- the persistent analysis cache, keyed by the file's own content only;
- process-local resolver caches, keyed by the project root only, so a
  long-running process (watch --follow, the MCP server) never saw the change.

Every mutation test runs in one process, with the analysis cache off and on,
and expects the same result a fresh analysis gives.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import List

import pytest

from slop_detector.analysis_cache import FileAnalysisCache
from slop_detector.core import SlopDetector

CACHE_MODES = pytest.mark.parametrize("cached", [False, True], ids=["cache-off", "cache-on"])


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _ids(analysis) -> List[str]:
    return sorted(
        i.pattern_id
        for i in analysis.pattern_issues
        if i.pattern_id.startswith("phantom") or i.pattern_id.endswith("dependency")
    )


def _analyzer(tmp_path: Path, cached: bool):
    db = tmp_path / "analysis_cache.db"

    def analyze(path: Path):
        detector = SlopDetector()
        detector._analysis_cache = FileAnalysisCache(db) if cached else None
        importlib.invalidate_caches()
        return detector.analyze_file(str(path))

    return analyze


def _pyproject(root: Path, deps: str = "") -> None:
    _write(
        root, "pyproject.toml", f'[project]\nname = "p"\nversion = "0"\ndependencies = [{deps}]\n'
    )


# ---------------------------------------------------------------------------
# 1. Dependency declarations
# ---------------------------------------------------------------------------


@CACHE_MODES
def test_declaring_a_dependency_in_pyproject(tmp_path, cached):
    root = tmp_path / "proj"
    _pyproject(root)
    path = _write(root, "user.py", "import notinstalledpkg\n")
    analyze = _analyzer(tmp_path, cached)
    assert _ids(analyze(path)) == ["phantom_import"]
    _pyproject(root, '"notinstalledpkg"')
    assert _ids(analyze(path)) == ["runtime_unavailable_dependency"]


@CACHE_MODES
@pytest.mark.parametrize("rel", ["requirements.txt", "requirements/base.txt"])
def test_declaring_a_dependency_in_requirements(tmp_path, cached, rel):
    """The file exists from the start; only its content changes (one axis)."""
    root = tmp_path / "proj"
    _write(root, "requirements.txt", "")
    _write(root, rel, "")
    path = _write(root, "user.py", "import notinstalledpkg\n")
    analyze = _analyzer(tmp_path, cached)
    assert _ids(analyze(path)) == ["phantom_import"]
    _write(root, rel, "notinstalledpkg>=1\n")
    assert _ids(analyze(path)) == ["runtime_unavailable_dependency"]


# ---------------------------------------------------------------------------
# 2. Sibling modules
# ---------------------------------------------------------------------------


@CACHE_MODES
@pytest.mark.parametrize("with_root", [True, False], ids=["project-root", "no-project-root"])
def test_adding_a_sibling_module(tmp_path, cached, with_root):
    root = tmp_path / "flat"
    if with_root:
        _pyproject(root)
    path = _write(root, "user.py", "import helperzz\n")
    analyze = _analyzer(tmp_path, cached)
    assert _ids(analyze(path)) == ["phantom_import"]
    _write(root, "helperzz.py", "def h():\n    return 1\n")
    assert _ids(analyze(path)) == []


# ---------------------------------------------------------------------------
# 3. Package and module topology
# ---------------------------------------------------------------------------


@CACHE_MODES
def test_adding_init_turns_a_directory_into_a_project_package(tmp_path, cached):
    """src layout: the project root is a conditional root, where only regular
    packages are project code. `extra/` becomes one when __init__.py appears."""
    root = tmp_path / "srcproj"
    _pyproject(root)
    _write(root, "src/app/__init__.py")
    _write(root, "extra/mod.py", "X = 1\n")
    path = _write(root, "src/app/a.py", "import extra.mod\n")
    analyze = _analyzer(tmp_path, cached)
    assert _ids(analyze(path)) == ["phantom_import"]
    _write(root, "extra/__init__.py")
    assert _ids(analyze(path)) == []


@CACHE_MODES
def test_removing_a_module_brings_the_phantom_back(tmp_path, cached):
    root = tmp_path / "proj"
    _pyproject(root)
    gone = _write(root, "nsdir/x.py", "X = 1\n")
    path = _write(root, "user.py", "import nsdir.x\n")
    analyze = _analyzer(tmp_path, cached)
    assert _ids(analyze(path)) == []
    gone.unlink()
    gone.parent.rmdir()
    assert _ids(analyze(path)) == ["phantom_import"]


@CACHE_MODES
def test_creating_a_directory_is_a_topology_change(tmp_path, cached):
    """A directory alone can resolve as a namespace package, so directories are
    part of the context, not only .py files."""
    root = tmp_path / "proj"
    _pyproject(root)
    path = _write(root, "user.py", "import emptynsdir\n")
    analyze = _analyzer(tmp_path, cached)
    assert _ids(analyze(path)) == ["phantom_import"]
    (root / "emptynsdir").mkdir()
    assert _ids(analyze(path)) == []


# ---------------------------------------------------------------------------
# Preservation
# ---------------------------------------------------------------------------


def test_editing_another_file_keeps_the_cache(tmp_path, monkeypatch):
    """Only topology and declarations are context: editing a module's content
    must not invalidate the cached results of other files."""
    root = tmp_path / "proj"
    _pyproject(root)
    helper = _write(root, "helper.py", "def h():\n    return 1\n")
    path = _write(root, "user.py", "import helper\nimport json\n")
    db = tmp_path / "analysis_cache.db"

    def analyze():
        detector = SlopDetector()
        detector._analysis_cache = FileAnalysisCache(db)
        built: List[str] = []
        original = detector._build_file_analysis

        def spy(file_path, *args, **kwargs):
            built.append(Path(file_path).name)
            return original(file_path, *args, **kwargs)

        monkeypatch.setattr(detector, "_build_file_analysis", spy)
        detector.analyze_file(str(path))
        return built

    assert analyze() == ["user.py"]
    helper.write_text("def h():\n    return 2\n", encoding="utf-8")
    assert analyze() == []


def test_context_snapshot_is_built_once_per_project_scan(tmp_path, monkeypatch):
    import importlib.util

    assert importlib.util.find_spec("slop_detector.project_context"), "no context snapshot"
    from slop_detector import project_context

    root = tmp_path / "proj"
    _pyproject(root)
    for name in ("a", "b", "c", "d"):
        _write(root, f"pkg/{name}.py", "import json\nimport notinstalledpkg\n")
    _write(root, "pkg/__init__.py")
    calls: List[Path] = []
    original = project_context.build_project_context_snapshot

    def counting(project_root):
        calls.append(project_root)
        return original(project_root)

    monkeypatch.setattr(project_context, "build_project_context_snapshot", counting)
    SlopDetector(read_only=True).analyze_project(str(root))
    assert len(calls) == 1, calls
