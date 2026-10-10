"""v3.10 import evidence: a module with evidence is never reported as phantom.

Found by the cross-domain study (1,116 `phantom_import`, 11 repositories) and
re-measured on the 3.9.3 source:
- 100 imports are declared in a conda `environment.yml` that sits between the
  importing file and its project root, a format and a location the resolver
  never read; setup.py and setup.cfg were project markers whose
  `install_requires` was never read, and Pipfile, Poetry and root
  `requirements-*.txt` were not read either;
- 32 imports name a package directory next to the script (Python puts the
  script's directory on sys.path), while only sibling `.py` files counted;
- in a long-lived process an uninstalled package stayed "installed": the
  resolvable-module set was built once per process and the environment
  fingerprint was keyed by the sys.path strings only;
- DDC `fake_imports` reported a heavyweight library used only in annotations,
  which `usage_ratio` already excludes.

Contract:
- declarations come from every supported format at each resolution root and
  from declaration files in the directories between the file and its nearest
  root; a declaration elsewhere in the tree is not evidence for the file;
- a sibling package directory (regular or namespace) is local evidence;
- the environment evidence follows installs and uninstalls in one process;
- `fake_imports` uses the same exclusions as `usage_ratio`.

Imports use names that are never installed (`zz...`).
"""

from __future__ import annotations

import ast
import importlib
import shutil
import sys
from pathlib import Path
from typing import List

import pytest

from slop_detector.analysis_cache import FileAnalysisCache
from slop_detector.config import Config
from slop_detector.core import SlopDetector
from slop_detector.metrics.ddc import DDCCalculator
from slop_detector.patterns import python_imports


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _import_findings(path: Path) -> List[tuple]:
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted(
        (issue.pattern_id, issue.message)
        for issue in result.pattern_issues
        if issue.pattern_id
        in {
            "phantom_import",
            "runtime_unavailable_dependency",
            "declared_outside_primary_metadata",
            "undeclared_optional_dependency",
        }
    )


def _ids(path: Path) -> List[str]:
    return [pattern_id for pattern_id, _ in _import_findings(path)]


ENVIRONMENT_YML = (
    "name: skill\n"
    "dependencies:\n"
    "  - python=3.11\n"
    "  - conda-forge::zz-condaonly>=1.0\n"
    "  - pip\n"
    "  - pip:\n"
    "    - zz-pipinconda>=2\n"
)


# --- declaration formats and locations --------------------------------------


def test_environment_yml_between_file_and_root_declares(tmp_path):
    _write(tmp_path, "requirements.txt", "")
    _write(tmp_path, "skills/a/repo/environment.yml", ENVIRONMENT_YML)
    user = _write(
        tmp_path, "skills/a/repo/src/graph.py", "import zz_condaonly\nimport zz_pipinconda\n"
    )

    findings = _import_findings(user)

    assert [pid for pid, _ in findings] == ["runtime_unavailable_dependency"] * 2
    assert all("skills/a/repo/environment.yml" in message for _, message in findings)


def test_nested_declaration_in_pyproject_project_is_a_metadata_gap(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "root"\nversion = "0"\n')
    _write(tmp_path, "skills/a/environment.yml", ENVIRONMENT_YML)
    user = _write(tmp_path, "skills/a/run.py", "import zz_condaonly\n")

    assert _ids(user) == ["declared_outside_primary_metadata"]


def test_declaration_outside_the_files_path_is_not_evidence(tmp_path):
    _write(tmp_path, "requirements.txt", "")
    _write(tmp_path, "other/environment.yml", ENVIRONMENT_YML)
    user = _write(tmp_path, "app/main.py", "import zz_condaonly\n")

    assert _ids(user) == ["phantom_import"]


@pytest.mark.parametrize(
    "files",
    [
        {
            "setup.py": (
                "from setuptools import setup\n"
                "setup(name='x', install_requires=['zz-setuppkg>=1'],\n"
                "      extras_require={'gpu': ['zz_extrapkg']})\n"
            )
        },
        {
            "setup.py": (
                "import setuptools\n"
                "REQUIRED = ['zz-setuppkg>=1']\n"
                "EXTRAS = {'gpu': ['zz_extrapkg']}\n"
                "setuptools.setup(name='x', install_requires=REQUIRED, extras_require=EXTRAS)\n"
            )
        },
        {
            "setup.cfg": (
                "[metadata]\nname = x\n\n[options]\ninstall_requires =\n    zz-setuppkg>=1\n\n"
                "[options.extras_require]\ngpu =\n    zz_extrapkg\n"
            )
        },
        {
            "requirements.txt": "",
            "Pipfile": '[packages]\nzz-setuppkg = "*"\n\n[dev-packages]\nzz_extrapkg = "*"\n',
        },
        {"requirements.txt": "", "requirements-dev.txt": "zz-setuppkg\nzz_extrapkg>=2\n"},
    ],
    ids=["setup-py-literal", "setup-py-names", "setup-cfg", "pipfile", "requirements-dev"],
)
def test_root_declaration_formats_declare(tmp_path, files):
    for name, text in files.items():
        _write(tmp_path, name, text)
    user = _write(tmp_path, "pkg_user.py", "import zz_setuppkg\nimport zz_extrapkg\n")

    assert _ids(user) == ["runtime_unavailable_dependency"] * 2


def test_poetry_dependencies_declare(tmp_path):
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.poetry]\nname = "x"\nversion = "0"\n\n'
        '[tool.poetry.dependencies]\npython = "^3.10"\nzz-setuppkg = "^1"\n\n'
        '[tool.poetry.group.dev.dependencies]\nzz_extrapkg = "*"\n',
    )
    user = _write(tmp_path, "pkg_user.py", "import zz_setuppkg\nimport zz_extrapkg\n")

    assert _ids(user) == ["runtime_unavailable_dependency"] * 2


