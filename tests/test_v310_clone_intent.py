"""v3.10 clone intent: protocol and polymorphic methods are not fragmentation.

Found by the cross-domain precision study (stage-1 sample: 5 of 9 CRITICAL
`function_clone_cluster` findings were false) and measured on the
18-repository corpus: of 27 findings (16 CRITICAL), 2 CRITICAL groups were
operator protocols (`__and__`, `__or__`, `__xor__`, ...) and 8 CRITICAL groups
were the same method implemented by sibling classes (`generate` in five
generators, `description` per chain type, `cut_once` per enzyme class).
The finding says "possible god function fragmented into helpers"; a protocol
method or a polymorphic implementation is neither.

Contract: before sizing a clone group, dunder methods and names the group
holds more than once (one name implemented by several functions) are left
out; a group still at the threshold is reported with its remaining size;
exact copies stay with `exact_duplicate_pair`.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector

BODY = """\
    total = 0
    for item in items:
        if item > {n}:
            total += item * {n}
    return total
"""


def _clone_findings(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(source, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return [
        (issue.severity.value, issue.message)
        for issue in result.pattern_issues
        if issue.pattern_id == "function_clone_cluster"
    ]


HELPERS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]  # no shared prefix


def _function(name: str, n: int, indent: str = "") -> str:
    signature = f"def {name}(self, items):\n" if indent else f"def {name}(items):\n"
    # One constant for all: functions differing only in constants have distinct
    # semantic signatures and are exempt already.
    return textwrap.indent(signature + BODY.format(n=2), indent)


def test_module_helpers_cloned_six_times_are_reported(tmp_path):
    source = "\n\n".join(_function(name, i) for i, name in enumerate(HELPERS))
    found = _clone_findings(tmp_path, source)
    assert [sev for sev, _ in found] == ["critical"]


def test_operator_protocol_is_not_a_clone_cluster(tmp_path):
    names = ["__and__", "__or__", "__xor__", "__rand__", "__ror__", "__rxor__"]
    methods = "\n".join(_function(name, i, "    ") for i, name in enumerate(names))
    source = "class Bits:\n" + methods
    assert _clone_findings(tmp_path, source) == []


def test_sibling_implementations_are_not_a_clone_cluster(tmp_path):
    # Two methods per chain type, as in alphafold3's ProteinChain / RnaChain /
    # DnaChain (one shared name would already be exempt as a dispatcher prefix).
    classes = [
        f"class Chain{i}(Base):\n"
        + _function("describe", i, "    ")
        + "\n"
        + _function("summarize", i, "    ")
        for i in range(3)
    ]
    source = "class Base:\n    pass\n\n\n" + "\n\n".join(classes)
    assert _clone_findings(tmp_path, source) == []


def test_remaining_helpers_are_sized_without_protocol_and_polymorphic_members(tmp_path):
    helpers = "\n\n".join(_function(name, i) for i, name in enumerate(HELPERS[:4]))
    siblings = "\n\n".join(
        f"class Generator{i}:\n" + _function("generate", i, "    ") for i in range(3)
    )
    found = _clone_findings(tmp_path, helpers + "\n\n" + siblings)
    assert [sev for sev, _ in found] == ["high"]
    assert found[0][1].startswith("4 structurally similar functions")
    assert "generate" not in found[0][1]


def test_a_name_the_module_defines_twice_is_not_a_fragment_even_once_in_the_group():
    import ast

    from slop_detector.patterns.python_clones import _fragmentation_candidates

    tree = ast.parse(
        "class Blunt:\n    def compatible_end(self):\n        return 1\n\n"
        "class Ov5:\n    def compatible_end(self):\n        return 2\n\n"
        "def alpha():\n    return 3\n"
    )
    # The clone group holds only Blunt.compatible_end, but Ov5 implements it too.
    assert _fragmentation_candidates(tree, ["compatible_end", "alpha"]) == ["alpha"]
