"""RED controls R1-R12 for import provider resolution (v3.18.0).

Design: docs/IMPORT_PROVIDER_RESOLUTION.md (section 10). Each control states
the verdict after the change. Controls marked KEEP pass today and must keep
passing; the others fail today for the reason in their docstring.

Environments are built from files, never by installing anything:
- the analyzer environment gets a fake site directory on sys.path with
  `*.dist-info` folders and module files;
- the target environment is a virtual environment inside the project root
  (a directory with `pyvenv.cfg`), read as files only.
Real ecosystem names (Pillow, PyPDF2, ...) are used where the control is about
ecosystem knowledge; if such a package is importable in the test environment,
the control is skipped with the reason, because absence cannot be simulated
without hiding real installs.

Contract fixed here (section 8 of the design):
- import-evidence findings carry `evidence` = {import_name, provider,
  provider_state, environment} in Issue.to_dict();
- provider_state is one of ARTIFACT_VERIFIED, METADATA_DECLARED,
  MAPPING_SUPPORTED, NAME_CANDIDATE, PROVIDER_UNKNOWN, PROVIDER_CONFLICT;
- environment is "target" or "analyzer";
- new finding IDs: undeclared_dependency (known provider, not declared),
  provider_conflict (installed provider differs from the declared one).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pytest

from slop_detector.analysis_cache import deserialize_file_analysis, serialize_file_analysis
from slop_detector.core import SlopDetector

IMPORT_EVIDENCE_IDS = {
    "phantom_import",
    "phantom_member",
    "runtime_unavailable_dependency",
    "declared_outside_primary_metadata",
    "undeclared_optional_dependency",
    "undeclared_dependency",
    "provider_conflict",
}
PROVIDER_STATES = {
    "ARTIFACT_VERIFIED",
    "METADATA_DECLARED",
    "MAPPING_SUPPORTED",
    "NAME_CANDIDATE",
    "PROVIDER_UNKNOWN",
    "PROVIDER_CONFLICT",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _dist(
    site: Path,
    name: str,
    version: str,
    modules: Dict[str, str],
    top_level: Optional[Sequence[str]] = None,
    import_names: Sequence[str] = (),
) -> None:
    """A distribution as installed files: dist-info (METADATA, RECORD, top_level.txt) + modules."""
    info = site / f"{re.sub(r'[-.]+', '_', name)}-{version}.dist-info"
    meta = [
        f"Metadata-Version: {'2.5' if import_names else '2.1'}",
        f"Name: {name}",
        f"Version: {version}",
    ]
    meta += [f"Import-Name: {n}" for n in import_names]
    _write(info, "METADATA", "\n".join(meta) + "\n")
    tops = (
        list(top_level)
        if top_level is not None
        else sorted({re.sub(r"\.py$", "", m.split("/")[0]) for m in modules})
    )
    _write(info, "top_level.txt", "\n".join(tops) + "\n")
    for rel, text in modules.items():
        _write(site, rel, text)
    record = [f"{rel},," for rel in modules] + [
        f"{info.name}/{f},," for f in ("METADATA", "RECORD", "top_level.txt")
    ]
    _write(info, "RECORD", "\n".join(record) + "\n")


def _target_site(project: Path) -> Path:
    """site-packages of a virtual environment inside the project, in this platform's layout."""
    venv = project / ".venv"
    _write(
        venv,
        "pyvenv.cfg",
        f"home = {Path(sys.executable).parent}\nversion = {sys.version.split()[0]}\n",
    )
    if sys.platform == "win32":
        return venv / "Lib" / "site-packages"
    return venv / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}" / "site-packages"


@pytest.fixture
def analyzer_site(tmp_path, monkeypatch):
    """A fake site directory on the analyzer's sys.path."""
    site = tmp_path / "analyzer_site"
    site.mkdir()
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()
    return site


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    return root


def _pyproject(project: Path, deps: Iterable[str]) -> None:
    listed = ", ".join(json.dumps(d) for d in deps)  # TOML basic strings, quotes escaped
    _write(
        project,
        "pyproject.toml",
        f'[project]\nname = "proj"\nversion = "0"\ndependencies = [{listed}]\n',
    )


def _require_absent(*names: str) -> None:
    for name in names:
        try:
            found = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            found = False
        if found:
            pytest.skip(
                f"'{name}' is importable in this test environment; absence cannot be simulated"
            )


def _issues(project: Path, source: str) -> List[dict]:
    path = _write(project, "user.py", source)
    importlib.invalidate_caches()
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return [i.to_dict() for i in result.pattern_issues if i.pattern_id in IMPORT_EVIDENCE_IDS]


def _ids(issues: List[dict]) -> List[str]:
    return sorted(i["pattern_id"] for i in issues)


def _norm(name: Optional[str]) -> Optional[str]:
    return None if name is None else re.sub(r"[-_.]+", "-", name).lower()


def _evidence(issue: dict) -> dict:
    evidence = issue.get("evidence")
    assert isinstance(
        evidence, dict
    ), f"{issue['pattern_id']} at line {issue['line']} has no evidence"
    assert set(evidence) >= {"import_name", "provider", "provider_state", "environment"}, evidence
    assert evidence["provider_state"] in PROVIDER_STATES, evidence
    assert evidence["environment"] in {"target", "analyzer"}, evidence
    return evidence


# ---------------------------------------------------------------------------
# R1-R3: distribution name vs import name, case
# ---------------------------------------------------------------------------

F1_PAIRS = [
    ("Pillow", "PIL"),
    ("scikit-learn", "sklearn"),
    ("absl-py", "absl"),
    ("dm-haiku", "haiku"),
    ("beautifulsoup4", "bs4"),
    ("biopython", "Bio"),
    ("PyOpenGL", "OpenGL"),
    ("py-cpuinfo", "cpuinfo"),
]


