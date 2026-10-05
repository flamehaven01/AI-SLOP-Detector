"""One root decides what is project code, for a whole project scan.

A service directory with its own requirements.txt (repo/backend/requirements.txt)
is the nearest project marker for its files, but the code imports from the
repository root (`from src.rex.engine import X`, `import backend.app.services.md`).
Scanning the repository, those imports are project code; they used to be
reported as phantom_import (CRITICAL) because the resolver picked the nearest
marker while the scan root was known only to the path facts.

Rule: the nearest marker by default (a single file, or a scan whose root is not
itself a project root, or a scan below the project root). During a scan whose
root is a project root, a marker nested inside it does not split the project.
The scan root is the ceiling: nothing above it is searched.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import List

import pytest

from slop_detector.analysis_cache import FileAnalysisCache
from slop_detector.core import SlopDetector


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


def _result_for(project, name):
    return next(r for r in project.file_results if Path(r.file_path).name == name)


@pytest.fixture
def service_repo(tmp_path):
    """RExSyn-shaped: repo pyproject + src package + backend with its own requirements."""
    repo = tmp_path / "repo"
    _write(repo, "pyproject.toml", '[project]\nname = "repo"\nversion = "0"\ndependencies = []\n')
    _write(repo, "src/__init__.py")
    _write(repo, "src/rex/__init__.py")
    _write(repo, "src/rex/engine.py", "class Engine:\n    pass\n")
    _write(repo, "backend/__init__.py")
    _write(repo, "backend/requirements.txt", "fastapi\n")
    _write(repo, "backend/app/__init__.py")
    _write(repo, "backend/app/services/__init__.py")
    _write(repo, "backend/app/services/md.py", "def refine():\n    return 1\n")
    _write(
        repo,
        "backend/app/api.py",
        "from src.rex.engine import Engine\nimport backend.app.services.md\n\n\n"
        "def handler():\n    return Engine, backend.app.services.md.refine()\n",
    )
    importlib.invalidate_caches()
    return repo


def test_project_scan_resolves_imports_from_the_scan_root(service_repo):
    project = SlopDetector(read_only=True).analyze_project(str(service_repo))
    assert _ids(_result_for(project, "api.py")) == []


def test_a_real_subproject_keeps_its_own_declarations_and_modules(tmp_path):
    """The other kind of nested marker: examples/x with its own pyproject that
    declares its dependencies and imports its own package. Using the scan root
    alone turned the declared dependency into a phantom (seen on LMCache,
    unsloth, OpenMythos, AI-Scientist): both roots count."""
    repo = tmp_path / "mono"
    _write(repo, "pyproject.toml", '[project]\nname = "mono"\nversion = "0"\ndependencies = []\n')
    _write(repo, "core/__init__.py")
    sub = "examples/plugin"
    _write(
        repo,
        f"{sub}/pyproject.toml",
        '[project]\nname = "plugin"\nversion = "0"\ndependencies = ["notinstalledpkg"]\n',
    )
    _write(repo, f"{sub}/plugin_pkg/__init__.py")
    _write(repo, f"{sub}/plugin_pkg/helpers.py", "def h():\n    return 1\n")
    _write(
        repo,
        f"{sub}/plugin_pkg/main.py",
        "import notinstalledpkg\nfrom plugin_pkg.helpers import h\nimport core\n",
    )
    importlib.invalidate_caches()
    project = SlopDetector(read_only=True).analyze_project(str(repo))
    assert _ids(_result_for(project, "main.py")) == ["runtime_unavailable_dependency"]


def test_a_dependency_declared_at_the_scan_root_counts_in_a_service_dir(service_repo):
    """Declarations merge across both roots: the repository pyproject declares
    a package that backend/ code imports (not installed here)."""
    _write(
        service_repo,
        "pyproject.toml",
        '[project]\nname = "repo"\nversion = "0"\ndependencies = ["rootonlydep"]\n',
    )
    _write(service_repo, "backend/app/uses_dep.py", "import rootonlydep\n")
    project = SlopDetector(read_only=True).analyze_project(str(service_repo))
    assert _ids(_result_for(project, "uses_dep.py")) == ["runtime_unavailable_dependency"]


def test_scan_root_packages_are_project_packages_in_a_service_dir(service_repo):
    """As for the nearest root's own packages, an import under a project package
    of the scan root is not a phantom check, even for a module not written yet."""
    _write(service_repo, "backend/app/future.py", "from src.rex.notyet import Thing\n")
    project = SlopDetector(read_only=True).analyze_project(str(service_repo))
    assert _ids(_result_for(project, "future.py")) == []


def test_a_conditional_package_name_of_the_scan_root_does_not_mute_a_phantom(tmp_path):
    """Seen on unsloth: a plugin with its own pyproject imports `utils.paths`,
    which exists nowhere. The scan root has a `utils` package only under a
    conditional (E4) root (repo/inner/utils), importable only with inner/ on
    sys.path. That name is not evidence for a file elsewhere: still a phantom."""
    repo = tmp_path / "big"
    _write(repo, "pyproject.toml", '[project]\nname = "big"\nversion = "0"\ndependencies = []\n')
    _write(repo, "inner/__init__.py")
    _write(repo, "inner/utils/__init__.py")
    _write(repo, "plugins/seed/pyproject.toml", '[project]\nname = "seed"\nversion = "0"\n')
    _write(repo, "plugins/seed/chunking.py", "from utils.paths import ensure_dir\n")
    importlib.invalidate_caches()
    project = SlopDetector(read_only=True).analyze_project(str(repo))
    assert _ids(_result_for(project, "chunking.py")) == ["phantom_import"]


def test_a_root_that_does_not_contain_the_file_adds_nothing(service_repo, tmp_path):
    """analyze_file(root=...) with a root elsewhere: that root's modules are not
    this file's project evidence."""
    other = tmp_path / "other"
    _write(other, "pyproject.toml", '[project]\nname = "other"\nversion = "0"\n')
    _write(other, "othermod.py", "X = 1\n")
    _write(tmp_path / "lone", "requirements.txt", "")
    path = _write(tmp_path / "lone", "user.py", "import othermod\n")
    analysis = SlopDetector(read_only=True).analyze_file(str(path), root=str(other))
    assert _ids(analysis) == ["phantom_import"]


