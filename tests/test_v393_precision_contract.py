"""v3.9.3 precision contract: elif nesting, typing.overload, no executable code.

Found by the cross-domain precision study on the published 3.9.2:

- An `elif` is an `If` in the parent's `orelse` at the same column; the nesting
  depth added a level for each one, so a flat dispatch chain (langdetect
  `NGram.normalize`) was reported at depth 11 (real depth 2). 1,158 of 3,291
  nesting findings in 11 Python repositories existed only through `elif`.
- An `@overload` signature (a typing construct whose body is `...` by
  definition) was reported as an unimplemented placeholder.
- A module with no executable code (0 bytes, whitespace, comments, or only a
  docstring) got LDR 0.0 and a deficit of 97.49 (critical_deficit), and failed
  the hard gate, although nothing in it was measured.

Controls pin what must not change: an `elif` still counts as a branch for
complexity, real nesting (including `else:` followed by `if`) still counts, a
plain `...` body is still a placeholder, `pass` / `...` / `raise
NotImplementedError` are code, an empty `__init__.py` keeps its packaging
semantics, and a syntax error stays a parse error.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from slop_detector.ci_gate import CIGate, GateMode
from slop_detector.core import SlopDetector
from slop_detector.patterns.placeholder import EllipsisPlaceholderPattern
from slop_detector.patterns.python_complexity import (
    DeepNestingPattern,
    NestedComplexityPattern,
    _cyclomatic_complexity,
)


def _ids(pattern, source: str):
    return [i.pattern_id for i in pattern.check(ast.parse(source), Path("m.py"), source)]


def _flat_chain(branches: int) -> str:
    lines = ["def dispatch(kind):", "    if kind == 0:", "        return 0"]
    for i in range(1, branches):
        lines += [f"    elif kind == {i}:", f"        return {i}"]
    lines.append("    return -1")
    return "\n".join(lines) + "\n"


# --- elif ---------------------------------------------------------------------


def test_flat_elif_chain_is_not_deep_nesting():
    source = _flat_chain(11)
    assert _ids(DeepNestingPattern(), source) == []
    assert _ids(NestedComplexityPattern(), source) == []


ELIF_THEN_NESTING = """\
def route(kind, rows):
    if kind == 0:
        return 0
    elif kind == 1:
        return 1
    elif kind == 2:
        for row in rows:
            if row:
                for cell in row:
                    print(cell)
    return -1
"""


def test_elif_does_not_add_to_nesting_inside_a_branch():
    """Real depth 4 (if, for, if, for); counting each elif would make it 6."""
    assert _ids(DeepNestingPattern(), ELIF_THEN_NESTING) == []


def test_elif_still_counts_as_a_branch():
    """Control: complexity keeps one decision per elif."""
    func = ast.parse(_flat_chain(11)).body[0]
    assert _cyclomatic_complexity(func) >= 11


REAL_NESTING = """\
def walk(rows):
    for row in rows:
        if row:
            for cell in row:
                if cell:
                    while cell:
                        if cell > 1:
                            cell -= 1
                        else:
                            break
    return rows
"""


def test_real_nesting_is_still_deep():
    """Control."""
    assert _ids(DeepNestingPattern(), REAL_NESTING) == ["deep_nesting"]
    assert _ids(NestedComplexityPattern(), REAL_NESTING) == ["nested_complexity"]


ELSE_THEN_IF = """\
def pick(a, b, c, d, e):
    if a:
        return 1
    else:
        if b:
            return 2
        else:
            if c:
                return 3
            else:
                if d:
                    return 4
                else:
                    if e:
                        return 5
    return 0
"""


def test_else_followed_by_if_is_real_nesting():
    """Control: only the `elif` spelling is flat; an `if` indented under
    `else:` is a nested block."""
    assert _ids(DeepNestingPattern(), ELSE_THEN_IF) == ["deep_nesting"]


# --- typing.overload ----------------------------------------------------------

OVERLOADS = """\
from typing import overload


@overload
def parse(value: int) -> int: ...


@overload
def parse(value: str) -> str: ...


def parse(value):
    return value
"""

TYPING_DOT_OVERLOAD = """\
import typing


class Table:
    @typing.overload
    def get(self, key: int) -> int:
        ...

    @typing.overload
    def get(self, key: str) -> str:
        ...

    def get(self, key):
        return key
