"""S2: items of the work order grouped into families, display only.

A family holds the items that share kind, rule, severity, fix, channel state
and evidence shape (the evidence sentence with quoted names and numbers
replaced); severity stands in for the fix-risk tier until S1 adds one. The
family header states the shared fix and channel once; every item keeps its
own block: id, location, locator, binding, evidence, promise and code. Each
file's scan-time SHA-256 and binding are stated once in FILES and items point
to it. Losslessness is the contract: every record id appears exactly once,
with fields equal to its record; a document that is not is never written.

The parser below is independent of the renderer's own check.
"""

import re

import pytest

from slop_detector import ai_report_md
from slop_detector.ai_report import AiReportInvalidError, build_records
from slop_detector.ai_report_md import render_ai_report_md
from slop_detector.core import SlopDetector
from slop_detector.report_view import build_report_view

A = (
    'def rate_a(order):\n    """Return the rate."""\n    return 0.1\n\n\n'
    'def rate_b(order):\n    """Return the rate."""\n    return 0.2\n\n\n'
    'def label(order):\n    """Return the label."""\n    return "x"\n\n\n'
    "def todo_one():\n    # TODO: write it\n    return None\n"
)
B = (
    'def rate_c(order):\n    """Return the rate."""\n    return 0.3\n\n\n'
    "def todo_two():\n    # TODO: write that\n    return None\n\n\n"
    # same rule and evidence shape as the 'order' items, another fix ('qty')
    'def tag(qty):\n    """Return the tag."""\n    return "y"\n'
)
LONGS = "\n\n".join(
    f"def long_{k}(items):\n"
    + "".join(f"    step_{n} = items[{n}]\n" for n in range(25))
    + f"    # TODO: validate batch {k}\n    return step_0\n"
    for k in range(4)
)
# paths come last on a line: a repository path may hold spaces
FILE_ROW = re.compile(r"^- (B\d+) binding:(MATCH|VOID HOLD|MISSING HOLD) sha256:(\S+) file:(.+)$")
FAMILY = re.compile(r"^### (G\d+) (FINDING|REVIEW_CANDIDATE) (\S+) (\S+) \| items (\d+)$")
MEMBER = re.compile(r"^#### W\d+ ([FC][0-9a-f]{12}) (FINDING|REVIEW_CANDIDATE) (\S+) (\S+)$")
INDEX = re.compile(
    r"^- ([FC][0-9a-f]{12}) (\S+) (\S+) file:(B\d+)(?: channel:(\S+) tier:3)? at:(.+):(\d+)$"
)