def test_a_single_file_keeps_the_nearest_marker(service_repo):
    """Boundary: without a scan root, backend/requirements.txt is the project."""
    analysis = SlopDetector(read_only=True).analyze_file(str(service_repo / "backend/app/api.py"))
    assert _ids(analysis) == ["phantom_import", "phantom_import"]


def test_scanning_below_the_project_root_keeps_its_declarations(tmp_path):
    """Preservation: scanning src/ must not lose the pyproject one level up."""
    repo = tmp_path / "proj"
    _write(
        repo,
        "pyproject.toml",
        '[project]\nname = "p"\nversion = "0"\ndependencies = ["notinstalledpkg"]\n',
    )
    _write(repo, "src/pkg/__init__.py")
    _write(repo, "src/pkg/a.py", "import notinstalledpkg\n")
    project = SlopDetector(read_only=True).analyze_project(str(repo / "src"))
    assert _ids(_result_for(project, "a.py")) == ["runtime_unavailable_dependency"]


def test_a_folder_of_projects_does_not_merge_them(tmp_path):
    """Preservation: a scan root without a marker is not a project; siblings stay foreign."""
    folder = tmp_path / "workspace"
    _write(folder, "alpha/pyproject.toml", '[project]\nname = "alpha"\nversion = "0"\n')
    # Resolvable only if the folder itself were the root (beta/ as a namespace there).
    _write(folder, "alpha/alpha_mod.py", "import beta.betapkg\n")
    _write(folder, "beta/pyproject.toml", '[project]\nname = "beta"\nversion = "0"\n')
    _write(folder, "beta/betapkg/__init__.py")
    project = SlopDetector(read_only=True).analyze_project(str(folder))
    assert _ids(_result_for(project, "alpha_mod.py")) == ["phantom_import"]


def test_cache_key_follows_the_scan_root_context(service_repo, tmp_path):
    """The analysis cache is keyed by the same root the resolver uses: a module
    added under the scan root (outside backend/) must not be served stale.
    (`src.*` would not do: imports of a project package are never phantom checks.)"""
    _write(service_repo, "backend/app/late.py", "import latemod\n")
    db = tmp_path / "cache.db"

    def scan():
        detector = SlopDetector()
        detector._analysis_cache = FileAnalysisCache(db)
        importlib.invalidate_caches()
        return detector.analyze_project(str(service_repo))

    assert _ids(_result_for(scan(), "late.py")) == ["phantom_import"]
    _write(service_repo, "latemod.py", "X = 1\n")
    assert _ids(_result_for(scan(), "late.py")) == []
