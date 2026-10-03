"""Path facts: one root-relative authority for what a path says about a file.

Only the part of a path below the root counts. A directory named `tests` or
`build` above the project is where the checkout happens to live, not a fact
about the file. The root is the scan root for a project scan, the nearest
project marker (find_project_root) for a single file, and absent otherwise; with
no root only the file name is a fact and directory facts are unknown.

Path facts say what a path is, not what the code does: `conftest.py` is a test
context file, which is not evidence that tests exist or run.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector

HOOK = "def setup_module():\n    pass\n"


@pytest.fixture
def base(tmp_path_factory):
    """A workspace with a decoy project marker ABOVE every fixture root.

    A consumer that ignores the root it was given and re-derives one from the
    nearest marker lands here, sees the outer `tests/` in the path, and fails.
    """
    ws = tmp_path_factory.mktemp("ws")
    (ws / "pyproject.toml").write_text("[project]\nname = 'decoy'\n", encoding="utf-8")
    return ws


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    return path


def _module():
    """slop_detector.path_facts, or an assertion failure (not ImportError) before it exists."""
    import importlib
    import importlib.util

    assert importlib.util.find_spec("slop_detector.path_facts"), "slop_detector.path_facts missing"
    return importlib.import_module("slop_detector.path_facts")


def _facts(path: Path, root):
    return _module().path_facts(path, root)


def _takes(func, name: str):
    """Assert a consumer accepts the path-facts input it needs (not a TypeError)."""
    import inspect

    assert name in inspect.signature(func).parameters, f"{func.__qualname__} has no {name!r}"


def _analyze(path: Path, root=None, detector=None):
    det = detector or SlopDetector(read_only=True)
    _takes(det.analyze_file, "root")
    return det.analyze_file(str(path), root=str(root) if root else None)


def _masked(analysis) -> bool:
    """A pytest no-op hook is masked only in a test file (FrameworkMasker)."""
    visible = [i.pattern_id for i in analysis.pattern_issues if i.pattern_id == "pass_placeholder"]
    masked = [m.pattern_id for m in analysis.masked_issues if m.pattern_id == "pass_placeholder"]
    assert visible or masked, "pass_placeholder did not fire; fixture is blind"
    return bool(masked) and not visible


# ---------------------------------------------------------------------------
# PathFacts: identity is decided below the root only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "tests/test_a.py",
        "tests/helpers.py",
        "test/helpers.py",
        "pkg/__tests__/x.py",
        "src/foo_test.py",
        "src/test_foo.py",
        "conftest.py",
        "tests/unit/conftest.py",
    ],
)
def test_test_identity_inside_the_root(base, rel):
    facts = _facts(base / rel, base)
    assert facts.is_test is True, rel
    assert facts.relative_path == rel


@pytest.mark.parametrize(
    "rel", ["src/service.py", "src/testing_utils.py", "src/contest.py", "latest.py"]
)
def test_source_identity_inside_the_root(base, rel):
    facts = _facts(base / rel, base)
    assert facts.is_test is False, rel
    assert facts.test_kind == "none"


def test_outer_tests_dir_does_not_make_a_source_file_a_test(base):
    root = base / "tests" / "proj"
    facts = _facts(root / "src" / "m.py", root)
    assert facts.is_test is False
    assert facts.relative_path == "src/m.py"


@pytest.mark.parametrize(
    "rel,kind",
    [
        ("tests/test_a.py", "unit"),
        ("tests/integration/test_a.py", "integration"),
        ("tests/it/test_a.py", "integration"),
        ("tests/test_integration_api.py", "integration"),
        ("tests/e2e/test_a.py", "e2e"),
        ("src/test_split_words.py", "unit"),
    ],
)
def test_test_kind(base, rel, kind):
    assert _facts(base / rel, base).test_kind == kind, rel


def test_corpus_is_a_corpus_dir_under_a_test_dir(base):
    assert _facts(base / "tests" / "corpus" / "x.py", base).is_corpus is True
    assert _facts(base / "corpus" / "x.py", base).is_corpus is False
    outer = base / "tests" / "proj"
    assert _facts(outer / "corpus" / "x.py", outer).is_corpus is False


def test_without_a_root_only_the_file_name_is_a_fact(base):
    assert _facts(base / "deep" / "test_x.py", None).is_test is True
    assert _facts(base / "deep" / "conftest.py", None).is_test is True
    unknown = _facts(base / "tests" / "helpers.py", None)
    assert unknown.is_test is None
    assert unknown.test_kind == "unknown"
    assert unknown.is_corpus is None
    assert unknown.relative_path is None


def test_exclusion_is_decided_below_the_root(base):
    assert _facts(base / "build" / "x.py", base).exclusion_reason == "directory:build"
    root = base / "build" / "proj"
    assert _facts(root / "src" / "m.py", root).exclusion_reason is None


def test_resolve_root_uses_the_scan_root_then_the_project_marker(base):
    resolve_root = _module().resolve_root

    proj = base / "tests" / "proj"
    _write(proj / "pyproject.toml", "[project]\nname = 'p'\n")
    target = _write(proj / "src" / "m.py", "x = 1\n")
    assert resolve_root(target, None) == proj
    assert resolve_root(target, base) == base


# ---------------------------------------------------------------------------
# Consumers see the same facts
# ---------------------------------------------------------------------------


def test_project_inside_an_outer_build_dir_is_scanned(base):
    """V3: every file used to be excluded because an ABOVE-root part was `build`."""
    root = base / "build" / "proj"
    _write(root / "src" / "m.py", "def f(x):\n    return x + 1\n")
    _write(root / "build" / "gen.py", "def g(x):\n    return x\n")
    result = SlopDetector(read_only=True).analyze_project(str(root))
    assert [Path(r.file_path).name for r in result.file_results] == ["m.py"]


def test_file_role_reads_root_relative_facts(base):
    from slop_detector.file_role import FileRole, classify_file

    _takes(classify_file, "facts")
    path_facts = _module().path_facts
    root = base / "tests" / "proj"
    path = _write(root / "src" / "m.py", "def f(x):\n    return x\n")
    source = path.read_text(encoding="utf-8")
    role = classify_file(str(path), source, ast.parse(source), path_facts(path, root))
    assert role is FileRole.SOURCE
    inner = _write(root / "tests" / "corpus" / "c.py", "def f(x):\n    return x\n")
    source = inner.read_text(encoding="utf-8")
    assert (
        classify_file(str(inner), source, ast.parse(source), path_facts(inner, root))
        is FileRole.CORPUS
    )


def test_masking_reads_root_relative_facts(base):
    root = base / "tests" / "proj"
    src_file = _write(root / "src" / "hooks.py", HOOK)
    test_file = _write(root / "tests" / "test_hooks.py", HOOK)
    assert _masked(_analyze(src_file, root)) is False
    assert _masked(_analyze(test_file, root)) is True


def test_project_scan_uses_the_scan_root_not_the_project_marker(base):
    root = base / "tests" / "proj"
    _write(root / "src" / "hooks.py", HOOK)
    result = SlopDetector(read_only=True).analyze_project(str(root))
    assert [Path(r.file_path).name for r in result.file_results] == ["hooks.py"]
    assert _masked(result.file_results[0]) is False


def test_single_file_uses_the_project_marker_root(base):
    proj = base / "tests" / "proj"
    _write(proj / "pyproject.toml", "[project]\nname = 'p'\n")
    src_file = _write(proj / "src" / "hooks.py", HOOK)
    assert _masked(_analyze(src_file)) is False


def test_context_jargon_test_evidence_reads_root_relative_facts(base):
    root = base / "tests" / "my_test_project"
    path = _write(
        root / "src" / "parse.py",
        '''
        def parse(value):
            """Fixture.

            Robust integer parser.
            """
            if not isinstance(value, str):
                raise TypeError("value must be a str")
            try:
                return int(value)
            except ValueError:
                return None
        ''',
    )
    analysis = _analyze(path, root)
    claim = [e for e in analysis.context_jargon.evidence_details if e.jargon == "robust"][0]
    assert "tests_unit" not in claim.found_evidence


def test_markdown_test_stats_read_root_relative_facts(base):
    from slop_detector.renderer_markdown import _collect_test_evidence_stats

    root = base / "tests" / "proj"
    src_file = _write(root / "src" / "m.py", "def f(x):\n    return x\n")
    test_file = _write(root / "it" / "test_flow.py", "def test_flow():\n    assert True\n")
    _takes(_collect_test_evidence_stats, "project_root")
    results = [_analyze(p, root) for p in (src_file, test_file)]
    stats = _collect_test_evidence_stats(results, project_root=root)
    assert stats["total_test_files"] == 1
    assert stats["integration_test_files"] == 1


# ---------------------------------------------------------------------------
# Cache: facts depend on the root, so the root context is part of the key
# ---------------------------------------------------------------------------


def test_cache_does_not_reuse_a_result_across_root_contexts(base):
    from slop_detector.analysis_cache import FileAnalysisCache

    outer = base / "tests" / "proj"
    path = _write(outer / "src" / "hooks.py", HOOK)
    det = SlopDetector()
    det._analysis_cache = FileAnalysisCache(base / "cache.db")
    assert _masked(_analyze(path, base, det)) is True
    assert _masked(_analyze(path, outer, det)) is False
    assert _masked(_analyze(path, base, det)) is True


def test_cache_version_moves_with_root_relative_facts():
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION

    assert CACHE_ENGINE_VERSION not in {f"analysis-cache-v{n}" for n in (11, 12, 13, 14)}
