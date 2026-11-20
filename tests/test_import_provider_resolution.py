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
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pytest

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
    still judged. Today: phantom_import for all three."""
    _write_pyproject(project, "")
    issues = _issues_of(project, "m.py", SYS_PATH_SRC)
    assert sorted((i["pattern_id"], i["line"]) for i in issues) == [
        ("phantom_import", 2),
        ("phantom_import", 6),
    ], issues
    rows = _unverified_of(project, "m.py", SYS_PATH_SRC)
    assert [(r["requested_module"], r["reason"]) for r in rows] == [
        ("zz_after_insert", "sys_path_modified")
    ], rows


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
