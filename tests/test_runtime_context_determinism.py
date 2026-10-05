"""Same target, same environment -> same result, wherever and however the analyzer runs.

D2 (runtime context): whether an import is installed is evidence about the
analyzer's environment. It must not come from the directory the analyzer runs
in ("" or the cwd on sys.path, as `python -m` and the pre-commit hooks put it
there) or from the analyzed project's own roots, which ProjectModuleIndex owns.
The persistent analysis cache must not return a result computed under a
different environment.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
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


def _phantom_ids(analysis) -> List[str]:
    return sorted(
        i.pattern_id for i in analysis.pattern_issues if i.pattern_id.startswith("phantom")
    )


def _issues(analysis):
    return sorted((i.pattern_id, i.line, i.column, i.message) for i in analysis.pattern_issues)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    _write(root, "pyproject.toml", '[project]\nname = "proj"\nversion = "0"\n')
    return root


@pytest.fixture
def cwd_with_package(tmp_path, monkeypatch):
    """The analyzer runs from a directory that happens to hold `cwdonlypkg`."""
    cwd = tmp_path / "analyzer_cwd"
    _write(cwd, "cwdonlypkg/__init__.py", "VALUE = 1\n")
    monkeypatch.chdir(cwd)
    importlib.invalidate_caches()
    return cwd


def _analyze(path: Path):
    return SlopDetector(read_only=True).analyze_file(str(path))


# ---------------------------------------------------------------------------
# D2: the analyzer's cwd is not an installed environment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", ["", "absolute"], ids=["empty-entry", "cwd-path"])
def test_package_only_in_analyzer_cwd_is_phantom(project, cwd_with_package, monkeypatch, entry):
    monkeypatch.syspath_prepend("" if entry == "" else str(cwd_with_package))
    importlib.invalidate_caches()
    path = _write(project, "user.py", "import cwdonlypkg\n")
    assert _phantom_ids(_analyze(path)) == ["phantom_import"]


def test_package_only_in_analyzer_cwd_is_not_a_phantom_member(
    project, cwd_with_package, monkeypatch
):
    """Found through the cwd, `from cwdonlypkg import nothing` became phantom_member
    (the package "exists", the name does not). It is a phantom_import."""
    monkeypatch.syspath_prepend("")
    importlib.invalidate_caches()
    path = _write(project, "user.py", "from cwdonlypkg import nothing\n")
    assert _phantom_ids(_analyze(path)) == ["phantom_import"]


def test_cwd_change_does_not_change_the_result(project, tmp_path, monkeypatch):
    """The reproduced case: a `models/` directory in the analyzer's cwd muted
    `import models.tensoRF` in an unrelated target (renamed here: this repository
    has its own `models/`, and `python -m pytest` puts the repository on sys.path)."""
    path = _write(project, "user.py", "import cwdmodels.tensoRF\nfrom cwdmodels import Net\n")
    with_models = tmp_path / "cwd_a"
    _write(with_models, "cwdmodels/__init__.py", "class Net:\n    pass\n")
    without = tmp_path / "cwd_b"
    without.mkdir()
    monkeypatch.syspath_prepend("")
    results = []
    for cwd in (with_models, without):
        monkeypatch.chdir(cwd)
        importlib.invalidate_caches()
        results.append(_issues(_analyze(path)))
    assert results[0] == results[1]
    assert [r[0] for r in results[0]].count("phantom_import") == 2


def test_explicit_environment_path_still_counts(project, tmp_path, monkeypatch):
    """Control: an environment directory on sys.path that is not the cwd is evidence."""
    env = tmp_path / "env_site"
    _write(env, "envpkg/__init__.py", "VALUE = 1\n")
    monkeypatch.syspath_prepend(str(env))
    importlib.invalidate_caches()
    path = _write(project, "user.py", "import envpkg\nfrom envpkg import VALUE\n")
    assert _phantom_ids(_analyze(path)) == []


def test_target_project_root_on_sys_path_is_not_installed_evidence(tmp_path, monkeypatch):
    """src layout: the project root is not a module root, so a namespace directory
    there is not project code (ProjectModuleIndex decides that). With the project
    root on sys.path, the environment lookup used to find it and mute the phantom."""
    root = tmp_path / "srcproj"
    _write(root, "pyproject.toml", '[project]\nname = "srcproj"\nversion = "0"\n')
    _write(root, "src/pkg/__init__.py", "")
    _write(root, "stray/mod.py", "X = 1\n")
    path = _write(root, "src/pkg/a.py", "import stray.mod\n")
    monkeypatch.syspath_prepend(str(root))
    importlib.invalidate_caches()
    assert _phantom_ids(_analyze(path)) == ["phantom_import"]


def test_target_project_root_is_not_installed_evidence_for_members(tmp_path, monkeypatch):
    """Same layout, `from stray import nothing`: not installed means phantom_import
    only. The member check used to find `stray` through the project root and also
    record the import as unverified, contradicting the phantom_import."""
    root = tmp_path / "srcproj"
    _write(root, "pyproject.toml", '[project]\nname = "srcproj"\nversion = "0"\n')
    _write(root, "src/pkg/__init__.py", "")
    _write(root, "stray/mod.py", "X = 1\n")
    path = _write(root, "src/pkg/a.py", "from stray import nothing\n")
    monkeypatch.syspath_prepend(str(root))
    importlib.invalidate_caches()
    analysis = _analyze(path)
    assert _phantom_ids(analysis) == ["phantom_import"]
    assert analysis.to_dict().get("unverified_imports") == []


# ---------------------------------------------------------------------------
# D2: the analysis cache does not cross environments
# ---------------------------------------------------------------------------


def test_cache_does_not_reuse_a_result_from_another_environment(project, tmp_path, monkeypatch):
    env = tmp_path / "env_site"
    _write(env, "envonlypkg/__init__.py", "VALUE = 1\n")
    path = _write(project, "user.py", "import envonlypkg\n")
    db = tmp_path / "cache.db"

    def analyze():
        detector = SlopDetector()
        detector._analysis_cache = FileAnalysisCache(db)
        return detector.analyze_file(str(path))

    monkeypatch.syspath_prepend(str(env))
    importlib.invalidate_caches()
    assert _phantom_ids(analyze()) == []

    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != str(env)])
    importlib.invalidate_caches()
    assert _phantom_ids(analyze()) == ["phantom_import"]


def test_cache_does_not_survive_an_uninstall_on_the_same_sys_path(project, tmp_path, monkeypatch):
    """Same sys.path, the package removed from its directory, then a new process."""
    import shutil

    from slop_detector import environment_resolution

    env = tmp_path / "env_site"
    _write(env, "goneloadpkg/__init__.py", "VALUE = 1\n")
    path = _write(project, "user.py", "import goneloadpkg\n")
    db = tmp_path / "cache.db"

    def analyze():
        detector = SlopDetector()
        detector._analysis_cache = FileAnalysisCache(db)
        return detector.analyze_file(str(path))

    monkeypatch.syspath_prepend(str(env))
    importlib.invalidate_caches()
    assert _phantom_ids(analyze()) == []

    shutil.rmtree(env / "goneloadpkg")
    monkeypatch.setattr(environment_resolution, "_FINGERPRINTS", {})
    importlib.invalidate_caches()
    assert _phantom_ids(analyze()) == ["phantom_import"]


def test_cwd_does_not_split_the_cache(project, tmp_path, monkeypatch):
    """Results no longer depend on the cwd, so the cache key must not either."""
    spec = importlib.util.find_spec("slop_detector.environment_resolution")
    assert spec is not None, "no environment fingerprint for the cache key"
    from slop_detector.environment_resolution import environment_fingerprint

    monkeypatch.syspath_prepend("")
    prints = []
    for name in ("cwd_a", "cwd_b"):
        cwd = tmp_path / name
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        prints.append(environment_fingerprint())
    assert prints[0] == prints[1]


# ---------------------------------------------------------------------------
# D1: one canonical file order, with or without the Rust discovery helper
# ---------------------------------------------------------------------------

_SOURCES = {
    "zeta.py": "def a(x):\n    return x + 1\n",
    "alpha/beta.py": "import os\n\n\ndef b(p):\n    return os.path.join(p, 'x')\n",
    "alpha/__init__.py": "",
    "mid.py": "def c(items):\n    total = 0\n    for i in items:\n        total += i\n    return total\n",
    "gamma/delta/eps.py": "class K:\n    def run(self):\n        pass\n",
    "gamma/__init__.py": "",
    "gamma/delta/__init__.py": "",
    # "gamma/" sorts before "gammaZ" with "/" but after it with a Windows "\":
    # the canonical key is the POSIX relative path on every platform.
    "gammaZ.py": "def g(v):\n    return v * 2\n",
    "tie_one.py": "def f():\n    try:\n        return 1\n    except:\n        pass\n",
    "tie_two.py": "def f():\n    try:\n        return 1\n    except:\n        pass\n",
    "omega.py": "import json\n\n\ndef d(s):\n    return json.loads(s)\n",
}


@pytest.fixture
def ordered_project(tmp_path):
    root = tmp_path / "ordered"
    for rel, text in _SOURCES.items():
        _write(root, rel, text)
    _write(root, ".slopconfig.yaml", "advanced:\n  exact_topology_ceiling: 3\n")
    return root


def _relative(root: Path, paths) -> List[str]:
    return [p.resolve().relative_to(root.resolve()).as_posix() for p in paths]


def test_discovery_returns_one_canonical_order(ordered_project):
    from slop_detector.core_project import discover_supported_files

    def reversed_rust(project_path, include_patterns, ignore_patterns):
        found = [p for pattern in include_patterns for p in project_path.glob(pattern)]
        return sorted(found, key=lambda p: p.as_posix(), reverse=True)

    without = discover_supported_files(
        ordered_project, ["**/*.py"], {".py"}, [], rust_discoverer=lambda *a: None
    )
    with_rust = discover_supported_files(
        ordered_project, ["**/*.py"], {".py"}, [], rust_discoverer=reversed_rust
    )
    canonical = sorted(_relative(ordered_project, without))
    assert _relative(ordered_project, without) == canonical
    assert _relative(ordered_project, with_rust) == canonical


def test_project_result_does_not_depend_on_the_rust_helper(ordered_project, monkeypatch):
    """Approximate coherence samples by position and the first of tied files is
    named in next_steps, so the order reaching them must be the same either way."""
    import json

    import slop_detector.core as core

    def analyze(discoverer):
        monkeypatch.setattr(core, "discover_project_files", discoverer)
        detector = SlopDetector(
            config_path=str(ordered_project / ".slopconfig.yaml"), read_only=True
        )
        return json.dumps(detector.analyze_project(str(ordered_project)).to_dict(), sort_keys=True)

    def reversed_rust(project_path, include_patterns, ignore_patterns):
        found = [p for pattern in include_patterns for p in project_path.glob(pattern)]
        return sorted(found, key=lambda p: p.as_posix(), reverse=True)

    without = analyze(lambda *a: None)
    with_rust = analyze(reversed_rust)
    assert '"vr_structural_approx"' in without, "approximate topology not exercised"
    assert without == with_rust


# ---------------------------------------------------------------------------
# D3: hallucinated_deps evidence does not depend on set iteration order
# ---------------------------------------------------------------------------


def test_hallucinated_deps_do_not_depend_on_category_iteration_order():
    """Each library sits in two categories, and 12 entries are truncated to 10:
    the iteration order of a library's categories (a str set, so it follows the
    hash seed) used to decide the order and which entries survived the cut."""
    import ast
    from types import SimpleNamespace

    from slop_detector.config import Config
    from slop_detector.metrics.hallucination_deps import HallucinationDepsDetector

    libs = [f"lib{i}" for i in range(6)]
    content = "".join(f"import {lib}\n" for lib in libs)
    tree = ast.parse(content)
    ddc = SimpleNamespace(imported=list(libs), unused=list(libs))

    def evidence(category_order):
        detector = HallucinationDepsDetector(Config())
        detector.available = True
        detector.CATEGORY_MAP = {"alpha": set(libs), "beta": set(libs)}
        detector.INTENT_PATTERNS = {}
        detector.lib_to_categories = {lib: list(category_order) for lib in libs}
        result = detector.analyze("f.py", content, tree, ddc)
        return [d.to_dict() for d in result.hallucinated_deps], result.total_hallucinated

    first, total = evidence(["alpha", "beta"])
    second, _ = evidence(["beta", "alpha"])
    assert total == 12 and len(first) == 10
    assert first == second


# ---------------------------------------------------------------------------
# Cache round trip: a cache hit serializes byte-for-byte like a fresh analysis
# ---------------------------------------------------------------------------


def test_cache_hit_serializes_like_a_fresh_analysis(project, tmp_path):
    """The cache stores results with sorted keys; a fresh `dcf` kept AST-walk
    order, so the same file printed differently on the first and second run."""
    import json

    path = _write(
        project,
        "mod.py",
        "import os\nfrom json import loads\n\n\ndef f(x):\n    if x:\n        return loads(x)\n"
        "    return os.sep\n",
    )
    db = tmp_path / "cache.db"

    def analyze():
        detector = SlopDetector()
        detector._analysis_cache = FileAnalysisCache(db)
        return json.dumps(detector.analyze_file(str(path)).to_dict())

    fresh = analyze()
    cached = analyze()
    assert fresh == cached