def _project(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "a.py").write_text(A, encoding="utf-8")
    (tmp_path / "pkg" / "b.py").write_text(B, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _records(result):
    return {r["id"]: r for r in build_records(build_report_view(result))[1:]}


def parse(doc):
    """FILES rows, families with their members, member fields, index lines."""
    files, families, items, index = {}, [], {}, {}
    family = member = None
    for line in doc.splitlines():
        m = FILE_ROW.match(line)
        if m:
            files[m.group(1)] = {"file": m.group(4), "sha": m.group(3), "binding": m.group(2)}
            continue
        m = FAMILY.match(line)
        if m:
            family = {
                "id": m.group(1),
                "kind": m.group(2),
                "rule": m.group(3),
                "severity": m.group(4),
                "n": int(m.group(5)),
                "members": [],
                "fix": None,
                "channel": None,
            }
            families.append(family)
            member = None
            continue
        m = MEMBER.match(line)
        if m:
            member = {
                "kind": m.group(2),
                "rule": m.group(3),
                "severity": m.group(4),
                "family": family["id"],
            }
            assert m.group(1) not in items, f"{m.group(1)} drawn twice"
            items[m.group(1)] = member
            family["members"].append(m.group(1))
            continue
        m = INDEX.match(line)
        if m:
            assert m.group(1) not in index, f"{m.group(1)} indexed twice"
            index[m.group(1)] = {
                "severity": m.group(2),
                "rule": m.group(3),
                "bound": m.group(4),
                "channel": m.group(5),
                "file": m.group(6),
                "line": int(m.group(7)),
            }
            continue
        if line.startswith("## "):
            family = member = None
            continue
        if member is not None:
            key, _, value = line.partition(" [")
            if value:
                text = value.split("]: ", 1)[1] if "]: " in value else ""
                if key == "at":
                    path, _, n = text.rpartition(":")
                    member["file"], member["line"] = path, int(n)
                elif key == "locator":
                    loc, _, sem = text.partition(" semantic_key=")
                    member["locator"], member["semantic_key"] = loc, sem
                elif key == "bound_to":
                    member["bound"] = text.split(" ", 1)[0]
                elif key == "evidence":
                    member["evidence"] = text
        elif family is not None:
            if line.startswith("fix [DERIVED]: "):
                family["fix"] = line[len("fix [DERIVED]: ") :]
            elif line.startswith("channel [FACT]: "):
                family["channel"] = line[len("channel [FACT]: ") :]
    return files, families, items, index


def _check_lossless(doc, records):
    files, families, items, index = parse(doc)
    assert set(items) | set(index) == set(records) and not set(items) & set(index)
    by_family = {f["id"]: f for f in families}
    for rid, item in items.items():
        r = records[rid]
        fam = by_family[item["family"]]
        assert (item["kind"], item["rule"], item["severity"]) == (
            r["kind"],
            r["rule"],
            r["severity"] or "review",
        )
        assert (item["file"], item["line"]) == (r["file"], r["line"])
        assert (
            item["locator"] == (r["locator"] or "(the symbol itself)")
            and item["semantic_key"] == r["semantic_key"]
        )
        assert item["evidence"] == r["evidence"]
        assert (
            files[item["bound"]]["file"] == r["file"]
            and files[item["bound"]]["sha"] == r["source_sha256"]
        )
        assert fam["fix"] == r["fix"] and fam["channel"] == r["channel_state"]
    for rid, line in index.items():
        r = records[rid]
        assert (line["rule"], line["file"], line["line"]) == (r["rule"], r["file"], r["line"])
        assert files[line["bound"]]["sha"] == r["source_sha256"]
    for f in families:
        assert f["n"] == len(f["members"]) > 0
    assert sum(f["n"] for f in families) == len(items)
    return files, families, items, index


@pytest.mark.parametrize("kwargs", [{}, {"mode": "agent"}, {"token_budget": 10**9}, {"limit": 3}])
def test_every_item_appears_once_with_its_own_fields(tmp_path, kwargs):
    result = _project(tmp_path)
    _check_lossless(render_ai_report_md(result, **kwargs), _records(result))


def test_a_family_holds_exactly_the_items_that_share_its_key(tmp_path):
    result = _project(tmp_path)
    records = _records(result)
    _, families, items, _ = _check_lossless(render_ai_report_md(result), records)

    def key(rid):
        r = records[rid]
        shape = re.sub(
            r"\d+(\.\d+)?", "<d>", re.sub(r"'[^']*'|\"[^\"]*\"|`[^`]*`", "<n>", r["evidence"])
        )
        return (r["kind"], r["rule"], r["severity"], r["fix"], r["channel_state"], shape)

    keys = [{key(rid) for rid in f["members"]} for f in families]
    assert all(len(k) == 1 for k in keys)  # members share the key
    assert len({next(iter(k)) for k in keys}) == len(families)  # no two families share one
    stubs = [f for f in families if f["rule"] == "return_constant_stub"]
    assert sorted(f["n"] for f in stubs) == [2, 3]  # a number and a string: two evidence shapes
    three = next(f for f in stubs if f["n"] == 3)
    assert {items[rid]["file"] for rid in three["members"]} == {"pkg/a.py", "pkg/b.py"}
    ignored = [f for f in families if f["rule"] == "ignored_parameter"]
    assert sorted(f["n"] for f in ignored) == [1, 4]  # 'qty' has another fix than 'order'


BASE = {
    "kind": "FINDING",
    "rule": "r",
    "severity": "medium",
    "fix": "do x",
    "channel_state": "COMPLETE",
    "evidence": "Function 'a' returns 1",
}


@pytest.mark.parametrize(
    "field, other",
    [
        ("kind", "REVIEW_CANDIDATE"),
        ("rule", "s"),
        ("severity", "high"),
        ("fix", "do y"),
        ("channel_state", "PARTIAL"),
        ("evidence", "Function 'a' returns 1 twice"),
    ],
)
def test_one_differing_component_makes_another_family(field, other):
    # one axis at a time: everything else equal
    assert ai_report_md._family_key(BASE) != ai_report_md._family_key(dict(BASE, **{field: other}))
    assert ai_report_md._family_key(BASE) == ai_report_md._family_key(
        dict(BASE, evidence="Function 'zz' returns 7")
    )


def test_each_file_is_bound_once_and_a_changed_file_holds_only_its_items(tmp_path):
    result = _project(tmp_path)
    records = _records(result)
    files, _, items, _ = _check_lossless(render_ai_report_md(result), records)
    assert sorted(f["file"] for f in files.values()) == ["pkg/a.py", "pkg/b.py"]
    assert {f["binding"] for f in files.values()} == {"MATCH"}
    (tmp_path / "pkg" / "b.py").write_text(B + "# edited after the scan\n", encoding="utf-8")
    doc = render_ai_report_md(result)
    files, _, items, _ = _check_lossless(doc, records)
    state = {f["file"]: f["binding"] for f in files.values()}
    assert state == {"pkg/a.py": "MATCH", "pkg/b.py": "VOID HOLD"}
    blocks = re.split(r"^#### ", doc, flags=re.M)[1:]
    for block in blocks:
        held = "code [FACT]: NOT-APPLICABLE: HOLD" in block
        assert held == (" pkg/b.py:" in block.split("\n", 2)[1] or "at [FACT]: pkg/b.py:" in block)


def test_index_lines_point_to_the_files_table(tmp_path):
    result = _project(tmp_path)
    records = _records(result)
    with pytest.raises(AiReportInvalidError) as refused:
        render_ai_report_md(result, token_budget=1)
    least = int(re.search(r"needs at least (\d+)", str(refused.value)).group(1))
    files, _, items, index = _check_lossless(
        render_ai_report_md(result, token_budget=least), records
    )
    assert not items and set(index) == set(records)
    assert all(line["channel"] == records[rid]["channel_state"] for rid, line in index.items())


def _altered_member(target_rule, change):
    """A member block renderer that alters the block of one item only."""
    original = ai_report_md._member_block

    def member(n, record, *args, **kwargs):
        lines = original(n, record, *args, **kwargs)
        return (
            change(lines)
            if record["rule"] == target_rule and record["file"] == "pkg/b.py"
            else lines
        )

    return member


@pytest.mark.parametrize(
    "defect",
    [
        "indexed_twice",
        "evidence_changed",
        "bound_to_another_file",
        "family_count_off",
        "family_fix_changed",
    ],
)
def test_the_gate_refuses_each_kind_of_loss(tmp_path, monkeypatch, defect):
    # each defect is one that a single check of the gate catches
    result = _project(tmp_path)
    kwargs = {}
    if defect == "indexed_twice":
        original = ai_report_md._index_line
        monkeypatch.setattr(
            ai_report_md, "_index_line", lambda *a: (lambda ln: ln + "\n" + ln)(original(*a))
        )
        kwargs = {"limit": 2}
    elif defect == "evidence_changed":
        monkeypatch.setattr(
            ai_report_md,
            "_member_block",
            _altered_member(
                "todo_comment", lambda ls: [ln.replace("TODO comment", "TODO note") for ln in ls]
            ),
        )
    elif defect == "bound_to_another_file":
        monkeypatch.setattr(
            ai_report_md,
            "_member_block",
            _altered_member(
                "todo_comment",
                lambda ls: [
                    ln.replace("bound_to [FACT]: B02", "bound_to [FACT]: B01") for ln in ls
                ],
            ),
        )
    elif defect == "family_count_off":
        original = ai_report_md._family
        monkeypatch.setattr(
            ai_report_md, "_family", lambda gid, record, count: original(gid, record, count + 1)
        )
    else:
        original = ai_report_md._family

        def family(gid, record, count):
            lines = original(gid, record, count)
            return [
                (
                    ln + " now"
                    if ln.startswith("fix [DERIVED]") and record["rule"] == "todo_comment"
                    else ln
                )
                for ln in lines
            ]

        monkeypatch.setattr(ai_report_md, "_family", family)
    with pytest.raises(AiReportInvalidError, match="not lossless"):
        render_ai_report_md(result, **kwargs)


def _all_t2_budget(result):
    """The least budget that holds every item at T2, family headers included
    (white-box: the renderer's own document in its own order)."""
    from pathlib import Path

    from slop_detector import ai_report

    view = build_report_view(result)
    rules = ai_report.ruleset()
    records = ai_report.build_records(view, rules=rules)
    items = ai_report_md._grouped(records[1:])
    fixed = (records[0], view, rules, "auditor", Path(view.target), {})
    budget = 1
    while (
        ai_report_md.estimate_tokens(
            ai_report_md._document(fixed, items, ["evidence"] * len(items), budget)
        )
        > budget
    ):
        budget = ai_report_md.estimate_tokens(
            ai_report_md._document(fixed, items, ["evidence"] * len(items), budget)
        )
    return budget


def test_family_headers_are_paid_for_in_the_budget(tmp_path):
    # S4-D1 with families: from the budget that holds every item at T2 up to
    # the one that holds every item whole, more budget never sends an item back
    # to the index line. Unpaid family headers did: the T1 pass spent their
    # room and the rendered check pushed the last T2 items down to T3. Cheap
    # stubs lead and long functions trail, so the T1 pass stops midway.
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "c.py").write_text(LONGS, encoding="utf-8")
    result = _project(tmp_path)
    low = _all_t2_budget(result)
    high = ai_report_md.estimate_tokens(render_ai_report_md(result, token_budget=10**7))
    # step 11: under the old final check the failing budgets came in runs 12
    # wide (5182-5193, 5346-5357, ...), so every run is sampled
    for budget in range(low, high + 1, 11):
        text = render_ai_report_md(result, token_budget=budget)
        t1, t2, t3 = (
            int(n) for n in re.search(r"tiers T1 (\d+), T2 (\d+), T3 (\d+)", text).groups()
        )
        assert t3 == 0 and t1 + t2 == len(_records(result)), (budget, t1, t2, t3)