@pytest.mark.parametrize("dist,module", F1_PAIRS)
def test_r1_declared_under_another_name_is_not_phantom(project, dist, module):
    """R1. Today: phantom_import CRITICAL ("not declared anywhere") although declared."""
    _require_absent(module)
    _pyproject(project, [dist])
    issues = _issues(project, f"import {module}\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    assert _norm(_evidence(issues[0])["provider"]) == _norm(dist)


def test_r2_case_of_a_declared_import_name_is_kept(project):
    """R2. Today: `import PyPDF2` with PyPDF2 declared is phantom_import CRITICAL."""
    _require_absent("PyPDF2")
    _pyproject(project, ["PyPDF2"])
    assert _ids(_issues(project, "import PyPDF2\n")) == ["runtime_unavailable_dependency"]


def test_r3_wrong_case_is_not_excused_as_declared(project):
    """R3. Today: `import pypdf2` with PyPDF2 declared is excused as declared (MEDIUM)."""
    _require_absent("PyPDF2", "pypdf2")
    _pyproject(project, ["PyPDF2"])
    ids = _ids(_issues(project, "import pypdf2\n"))
    assert "runtime_unavailable_dependency" not in ids, ids
    assert ids == ["phantom_import"], ids


# ---------------------------------------------------------------------------
# R4: namespace portions
# ---------------------------------------------------------------------------


def test_r4_namespace_portions_are_attributed_to_their_own_provider(project):
    """R4. Today: both imports reported as phantom_import (top-level name `google` only)."""
    _require_absent("google")
    _pyproject(project, ["google-generativeai", "google-cloud-storage"])
    issues = _issues(project, "import google.generativeai\nfrom google.cloud import storage\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"] * 2, issues
    by_line = {i["line"]: _norm(_evidence(i)["provider"]) for i in issues}
    assert by_line == {1: "google-generativeai", 2: "google-cloud-storage"}


# ---------------------------------------------------------------------------
# R5-R6: two distributions provide one module
# ---------------------------------------------------------------------------

PYJWT_MODULE = (
    "def encode(payload, key):\n    return ''\n\ndef decode(token, key):\n    return {}\n"
)


def test_r5_member_check_skips_a_different_installed_provider(project, analyzer_site):
    """R5. Today: `JWT` and `jwk_from_pem` reported as phantom_member HIGH from PyJWT's source."""
    _dist(analyzer_site, "PyJWT", "2.8.0", {"jwt/__init__.py": PYJWT_MODULE})
    _pyproject(project, ["jwt>=1.3.1,<2"])
    issues = _issues(project, "from jwt import JWT, jwk_from_pem\n")
    assert "phantom_member" not in _ids(issues), issues
    conflicts = [i for i in issues if i["pattern_id"] == "provider_conflict"]
    assert len(conflicts) == 1, issues
    assert "PyJWT" in conflicts[0]["message"] and "'jwt'" in conflicts[0]["message"], conflicts[0]
    assert _evidence(conflicts[0])["provider_state"] == "PROVIDER_CONFLICT"


def test_r6_member_check_uses_the_declared_provider_in_the_target(project, analyzer_site):
    """R6. Today: both names reported from the analyzer's PyJWT; the target environment is not read."""
    _dist(analyzer_site, "PyJWT", "2.8.0", {"jwt/__init__.py": PYJWT_MODULE})
    _dist(_target_site(project), "jwt", "1.3.1", {"jwt/__init__.py": "class JWT:\n    pass\n"})
    _pyproject(project, ["jwt>=1.3.1,<2"])
    issues = _issues(project, "from jwt import JWT, jwk_from_pem\n")
    assert _ids(issues) == ["phantom_member"], issues
    assert "jwk_from_pem" in issues[0]["message"] and "JWT'" not in issues[0]["message"], issues[0]
    evidence = _evidence(issues[0])
    assert evidence["environment"] == "target" and _norm(evidence["provider"]) == "jwt", evidence


# ---------------------------------------------------------------------------
# R7-R8: unknown provider vs known provider not declared
# ---------------------------------------------------------------------------


def test_r7_keep_a_name_no_source_knows_stays_phantom(project):
    """R7 (KEEP). An invented, undeclared name stays phantom_import."""
    _pyproject(project, [])
    issues = _issues(project, "import zz_invented_llm_sdk_q7\n")
    assert _ids(issues) == ["phantom_import"], issues


def test_r8_known_provider_not_declared_names_the_provider(project):
    """R8. Today: phantom_import CRITICAL; the provider (Pillow) is known but not named."""
    _require_absent("PIL")
    _pyproject(project, [])
    issues = _issues(project, "import PIL\n")
    assert _ids(issues) == ["undeclared_dependency"], issues
    # the provider is known from the shipped mapping only: a review candidate, not HIGH
    assert issues[0]["severity"] == "medium", issues[0]
    assert _norm(_evidence(issues[0])["provider"]) == "pillow"
    assert _evidence(issues[0])["provider_state"] == "MAPPING_SUPPORTED"
    assert "pip install" not in (issues[0]["suggestion"] or ""), issues[0]


def test_suggestion_never_says_add_it_because_it_exists(project):
    """Section 8: the phantom_import suggestion asks to confirm the package, not to declare it.

    Today: "Verify '<name>' exists on PyPI and add it to [project.dependencies]".
    """
    _pyproject(project, [])
    issues = _issues(project, "import zz_invented_llm_sdk_q7\n")
    suggestion = issues[0]["suggestion"] or ""
    assert "exists on PyPI" not in suggestion and "add it to" not in suggestion, suggestion
    assert "does not exist" not in issues[0]["message"], issues[0]["message"]


# ---------------------------------------------------------------------------
# R9: declared vs active (environment markers, platform tests in code). The platform and
# Python version come from the target environment's files only (P1, option a): with no
# target environment they are unknown, whatever the analyzer runs on.
# ---------------------------------------------------------------------------

PYWIN32 = 'pywin32; sys_platform == "win32"'
GUARDED_WIN32API = 'import sys\n\nif sys.platform == "win32":\n    import win32api\n'


def _venv(project: Path, layout: str, version: str = "3.11.4") -> Path:
    """A target environment with an explicit layout ("windows" or "posix") and Python version."""
    venv = project / ".venv"
    _write(venv, "pyvenv.cfg", f"home = /usr/bin\nversion = {version}\n")
    if layout == "windows":
        site = venv / "Lib" / "site-packages"
    else:
        site = venv / "lib" / f"python{'.'.join(version.split('.')[:2])}" / "site-packages"
    _dist(site, "zz-placeholder", "1.0", {"zz_placeholder/__init__.py": "X = 1\n"})
    return site


def _unverified(project: Path, source: str) -> List[dict]:
    path = _write(project, "user.py", source)
    importlib.invalidate_caches()
    return SlopDetector(read_only=True).analyze_file(str(path)).to_dict()["unverified_imports"]


def test_r9a_unknown_target_guarded_import_is_unverified_not_a_finding(project):
    """R9a, no target environment: the platform test cannot be decided, so the guarded import
    is an unverified import (no score), not a finding. The analyzer's own platform is not used."""
    _require_absent("win32api")
    _pyproject(project, [PYWIN32])
    assert _ids(_issues(project, GUARDED_WIN32API)) == []
    rows = _unverified(project, GUARDED_WIN32API)
    assert [(r["requested_module"], r["reason"]) for r in rows] == [
        ("win32api", "platform_guard_undecided")
    ], rows


def test_r9a_posix_target_guarded_import_is_clean(project):
    """R9a, POSIX target: `sys.platform == "win32"` is false there; the import never runs."""
    _require_absent("win32api")
    _venv(project, "posix")
    _pyproject(project, [PYWIN32])
    assert _ids(_issues(project, GUARDED_WIN32API)) == []
    assert _unverified(project, GUARDED_WIN32API) == []


def test_r9a_windows_target_guarded_import_is_declared_but_unavailable(project):
    """R9a, Windows target: the guard is true and pywin32 is active but not installed there."""
    _require_absent("win32api")
    _venv(project, "windows")
    _pyproject(project, [PYWIN32])
    issues = _issues(project, GUARDED_WIN32API)
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    ev = _evidence(issues[0])
    assert ev["target_platform"] == "win32" and ev["marker_evaluation"] == "ACTIVE", ev


def test_r9b_posix_target_unconditional_import_of_an_inactive_dependency_is_reported(project):
    """R9b, POSIX target: the import always runs and its only provider is inactive there."""
    _require_absent("win32api")
    _venv(project, "posix")
    _pyproject(project, [PYWIN32])
    issues = _issues(project, "import win32api\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    assert _norm(_evidence(issues[0])["provider"]) == "pywin32"
    assert _evidence(issues[0])["marker_evaluation"] == "INACTIVE"
    assert "sys_platform" in issues[0]["message"], issues[0]["message"]


def test_r9b_unknown_target_marker_is_unknown(project):
    """R9b, no target environment: the declaration's marker is UNKNOWN (not decided on the
    analyzer's platform); the import is declared and not installed: environment evidence."""
    _require_absent("win32api")
    _pyproject(project, [PYWIN32])
    issues = _issues(project, "import win32api\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    ev = _evidence(issues[0])
    assert ev["marker_evaluation"] == "UNKNOWN" and ev["target_platform"] is None, ev
    assert "sys_platform" not in issues[0]["message"], issues[0]["message"]


@pytest.mark.parametrize(
    "version,expected", [("3.11.4", "INACTIVE"), ("3.7.9", "ACTIVE"), (None, "UNKNOWN")]
)
def test_r9c_python_version_marker_uses_the_target_python(project, version, expected):
    """R9c: `python_version` markers are evaluated for the target's Python (pyvenv.cfg), not the
    analyzer's; no target: UNKNOWN."""
    if version is not None:
        _venv(project, "posix", version)
    _pyproject(project, ['zz-backport; python_version < "3.8"'])
    issues = _issues(project, "import zz_backport\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    assert _evidence(issues[0])["marker_evaluation"] == expected, _evidence(issues[0])


# ---------------------------------------------------------------------------
# R12: PEP 735 dependency groups are declarations
# ---------------------------------------------------------------------------


def _pyproject_groups(project: Path, groups: Dict[str, List[str]]) -> None:
    body = "".join(
        f"{name} = [{', '.join(repr(d).replace(chr(39), chr(34)) for d in deps)}]\n"
        for name, deps in groups.items()
    )
    _write(
        project,
        "pyproject.toml",
        '[project]\nname = "proj"\nversion = "0"\ndependencies = []\n\n[dependency-groups]\n'
        + body,
    )


def test_r12_dependency_group_declares_a_same_named_dependency(project):
    """R12a. Today: phantom_import CRITICAL; [dependency-groups] (PEP 735) is not read."""
    _pyproject_groups(project, {"scripts": ["zz-groupdep>=1"]})
    assert _ids(_issues(project, "import zz_groupdep\n")) == ["runtime_unavailable_dependency"]


def test_r12_dependency_group_declares_a_provider_under_another_name(project):
    """R12b. Today: phantom_import CRITICAL (group not read, and scikit-learn -> sklearn not linked)."""
    _require_absent("sklearn")
    _pyproject_groups(project, {"scripts": ["scikit-learn>=1.7.2"]})
    issues = _issues(project, "import sklearn\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    assert _norm(_evidence(issues[0])["provider"]) == "scikit-learn"


# ---------------------------------------------------------------------------
# R10: everything installed -> existing fields unchanged
# ---------------------------------------------------------------------------


def test_r10_keep_installed_dependencies_keep_every_existing_field(project, analyzer_site):
    """R10 (KEEP). With every dependency installed, findings and existing keys are unchanged.

    Declared `zz-fmt-dist` provides `zz_fmt` and `zz_lib2to3`; both installed in
    the analyzer environment. 3.17.0 reports nothing for these imports.
    """
    _dist(
        analyzer_site,
        "zz-fmt-dist",
        "1.0",
        {"zz_fmt/__init__.py": "def run():\n    return 1\n", "zz_lib2to3/__init__.py": "G = 1\n"},
    )
    _pyproject(project, ["zz-fmt-dist"])
    path = _write(project, "user.py", "import zz_fmt\nimport zz_lib2to3\nfrom zz_fmt import run\n")
    importlib.invalidate_caches()
    result = SlopDetector(read_only=True).analyze_file(str(path)).to_dict()
    # Fields and values 3.17.0 produces for this file (measured on 4781ca7 source).
    # New keys may be added; none of these may disappear or change value.
    assert set(R10_KEYS) <= set(result), sorted(set(R10_KEYS) - set(result))
    assert result["pattern_issues"] == [], result["pattern_issues"]
    assert result["unverified_imports"] == [], result["unverified_imports"]
    assert result["pattern_errors"] == [], result["pattern_errors"]
    assert result["deficit_score"] == 0.0 and result["status"] == "clean", (
        result["deficit_score"],
        result["status"],
    )


R10_KEYS = (
    "claim_coverage claim_findings content_origin context_jargon dcf ddc deficit_breakdown "
    "deficit_score docstring_inflation file_path file_role flags hallucination_deps inflation ldr "
    "ml_scoring pattern_errors pattern_issues semantic_coverage semantic_findings skipped_metrics "
    "source_sha256 status unverified_imports warnings"
).split()


# ---------------------------------------------------------------------------
# R11: byte-identical project, two analyzer environments, one target environment
# ---------------------------------------------------------------------------


def _r11_project(project: Path) -> None:
    _dist(
        _target_site(project),
        "zz-fmt-dist",
        "1.0",
        {"zz_fmt/__init__.py": "X = 1\n", "zz_lib2to3/__init__.py": "G = 1\n"},
    )
    _pyproject(project, ["zz-fmt-dist"])


def test_r11_target_environment_makes_the_verdict_independent_of_the_analyzer(
    project, tmp_path, monkeypatch
):
    """R11. Today: without the dist in the analyzer, `import zz_lib2to3` is phantom_import CRITICAL;
    with it, nothing. The target environment (which has it) is not read."""
    _r11_project(project)
    source = "import zz_lib2to3\n"
    without = _issues(project, source)

    site = tmp_path / "analyzer_site_b"
    _dist(
        site,
        "zz-fmt-dist",
        "1.0",
        {"zz_fmt/__init__.py": "X = 1\n", "zz_lib2to3/__init__.py": "G = 1\n"},
    )
    monkeypatch.syspath_prepend(str(site))
    importlib.invalidate_caches()
    with_dist = _issues(project, source)

    assert _ids(without) == _ids(with_dist) == [], (without, with_dist)


# ---------------------------------------------------------------------------
# R13-R16: evidence boundaries found in review (cache identity, target boundary,
# several providers, score contract)
# ---------------------------------------------------------------------------


def test_r13_target_metadata_edited_in_place_is_a_new_context(project):
    """R13. The target environment is identified by the content of the files it is read
    from, not by its directory listing. Today: an in-place METADATA edit (same dist-info
    directory, same version) is served from the cached environment."""
    site = _target_site(project)
    _dist(site, "zz-other", "1.0", {"zz_mod/__init__.py": "Present = 1\n"})
    _pyproject(project, ["zz-mod"])
    first = _issues(project, "from zz_mod import Missing\n")
    assert _ids(first) == ["provider_conflict"], first
    meta = site / "zz_other-1.0.dist-info" / "METADATA"
    meta.write_text(
        meta.read_text(encoding="utf-8").replace("zz-other", "zz-mod"), encoding="utf-8"
    )
    second = _issues(project, "from zz_mod import Missing\n")
    assert _ids(second) == ["phantom_member"], second
    assert _evidence(second[0])["environment"] == "target"


def test_r14_target_without_the_module_is_not_checked_against_the_analyzer(project, analyzer_site):
    """R14. With a target environment, the analyzer's installed files are not evidence about
    the project. Today: the member is checked against the analyzer's copy (phantom_member HIGH)."""
    _dist(_target_site(project), "zz-unrelated", "1.0", {"zz_unrelated/__init__.py": "X = 1\n"})
    _dist(analyzer_site, "zz-ana", "1.0", {"zz_ana/__init__.py": "Present = 1\n"})
    _pyproject(project, ["zz-ana"])
    issues = _issues(project, "from zz_ana import Missing\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    assert _evidence(issues[0])["environment"] == "target"


@pytest.mark.parametrize("module,providers", [("cv2", 3), ("faiss", 2)])
def test_r15_several_known_providers_are_not_narrowed_to_one(project, module, providers):
    """R15. When several distributions provide the name and nothing selects one, no provider
    is named and the finding is not HIGH. Today: the first candidate in sort order is named."""
    _require_absent(module)
    _pyproject(project, [])
    issues = _issues(project, f"import {module}\n")
    assert _ids(issues) == ["undeclared_dependency"], issues
    assert issues[0]["severity"] == "medium", issues[0]
    evidence = _evidence(issues[0])
    assert evidence["provider"] is None, evidence
    assert len(evidence.get("candidates") or []) == providers, evidence


def _issue(pattern_id, severity, line, evidence):
    from slop_detector.patterns.base import Axis, Issue, Severity

    return Issue(
        pattern_id=pattern_id,
        severity=Severity(severity),
        axis=Axis.QUALITY,
        file=Path("m.py"),
        line=line,
        column=0,
        message="",
        evidence=evidence,
    )


def test_r16_score_contract_for_provider_findings():
    """R16. Score contract (3.18): an analyzer-only provider_conflict is diagnostic (no
    penalty); undeclared_dependency counts once per (file, provider). Today: each adds."""
    from slop_detector.core_scoring import calculate_pattern_penalty

    conflict = _issue(
        "provider_conflict", "medium", 1, {"environment": "analyzer", "provider": "jwt"}
    )
    assert calculate_pattern_penalty([conflict]) == 0.0
    a1 = _issue(
        "undeclared_dependency", "medium", 1, {"environment": "analyzer", "provider": "pillow"}
    )
    a2 = _issue(
        "undeclared_dependency", "medium", 9, {"environment": "analyzer", "provider": "Pillow"}
    )
    b = _issue(
        "undeclared_dependency", "medium", 5, {"environment": "analyzer", "provider": "biopython"}
    )
    assert calculate_pattern_penalty([a1, a2]) == 2.0
    assert calculate_pattern_penalty([a1, a2, b]) == 4.0


# ---------------------------------------------------------------------------
# R17-R21 (3.18 holdout follow-up): declaration formats found missing on projects not used to
# build the resolver (F8, F9); phantom_import capped at HIGH; imports that do not run, or whose
# search path the file itself changes, are unverified (no score)
# ---------------------------------------------------------------------------


def _write_pyproject(project: Path, body: str) -> None:
    _write(
        project,
        "pyproject.toml",
        '[project]\nname = "proj"\nversion = "0"\ndependencies = []\n' + body,
    )


def _issues_of(project: Path, rel: str, source: str) -> List[dict]:
    path = _write(project, rel, source)
    importlib.invalidate_caches()
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return [i.to_dict() for i in result.pattern_issues if i.pattern_id in IMPORT_EVIDENCE_IDS]


def _unverified_of(project: Path, rel: str, source: str) -> List[dict]:
    path = _write(project, rel, source)
    importlib.invalidate_caches()
    return SlopDetector(read_only=True).analyze_file(str(path)).to_dict()["unverified_imports"]


def test_r17_uv_dev_dependencies_are_declarations(project):
    """R17 (F8). `[tool.uv] dev-dependencies` (uv's development list before PEP 735) declares.
    Today: phantom_import for both imports."""
    _require_absent("PIL")
    _write_pyproject(project, '\n[tool.uv]\ndev-dependencies = ["zz-uvdev>=1", "Pillow"]\n')
    issues = _issues_of(project, "m.py", "import zz_uvdev\nimport PIL\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"] * 2, issues


def test_r18_build_requires_declare_for_setup_py_only(project):
    """R18 (F9). `[build-system] requires` declares for the build script (setup.py next to the
    pyproject.toml), not for the package's modules. Today: phantom_import in setup.py."""
    _write(
        project,
        "pyproject.toml",
        '[build-system]\nrequires = ["zz-buildtool>=1"]\n\n[project]\nname = "proj"\nversion = "0"\n'
        "dependencies = []\n",
    )
    in_setup = _issues_of(project, "setup.py", "import zz_buildtool\n")
    assert _ids(in_setup) == ["runtime_unavailable_dependency"], in_setup
    in_module = _issues_of(project, "pkg/mod.py", "import zz_buildtool\n")
    assert _ids(in_module) == ["phantom_import"], in_module


def test_r19_phantom_import_is_at_most_high(project):
    """R19. 3.18: phantom_import is HIGH (no provider known is not proof that none exists).
    Today: CRITICAL."""
    _write_pyproject(project, "")
    issues = _issues_of(project, "m.py", "import zz_invented_llm_sdk_q7\n")
    assert _ids(issues) == ["phantom_import"] and issues[0]["severity"] == "high", issues


TYPE_CHECKING_SRC = (
    "from typing import TYPE_CHECKING\n"
    "import typing\n"
    "\n"
    "if TYPE_CHECKING:\n"
    "    import zz_typing_only_a\n"
    "if typing.TYPE_CHECKING:\n"
    "    import zz_typing_only_b\n"
    "else:\n"
    "    import zz_runtime_c\n"
)


def test_r20_type_checking_imports_are_unverified_not_findings(project):
    """R20. Imports under `if TYPE_CHECKING:` do not run: unverified (`type_checking_only`, no
    score); the else branch runs and is judged. Today: phantom_import for all three."""
    _write_pyproject(project, "")
    issues = _issues_of(project, "m.py", TYPE_CHECKING_SRC)
    assert [(i["pattern_id"], i["line"]) for i in issues] == [("phantom_import", 9)], issues
    rows = _unverified_of(project, "m.py", TYPE_CHECKING_SRC)
    assert sorted((r["requested_module"], r["reason"]) for r in rows) == [
        ("zz_typing_only_a", "type_checking_only"),
        ("zz_typing_only_b", "type_checking_only"),
    ], rows


SYS_PATH_SRC = (
    "import sys\n"
    "import zz_before_insert\n"
    "\n"
    "\n"
    "def other():\n"
    "    import zz_other_scope\n"
    "\n"
    "\n"
    "def run(d):\n"
    "    sys.path.insert(0, d)\n"
    "    import zz_after_insert\n"
    "    return zz_after_insert\n"
)


def test_r21_sys_path_change_withholds_only_the_imports_it_reaches(project):
    """R21. A sys.path change withholds only imports that run after it in its scope: those are
    unverified (`sys_path_modified`, no score). An import before it, or in another function, is
    still judged. Today: phantom_import for all three. (Every name here exists in the project
    outside the search path, so the unresolved path could supply it: R23f.)"""
    _write_pyproject(project, "")
    for name in ("zz_before_insert", "zz_other_scope", "zz_after_insert"):
        _write(project, f"tools/plugins/{name}.py", "")
    issues = _issues_of(project, "m.py", SYS_PATH_SRC)
    assert sorted((i["pattern_id"], i["line"]) for i in issues) == [
        ("phantom_import", 2),
        ("phantom_import", 6),
    ], issues
    rows = _unverified_of(project, "m.py", SYS_PATH_SRC)
    assert [(r["requested_module"], r["reason"]) for r in rows] == [
        ("zz_after_insert", "sys_path_modified")
    ], rows


# ---------------------------------------------------------------------------
# R23 (3.18 r6 follow-up): a sys.path change withholds an import only when the added path could
# supply it. A path tied to the file's own location is evaluated; a relative string ("../") or
# os.getcwd() depends on the working directory and is never pinned to a directory: under it,
# only a name that exists as a module or package somewhere in the project is withheld.
# ---------------------------------------------------------------------------


def test_r23a_unresolved_path_does_not_withhold_a_name_the_project_lacks(project):
    """R23a. After `sys.path.append("../")` an import no file of the project could supply is
    judged as before. Today (r6): unverified `sys_path_modified`."""
    _write_pyproject(project, "")
    src = 'import sys\nsys.path.append("../")\nimport zz_unrelated_r23a\n'
    assert _ids(_issues_of(project, "scripts/run.py", src)) == ["phantom_import"]
    assert _unverified_of(project, "scripts/run.py", src) == []


R23B_SRC = (
    "import sys\n"
    "from pathlib import Path\n"
    'sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor_r23"))\n'
    "import zz_vendored_r23b\n"
    "import zz_not_vendored_r23b\n"
)


def test_r23b_file_anchored_path_supplies_only_what_it_contains(project):
    """R23b. A path built from `__file__` is evaluated: the module it contains is provided there
    (no finding, nothing withheld); another import is judged as before. Today (r6): both
    unverified."""
    _write_pyproject(project, "")
    _write(project, "app/vendor_r23/zz_vendored_r23b.py", "")
    issues = _issues_of(project, "app/main.py", R23B_SRC)
    assert [(i["pattern_id"], i["line"]) for i in issues] == [("phantom_import", 5)], issues
    assert _unverified_of(project, "app/main.py", R23B_SRC) == []


def test_r23c_file_anchored_path_without_the_module_keeps_the_verdict(project):
    """R23c. A file-anchored path that does not hold the module (here: a directory that is not
    in the project at all) leaves the verdict as it was. Today (r6): unverified."""
    _write_pyproject(project, "")
    src = (
        "import os\nimport sys\n"
        'sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "LEANN_r23", "src"))\n'
        "import zz_absent_r23c\n"
    )
    assert _ids(_issues_of(project, "eval/lib.py", src)) == ["phantom_import"]
    assert _unverified_of(project, "eval/lib.py", src) == []


def test_r23d_import_before_the_change_keeps_its_verdict(project):
    """R23d. An import that runs before the sys.path change is judged as before, even when the
    project has a module of that name. Holds today; kept as a control."""
    _write_pyproject(project, "")
    _write(project, "tools/plugins/zz_local_r23d.py", "")
    src = 'import sys\nimport zz_local_r23d\nsys.path.append("../")\n'
    assert _ids(_issues_of(project, "scripts/run.py", src)) == ["phantom_import"]
    assert _unverified_of(project, "scripts/run.py", src) == []


def test_r23e_change_inside_a_function_does_not_reach_outer_imports(project):
    """R23e. A sys.path change inside a function does not withhold imports of the enclosing
    scope, before or after the function. Holds today; kept as a control."""
    _write_pyproject(project, "")
    _write(project, "tools/plugins/zz_local_r23e.py", "")
    src = (
        "import sys\n\n\ndef setup():\n" '    sys.path.append("../")\n\n\n' "import zz_local_r23e\n"
    )
    assert _ids(_issues_of(project, "scripts/run.py", src)) == ["phantom_import"]
    assert _unverified_of(project, "scripts/run.py", src) == []


def test_r23f_unresolved_path_withholds_a_project_name_with_its_candidates(project):
    """R23f. Under a path that cannot be resolved statically, an import of a name that exists in
    the project is not resolved by guessing: it is unverified (`sys_path_modified`) and the row
    names the project files that could provide it. Today (r6): unverified, no candidates."""
    _write_pyproject(project, "")
    _write(project, "tools/plugins/zz_plugin_r23f.py", "")
    src = (
        'import os\nimport sys\nsys.path.append(os.environ["PLUGIN_DIR"])\nimport zz_plugin_r23f\n'
    )
    assert _issues_of(project, "scripts/run.py", src) == []
    rows = _unverified_of(project, "scripts/run.py", src)
    assert [(r["requested_module"], r["reason"], r.get("local_candidates")) for r in rows] == [
        ("zz_plugin_r23f", "sys_path_modified", ["tools/plugins/zz_plugin_r23f.py"])
    ], rows


# R23g-i (3.18 r7 review): a directory the file adds is read only inside the scanned project
# (its real path, links resolved); outside it the directory counts as not known statically, which
# is not evidence that the module is missing. A finding after such a directory says so.

_FS_EVENTS = ("open", "os.listdir", "os.scandir")
_FS_WATCH: Dict[str, object] = {"root": None, "seen": []}


def _fs_hook(event: str, args: tuple) -> None:
    try:
        root = _FS_WATCH["root"]
        if root is None or event not in _FS_EVENTS or not args:
            return
        target = args[0]
        if isinstance(target, (str, bytes, os.PathLike)):
            path = os.path.normcase(os.path.abspath(os.fsdecode(target)))
            if path == root or path.startswith(root + os.sep):
                _FS_WATCH["seen"].append((event, path))  # type: ignore[union-attr]
    except Exception:  # an audit hook must never break the audited call
        return


sys.addaudithook(_fs_hook)


@pytest.fixture
def outside(tmp_path):
    """A directory next to the project (outside it)."""
    root = tmp_path / "outside"
    root.mkdir()
    yield root
    _FS_WATCH["root"] = None


def _watch(root: Path) -> None:
    """From now on, record every open or listing of a path written under `root`. A path reached
    through a link inside the project is written under the project, so it is not seen here."""
    _FS_WATCH["root"] = os.path.normcase(os.path.abspath(str(root)))
    _FS_WATCH["seen"] = []


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


def _flagged(issues: List[dict]) -> List[str]:
    return sorted(
        i["evidence"]["import_name"]
        for i in issues
        if (i.get("evidence") or {}).get("sys_path_unresolved") is True
    )


def test_r23g_path_leaving_the_project_is_not_read(project, outside):
    """R23g. A `__file__`-based path that leads out of the project is not read: no file or
    directory listing there is opened. Not looking is not evidence of absence, so both imports,
    the one present outside and the one not, are unverified (`out_of_boundary`), not findings
    (S1 condition 4). Today (r8): findings flagged `sys_path_unresolved`."""
    _write_pyproject(project, "")
    _write(outside, "zz_outside_r23g/mod.py", "")  # a namespace package: found only by walking
    src = (
        "import sys\nfrom pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "outside"))\n'
        "import zz_outside_r23g\n"
        "import zz_missing_r23g\n"
    )
    _write(project, "m.py", src)
    _watch(outside)  # armed after the fixtures are written: only the analysis is watched
    issues = _issues_of(project, "m.py", src)
    assert issues == [], issues
    assert _FS_WATCH["seen"] == [], _FS_WATCH["seen"]
    rows = _unverified_of(project, "m.py", src)
    assert sorted((r["requested_module"], r["reason"]) for r in rows) == [
        ("zz_missing_r23g", "out_of_boundary"),
        ("zz_outside_r23g", "out_of_boundary"),
    ], rows


def test_r23h_link_out_of_the_project_is_not_followed(project, outside):
    """R23h. A directory inside the project that is a link (a symlink, or a junction on Windows)
    to a directory outside it is not read through: the import is unverified (`out_of_boundary`),
    and a module behind it is no local candidate. Today (r8): a finding flagged
    `sys_path_unresolved`. The shared walks are covered in tests/test_project_walk_boundary.py."""
    _write_pyproject(project, "")
    _write(outside, "zz_linked_r23h.py", "")
    _link_dir(project / "app" / "link_r23h", outside)
    src = (
        "import sys\nfrom pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).parent / "link_r23h"))\n'
        "import zz_linked_r23h\n"
    )
    assert _issues_of(project, "app/main.py", src) == []
    rows = _unverified_of(project, "app/main.py", src)
    assert [(r["requested_module"], r["reason"]) for r in rows] == [
        ("zz_linked_r23h", "out_of_boundary")
    ], rows


def test_r23h_package_link_inside_a_project_directory_is_not_followed(project, outside):
    """R23h, entry: the added directory is the project's own, but its entry for the module is a
    link to a package outside: not read through, unverified (`out_of_boundary`). Today (r8): a
    flagged finding."""
    _write_pyproject(project, "")
    _write(outside, "pkg/mod.py", "")
    (project / "app" / "vendor").mkdir(parents=True)
    _link_dir(project / "app" / "vendor" / "zz_pkg_r23h", outside / "pkg")
    src = (
        "import sys\nfrom pathlib import Path\n"
        'sys.path.insert(0, str(Path(__file__).parent / "vendor"))\n'
        "import zz_pkg_r23h\n"
    )
    assert _issues_of(project, "app/main.py", src) == []
    rows = _unverified_of(project, "app/main.py", src)
    assert [(r["requested_module"], r["reason"]) for r in rows] == [
        ("zz_pkg_r23h", "out_of_boundary")
    ], rows


R23I_SRC = (
    "import os\n"
    "import sys\n"
    "from pathlib import Path\n"
    "import zz_before_r23i\n"
    'sys.path.insert(0, str(Path(__file__).parent / "vendor_r23i"))\n'
    "import zz_after_resolved_r23i\n"
    "\n"
    "\n"
    "def helper():\n"
    '    sys.path.append(os.environ["PLUGIN_DIR"])\n'
    "    import zz_in_helper_r23i\n"
    "\n"
    "\n"
    "import zz_outer_r23i\n"
    'sys.path.append("../")\n'
    "import zz_after_unresolved_r23i\n"
)


def test_r23i_only_findings_after_an_unresolved_directory_are_flagged(project):
    """R23i. `evidence.sys_path_unresolved` is true only on a finding that runs after a directory
    not known statically: not after a resolved directory, not before a change, not in a scope the
    change does not reach. It means the search path was not fully known, not that no provider
    exists outside the project; the verdict is unchanged. It survives the analysis cache.
    Today (r7): no such field."""
    _write_pyproject(project, "")
    (project / "vendor_r23i").mkdir()
    path = _write(project, "m.py", R23I_SRC)
    importlib.invalidate_caches()
    result = SlopDetector(read_only=True).analyze_file(str(path))
    issues = [i.to_dict() for i in result.pattern_issues if i.pattern_id in IMPORT_EVIDENCE_IDS]
    assert _ids(issues) == ["phantom_import"] * 5, issues
    expected = ["zz_after_unresolved_r23i", "zz_in_helper_r23i"]
    assert _flagged(issues) == expected, issues
    restored = deserialize_file_analysis(serialize_file_analysis(result))
    assert _flagged([i.to_dict() for i in restored.pattern_issues]) == expected


def test_r23f_candidates_survive_the_analysis_cache(project):
    """R23f, cache: the unverified row keeps `local_candidates` after a cache round trip."""
    _write_pyproject(project, "")
    _write(project, "tools/plugins/zz_plugin_r23f.py", "")
    src = 'import sys\nsys.path.append("../")\nimport zz_plugin_r23f\n'
    path = _write(project, "scripts/run.py", src)
    importlib.invalidate_caches()
    result = SlopDetector(read_only=True).analyze_file(str(path))
    restored = deserialize_file_analysis(serialize_file_analysis(result)).to_dict()
    assert [r.get("local_candidates") for r in restored["unverified_imports"]] == [
        ["tools/plugins/zz_plugin_r23f.py"]
    ]


@pytest.mark.parametrize(
    "dist,module,audit",
    [("Pillow", "PIL", "ARTIFACT_VERIFIED"), ("absl-py", "absl", "AUDIT_PENDING")],
)
def test_r22_mapping_evidence_carries_its_audit_state(project, dist, module, audit):
    """R22. A provider known from the shipped mapping says how far that mapping entry was audited
    (ARTIFACT_VERIFIED only when a local artifact's files matched their RECORD hashes; else
    AUDIT_PENDING), so an unaudited entry is not read as confirmed. Today: no audit field."""
    _require_absent(module)
    _pyproject(project, [dist])
    issues = _issues(project, f"import {module}\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    ev = _evidence(issues[0])
    assert ev["provider_state"] == "MAPPING_SUPPORTED" and ev.get("mapping_audit") == audit, ev


# ---------------------------------------------------------------------------
# R24 (3.18 P1): a declaration of the import in another subtree of the project is attached to the
# finding as context (`evidence.related_declarations`), never as the file's provider: the finding,
# its severity and the score stay what they were. A line is given only when the declaration file
# holds the name on exactly one line.
# ---------------------------------------------------------------------------


def _related(issue: dict) -> List[dict]:
    return (issue.get("evidence") or {}).get("related_declarations") or []


def _sha(path: Path) -> str:
    return __import__("hashlib").sha256(path.read_bytes()).hexdigest()


def test_r24a_same_named_declaration_elsewhere_is_context(project):
    """R24a. tools/requirements.txt declares `zz-rel-a`; m.py at the root imports zz_rel_a: still
    phantom_import HIGH, with the declaration as context (same name, not a known provider).
    Today: no related_declarations."""
    _write_pyproject(project, "")
    req = _write(project, "tools/requirements.txt", "# tools\nzz-rel-a>=1\n")
    issues = _issues_of(project, "m.py", "import zz_rel_a\n")
    assert _ids(issues) == ["phantom_import"] and issues[0]["severity"] == "high", issues
    assert _related(issues[0]) == [
        {
            "source_path": "tools/requirements.txt",
            "line": 2,
            "declared_distribution": "zz-rel-a",
            "match_basis": "SAME_NAME",
            "provider_state": "NAME_CANDIDATE",
            "relationship": "OTHER_SUBTREE",
            "verification_state": "CONTEXT_ONLY",
            "source_sha256": _sha(req),
        }
    ], issues[0]


def test_r24b_known_provider_declared_elsewhere_is_context(project):
    """R24b. Another subtree declares Pillow; m.py imports PIL (not installed): the finding is
    what it was (undeclared_dependency), and the declaration is context with the provider's
    evidence state. Today: no related_declarations."""
    _require_absent("PIL")
    _write_pyproject(project, "")
    _write(project, "svc/requirements.txt", "Pillow\n")
    issues = _issues_of(project, "m.py", "import PIL\n")
    assert _ids(issues) == ["undeclared_dependency"], issues
    rel = _related(issues[0])
    assert [
        (r["source_path"], r["declared_distribution"], r["match_basis"], r["provider_state"])
        for r in rel
    ] == [("svc/requirements.txt", "Pillow", "KNOWN_PROVIDER", "MAPPING_SUPPORTED")]


def test_r24c_declared_on_the_path_gets_no_context(project):
    """R24c. A declaration on the file's own path (the root pyproject.toml) makes it declared
    (runtime_unavailable): no related_declarations, even though another subtree of the same root
    declares it too. (A requirements.txt in sub/ would make sub/ its own project root, so
    tools/ would not be searched at all and the check would be vacuous.)"""
    _pyproject(project, ["zz-rel-c"])
    _write(project, "tools/requirements.txt", "zz-rel-c\n")
    issues = _issues_of(project, "sub/m.py", "import zz_rel_c\n")
    assert _ids(issues) == ["runtime_unavailable_dependency"], issues
    assert _related(issues[0]) == [], issues[0]


def test_r24d_markers_duplicates_and_ambiguous_lines(project):
    """R24d. Two subtrees declare it: each is listed (sorted by path), a marker is kept as
    written, and a file that holds the name on more than one line gives no line."""
    _write_pyproject(project, "")
    _write(project, "a/requirements.txt", "zz-rel-d; sys_platform == 'linux'\n")
    _write(
        project,
        "b/pyproject.toml",
        '[project]\nname = "b"\nversion = "0"\ndependencies = ["zz-rel-d"]\n# zz-rel-d is pinned\n',
    )
    issues = _issues_of(project, "m.py", "import zz_rel_d\n")
    rel = _related(issues[0])
    assert [r["source_path"] for r in rel] == ["a/requirements.txt", "b/pyproject.toml"], rel
    assert rel[0]["line"] == 1 and rel[0]["marker"] == "sys_platform == 'linux'", rel[0]
    assert "line" not in rel[1] and "marker" not in rel[1], rel[1]


def test_r24e_finding_and_score_do_not_change(project, tmp_path):
    """R24e. The same project with and without the other subtree's declaration: identical finding
    (pattern, severity, message, suggestion, every other evidence key) and identical score."""
    twin = tmp_path / "twin"
    for root in (project, twin):
        root.mkdir(exist_ok=True)
        _write_pyproject(root, "")
    _write(project, "tools/requirements.txt", "zz-rel-e\n")
    results = []
    for root in (project, twin):
        path = _write(root, "m.py", "import zz_rel_e\n")
        importlib.invalidate_caches()
        results.append(SlopDetector(read_only=True).analyze_file(str(path)))
    with_rel, without = ([i.to_dict() for i in r.pattern_issues] for r in results)
    assert len(with_rel) == len(without) == 1
    for d in (with_rel[0], without[0]):
        d.pop("file", None)
        (d.get("evidence") or {}).pop("related_declarations", None)
    assert with_rel == without
    assert results[0].deficit_score == results[1].deficit_score


def test_r24f_changed_declaration_is_seen(project):
    """R24f. Editing the other subtree's declaration is a new project context: the next analysis
    in the same process reports the new declaration, not a cached one."""
    _write_pyproject(project, "")
    _write(project, "tools/requirements.txt", "zz-rel-f\n")
    first = _issues_of(project, "m.py", "import zz_rel_f\n")
    _write(project, "tools/requirements.txt", "# moved\n\nzz-rel-f==2\n")
    second = _issues_of(project, "m.py", "import zz_rel_f\n")
    assert [r["line"] for r in _related(first[0])] == [1]
    assert [r["line"] for r in _related(second[0])] == [3]


def test_r24h_build_only_requirements_are_not_context(project):
    """R24h. A build requirement ([build-system] requires) of another subtree is not a runtime
    declaration: not listed."""
    _write_pyproject(project, "")
    _write(project, "b/pyproject.toml", '[build-system]\nrequires = ["zz-rel-h"]\n')
    issues = _issues_of(project, "m.py", "import zz_rel_h\n")
    assert _ids(issues) == ["phantom_import"] and _related(issues[0]) == [], issues


def test_r24i_declarations_inside_environments_are_not_context(project):
    """R24i. A requirements file inside an environment directory (venv/, site-packages/) belongs
    to an installed package, not to the project: not listed."""
    _write_pyproject(project, "")
    _write(project, "venv/lib/site-packages/dep/requirements.txt", "zz-rel-i\n")
    issues = _issues_of(project, "m.py", "import zz_rel_i\n")
    assert _ids(issues) == ["phantom_import"] and _related(issues[0]) == [], issues


# ---------------------------------------------------------------------------
# R25 (3.18, holdout 2 HOLD2-F1): inside a regular package, `import name` is absolute. A module
# `name.py` next to the file is not what it loads (only `from . import name` is), so the sibling
# is no evidence that the import is the project's own. In a script directory (no __init__.py) the
# script's directory is sys.path[0] and the sibling is what it loads.
# ---------------------------------------------------------------------------


def test_r25a_sibling_in_a_regular_package_does_not_hide_an_absolute_import(project):
    """R25a. pkg/ is a regular package with zz_r25a.py; pkg/zz_r25a.py and pkg/other.py both
    `import zz_r25a` (absolute): judged as an external import (phantom_import). Today: neither
    a finding nor an unverified row (the sibling counted as the project's module)."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    _write(project, "pkg/zz_r25a.py", "import zz_r25a\n")
    for rel in ("pkg/zz_r25a.py", "pkg/other.py"):
        issues = _issues_of(project, rel, "import zz_r25a\n")
        assert _ids(issues) == ["phantom_import"], (rel, issues)


def test_r25b_explicit_relative_import_of_a_sibling_is_not_judged(project):
    """R25b. `from . import zz_r25b` names the sibling module itself: no finding. Holds today;
    kept as a control."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    _write(project, "pkg/zz_r25b.py", "")
    assert _issues_of(project, "pkg/other.py", "from . import zz_r25b\n") == []
    assert _unverified_of(project, "pkg/other.py", "from . import zz_r25b\n") == []


def test_r25c_sibling_in_a_script_directory_is_what_it_loads(project):
    """R25c. tools/ has no __init__.py: run as a script, its directory is sys.path[0], so the
    sibling zz_r25c.py is the import's provider: no finding. Holds today; kept as a control."""
    _write_pyproject(project, "")
    _write(project, "tools/zz_r25c.py", "")
    assert _issues_of(project, "tools/run.py", "import zz_r25c\n") == []
    assert _unverified_of(project, "tools/run.py", "import zz_r25c\n") == []


def test_r25d_type_checking_import_in_a_package_is_unverified_not_hidden(project):
    """R25d. The holdout 2 shape (an ops module importing the distribution of its own name, under
    TYPE_CHECKING): unverified `type_checking_only`, not hidden by the sibling. Today: no row."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    src = "import typing\n\nif typing.TYPE_CHECKING:\n    import zz_r25d\n"
    _write(project, "pkg/zz_r25d.py", src)
    assert _issues_of(project, "pkg/zz_r25d.py", src) == []
    rows = _unverified_of(project, "pkg/zz_r25d.py", src)
    assert [(r["requested_module"], r["reason"]) for r in rows] == [
        ("zz_r25d", "type_checking_only")
    ]


def test_r25e_package_module_that_runs_as_a_script_depends_on_how_it_runs(project):
    """R25e. A module of a regular package with a `__main__` block also runs as a script
    (`python pkg/runner.py`), and then the sibling is what `import zz_r25e` loads; imported as
    part of the package, it is not. Not known statically: unverified (`depends_on_run_mode`, with
    the sibling as candidate), not a finding and not hidden. Today: hidden."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    _write(project, "pkg/zz_r25e.py", "")
    src = 'import zz_r25e\n\nif __name__ == "__main__":\n    print(zz_r25e)\n'
    assert _issues_of(project, "pkg/runner.py", src) == []
    rows = _unverified_of(project, "pkg/runner.py", src)
    assert [(r["requested_module"], r["reason"], r.get("local_candidates")) for r in rows] == [
        ("zz_r25e", "depends_on_run_mode", ["pkg/zz_r25e.py"])
    ], rows


def test_r25f_subpackage_next_to_a_package_module_is_not_its_provider(project):
    """R25f. A subpackage directory next to the module (lib/pkg/zz_r25f/) is not what an absolute
    `import zz_r25f` loads either: phantom_import. Holds today (directories already needed a
    script directory); kept as a control. Under lib/ so that only sibling discovery is tested: a
    first-level regular package holding subpackages is itself a conditional module root (E4),
    which resolves the subpackage by another rule."""
    _write_pyproject(project, "")
    _write(project, "lib/pkg/__init__.py", "")
    _write(project, "lib/pkg/zz_r25f/__init__.py", "")
    assert _ids(_issues_of(project, "lib/pkg/other.py", "import zz_r25f\n")) == ["phantom_import"]


R25H_SRC = (
    "try:\n"
    "    from .zz_helper_r25h import f\n"
    "except ImportError:\n"
    "    from zz_helper_r25h import f\n"
)


def test_r25h_relative_import_with_absolute_fallback_is_run_mode_dependent(project):
    """R25h. `try: from .x import f / except ImportError: from x import f` is written for both
    ways of running. The fallback runs when the relative import fails: when the file runs
    directly (then the sibling x.py is what it loads), or when x itself fails to import inside a
    package (then the cause is x's own import, reported in x: R25j). Unverified
    (`depends_on_run_mode`, the sibling as candidate), not a finding. Today (R13):
    phantom_import HIGH (corpus: PageIndex retrieve.py, holdout 1: cognee cognee_client.py)."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    _write(project, "pkg/zz_helper_r25h.py", "def f():\n    return 1\n")
    assert _issues_of(project, "pkg/mod.py", R25H_SRC) == []
    rows = _unverified_of(project, "pkg/mod.py", R25H_SRC)
    assert [(r["requested_module"], r["reason"], r.get("local_candidates")) for r in rows] == [
        ("zz_helper_r25h", "depends_on_run_mode", ["pkg/zz_helper_r25h.py"])
    ], rows


def test_r25h_fallback_without_a_sibling_is_still_judged(project):
    """R25h, control: the same fallback with no sibling module: nothing local could supply it in
    either way of running, so it is judged (inside the except handler: phantom_import)."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    issues = _issues_of(project, "pkg/mod.py", R25H_SRC)
    assert [(i["pattern_id"], i["line"]) for i in issues] == [("phantom_import", 4)], issues


def test_r25g_package_module_without_main_block_is_an_absolute_import(project):
    """R25g. No `__main__` block and no fallback: package membership sets the default reading
    (absolute import), so a same-named sibling does not make it local: phantom_import. Holds after
    R13; kept as a control (Inspector: the default is not proof of how it runs)."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    _write(project, "pkg/zz_helper_r25g.py", "")
    issues = _issues_of(project, "pkg/worker.py", "import zz_helper_r25g\n")
    assert _ids(issues) == ["phantom_import"], issues


def test_r25i_python_semantics_the_contract_rests_on(tmp_path):
    """R25i (ground truth, synthetic package only; never the analyzed code): `import helper` in
    pkg/worker.py with pkg/helper.py beside it loads the sibling when the file runs directly
    (its directory is sys.path[0]) and fails as `python -m pkg.worker`."""
    import subprocess

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "zz_helper_r25i.py").write_text("VALUE = 7\n", encoding="utf-8")
    (pkg / "worker.py").write_text(
        "import zz_helper_r25i\nprint(zz_helper_r25i.VALUE)\n", encoding="utf-8"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    direct = subprocess.run(
        [sys.executable, str(pkg / "worker.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    as_module = subprocess.run(
        [sys.executable, "-m", "pkg.worker"], cwd=tmp_path, capture_output=True, text=True, env=env
    )
    assert direct.returncode == 0 and direct.stdout.strip() == "7", direct.stderr
    assert as_module.returncode != 0 and "No module named 'zz_helper_r25i'" in as_module.stderr


@pytest.mark.xfail(
    strict=True,
    reason="HOLD2-F2 (open, not fixed in 3.18 R14): a first-level regular package holding "
    "subpackages is taken as a conditional module root (E4), so pkg/zz_r26/ answers an absolute "
    "`import zz_r26` that Python does not resolve (pkg/ is not on sys.path)",
)
def test_hold2_f2_e4_root_does_not_answer_an_absolute_import(project):
    """HOLD2-F2 reproduction, kept apart from HOLD2-F1 (R25f tests sibling discovery only). An
    expected failure while open: when E4 is fixed this test passes and strict xfail flags it."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    _write(project, "pkg/zz_r26/__init__.py", "")
    assert _ids(_issues_of(project, "pkg/other.py", "import zz_r26\n")) == ["phantom_import"]


def test_r25j_withheld_fallback_does_not_hide_the_failure_behind_it(project):
    """R25j. The package-mode way the fallback runs: the sibling x itself fails to import (it
    imports an undeclared package). That cause is reported where it is, in x, while the fallback
    in mod.py stays unverified: withholding the fallback hides no defect."""
    _write_pyproject(project, "")
    _write(project, "pkg/__init__.py", "")
    helper_src = "import zz_missing_inside_r25j\n\n\ndef f():\n    return 1\n"
    _write(project, "pkg/zz_helper_r25h.py", helper_src)
    inside = _issues_of(project, "pkg/zz_helper_r25h.py", helper_src)
    assert [(i["pattern_id"], i["line"]) for i in inside] == [("phantom_import", 1)], inside
    assert _issues_of(project, "pkg/mod.py", R25H_SRC) == []
    rows = _unverified_of(project, "pkg/mod.py", R25H_SRC)
    assert [(r["requested_module"], r["reason"]) for r in rows] == [
        ("zz_helper_r25h", "depends_on_run_mode")
    ], rows
