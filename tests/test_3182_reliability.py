"""3.18.2 reliability: findings an agent would act on must not ask it to change code
that is already right, and `explain` must say what a rule checks.

Found by the 3.18.1 agent dogfood (four repositories, the agent docs followed as
written):

- ignored_parameter reported parameters that a `locals()` / `vars()` snapshot
  carries into the result (one repository: 8 of 9 findings). The semantic
  channel already treats such a snapshot as a use (semantic._SNAPSHOT_READERS);
  the pattern now reads the same evidence. A snapshot that is dropped is still
  no use, and `eval` / `exec` leave every input undecided (not reported).
  The pairs below keep the same meaning and differ only in how the value is
  read (metamorphic controls).
- a well-known import name with no identified provider was a phantom_import
  (HIGH) worded as if the package did not exist; it is an undeclared
  dependency (MEDIUM) when the name is in config/known_deps.yaml. A name known
  nowhere stays HIGH, worded as an unresolved provider.
- `explain <rule>` answered every rule with the same placeholder sentence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from slop_detector.core import SlopDetector
from slop_detector.operations import build_explain_payload

ROOT = Path(__file__).resolve().parents[1]


def _issues(tmp_path: Path, source: str, name: str = "m.py") -> List:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return result.pattern_issues


def _ignored(tmp_path: Path, source: str) -> List[str]:
    return sorted(
        i.subject or "" for i in _issues(tmp_path, source) if i.pattern_id == "ignored_parameter"
    )


# -- ignored_parameter: metamorphic pairs -------------------------------------------


def test_direct_read_is_a_use(tmp_path):
    assert _ignored(tmp_path, 'def config(x=1):\n    return {"x": x}\n') == []


def test_returned_snapshot_is_a_use(tmp_path):
    assert _ignored(tmp_path, "def config(x=1):\n    return locals()\n") == []


def test_copied_snapshot_is_a_use(tmp_path):
    assert _ignored(tmp_path, "def config(x=1):\n    return dict(locals())\n") == []


def test_vars_without_arguments_is_a_use(tmp_path):
    assert _ignored(tmp_path, "def config(x=1):\n    return dict(vars())\n") == []


def test_snapshot_filtered_into_options_is_a_use(tmp_path):
    source = (
        "def page_index(doc, model=None, toc_check=None):\n"
        "    user_opt = {arg: value for arg, value in locals().items()\n"
        '                if arg != "doc" and value is not None}\n'
        "    return run(doc, user_opt)\n"
    )
    assert _ignored(tmp_path, source) == []


def test_dropped_snapshot_is_no_use(tmp_path):
    source = 'def config(x=1):\n    unused = dict(locals())\n    return {"ok": True}\n'
    assert _ignored(tmp_path, source) == ["x"]


def test_snapshot_as_a_bare_statement_is_no_use(tmp_path):
    assert _ignored(tmp_path, 'def config(x=1):\n    locals()\n    return {"ok": True}\n') == ["x"]


def test_unread_parameter_is_still_reported(tmp_path):
    assert _ignored(tmp_path, 'def config(x=1):\n    return {"ok": True}\n') == ["x"]


def test_vars_of_an_object_is_not_a_frame_snapshot(tmp_path):
    source = "def config(obj, x=1):\n    return vars(obj)\n"
    assert _ignored(tmp_path, source) == ["x"]


def test_a_shadowed_locals_is_not_a_frame_snapshot(tmp_path):
    source = "def locals():\n    return {}\n\n\n" "def config(x=1):\n    return locals()\n"
    assert _ignored(tmp_path, source) == ["x"]


def test_eval_leaves_the_inputs_undecided(tmp_path):
    source = "def config(expr, x=1):\n    return eval(expr)\n"
    assert _ignored(tmp_path, source) == []


def test_suggestion_does_not_tell_to_drop_a_parameter_blindly(tmp_path):
    issues = [
        i
        for i in _issues(tmp_path, 'def config(x=1):\n    return {"ok": True}\n')
        if i.pattern_id == "ignored_parameter"
    ]
    assert issues
    assert "or remove it" not in issues[0].suggestion
    assert "caller" in issues[0].suggestion


# -- provider: known import name vs unknown provider --------------------------------


def _import_findings(tmp_path: Path, module: str):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1"\ndependencies = []\n', encoding="utf-8"
    )
    issues = _issues(tmp_path, f"import {module}\n\n\ndef f():\n    return {module}\n")
    return [i for i in issues if i.subject == module]


def test_a_known_import_name_is_an_undeclared_dependency(tmp_path):
    found = _import_findings(tmp_path, "pymongo")
    assert [(i.pattern_id, i.severity.value) for i in found] == [
        ("undeclared_dependency", "medium")
    ]


def test_a_name_known_nowhere_stays_high_and_is_not_called_invented(tmp_path):
    found = _import_findings(tmp_path, "zzqx_not_a_known_name")
    assert [(i.pattern_id, i.severity.value) for i in found] == [("phantom_import", "high")]
    assert found[0].message.startswith("Provider not found:")
    assert "supplies 'zzqx_not_a_known_name'" in found[0].message  # the VS Code Quick Fix reads it


# -- explain ------------------------------------------------------------------------


def _documented_rules() -> List[str]:
    import re

    doc = (ROOT / "docs" / "PATTERNS.md").read_text(encoding="utf-8")
    block = doc[
        doc.index("ACTIVE_PATTERN_REGISTRY:START") : doc.index("ACTIVE_PATTERN_REGISTRY:END")
    ]
    return sorted(set(re.findall(r"^\| `([a-z_]+)` \|", block, re.M)))


@pytest.mark.parametrize("rule", _documented_rules())
def test_explain_gives_the_rules_own_question(rule):
    payload = build_explain_payload(rule)
    assert payload["known"] is True
    assert payload["family"]
    assert "ACK" in payload["verify_question"] and "REJECT" in payload["verify_question"]
    assert "Review the rule or target manually" not in json.dumps(payload)


def test_explain_states_what_a_finding_does_not_prove():
    payload = build_explain_payload("ignored_parameter")
    assert any("FINDING != proven defect" in line for line in payload["limits"])


def test_explain_of_an_unknown_rule_says_so():
    payload = build_explain_payload("no_such_rule")
    assert payload["known"] is False


def test_explain_keeps_the_cleanup_families():
    assert build_explain_payload("dead-code")["summary"]["message"].startswith("Cleanup dead code")


# -- agent documents point at the work order ----------------------------------------


@pytest.mark.parametrize(
    "doc",
    ["docs/AGENT_WORKFLOW.md", "claude-skills/slop-detector/SKILL.md", "docs/CLAUDE_CODE_SKILL.md"],
)
def test_agent_docs_name_the_work_order(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    assert "--format ai-md" in text
    assert "--format ai" in text