def test_the_allocation_pays_for_what_it_draws(tmp_path, monkeypatch):
    # The final check corrects small layout effects, it does not allocate: with
    # family headers paid, it took back at most 2 steps on any budget (measured
    # on this fixture); unpaid, up to 14, on 273 of 274 budgets.
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "c.py").write_text(LONGS, encoding="utf-8")
    result = _project(tmp_path)
    rank = {"full": 2, "evidence": 1, ai_report_md._INDEX: 0}
    taken = []
    settle = ai_report_md._settle

    def counting(fixed, items, tiers, budget):
        before = list(tiers)
        after = settle(fixed, items, tiers, budget)
        taken.append(sum(rank[a] - rank[b] for a, b in zip(before, after)))
        return after

    monkeypatch.setattr(ai_report_md, "_settle", counting)
    low = _all_t2_budget(result) - 600
    high = ai_report_md.estimate_tokens(render_ai_report_md(result, token_budget=10**7))
    for budget in range(low, high + 1, 21):
        render_ai_report_md(result, token_budget=budget)
    assert taken and max(taken) <= 2, max(taken)


PROMISED = 'def compute_total(order):\n    """Compute the total for the order."""\n    return 0.1\n'


def _altered(lines, record, field):
    """One shown field of one item changed, everything else as rendered."""
    out = []
    for ln in lines:
        if ln.startswith("#### W"):
            head = ln.split(" ")
            if field == "severity":
                head[-1] = "low" if head[-1] != "low" else "medium"
            elif field == "kind":
                head[3] = "REVIEW_CANDIDATE" if head[3] == "FINDING" else "FINDING"
            elif field == "rule":
                head[4] = head[4] + "_x"
            ln = " ".join(head)
        elif ln.startswith("locator [FACT]: ") and field == "locator":
            ln = ln.replace("locator [FACT]: ", "locator [FACT]: body[9]", 1)
        elif ln.startswith("locator [FACT]: ") and field == "semantic_key":
            ln = ln[:-1] + ("0" if ln[-1] != "0" else "1")
        elif ln.startswith("promise [FACT]: ") and field == "promise":
            ln = ln.replace("Compute the total", "Compute the sum")
        out.append(ln)
    return out


