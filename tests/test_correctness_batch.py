"""Independent correctness fixes V5, V6, V11, V12.

V5a Logic density: docstrings are prose, treated exactly like comments (in
    neither the lines nor the logic), so a docstring cannot change logic
    density; a docstring-only __init__.py is a packaging init.
V5b An expression statement such as a call is implementation: only a leading
    docstring, pass, `...`, and `return None` make a function empty.
V6  A pattern that raises leaves a trace in the result (`pattern_errors`, state
    `unmeasured`); it is not a finding and does not change the score.
V11 Changed-code attribution compares one representation, the project-relative
    path: a changed `pkg_a/util.py` does not make `pkg_b/util.py`
    introduced, and git paths are taken relative to the project, not the repo.
V12 If known_deps.yaml is missing, unreadable, or not shaped as expected, the
    hallucination-dependency check is unmeasured, never PASS; analysis goes on.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector


@pytest.fixture
def root(tmp_path_factory):
    return tmp_path_factory.mktemp("proj")


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    return path


def _analyze(path: Path):
    return SlopDetector(read_only=True).analyze_file(str(path))


# ---------------------------------------------------------------------------
# V5a: docstrings are prose, exactly like comments (out of lines and logic)
# V5b: an expression statement such as a call is implementation, not emptiness
# ---------------------------------------------------------------------------

BODY = "def f(x):\n    y = x + 1\n    return y\n\n\ndef g(x):\n    return x * 2\n"


def _with_docstring(lines: int) -> str:
    doc = '"""Module.\n\n' + "".join(f"Detail line {i}.\n" for i in range(lines)) + '"""\n\n'
    return doc + BODY


def _ldr(root: Path, name: str, source: str):
    return _analyze(_write(root / name, source))


def test_a_longer_docstring_leaves_logic_density_unchanged(root):
    short = _ldr(root, "short.py", _with_docstring(1))
    long = _ldr(root, "long.py", _with_docstring(30))
    assert (long.ldr.total_lines, long.ldr.logic_lines) == (
        short.ldr.total_lines,
        short.ldr.logic_lines,
    )
    assert long.ldr.ldr_score == short.ldr.ldr_score
    assert long.deficit_score == short.deficit_score


def test_a_function_docstring_counts_in_neither_lines_nor_logic(root):
    source = 'def f(x):\n    """Doc.\n\n    More.\n    """\n    return x\n'
    ldr = _ldr(root, "m.py", source).ldr
    assert (ldr.total_lines, ldr.logic_lines) == (2, 2)


def test_module_class_and_function_docstrings_are_all_prose(root):
    source = (
        '"""Module doc."""\n\n\nclass C:\n    """Class doc.\n\n    More.\n    """\n\n'
        '    def m(self):\n        """Method doc."""\n        return 1\n'
    )
    ldr = _ldr(root, "m.py", source).ldr
    assert (ldr.total_lines, ldr.logic_lines) == (3, 3)


def test_a_docstring_only_init_is_a_packaging_init(root):
    ldr = _ldr(root, "pkg/__init__.py", '"""Package doc.\n\nMore.\n"""\n').ldr
    assert ldr.is_packaging_init is True
    assert ldr.ldr_score == 1.0


def test_a_stub_file_does_not_improve_with_a_long_docstring(root):
    stubs = "def f():\n    pass\n\n\ndef g():\n    pass\n"
    doc = '"""' + "\n".join(f"Prose line {i}." for i in range(30)) + '\n"""\n'
    plain = _ldr(root, "plain.py", stubs)
    documented = _ldr(root, "documented.py", doc + stubs)
    assert documented.ldr.logic_lines == 0
    assert documented.deficit_score == plain.deficit_score


def test_a_call_only_function_is_not_empty(root):
    source = "def configure(c):\n    c.add(1)\n    c.add(2)\n"
    ldr = _ldr(root, "m.py", source).ldr
    assert ldr.logic_lines == ldr.total_lines == 3


def test_a_docstring_and_calls_function_is_not_empty(root):
    source = 'def configure(c):\n    """Register markers."""\n    c.add(1)\n    c.add(2)\n'
    ldr = _ldr(root, "m.py", source).ldr
    assert ldr.logic_lines == ldr.total_lines == 3


@pytest.mark.parametrize("stub", ["pass", "...", "return None", "return"])
def test_pass_ellipsis_and_bare_return_stay_empty(root, stub):
    source = f'def f():\n    """Doc."""\n    {stub}\n\n\ndef g(x):\n    return x + 1\n'
    ldr = _ldr(root, "m.py", source).ldr
    assert (ldr.total_lines, ldr.logic_lines) == (4, 2), stub


def test_a_string_that_is_not_a_docstring_is_still_code(root):
    source = 'QUERY = """\nselect id\nfrom t\n"""\n\n\ndef run(db):\n    return db.execute(QUERY)\n'
    ldr = _ldr(root, "q.py", source).ldr
    assert ldr.logic_lines == ldr.total_lines


# ---------------------------------------------------------------------------
# V6: a failing pattern leaves a trace
# ---------------------------------------------------------------------------


class _Boom:
    id = "boom"

    def check(self, tree, file, content):
        raise RuntimeError("pattern bug")


def test_a_failing_pattern_leaves_a_trace_and_no_finding(root):
    path = _write(root / "m.py", "def f(x):\n    return x + 1\n")
    det = SlopDetector(read_only=True)
    baseline = det.analyze_file(str(path))
    det.pattern_registry._patterns["boom"] = _Boom()
    result = det.analyze_file(str(path))
    errors = getattr(result, "pattern_errors", None)
    assert errors == [{"pattern_id": "boom", "error_type": "RuntimeError", "state": "unmeasured"}]
    assert result.to_dict().get("pattern_errors") == errors
    assert all(issue.pattern_id != "boom" for issue in result.pattern_issues)
    assert result.deficit_score == baseline.deficit_score


def test_pattern_errors_survive_the_cache(root):
    from slop_detector.analysis_cache import deserialize_file_analysis, serialize_file_analysis

    path = _write(root / "m.py", "def f(x):\n    return x + 1\n")
    det = SlopDetector(read_only=True)
    det.pattern_registry._patterns["boom"] = _Boom()
    result = det.analyze_file(str(path))
    restored = deserialize_file_analysis(serialize_file_analysis(result))
    assert getattr(result, "pattern_errors", None), "pattern_errors missing"
    assert getattr(restored, "pattern_errors", None) == result.pattern_errors


# ---------------------------------------------------------------------------
# V11: changed-code attribution uses one path representation
# ---------------------------------------------------------------------------


def _project_with_two_same_named_files(root: Path):
    _write(root / "pkg_a" / "util.py", "def f(x):\n    return x + 1\n")
    _write(root / "pkg_b" / "util.py", "def g(x):\n    return x * 2\n")
    result = SlopDetector(read_only=True).analyze_project(str(root))
    assert len(result.file_results) == 2, "fixture is blind"
    return result


def _introduced(result, root: Path, changed):
    from slop_detector.operations_payloads import build_audit_payload

    payload = build_audit_payload(result, root, get_changed_files_func=lambda p, b: list(changed))
    return payload["attribution"]["introduced_files"]


def test_a_same_named_file_elsewhere_is_not_introduced(root):
    result = _project_with_two_same_named_files(root)
    assert _introduced(result, root, ["pkg_a/util.py"]) == ["pkg_a/util.py"]


def test_absolute_changed_paths_are_normalized_to_the_project(root):
    result = _project_with_two_same_named_files(root)
    changed = [str((root / "pkg_b" / "util.py").resolve())]
    assert _introduced(result, root, changed) == ["pkg_b/util.py"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_changed_files_are_relative_to_the_project_not_the_repository(root):
    from slop_detector.operations_payloads import get_changed_files

    def git(*args):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    _write(root / "src" / "x.py", "X = 1\n")
    git("init", "-q")
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init")
    _write(root / "src" / "x.py", "X = 2\n")
    assert get_changed_files(root / "src") == ["x.py"]


# ---------------------------------------------------------------------------
# V12: known_deps that cannot be loaded is unmeasured, never PASS
# ---------------------------------------------------------------------------


def _deps_module():
    module = importlib.import_module("slop_detector.metrics.hallucination_deps")
    assert hasattr(module, "KNOWN_DEPS_PATH"), "hallucination_deps.KNOWN_DEPS_PATH missing"
    return module


UNUSED_TORCH = "import torch\n\n\ndef f(x):\n    return x\n"


@pytest.mark.parametrize(
    "content",
    [None, "categories: [unterminated\n", "categories:\n  - torch\n", "- just a list\n"],
    ids=["missing", "unparseable", "categories-not-a-mapping", "not-a-mapping"],
)
def test_unloadable_known_deps_is_unmeasured_not_pass(root, monkeypatch, content):
    module = _deps_module()
    deps = root / "known_deps.yaml"
    if content is not None:
        deps.write_text(content, encoding="utf-8")
    monkeypatch.setattr(module, "KNOWN_DEPS_PATH", deps)
    result = _analyze(_write(root / "m.py", UNUSED_TORCH))
    deps_result = result.hallucination_deps
    assert deps_result.status != "PASS"
    assert getattr(deps_result, "evidence_state", None) == "unmeasured"
    assert result.to_dict()["hallucination_deps"].get("evidence_state") == "unmeasured"


def test_loaded_known_deps_is_measured(root):
    _deps_module()
    result = _analyze(_write(root / "m.py", UNUSED_TORCH))
    deps_result = result.hallucination_deps
    assert getattr(deps_result, "evidence_state", None) == "measured"
    assert deps_result.total_hallucinated >= 1


def test_cached_results_from_before_the_batch_are_not_reused():
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION

    assert CACHE_ENGINE_VERSION not in {f"analysis-cache-v{n}" for n in range(11, 18)}