# --- script-directory packages ----------------------------------------------


def test_package_directory_next_to_the_script_is_local(tmp_path):
    _write(tmp_path, "requirements.txt", "")
    _write(tmp_path, "skill/scripts/zzhelpers/__init__.py", "X = 1\n")
    _write(tmp_path, "skill/scripts/zznamespace/util.py", "Y = 1\n")
    _write(tmp_path, "skill/scripts/zzassets/logo.txt", "not code\n")
    user = _write(
        tmp_path,
        "skill/scripts/run.py",
        "import zzhelpers\nimport zznamespace.util\nimport zzassets\n",
    )

    findings = _import_findings(user)

    assert [pid for pid, _ in findings] == ["phantom_import"]
    assert "zzassets" in findings[0][1]


def test_subpackage_directory_inside_a_package_is_not_the_imported_module(tmp_path):
    # Inside a regular package `import zzdatasets` is absolute: the
    # `zzdatasets/` subpackage next to the module is not what it loads
    # (sentence-transformers: `datasets` the library vs `datasets/` subpackage).
    # One level below the top package, as in sentence-transformers (a direct
    # child of the root is a layout root of its own and resolves either way).
    _write(tmp_path, "requirements.txt", "")
    _write(tmp_path, "pkg/__init__.py", "")
    _write(tmp_path, "pkg/sub/__init__.py", "")
    _write(tmp_path, "pkg/sub/zzdatasets/__init__.py", "")
    user = _write(tmp_path, "pkg/sub/trainer.py", "import zzdatasets\n")

    assert _ids(user) == ["phantom_import"]


# --- cache identity follows the new declaration files -----------------------


def test_editing_a_nested_environment_file_invalidates_the_cache(tmp_path):
    root = tmp_path / "proj"
    _write(root, "requirements.txt", "")
    env_file = _write(root, "skills/a/environment.yml", "dependencies:\n  - zz-other\n")
    user = _write(root, "skills/a/run.py", "import zz_condaonly\n")
    db = tmp_path / "cache.db"

    def analyze():
        detector = SlopDetector()
        detector._analysis_cache = FileAnalysisCache(db)
        result = detector.analyze_file(str(user))
        return sorted(
            i.pattern_id
            for i in result.pattern_issues
            if "depend" in i.pattern_id or "phantom" in i.pattern_id
        )

    assert analyze() == ["phantom_import"]
    env_file.write_text(ENVIRONMENT_YML, encoding="utf-8")
    assert analyze() == ["runtime_unavailable_dependency"]


# --- environment freshness in one process -----------------------------------


def test_uninstall_is_seen_in_the_same_process(tmp_path, monkeypatch):
    site = tmp_path / "site"
    _write(site, "zzgonepkg/__init__.py", "VALUE = 1\n")
    _write(site, "zzgonepkg-1.0.dist-info/METADATA", "Name: zzgonepkg\nVersion: 1.0\n")
    _write(site, "zzgonepkg-1.0.dist-info/top_level.txt", "zzgonepkg\n")
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()
    # The first scan after the install builds the resolvable-module set.
    monkeypatch.setattr(python_imports, "_RESOLVABLE_MODULES_STORE", {})

    assert python_imports._module_exists("zzgonepkg") is True
    from slop_detector.environment_resolution import environment_fingerprint

    before = environment_fingerprint()

    shutil.rmtree(site / "zzgonepkg")
    shutil.rmtree(site / "zzgonepkg-1.0.dist-info")
    importlib.invalidate_caches()

    assert python_imports._module_exists("zzgonepkg") is False
    assert environment_fingerprint() != before


# --- DDC uses one exclusion rule --------------------------------------------


def test_fake_imports_skip_annotation_only_heavyweight_libs():
    code = (
        "import numpy as np\n"
        "import pandas as pd\n\n\n"
        "def shape(values: np.ndarray) -> int:\n"
        "    return len(values)\n"
    )
    result = DDCCalculator(Config()).calculate("m.py", code, ast.parse(code))

    assert result.fake_imports == ["pandas"]


@pytest.fixture(autouse=True)
def _fresh_import_state():
    importlib.invalidate_caches()
    yield
    importlib.invalidate_caches()
    assert "zzgonepkg" not in sys.modules
