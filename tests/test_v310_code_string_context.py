"""v3.10 P3-1: analyze_code_string has no implicit file system context.

Measured: the same string scored 37.8 (SUSPICIOUS, 1 CRITICAL phantom_import)
run from a directory holding a sibling module, a local package and a
pyproject.toml, and 76.8 (CRITICAL_DEFICIT, 4 CRITICAL) run from an empty
directory: the virtual filename "<string>" resolved to the working directory,
whose siblings, project root and declarations were read as the source's own.
The ML dataset pipeline labels code through this call.

Contract:
- Without project_root the source has no location: no sibling, project root
  or declaration evidence is read. An import the environment cannot resolve
  may be local code, so it is not a finding; it is listed in
  unverified_imports (reason no_project_context, no score effect).
  Environment evidence (stdlib, installed packages, their members) still
  applies. A filename, even a real path, gives no context.
- With project_root the source is analyzed as the file project_root/filename,
  exactly as analyze_file(that path, root=project_root) would analyze it.
- analyze_file and analyze_project are unchanged.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from slop_detector.core import SlopDetector

SOURCE = textwrap.dedent(
    """
    import json
    import sibling_mod
    import localpkg
    import declared_only_pkg
    import totally_made_up_pkg
    from json import nonexistent_member
    from localpkg.sub import thing

    try:
        import optional_extra
    except ImportError:
        optional_extra = None


    def run(x):
        return sibling_mod.X + json.dumps(x)
    """
)
UNRESOLVED = [
    "sibling_mod",
    "localpkg",
    "declared_only_pkg",
    "totally_made_up_pkg",
    "localpkg.sub",
    "optional_extra",
]
LOCAL_IDS = {
    "phantom_import",
    "runtime_unavailable_dependency",
    "undeclared_optional_dependency",
    "requirements_only_dependency",
}


@pytest.fixture
def dirs(tmp_path):
    rich = tmp_path / "rich"
    (rich / "localpkg").mkdir(parents=True)
    (rich / "localpkg" / "__init__.py").write_text("", encoding="utf-8")
    (rich / "sibling_mod.py").write_text("X = 1\n", encoding="utf-8")
    (rich / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["declared-only-pkg"]\n', encoding="utf-8"
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    return rich, empty


def _dump(result) -> str:
    return json.dumps(result.to_dict(), sort_keys=True, default=str)


def test_result_does_not_depend_on_the_working_directory(dirs, monkeypatch):
    rich, empty = dirs
    monkeypatch.chdir(rich)
    from_rich = _dump(SlopDetector(read_only=True).analyze_code_string(SOURCE))
    monkeypatch.chdir(empty)
    from_empty = _dump(SlopDetector(read_only=True).analyze_code_string(SOURCE))
    assert from_rich == from_empty


def _check_virtual(result):
    assert not [i for i in result.pattern_issues if i.pattern_id in LOCAL_IDS]
    rows = {row["requested_module"]: row for row in result.unverified_imports}
    assert sorted(rows) == sorted(UNRESOLVED)
    assert all(row["reason"] == "no_project_context" for row in rows.values())
    assert all(row["score_effect"] == "none" for row in rows.values())
    assert all(row["verification_basis"] == "environment_only" for row in rows.values())
    # Environment evidence is kept: json is stdlib, its member is checked.
    members = [i for i in result.pattern_issues if i.pattern_id == "phantom_member"]
    assert [(i.line, "nonexistent_member" in i.message) for i in members] == [(7, True)]


def test_virtual_source_reads_no_local_evidence(dirs, monkeypatch):
    rich, _ = dirs
    monkeypatch.chdir(rich)
    _check_virtual(SlopDetector(read_only=True).analyze_code_string(SOURCE))


def test_a_real_path_as_filename_gives_no_context(dirs, monkeypatch):
    rich, empty = dirs
    monkeypatch.chdir(empty)
    result = SlopDetector(read_only=True).analyze_code_string(
        SOURCE, filename=str(rich / "code.py")
    )
    _check_virtual(result)


def _issues(result) -> list:
    return sorted(
        (i.pattern_id, i.severity.value, i.line, i.column, i.message) for i in result.pattern_issues
    )


def test_explicit_project_root_is_analyze_file_at_that_path(dirs, monkeypatch):
    rich, empty = dirs
    monkeypatch.chdir(empty)
    path = rich / "code.py"
    path.write_text(SOURCE, encoding="utf-8")
    from_file = SlopDetector(read_only=True).analyze_file(str(path), root=str(rich))
    path.unlink()  # the string call must not need the file
    from_string = SlopDetector(read_only=True).analyze_code_string(
        SOURCE, filename="code.py", project_root=str(rich)
    )
    assert _issues(from_string) == _issues(from_file)
    assert from_string.deficit_score == from_file.deficit_score
    assert from_string.unverified_imports == from_file.unverified_imports
    ids = {i.pattern_id for i in from_string.pattern_issues}
    assert "phantom_import" in ids and "runtime_unavailable_dependency" in ids


def test_project_root_is_the_scan_root(tmp_path, monkeypatch):
    """No project marker: only project_root says tests/ is the project's test folder."""
    root = tmp_path / "plain"
    (root / "tests").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    path = root / "tests" / "helpers.py"
    code = "def helper():\n    return 1\n"
    path.write_text(code, encoding="utf-8")
    from_file = SlopDetector(read_only=True).analyze_file(str(path), root=str(root))
    from_string = SlopDetector(read_only=True).analyze_code_string(
        code, filename="tests/helpers.py", project_root=str(root)
    )
    assert from_file.file_role == "test"
    assert from_string.file_role == from_file.file_role
