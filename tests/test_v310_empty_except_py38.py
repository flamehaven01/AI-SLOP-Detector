"""empty_except on Python 3.8: no ast.unparse.

ast.unparse is 3.9+. On 3.8 (in the CI matrix) the pattern raised on the
first typed handler, so every empty_except finding of that file was lost and
the run recorded pattern_errors (state "unmeasured"). Found by the A/B test
`test_typed_empty_handler_and_bare_handler_with_a_body`; present since v3.0.2.

Contract: without ast.unparse, findings, severities and messages are the
same as on 3.9+ (names, dotted names and tuples are written as ast.unparse
writes them), and empty_except records no pattern error. When no source text
is available, the message leaves the type out instead of inventing one.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector

SOURCE = """
    def f(x, log):
        try:
            import numpy
        except ImportError:
            pass
        try:
            return int(x)
        except ValueError:
            pass
        try:
            return int(x)
        except (
            KeyError,
            os.error,
        ):
            pass
        try:
            return int(x)
        except (ValueError,):
            pass
        try:
            return int(x)
        except get_errors():
            pass
        try:
            return float(x)
        except:
            pass
        try:
            import scipy
        except (ImportError, guard_error()):
            pass
    """

EXPECTED = [
    ("bare_except", "critical", 28),
    ("empty_except", "low", 5),
    ("empty_except", "low", 32),
    ("empty_except", "medium", 9),
    ("empty_except", "medium", 13),
    ("empty_except", "medium", 20),
    ("empty_except", "medium", 24),
]


def _analyze(tmp_path: Path):
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(SOURCE), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    found = sorted(
        (issue.pattern_id, issue.severity.value, issue.line, issue.message)
        for issue in result.pattern_issues
        if issue.pattern_id in {"bare_except", "empty_except"}
    )
    return found, result.pattern_errors


def _check(tmp_path: Path) -> dict:
    found, errors = _analyze(tmp_path)
    assert [(pid, sev, line) for pid, sev, line, _ in found] == EXPECTED
    assert not [e for e in errors if e["pattern_id"] in {"bare_except", "empty_except"}]
    return {line: message for _, _, line, message in found}


def test_messages_match_unparse_spelling(tmp_path):
    messages = _check(tmp_path)
    assert messages[5].startswith("'except ImportError: pass'")
    assert "'ValueError'" in messages[9]
    assert "'(KeyError, os.error)'" in messages[13]
    assert "'(ValueError,)'" in messages[20]
    assert "'get_errors()'" in messages[24]
    assert messages[32].startswith("'except (ImportError, guard_error()): pass'")


def test_without_ast_unparse_as_on_python_38(tmp_path, monkeypatch):
    monkeypatch.delattr(ast, "unparse", raising=False)
    test_messages_match_unparse_spelling(tmp_path)


def test_no_source_text_leaves_the_type_out(tmp_path, monkeypatch):
    monkeypatch.delattr(ast, "unparse", raising=False)
    monkeypatch.setattr(ast, "get_source_segment", lambda *args, **kwargs: None)
    messages = _check(tmp_path)
    # Names, dotted names and tuples of them need no source text.
    assert messages[5].startswith("'except ImportError: pass'")
    assert "'(KeyError, os.error)'" in messages[13]
    assert "'(ValueError,)'" in messages[20]
    assert messages[24] == "Empty handler silently discards the exception"
    assert messages[32] == "Empty optional dependency guard; verify this is intentional"


def test_multiline_expression_is_one_line():
    from slop_detector.patterns.placeholder import _exception_type_text

    source = 'try:\n    pass\nexcept get_errors(\n    "io",\n):\n    pass\n'
    handler = ast.parse(source).body[0].handlers[0]
    assert _exception_type_text(handler.type, source) == 'get_errors( "io", )'
