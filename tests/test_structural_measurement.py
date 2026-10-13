"""god_function length and nesting depth measure logic, not layout.

V311_P01 primary review: 30 of 60 god_function flags and 17 of 60
nested_complexity CRITICAL flags were false, almost all metric_error.
Length came from multi-line literals, SQL strings and call arguments;
depth came from try/with wrappers around trivial loops.

Length now counts Python logical lines (a statement spanning many physical
lines is one); the 50 limit matches pylint's too-many-statements default.
Depth now rises only for decisions, loops and except handlers, as in
SonarSource Cognitive Complexity; a try body or a with block is not nested.
"""

from __future__ import annotations

import ast
from pathlib import Path

from slop_detector.patterns.python_complexity import (
    DeepNestingPattern,
    GodFunctionPattern,
    NestedComplexityPattern,
)


def _check(pattern, source: str):
    return pattern.check(ast.parse(source), Path("m.py"), source)


def _branchy_head(n_ifs: int = 4) -> list[str]:
    lines = ["def target(x):", "    total = 0"]
    for i in range(n_ifs):
        lines += [f"    if x > {i}:", f"        total += {i}"]
    return lines


def test_multiline_literal_is_one_logic_line():
    lines = _branchy_head() + ["    table = {"]
    lines += [f"        'k{i}': {i}," for i in range(60)]
    lines += ["    }", "    return total, table"]
    source = "\n".join(lines) + "\n"
    assert _check(GodFunctionPattern(), source) == []


def test_multiline_call_arguments_are_one_logic_line():
    lines = _branchy_head() + ["    run("]
    lines += [f"        arg{i}={i}," for i in range(60)]
    lines += ["    )", "    return total"]
    source = "\n".join(lines) + "\n"
    assert _check(GodFunctionPattern(), source) == []


def test_many_statements_are_still_a_god_function():
    """Control: 55 one-line statements (def + 54) with complexity 5."""
    lines = _branchy_head()
    lines += [f"    total += {i}" for i in range(44)]
    lines += ["    return total"]
    source = "\n".join(lines) + "\n"
    issues = _check(GodFunctionPattern(), source)
    assert len(issues) == 1 and "55 logic lines" in issues[0].message


_WRAPPED = """
def target(paths):
    out = []
    for p in paths:
        try:
            with open(p) as f:
                with lock:
                    for line in f:
                        if line and x:
                            out.append(line)
                        elif line or y:
                            out.append(None)
        except OSError:
            pass
    return out
"""

_DEEP = """
def target(rows):
    out = []
    for r in rows:
        if r and x:
            for c in r:
                if c or y:
                    while c:
                        if c > 1:
                            out.append(c)
                        c -= 1
    return out
"""


def test_try_and_with_wrappers_do_not_nest():
    assert _check(NestedComplexityPattern(), _WRAPPED) == []
    assert _check(DeepNestingPattern(), _WRAPPED) == []


def test_real_decision_nesting_is_still_flagged():
    assert len(_check(NestedComplexityPattern(), _DEEP)) == 1
    assert len(_check(DeepNestingPattern(), _DEEP)) == 1


def test_except_handler_body_is_nested():
    """An except clause is a branch: its body sits one level deeper."""
    source = """
def target(rows):
    for r in rows:
        if r:
            try:
                pass
            except ValueError:
                for c in r:
                    if c:
                        pass
"""
    issues = _check(DeepNestingPattern(), source)
    assert len(issues) == 1 and "nesting depth 5" in issues[0].message
