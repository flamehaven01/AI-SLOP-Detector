"""Release metadata says one thing: one version, and no status claim pyproject does not make.

pyproject.toml is the source: its version and its Development Status classifier.
"""

from __future__ import annotations

import re
from pathlib import Path

import slop_detector

REPO = Path(__file__).resolve().parents[1]
PYPROJECT = (REPO / "pyproject.toml").read_text(encoding="utf-8")
DOCKERFILE = (REPO / "Dockerfile").read_text(encoding="utf-8")


def _pyproject_version() -> str:
    match = re.search(r'^version = "([^"]+)"', PYPROJECT, re.MULTILINE)
    assert match, "pyproject.toml has no version"
    return match.group(1)


def test_package_and_image_carry_the_pyproject_version():
    version = _pyproject_version()
    assert slop_detector.__version__ == version
    label = re.search(r'^LABEL version="([^"]+)"', DOCKERFILE, re.MULTILINE)
    assert label and label.group(1) == version, f"Dockerfile LABEL version != {version}"


def test_no_production_ready_claim_while_pyproject_says_beta():
    assert "Development Status :: 4 - Beta" in PYPROJECT
    claim = re.compile(r"production[- ]ready", re.IGNORECASE)
    assert not claim.search(
        slop_detector.__doc__ or ""
    ), "package docstring claims production-ready"
    labels = "\n".join(line for line in DOCKERFILE.splitlines() if line.startswith("LABEL"))
    assert not claim.search(labels), "Dockerfile label claims production-ready"


def test_changelog_footer_does_not_restate_version_or_status():
    tail = (REPO / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()[-12:]
    text = "\n".join(tail)
    assert "**Current Version**" not in text and "**Status**" not in text


def _guide_pattern_ids() -> set:
    lines = (REPO / "docs" / "GUIDE.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| **Placeholder**"))
    ids: set = set()
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        ids |= set(re.findall(r"`([a-z_]+)`", line.split("|")[2]))
    return ids


def test_guide_pattern_table_is_the_registry():
    """Every ID in the guide's table is a real pattern ID (usable with --disable), and none is missing."""
    from slop_detector.patterns import get_all_patterns

    registry = {p.id for p in get_all_patterns()}
    table = _guide_pattern_ids()
    assert table == registry, (sorted(registry - table), sorted(table - registry))


def test_guide_states_the_python_pattern_count_and_the_release_tag():
    """The guide's Python pipeline names the registry's pattern count, and its
    pre-commit example pins the release this tree is."""
    from slop_detector.patterns import get_all_patterns

    guide = (REPO / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    stated = [int(n) for n in re.findall(r"(\d+) [Pp]attern [Cc]hecks", guide)]
    count = len(get_all_patterns())
    assert stated and all(n == count for n in stated), (stated, count)
    revs = re.findall(r"^\s+rev: (v[\d.]+)$", guide, re.MULTILINE)
    assert revs == ["v" + _pyproject_version()], revs


def test_guide_rule_totals_are_the_registry_table():
    """Next to the 34 pattern checks, the guide states the Python rule total and
    the total over all languages; both are the registry table's counts."""
    counts = _rules_per_language()
    guide = (REPO / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    python = [int(n) for n in re.findall(r"(\d+) Python rules", guide)]
    total = [int(n) for n in re.findall(r"(\d+) rules in all languages", guide)]
    assert python and all(n == counts["Python"] for n in python), (python, counts)
    assert total and all(n == sum(counts.values()) for n in total), (total, counts)


# Commands a reader may run that are not this package's own (pyproject scripts).
_KNOWN_TOOLS = {
    "pip",
    "python",
    "npx",
    "npm",
    "node",
    "uvx",
    "cd",
    "cp",
    "git",
    "pytest",
    "black",
    "ruff",
    "code",
}


def test_every_guide_command_is_one_a_reader_can_run():
    """A shell line in the guide starts with this package's own command or a
    common tool; a command the package does not install is not documented."""
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    scripts = set(re.findall(r"^([\w-]+) = \"slop_detector[.\w]*:\w+\"$", text, re.MULTILINE))
    assert "slop-detector" in scripts, scripts
    guide = (REPO / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    unknown = []
    for block in re.findall(r"```(?:bash|sh|shell)\n(.*?)```", guide, re.DOTALL):
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "-", "import ")):
                continue  # comment, continued option, line of a python -c string
            if line.split()[0] not in scripts | _KNOWN_TOOLS:
                unknown.append(line)
    assert not unknown, unknown


def _rules_per_language() -> dict:
    """Rule ids per language in the registry table of docs/PATTERNS.md, which
    tests/test_patterns_doc_consistency.py keeps equal to what the analyzers report."""
    text = (REPO / "docs" / "PATTERNS.md").read_text(encoding="utf-8")
    block = text.split("<!-- ACTIVE_PATTERN_REGISTRY:START -->")[1].split(
        "<!-- ACTIVE_PATTERN_REGISTRY:END -->"
    )[0]
    counts: dict = {}
    for line in block.splitlines():
        if line.startswith("| `"):
            language = line.split("|")[2].strip()
            counts[language] = counts.get(language, 0) + 1
    return counts


def test_readme_rule_counts_match_the_pattern_registry():
    """The README's language table and its total state the registry's counts."""
    counts = _rules_per_language()
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    rows = {
        "Python": r"^\| Python \|",
        "JS/TS": r"^\| JavaScript / TypeScript \|",
        "Go": r"^\| Go \|",
        "Rust": r"^\| Rust \|",
    }
    assert set(counts) == set(rows), counts
    for language, pattern in rows.items():
        row = next(line for line in readme.splitlines() if re.match(pattern, line))
        stated = int(row.rstrip(" |").rsplit("|", 1)[1])
        assert stated == counts[language], (language, stated, counts[language])
    names = {"Python": "Python", "JavaScript / TypeScript": "JS/TS", "Go": "Go", "Rust": "Rust"}
    diagram = re.findall(r'"(Python|JavaScript / TypeScript|Go|Rust)<br/>[^"]*?(\d+) rules', readme)
    assert {names[n] for n, _ in diagram} == set(rows), diagram
    for name, stated in diagram:
        assert int(stated) == counts[names[name]], (name, stated)
    total = sum(counts.values())
    stated_totals = [int(a or b) for a, b in re.findall(r"\((\d+) rules\)|All (\d+) rules", readme)]
    assert stated_totals and all(n == total for n in stated_totals), (stated_totals, total)
