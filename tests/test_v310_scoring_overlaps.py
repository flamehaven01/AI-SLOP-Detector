"""v3.10 scoring study A/B: one finding per defect, CRITICAL only with evidence.

Measured on 18 repositories (rescored with the canonical scoring function):
- A: `except: pass` was reported twice as CRITICAL (bare_except and
  empty_except on the same handler; 6 handlers in 5 files);
- B: mutable_default_arg was CRITICAL ("shared state bug") without any
  mutation of the default (stage-1 sample: 4 of 4 overstated).

Contract:
- A bare handler is bare_except's; empty_except reports typed handlers only,
  and bare_except says when the bare handler only passes;
- mutable_default_arg is CRITICAL when the function mutates the default
  (method call that mutates, item/attribute assignment, augmented
  assignment) or lets it escape (return, yield, alias); otherwise HIGH.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector


def _findings(tmp_path: Path, source: str, ids) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted(
        (issue.pattern_id, issue.severity.value, issue.line, issue.message)
        for issue in result.pattern_issues
        if issue.pattern_id in ids
    )


EXCEPT_IDS = {"bare_except", "empty_except"}


def test_bare_except_pass_is_one_finding(tmp_path):
    source = """
        def f(x):
            try:
                return int(x)
            except:
                pass
        """
    found = _findings(tmp_path, source, EXCEPT_IDS)
    assert [(pid, sev, line) for pid, sev, line, _ in found] == [("bare_except", "critical", 5)]
    assert "pass" in found[0][3]


def test_typed_empty_handler_and_bare_handler_with_a_body(tmp_path):
    source = """
        def f(x, log):
            try:
                return int(x)
            except ValueError:
                pass
            try:
                return float(x)
            except:
                log(x)
        """
    found = _findings(tmp_path, source, EXCEPT_IDS)
    assert [(pid, sev, line) for pid, sev, line, _ in found] == [
        ("bare_except", "critical", 9),
        ("empty_except", "medium", 5),
    ]
    assert "pass" not in found[0][3]


MUTABLE = {"mutable_default_arg"}


def test_mutable_default_is_critical_only_with_mutation_or_escape(tmp_path):
    source = """
        def appends(x, acc=[]):
            acc.append(x)
            return len(acc)

        def returns(acc=[]):
            return acc

        def augments(x, acc=[]):
            acc += [x]
            return len(acc)

        def stores(k, v, cache={}):
            cache[k] = v
            return v

        def aliases(acc=[]):
            alias = acc
            return len(alias)

        def reads(key, options={}):
            return options.get(key)

        def iterates(items=[]):
            return [i * 2 for i in items]
        """
    found = [(sev, line) for _, sev, line, _ in _findings(tmp_path, source, MUTABLE)]
    assert found == [
        ("critical", 2),
        ("critical", 6),
        ("critical", 9),
        ("critical", 13),
        ("critical", 17),
        ("high", 21),
        ("high", 24),
    ]
