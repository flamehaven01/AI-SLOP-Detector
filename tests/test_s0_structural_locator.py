"""D-S0-1 (FH-S0-P0-INDEPENDENT-REVIEW): repeated identical code is told apart
by a structural locator, the address of the statement in the analyzed AST.

An item carries a semantic_key (rule, path, symbol, subject, the text of its
own line) and a locator (the statement path inside the symbol); its id is the
pair. The locator is an address in one source snapshot, not a permanent name:
a moved finding keeps its semantic_key, and prove_state() never reads a
changed id as a fix.
"""

import pytest

import slop_detector.ai_report as ai_report
from slop_detector.ai_report import AiReportInvalid, build_records, prove_state
from slop_detector.ai_report_md import render_ai_report_md
from slop_detector.core import SlopDetector
from slop_detector.report_view import build_report_view

# The corpus shapes: one import guarded four times, one handler repeated, one
# comment repeated before different methods of a class.
GUARDS = '''
def load():
    try:
        import nonexistent_opt_pkg
    except ImportError:
        nonexistent_opt_pkg = None
    try:
        import nonexistent_opt_pkg
    except ImportError:
        nonexistent_opt_pkg = None
    return nonexistent_opt_pkg
'''
HANDLERS = '''
def run(jobs, log):
    try:
        jobs.first()
    except Exception:
        pass
    try:
        jobs.second()
    except Exception:
        pass
    try:
        jobs.third()
    except Exception:
        pass
    log("done")
'''
CLASS_TODOS = '''
class Policy:
    # TODO: unify the Any type
    def on_hit(self, key):
        return key

    # TODO: unify the Any type
    def on_put(self, key):
        return key
'''


def _write(tmp_path, name, text):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    path = tmp_path / "pkg" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _records(tmp_path):
    return build_records(build_report_view(SlopDetector(read_only=True).analyze_project(str(tmp_path))))[1:]


def _rule(records, rule):
    return [r for r in records if r["rule"] == rule]


@pytest.mark.parametrize("name, source, rule, count", [
    ("guards.py", GUARDS, "undeclared_optional_dependency", 2),
    ("handlers.py", HANDLERS, "empty_except", 3),
    ("policy.py", CLASS_TODOS, "todo_comment", 2),
])
def test_repeated_identical_code_is_several_items_not_a_refused_report(tmp_path, name, source, rule, count):
    _write(tmp_path, name, source)
    items = _rule(_records(tmp_path), rule)
    assert len(items) == count
    assert len({r["id"] for r in items}) == count  # told apart by the locator
    assert len({r["semantic_key"] for r in items}) == 1  # one finding shape
    assert len({r["locator"] for r in items}) == count


def test_a_blank_or_comment_line_keeps_every_id(tmp_path):
    path = _write(tmp_path, "handlers.py", HANDLERS)
    before = {r["id"] for r in _rule(_records(tmp_path), "empty_except")}
    # right above the reported except line: its neighbour text changes, its AST does not
    edited = HANDLERS.replace("        jobs.second()\n    except", "        jobs.second()\n        # a note\n\n    except")
    path.write_text(edited, encoding="utf-8")
    assert {r["id"] for r in _rule(_records(tmp_path), "empty_except")} == before


def test_fixing_one_copy_leaves_the_other_ids_and_is_a_fix_candidate(tmp_path):
    path = _write(tmp_path, "handlers.py", HANDLERS)
    before = _rule(_records(tmp_path), "empty_except")
    fixed = HANDLERS.replace("        jobs.second()\n    except Exception:\n        pass\n",
                             "        jobs.second()\n    except Exception:\n        log(\"second failed\")\n")
    path.write_text(fixed, encoding="utf-8")
    after = _records(tmp_path)
    gone = [r for r in before if r["id"] not in {a["id"] for a in after}]
    assert len(gone) == 1 and len(_rule(after, "empty_except")) == 2
    assert prove_state(before, after, gone[0]["id"], symbol_present=True) == "FIXED_CANDIDATE"
    kept = [r for r in before if r is not gone[0]]
    assert all(prove_state(before, after, r["id"], symbol_present=True) == "PERSISTS" for r in kept)


def test_a_moved_finding_is_never_read_as_fixed(tmp_path):
    path = _write(tmp_path, "handlers.py", HANDLERS)
    before = _rule(_records(tmp_path), "empty_except")
    # a new sibling statement in front shifts every locator: ids change, the findings stay
    path.write_text(HANDLERS.replace("def run(jobs, log):\n", "def run(jobs, log):\n    jobs.prepare()\n"),
                    encoding="utf-8")
    after = _records(tmp_path)
    moved = [r for r in before if r["id"] not in {a["id"] for a in after}]
    assert moved  # the address changed
    assert all(prove_state(before, after, r["id"], symbol_present=True) == "PERSISTS" for r in moved)


def test_a_vanished_symbol_or_an_ambiguous_match_is_hold(tmp_path):
    _write(tmp_path, "handlers.py", HANDLERS)
    before = _rule(_records(tmp_path), "empty_except")
    assert prove_state(before, [], before[0]["id"], symbol_present=False) == "HOLD"
    # two of three copies left, and the remaining ids are new: which one was fixed is not known
    after = [dict(r, id=r["id"] + "x") for r in before[:2]]
    assert prove_state(before, after, before[0]["id"], symbol_present=True) == "HOLD"
    assert prove_state(before, before, before[0]["id"], symbol_present=True) == "PERSISTS"


def test_the_work_order_shows_the_locator_and_the_report_still_refuses_a_true_duplicate(tmp_path, monkeypatch):
    _write(tmp_path, "handlers.py", HANDLERS)
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    text = render_ai_report_md(result)
    assert text.count("locator [FACT]: ") == len(build_records(build_report_view(result))) - 1
    monkeypatch.setattr(ai_report, "_item_id", lambda item, rel: "Fsame")
    with pytest.raises(AiReportInvalid):
        render_ai_report_md(result)


def test_consecutive_identical_comments_are_counted_apart(tmp_path):
    _write(tmp_path, "twice.py", "def f(x):\n    # TODO: same\n    # TODO: same\n    return x\n")
    todos = _rule(_records(tmp_path), "todo_comment")
    assert sorted(r["locator"] for r in todos) == ["body[0]~before0", "body[0]~before1"]


def test_a_comment_is_addressed_inside_its_own_scope(tmp_path):
    # the class sits inside an if: the comments belong to the class, not to the if
    nested = "import sys\nif sys:\n" + "".join("    " + line + "\n" for line in CLASS_TODOS.strip().splitlines())
    _write(tmp_path, "nested.py", nested)
    todos = _rule(_records(tmp_path), "todo_comment")
    assert sorted(r["locator"] for r in todos) == ["def:on_hit~before0", "def:on_put~before0"]
