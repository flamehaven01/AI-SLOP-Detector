"""Cross-language method patterns fire only on a receiver proven to be a built-in.

`js_push`, `java_equals`, `ruby_each`, and `csharp_length` used to fire on any
method or attribute of that name, so `self.pool.push(x)` (a real API) was
reported and its line rewritten by autofix. On 9 codebases both `js_push` hits
were such false positives. Now the receiver must be a built-in literal, or a
name bound exactly once in the same scope, at the top of that scope and before
the use, to a built-in literal or an unshadowed built-in constructor. Calling
`.push` on a list always raises AttributeError, so what remains is a definite
foreign-language idiom. Anything not proven is not a finding.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import List

import pytest

from slop_detector.patterns.cross_language import (
    CSharpLengthPattern,
    GoPrintPattern,
    JavaEqualsPattern,
    JavaScriptPushPattern,
    PHPStrlenPattern,
    RubyEachPattern,
)


def _ids(source: str) -> List[str]:
    source = textwrap.dedent(source)
    tree = ast.parse(source)
    patterns = [
        JavaScriptPushPattern(),
        JavaEqualsPattern(),
        RubyEachPattern(),
        CSharpLengthPattern(),
        GoPrintPattern(),
        PHPStrlenPattern(),
    ]
    return sorted(i.pattern_id for p in patterns for i in p.check(tree, Path("m.py"), source))


# ---------------------------------------------------------------------------
# definite positives
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,expected",
    [
        ("def f(x):\n    items = []\n    items.push(x)\n", ["js_push"]),
        ("def f(other):\n    text = str()\n    return text.equals(other)\n", ["java_equals"]),
        ("def f():\n    names = {'a', 'b'}\n    names.each(print)\n", ["ruby_each"]),
        ("def f():\n    word = 'abc'\n    return word.Length\n", ["csharp_length"]),
        ("def f(x):\n    [].push(x)\n", ["js_push"]),
        ("items = list()\nitems.push(1)\n", ["js_push"]),
        ("def f(x):\n    items = []\n    if x:\n        items.push(x)\n", ["js_push"]),
        ("def f():\n    pairs: dict = {}\n    pairs.each(print)\n", ["ruby_each"]),
    ],
    ids=[
        "list-literal",
        "str-constructor",
        "set-literal",
        "str-constant-attribute",
        "direct-literal",
        "module-scope",
        "use-inside-branch-after-binding",
        "annotated-binding",
    ],
)
def test_a_proven_builtin_receiver_is_reported(source, expected):
    assert _ids(source) == expected


# ---------------------------------------------------------------------------
# not proven: not a finding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "class Pool:\n    def push(self, x):\n        return x\n\n    def run(self):\n        self.push(1)\n",
        "def f(self, x):\n    self.pool.push(x)\n",
        "def f(items, x):\n    items.push(x)\n",
        "import pandas as pd\n\n\ndef f(a, b):\n    return pd.DataFrame(a).equals(b)\n",
        "def f(df, other):\n    return df.equals(other)\n",
        "def f(x: list):\n    x.push(1)\n",
        "def f(factory):\n    x = factory()\n    x.push(1)\n",
        "list = dict\n\n\ndef f():\n    x = list()\n    x.push(1)\n",
        "def f(factory):\n    x = []\n    x = factory()\n    x.push(1)\n",
        "def f(cond, custom):\n    if cond:\n        x = []\n    else:\n        x = custom\n    x.push(1)\n",
        "def f(factory):\n    x = []\n    x.push(1)\n    x = factory()\n",
        "def f(x):\n    x.push(1)\n    x = []\n",
        "def f():\n    x = []\n\n    def g():\n        x.push(1)\n\n    return g\n",
        "def f():\n    global x\n    x = []\n    x.push(1)\n",
        "def f(rows):\n    for x in rows:\n        x.push(1)\n",
        "def f(cond):\n    if cond:\n        x = []\n    x.push(1)\n",
        "def f():\n    x.push(1)\n    x = []\n",
    ],
    ids=[
        "own-method",
        "attribute-receiver",
        "parameter",
        "pandas-equals-on-call",
        "pandas-equals-on-parameter",
        "annotation-only",
        "factory-return",
        "constructor-shadowed",
        "rebound-before-use",
        "branch-ambiguity",
        "rebound-after-use",
        "bound-after-use",
        "use-in-nested-scope",
        "global-name",
        "loop-target",
        "bound-only-in-branch",
        "used-before-its-only-binding",
    ],
)
def test_an_unproven_receiver_is_not_reported(source):
    assert _ids(source) == []


# ---------------------------------------------------------------------------
# unchanged rules and public surface
# ---------------------------------------------------------------------------


def test_go_println_and_php_strlen_are_unchanged():
    source = "import fmt\n\n\ndef f(text):\n    fmt.Println(text)\n    return strlen(text)\n"
    assert _ids(source) == ["go_println", "php_strlen"]


def test_the_six_pattern_ids_stay_public():
    from slop_detector.patterns import get_all_patterns

    ids = {p.id for p in get_all_patterns()}
    assert {
        "js_push",
        "java_equals",
        "ruby_each",
        "csharp_length",
        "go_println",
        "php_strlen",
    } <= ids


# ---------------------------------------------------------------------------
# autofix rewrites only the proven occurrence
# ---------------------------------------------------------------------------


def _fix(pattern, source: str):
    from slop_detector.autofix.engine import _PATCHERS

    tree = ast.parse(source)
    issues = pattern.check(tree, Path("m.py"), source)
    assert len(issues) == 1, issues
    lines = source.splitlines()
    return _PATCHERS[pattern.id](lines, issues[0].line - 1, issues[0])


def test_push_fix_rewrites_only_the_reported_call():
    source = "def f(pool, x):\n    items = []\n    pool.push(x); items.push(x)\n"
    change = _fix(JavaScriptPushPattern(), source)
    assert change.replacement == "    pool.push(x); items.append(x)"


def test_length_fix_rewrites_only_the_reported_attribute():
    source = "def f(arr):\n    word = 'abc'\n    return arr.Length + word.Length\n"
    change = _fix(CSharpLengthPattern(), source)
    assert change.replacement == "    return arr.Length + len(word)"