@pytest.mark.parametrize(
    "field", ["severity", "kind", "rule", "locator", "semantic_key", "promise"]
)
def test_the_gate_checks_every_field_an_item_block_shows(tmp_path, monkeypatch, field):
    # FH-S2-01: each shown field of an item, changed alone, is refused
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "d.py").write_text(PROMISED, encoding="utf-8")
    result = _project(tmp_path)
    target = "return_constant_stub" if field == "promise" else "todo_comment"
    original = ai_report_md._member_block

    def member(n, record, *args, **kwargs):
        lines = original(n, record, *args, **kwargs)
        chosen = record["rule"] == target and record["file"] == (
            "pkg/d.py" if field == "promise" else "pkg/b.py"
        )
        return _altered(lines, record, field) if chosen else lines

    plain = render_ai_report_md(result)
    assert "promise [FACT]: " in plain  # the promise is there to change
    monkeypatch.setattr(ai_report_md, "_member_block", member)
    with pytest.raises(AiReportInvalidError, match="not lossless"):
        render_ai_report_md(result)


@pytest.mark.parametrize("field", ["severity", "rule"])
def test_the_gate_checks_every_field_an_index_line_shows(tmp_path, monkeypatch, field):
    result = _project(tmp_path)
    original = ai_report_md._index_line

    def index_line(record, tiered, bref):
        line = original(record, tiered, bref)
        if record["rule"] != "todo_comment":
            return line
        parts = line.split(" ")
        if field == "severity":
            parts[2] = "low"
        else:
            parts[3] = parts[3] + "_x"
        return " ".join(parts)

    monkeypatch.setattr(ai_report_md, "_index_line", index_line)
    with pytest.raises(AiReportInvalidError, match="not lossless"):
        render_ai_report_md(result, limit=0)


