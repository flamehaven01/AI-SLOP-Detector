"""god_function counts logic lines; a docstring is not logic.

The message says "N logic lines (limit 50)", but the count included docstring
lines, while LDR already treats docstrings exactly like comments. In the
TOE/RExSyn dogfood, 34 of 181 god_function findings existed only because of
docstrings (e.g. spectral.py:49 reported 75 lines, 31 of them docstring).
"""

from __future__ import annotations

import ast
from pathlib import Path

from slop_detector.patterns.python_complexity import GodFunctionPattern


def _function(code_lines: int, doc_lines: int, branches: int = 4) -> str:
    """A function with `code_lines` statement lines, a `doc_lines` docstring and
    `branches` if-statements (complexity 1 + branches)."""
    lines = ["def target(x):"]
    if doc_lines:
        lines.append('    """Summary line.')
        lines.extend("    More prose." for _ in range(doc_lines - 2))
        lines.append('    """')
    lines.append("    total = 0")
    for i in range(branches):
        lines.append(f"    if x > {i}:")
        lines.append(f"        total += {i}")
    used = 1 + 1 + 2 * branches  # def line, total = 0, branches
    for i in range(code_lines - used - 1):
        lines.append(f"    total += {i}")
    lines.append("    return total")
    return "\n".join(lines) + "\n"


def _issues(source: str):
    return GodFunctionPattern().check(ast.parse(source), Path("m.py"), source)


def test_docstring_lines_do_not_make_a_god_function():
    source = _function(code_lines=45, doc_lines=20)
    assert _issues(source) == []


def test_long_code_is_still_a_god_function():
    """Control: 55 real lines, no docstring."""
    issues = _issues(_function(code_lines=55, doc_lines=0))
    assert len(issues) == 1 and "55 logic lines" in issues[0].message


def test_comment_lines_are_not_logic_either():
    """Preservation: comments were never logic lines; the rewrite keeps that."""
    source = _function(code_lines=45, doc_lines=0).replace(
        "    total = 0\n", "    total = 0\n" + "    # note\n" * 20, 1
    )
    assert _issues(source) == []


def test_reported_logic_lines_exclude_the_docstring():
    issues = _issues(_function(code_lines=55, doc_lines=12))
    assert len(issues) == 1 and "55 logic lines" in issues[0].message


def test_nested_function_docstrings_are_not_logic_either():
    inner = (
        '    def helper():\n        """'
        + "\n        text" * 10
        + '\n        """\n        return 1\n'
    )
    source = _function(code_lines=45, doc_lines=0).replace(
        "def target(x):\n", "def target(x):\n" + inner, 1
    )
    issues = _issues(source)
    assert all("target" not in issue.message for issue in issues)
