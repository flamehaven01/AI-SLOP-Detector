"""A rule's fix text sends the reader only to changes that resolve the finding.

Measured before this test (P0-3): six fix texts offered a change the detector
does not accept: a comment in an empty handler, a comment on an optional
import guard, a docstring on a placeholder, a ticket number in a TODO, a
rule-specific noqa, and a configuration key that does not exist for the rule.
An agent that followed them got the same finding back. Each case below holds
three things: the original fires the rule; the change the fix text recommends
clears it; a change that only explains (a comment, a ticket number, a narrower
noqa) does not clear it, and the fix text says so instead of recommending it.
"""

from __future__ import annotations

import pytest

from slop_detector.core import SlopDetector

CASES = {
    "empty_except": (
        "def send(client, payload):\n    try:\n        client.post(payload)\n"
        "    except Exception:\n        pass\n    return True\n",
        "def send(client, payload):\n    try:\n        client.post(payload)\n"
        "    except Exception:\n        return False\n    return True\n",
        "def send(client, payload):\n    try:\n        client.post(payload)\n    except Exception:\n"
        "        # The caller retries, so a failed post is ignored here.\n        pass\n    return True\n",
        "A comment alone does not resolve this finding",
    ),
    "empty_except/import_guard": (
        "try:\n    import yaml\nexcept ImportError:\n    pass\n",
        "try:\n    import yaml\nexcept ImportError:\n    yaml = None\n",
        "try:\n    import yaml\nexcept ImportError:\n"
        "    # yaml is optional; without it the JSON loader is used.\n    pass\n",
        "A comment alone does not resolve this finding",
    ),
    "return_none_placeholder": (
        "def persist(record):\n    return None\n",
        "STORE = []\n\n\ndef persist(record):\n    STORE.append(record)\n    return None\n",
        'def persist(record):\n    """Intentionally a no-op: records stay in memory."""\n    return None\n',
        "A docstring or comment alone does not resolve this finding",
    ),
    "todo_comment": (
        "def total(items):\n    # TODO: handle discounts\n    return sum(items)\n",
        "def total(items):\n    # Discounts: tracked in issue #123.\n    return sum(items)\n",
        "def total(items):\n    # TODO(#123): handle discounts\n    return sum(items)\n",
        "a TODO with a ticket number is still a TODO",
    ),
    "lint_escape": (
        "import os  # noqa\n\nprint(os.sep)\n",
        "import os\n\nprint(os.sep)\n",
        "import os  # noqa: F401\n\nprint(os.sep)\n",
        "is still reported as a suppression to review",
    ),
}
COMMENT_FIXES = (
    "or a comment explaining",
    "Add a comment explaining",
    "or clarify intent",
    "or create a ticket",
)


def _scan(tmp_path, name, code):
    project = tmp_path / name
    (project / "pkg").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[project]\nname = 'x'\nversion = '0'\n", encoding="utf-8"
    )
    (project / "pkg" / "mod.py").write_text(code, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(project))
    return [i for fr in result.file_results for i in fr.pattern_issues]


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_recommended_change_resolves_and_an_explanation_does_not(tmp_path, case):
    rule = case.split("/")[0]
    original, fixed, explained, says = CASES[case]
    issues = [i for i in _scan(tmp_path, "orig", original) if i.pattern_id == rule]
    assert issues, f"{case}: the original must fire {rule}"
    fix_text = issues[0].suggestion
    assert says in fix_text, (case, fix_text)
    assert not any(phrase in fix_text for phrase in COMMENT_FIXES), (case, fix_text)
    assert not [i for i in _scan(tmp_path, "fixed", fixed) if i.pattern_id == rule], case
    assert [i for i in _scan(tmp_path, "explained", explained) if i.pattern_id == rule], case


def test_the_naming_fix_text_names_a_setting_that_exists_and_works(tmp_path):
    code = "def area(a, b, c, d, e, f, g, h, i, j):\n    return a * b + c * d + e * f + g * h + i * j\n"
    issues = [
        i for i in _scan(tmp_path, "orig", code) if i.pattern_id == "placeholder_variable_naming"
    ]
    assert issues
    assert "patterns.disabled" in issues[0].suggestion
    assert "domain_overrides" not in issues[0].suggestion  # exists only for god_function / nesting
    project = tmp_path / "disabled"
    (project / "pkg").mkdir(parents=True)
    (project / "pkg" / "geo.py").write_text(code, encoding="utf-8")
    config = project / "cfg.yaml"
    config.write_text(
        "patterns:\n  disabled:\n    - placeholder_variable_naming\n", encoding="utf-8"
    )
    result = SlopDetector(config_path=str(config), read_only=True).analyze_project(str(project))
    assert not [
        i
        for fr in result.file_results
        for i in fr.pattern_issues
        if i.pattern_id == "placeholder_variable_naming"
    ]
