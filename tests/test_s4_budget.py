"""S4: an auditor work order within an estimated-token budget.

Each item is drawn at the deepest tier the budget allows, in priority order:
T1 the whole function (AST bounds), T2 its signature, the exact evidence
lines and the range to read, T3 one index line (id, rule, location, channel,
binding). No item is ever left out; a budget below the index of every item
is BUDGET_UNSATISFIABLE. Tokens are estimated as characters / 4, not counted
by a tokenizer. Without a budget the work order is unchanged.
"""

import re

import pytest

from slop_detector.ai_report import AiReportInvalid, build_records
from slop_detector.ai_report_md import estimate_tokens, render_ai_report_md
from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.report_view import build_report_view

LONG = "def long_job(items, log):\n" + "".join(f"    step_{n} = items[{n}]\n" for n in range(30)) + (
    "    # TODO: validate the steps\n    return step_0\n")
SHORT = "".join(f"\n\ndef stub_{n}():\n    # TODO: write {n}\n    return None\n" for n in range(4))
BLOCK = re.compile(r"^### W\d+ ([FC][0-9a-f]{12}) ", re.M)
INDEX = re.compile(r"^- ([FC][0-9a-f]{12}) ", re.M)


def _result(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "jobs.py").write_text(LONG + SHORT, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _ids(result):
    return sorted(r["id"] for r in build_records(build_report_view(result))[1:])


def _minimum(result):
    with pytest.raises(AiReportInvalid) as refused:
        render_ai_report_md(result, token_budget=1)
    assert "BUDGET_UNSATISFIABLE" in str(refused.value)
    return int(re.search(r"needs at least (\d+)", str(refused.value)).group(1))


def _tiers(text):
    return tuple(int(n) for n in re.search(r"tiers T1 (\d+), T2 (\d+), T3 (\d+)", text).groups())


def test_without_a_budget_the_work_order_is_unchanged(tmp_path):
    result = _result(tmp_path)
    assert render_ai_report_md(result) == render_ai_report_md(result, token_budget=None)
    assert "budget:" not in render_ai_report_md(result)


def test_a_large_budget_draws_every_item_whole(tmp_path):
    result = _result(tmp_path)
    text = render_ai_report_md(result, token_budget=10 ** 7)
    n = len(_ids(result))
    assert _tiers(text) == (n, 0, 0)
    assert "not shown" not in text.split("## WORK-ORDER")[1]  # T1: the whole function, no cut
    assert "32|     # TODO: validate the steps" in text


def test_a_tight_budget_keeps_every_item_as_an_index_line(tmp_path):
    result = _result(tmp_path)
    minimum = _minimum(result)
    text = render_ai_report_md(result, token_budget=minimum)
    assert BLOCK.findall(text) == [] and sorted(INDEX.findall(text)) == _ids(result)
    assert _tiers(text) == (0, 0, len(_ids(result)))
    assert estimate_tokens(text) <= minimum
    index = [l for l in text.splitlines() if INDEX.match(l)]
    assert all(" channel:" in l and " sha256:" in l and " tier:3" in l for l in index)
    with pytest.raises(AiReportInvalid):
        render_ai_report_md(result, token_budget=minimum - 1)


def test_a_middle_budget_degrades_in_priority_order_and_never_drops_an_item(tmp_path):
    result = _result(tmp_path)
    minimum = _minimum(result)
    whole = estimate_tokens(render_ai_report_md(result, token_budget=10 ** 7))
    ordered = [r["id"] for r in sorted(build_records(build_report_view(result))[1:],
                                       key=lambda r: {"critical": 0, "high": 1, None: 2, "medium": 3, "low": 4}[r["severity"]])]
    seen = set()
    for budget in range(minimum, whole + 1, max(1, (whole - minimum) // 12)):
        text = render_ai_report_md(result, token_budget=budget)
        assert estimate_tokens(text) <= budget
        drawn = BLOCK.findall(text)
        assert sorted(drawn + INDEX.findall(text)) == _ids(result)  # each once
        assert drawn == ordered[:len(drawn)]  # monotone priority: the drawn items lead
        t1, t2, _ = _tiers(text)
        blocks = text.split("## WORK-ORDER")[1].split("## BACKLOG")[0].split("### W")[1:]
        assert all("not shown" not in b for b in blocks[:t1])  # T1 blocks come first, whole
        seen.add((t1, t2))
    assert any(t[1] > 0 for t in seen)  # T2 was used somewhere between the extremes


def test_a_t2_block_shows_the_signature_the_evidence_and_the_range_to_read(tmp_path):
    result = _result(tmp_path)
    minimum, whole = _minimum(result), 10 ** 7
    body = None
    for budget in range(minimum, minimum + 6000, 10):
        work = render_ai_report_md(result, token_budget=budget).split("## WORK-ORDER")[1].split("## BACKLOG")[0]
        found = [b for b in work.split("### W")[1:] if "32|     # TODO" in b and "15|" not in b]
        if found:
            body = found[0]
            break
    assert body is not None and whole, "the long function's TODO item is drawn at T2 at some budget"
    assert " 1| def long_job(items, log):" in body or "1| def long_job(items, log):" in body
    assert "32|     # TODO: validate the steps" in body
    assert "not shown (read pkg/jobs.py:1-" in body and "15|" not in body


def test_the_budget_is_for_the_auditor_and_the_cli_refuses_an_unsatisfiable_one(tmp_path, capsys):
    result = _result(tmp_path)
    with pytest.raises(AiReportInvalid):
        render_ai_report_md(result, mode="agent", token_budget=10 ** 6)
    out = tmp_path / "wo.md"
    with pytest.raises(SystemExit) as stop:
        main([str(tmp_path), "--project", "--format", "ai-md", "--ai-token-budget", "1", "--no-history",
              "-o", str(out)])
    assert stop.value.code == 2 and not out.exists()
    assert "BUDGET_UNSATISFIABLE" in capsys.readouterr().err  # the budget refused it, not argparse
    main([str(tmp_path), "--project", "--format", "ai-md", "--ai-token-budget", str(10 ** 7), "--no-history",
          "-o", str(out)])
    assert re.search(r"tiers T1 \d+, T2 0, T3 0", out.read_text(encoding="utf-8"))


PAIR = (
    "def first_rate():\n    return 2\n\n\n"
    "def later(x):\n    # TODO: check x\n    return x\n"
)


def test_the_budget_goes_to_the_higher_priority_item_first(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "pair.py").write_text(PAIR, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    records = sorted(build_records(build_report_view(result))[1:],
                     key=lambda r: {"critical": 0, "high": 1, None: 2, "medium": 3, "low": 4}[r["severity"]])
    assert len(records) >= 2 and records[0]["severity"] != records[-1]["severity"]
    minimum = _minimum(result)
    for budget in range(minimum, minimum + 2000):
        drawn = BLOCK.findall(render_ai_report_md(result, token_budget=budget))
        if drawn:
            assert drawn == [records[0]["id"]]  # the first budget that draws anything draws the first item
            break
    else:
        raise AssertionError("no budget drew a block")


def test_every_budget_from_the_minimum_up_holds_the_document(tmp_path):
    # 12 items: drawing changes the digits of the counts and block numbers, which
    # the greedy estimate does not see; the rendered document is the check
    stubs = "".join(f"\n\ndef stub_{n}():\n    # TODO: write {n}\n    return None\n" for n in range(6))
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "m.py").write_text(stubs, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    minimum = _minimum(result)
    whole = estimate_tokens(render_ai_report_md(result, token_budget=10 ** 7))
    over = [b for b in range(minimum, whole + 1) if estimate_tokens(render_ai_report_md(result, token_budget=b)) > b]
    assert over == []


def test_an_index_line_states_whether_its_file_is_still_the_scanned_content(tmp_path):
    # FH-S4-F01: a T3 line carries the full scan-time hash and its binding state
    result = _result(tmp_path)
    text = render_ai_report_md(result, token_budget=_minimum(result))
    index = [l for l in text.splitlines() if INDEX.match(l)]
    assert index and all(re.search(r" sha256:[0-9a-f]{64} binding:MATCH", l) for l in index)
    (tmp_path / "pkg" / "jobs.py").write_text(LONG + SHORT + "# edited after the scan\n", encoding="utf-8")
    stale = render_ai_report_md(result, token_budget=_minimum(result))
    index = [l for l in stale.splitlines() if INDEX.match(l)]
    assert index and all(" binding:VOID HOLD" in l for l in index)
    # the backlog of --ai-limit (no budget) states it the same way
    backlog = [l for l in render_ai_report_md(result, limit=0).splitlines() if INDEX.match(l)]
    assert backlog and all(" binding:VOID HOLD" in l for l in backlog)
    # a result with no scan-time hash is MISSING, held the same way
    result.file_results[0].source_sha256 = ""
    missing = [l for l in render_ai_report_md(result, limit=0).splitlines() if INDEX.match(l)]
    assert missing and all(" sha256:MISSING binding:MISSING HOLD" in l for l in missing)


def test_a_limit_and_a_budget_together_are_refused(tmp_path, capsys):
    # FH-S4-F02: neither bound may silently override the other
    result = _result(tmp_path)
    for limit in (0, 1):
        with pytest.raises(AiReportInvalid):
            render_ai_report_md(result, limit=limit, token_budget=10 ** 7)
    out = tmp_path / "wo.md"
    with pytest.raises(SystemExit) as stop:
        main([str(tmp_path), "--project", "--format", "ai-md", "--ai-limit", "1", "--ai-token-budget",
              str(10 ** 7), "--no-history", "-o", str(out)])
    assert stop.value.code == 2 and not out.exists() and "--ai-limit" in capsys.readouterr().err


# A long function first, then short ones, all one severity: depth-first spends
# the budget on the first item's whole body; breadth-first gives every item its
# evidence first (S4-D1).
BREADTH = "def long_first(items):\n" + "".join(f"    step_{n} = items[{n}]\n" for n in range(40)) + (
    "    # TODO: check the steps\n    return step_0\n") + "".join(
    f"\n\ndef short_{n}(x):\n    # TODO: check {n}\n    return x\n" for n in range(8))


def _all_t2_budget(result):
    """The least budget that holds every item at T2 (white-box: the renderer's own document)."""
    import slop_detector.ai_report as ai_report
    import slop_detector.ai_report_md as md
    from pathlib import Path

    view = build_report_view(result)
    rules = ai_report.ruleset()
    records = ai_report.build_records(view, rules=rules)
    header, items = records[0], sorted(records[1:], key=lambda r: md._RANK.get(r["severity"], 5))
    fixed = (header, view, rules, "auditor", Path(view.target), {})
    budget = 1
    while md.estimate_tokens(md._document(fixed, items, ["evidence"] * len(items), budget)) > budget:
        budget = md.estimate_tokens(md._document(fixed, items, ["evidence"] * len(items), budget))
    return budget


def test_every_item_gets_its_evidence_before_any_item_gets_its_whole_body(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b.py").write_text(BREADTH, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    budget = _all_t2_budget(result) + 50
    text = render_ai_report_md(result, token_budget=budget)
    t1, t2, t3 = _tiers(text)
    assert t3 == 0 and t1 + t2 == len(_ids(result))  # nobody is left at the index line