def test_an_item_whose_whole_body_is_cheaper_than_its_excerpt_is_drawn_whole(tmp_path):
    # FH-S4-D1-01: for a short function the whole body (T1) costs less than the
    # signature, evidence and range to read (T2); a budget that holds T1 but
    # not T2 draws the item whole instead of leaving it at the index line
    from pathlib import Path

    from slop_detector import ai_report

    result = _project(tmp_path)
    view = build_report_view(result)
    rules = ai_report.ruleset()
    records = ai_report.build_records(view, rules=rules)
    items = ai_report_md._grouped(records[1:])
    fixed = (records[0], view, rules, "auditor", Path(view.target), {})
    rest = [ai_report_md._INDEX] * (len(items) - 1)

    def holding(tiers):
        budget = 1
        while (
            ai_report_md.estimate_tokens(ai_report_md._document(fixed, items, tiers, budget))
            > budget
        ):
            budget = ai_report_md.estimate_tokens(
                ai_report_md._document(fixed, items, tiers, budget)
            )
        return budget

    whole, excerpt = holding(["full"] + rest), holding(["evidence"] + rest)
    assert whole < excerpt  # the case this control is about
    text = render_ai_report_md(result, token_budget=whole)
    t1, t2, t3 = (int(n) for n in re.search(r"tiers T1 (\d+), T2 (\d+), T3 (\d+)", text).groups())
    assert t1 >= 1, (t1, t2, t3)


def test_the_whole_body_pass_goes_past_an_item_already_drawn_whole(tmp_path):
    # FH-S2-P1: a short item drawn whole in the evidence pass (T1 cheaper than
    # T2) is skipped by the whole-body pass, which goes on to the long items
    # after it; stopping there would leave every later item at T2 whatever
    # the budget. Room is exactly every item's evidence form plus the whole
    # body of each long item up to the first long item after a short one.
    from pathlib import Path

    from slop_detector import ai_report

    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "c.py").write_text(LONGS, encoding="utf-8")
    result = _project(tmp_path)
    view = build_report_view(result)
    rules = ai_report.ruleset()
    records = ai_report.build_records(view, rules=rules)
    items = ai_report_md._grouped(records[1:])
    fixed = (records[0], view, rules, "auditor", Path(view.target), {})
    cost = ai_report_md._coster(fixed, items)
    short = [i for i in range(len(items)) if cost(i, "full") <= cost(i, "evidence")]
    later = [i for i in range(len(items)) if short and i > short[0]]
    long_after = [i for i in later if cost(i, "full") > cost(i, "evidence")]
    assert short and long_after  # the case this control is about
    target = long_after[0]
    room = sum(min(cost(i, "full"), cost(i, "evidence")) for i in range(len(items))) + sum(
        cost(i, "full") - cost(i, "evidence")
        for i in range(target + 1)
        if cost(i, "full") > cost(i, "evidence")
    )
    tiers = [ai_report_md._INDEX] * len(items)
    ai_report_md._allocate(fixed, items, tiers, room)
    assert tiers[short[0]] == "full" and tiers[target] == "full", (short[0], target, tiers)


def test_the_work_order_names_its_own_format(tmp_path):
    # FH-S2-FORMAT: the Markdown work order changed with S2; its records did not
    text = render_ai_report_md(_project(tmp_path))
    assert text.splitlines()[1].startswith(
        "format: ai-slop-work-order/2 markdown work order | records ai-slop-report/1 | tool "
    )


def test_a_document_that_would_lose_an_item_is_never_written(tmp_path, monkeypatch):
    result = _project(tmp_path)
    original = ai_report_md._member_block

    def drop_one(n, record, *args, **kwargs):
        return (
            []
            if record["rule"] == "todo_comment" and record["file"] == "pkg/b.py"
            else original(n, record, *args, **kwargs)
        )

    monkeypatch.setattr(ai_report_md, "_member_block", drop_one)
    with pytest.raises(AiReportInvalidError, match="lossless"):
        render_ai_report_md(result)