"""


def test_overload_signatures_are_not_placeholders():
    assert _ids(EllipsisPlaceholderPattern(), OVERLOADS) == []


def test_typing_dot_overload_methods_are_not_placeholders():
    assert _ids(EllipsisPlaceholderPattern(), TYPING_DOT_OVERLOAD) == []


def test_plain_ellipsis_body_is_still_a_placeholder():
    """Control."""
    assert _ids(EllipsisPlaceholderPattern(), "def todo(x):\n    ...\n") == ["ellipsis_placeholder"]


def test_other_decorators_do_not_exempt_an_ellipsis_body():
    """Control: the exemption is `overload` only (other decorators are v3.10)."""
    source = "class C:\n    @staticmethod\n    def todo():\n        ...\n"
    assert _ids(EllipsisPlaceholderPattern(), source) == ["ellipsis_placeholder"]


CUSTOM_OVERLOAD = """\
class Custom:
    def overload(self, fn):
        return fn


custom = Custom()


@custom.overload
def todo():
    ...
"""


def test_a_non_typing_overload_attribute_does_not_exempt():
    """Control: only `overload` and `typing.overload` mark a typing signature;
    another object's `.overload` (or an aliased `typing`) is v3.10 context."""
    assert _ids(EllipsisPlaceholderPattern(), CUSTOM_OVERLOAD) == ["ellipsis_placeholder"]


# --- no executable code -------------------------------------------------------

NO_CODE = {
    "empty.py": "",
    "blank.py": "\n   \n\n",
    "comment_only.py": "# reserved\n# nothing here yet\n",
    "docstring_only.py": '"""Module reserved for future hooks."""\n',
}


def _analyze(path: Path):
    return SlopDetector(read_only=True).analyze_file(str(path))


@pytest.mark.parametrize("name", sorted(NO_CODE))
def test_module_without_code_is_not_applicable(tmp_path, name):
    path = tmp_path / name
    path.write_text(NO_CODE[name], encoding="utf-8")
    result = _analyze(path)
    assert "no_executable_code" in result.flags
    assert {"ldr", "ddc"} <= set(result.skipped_metrics)
    assert result.deficit_score < 30
    assert result.status.value == "clean"


def test_hard_gate_does_not_fail_on_absent_code(tmp_path):
    path = tmp_path / "empty.py"
    path.write_text("", encoding="utf-8")
    verdict = CIGate(mode=GateMode.HARD).evaluate(_analyze(path))
    assert not verdict.should_fail_build


def test_patterns_still_run_on_a_module_without_code(tmp_path):
    """Only LDR and DDC stop applying; findings in comments are still reported."""
    path = tmp_path / "comment_only.py"
    path.write_text("# TODO: implement the reader\n", encoding="utf-8")
    result = _analyze(path)
    assert "no_executable_code" in result.flags
    assert any(issue.pattern_id == "todo_comment" for issue in result.pattern_issues)


@pytest.mark.parametrize(
    "source",
    ["X = 1\n", "def f():\n    pass\n", "...\n", "raise NotImplementedError\n"],
)
def test_placeholders_and_code_are_not_no_code(tmp_path, source):
    """Control: `pass`, `...` and `raise NotImplementedError` are lines of code."""
    path = tmp_path / "m.py"
    path.write_text(source, encoding="utf-8")
    assert "no_executable_code" not in _analyze(path).flags


def test_pass_placeholder_is_still_reported(tmp_path):
    """Control."""
    path = tmp_path / "m.py"
    path.write_text("def f():\n    pass\n", encoding="utf-8")
    assert any(i.pattern_id == "pass_placeholder" for i in _analyze(path).pattern_issues)


def test_empty_init_keeps_packaging_semantics(tmp_path):
    """Control."""
    path = tmp_path / "__init__.py"
    path.write_text("", encoding="utf-8")
    result = _analyze(path)
    assert result.ldr.is_packaging_init
    assert result.deficit_score == 0.0


def test_syntax_error_stays_a_parse_error(tmp_path):
    """Control: a file that cannot be parsed is not a module without code."""
    path = tmp_path / "broken.py"
    path.write_text("def f(:\n", encoding="utf-8")
    result = _analyze(path)
    assert "parse_error" in result.flags
    assert "no_executable_code" not in result.flags


GOOD = "def add(a, b):\n    total = a + b\n    return total\n"


def test_module_without_code_does_not_change_project_ldr(tmp_path):
    only = tmp_path / "only"
    only.mkdir()
    (only / "good.py").write_text(GOOD, encoding="utf-8")
    both = tmp_path / "both"
    both.mkdir()
    (both / "good.py").write_text(GOOD, encoding="utf-8")
    (both / "empty.py").write_text("", encoding="utf-8")
    detector = SlopDetector(read_only=True)
    reference = detector.analyze_project(str(only))
    result = detector.analyze_project(str(both))
    assert result.avg_ldr == reference.avg_ldr
    assert result.overall_status.value == "clean"
    assert not CIGate(mode=GateMode.HARD).evaluate(result).should_fail_build
