"""`fp:` after one rule of `# slop-disable-next-line`: the user declares the
finding a false positive, with a reason.

- the existing suppression syntax keeps its meaning;
- the words of the reason are never rule ids (`all` in a reason must not
  suppress every rule on the line);
- a declaration is valid only for exactly one rule, a non-empty reason, and
  the next-line form; otherwise the line is a plain suppression of the rules
  before `fp:`;
- a declaration records that the user judged the finding a false positive.
  It suppresses exactly what a plain suppression of that rule suppresses, and
  it changes no score; the reason itself is never written out, only its hash.
"""

from __future__ import annotations

import hashlib
import json

from slop_detector.core import SlopDetector
from slop_detector.models import SuppressionLedgerEntry
from slop_detector.suppression_handler import SuppressionHandler

REASON = "External callback contract requires this handler"


def _one(line: str):
    directives = SuppressionHandler.parse_comment_suppressions(line)
    assert len(directives) == 1, directives
    return directives[0]


def test_the_existing_syntax_keeps_its_meaning():
    d = _one("# slop-disable-next-line bare_except")
    assert d.rules == ["bare_except"] and not d.declared_false_positive
    assert _one("# slop-disable-next-line bare_except, empty_except").rules == [
        "bare_except",
        "empty_except",
    ]
    assert _one("# slop-disable-next-line").rules == ["all"]
    assert _one("# slop-disable todo_comment").scope == "block"


def test_a_declaration_names_one_rule_and_keeps_only_the_hash_of_its_reason():
    d = _one(f"# slop-disable-next-line bare_except fp: {REASON}")
    assert d.rules == ["bare_except"]
    assert d.declared_false_positive is True
    assert d.reason_sha256 == hashlib.sha256(REASON.encode("utf-8")).hexdigest()
    assert REASON not in json.dumps(d.to_dict())
    tight = _one(f"#slop-disable-next-line bare_except FP:{REASON}")
    assert tight.declared_false_positive and tight.reason_sha256 == d.reason_sha256


def test_words_of_the_reason_are_never_rules():
    d = _one("# slop-disable-next-line bare_except fp: all callers expect todo_comment here")
    assert d.rules == ["bare_except"]
    assert SuppressionHandler.match_issue("m.py", 2, "todo_comment", [d]) is None
    assert SuppressionHandler.match_issue("m.py", 2, "bare_except", [d]) is not None


def test_an_invalid_declaration_is_a_plain_suppression_of_the_rules_before_it():
    cases = {
        "# slop-disable-next-line bare_except fp:": ["bare_except"],  # no reason
        "# slop-disable-next-line bare_except fp:    ": ["bare_except"],
        "# slop-disable-next-line bare_except empty_except fp: one reason": [
            "bare_except",
            "empty_except",
        ],
        "# slop-disable-next-line all fp: every rule here is wrong": ["all"],
        # no rule before fp: suppresses nothing, as the words did before (unknown ids)
        "# slop-disable-next-line fp: no rule named": [],
        "# slop-disable bare_except fp: block scope is not supported yet": ["bare_except"],
    }
    for line, rules in cases.items():
        d = _one(line)
        assert d.rules == rules, (line, d.rules)
        assert not d.declared_false_positive and d.reason_sha256 is None, line


def test_the_ledger_marks_a_declaration_and_leaves_plain_entries_as_they_were():
    plain = SuppressionLedgerEntry("m.py", 1, 2, "bare_except", "next_line", "bare_except")
    assert list(plain.to_dict()) == [
        "file_path",
        "directive_line",
        "suppressed_line",
        "pattern_id",
        "scope",
        "matched_rule",
        "source",
    ]
    d = _one(f"# slop-disable-next-line bare_except fp: {REASON}")
    entry = SuppressionHandler.match_issue("m.py", 2, "bare_except", [d])
    data = entry.to_dict()
    assert data["declaration"] == "user_declared_false_positive"
    assert data["reason_sha256"] == d.reason_sha256
    assert REASON not in json.dumps(data)


CODE_PLAIN = """def load(path):
    try:
        return open(path).read()
    # slop-disable-next-line bare_except
    except:
        return None
"""
CODE_DECLARED = CODE_PLAIN.replace(
    "# slop-disable-next-line bare_except", f"# slop-disable-next-line bare_except fp: {REASON}"
)


def test_a_declaration_suppresses_like_a_plain_suppression_and_moves_no_score(tmp_path):
    results = []
    for name, code in (("plain.py", CODE_PLAIN), ("declared.py", CODE_DECLARED)):
        path = tmp_path / name
        path.write_text(code, encoding="utf-8")
        results.append(SlopDetector(read_only=True).analyze_file(str(path)))
    plain, declared = results
    assert [e.pattern_id for e in plain.suppression_ledger] == ["bare_except"]
    assert [e.pattern_id for e in declared.suppression_ledger] == ["bare_except"]
    assert declared.deficit_score == plain.deficit_score
    assert [i.pattern_id for i in declared.pattern_issues] == [
        i.pattern_id for i in plain.pattern_issues
    ]
    assert declared.suppression_ledger[0].declared_false_positive is True
    assert plain.suppression_ledger[0].declared_false_positive is False
    assert REASON not in json.dumps(declared.to_dict())
