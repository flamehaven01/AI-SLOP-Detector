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


def _readme_pattern_ids() -> set:
    lines = (REPO / "README.md").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("| **Placeholder**"))
    ids: set = set()
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        ids |= set(re.findall(r"`([a-z_]+)`", line.split("|")[2]))
    return ids


def test_readme_pattern_table_is_the_registry():
    """Every ID in the README table is a real pattern ID (usable with --disable), and none is missing."""
    from slop_detector.patterns import get_all_patterns

    registry = {p.id for p in get_all_patterns()}
    table = _readme_pattern_ids()
    assert table == registry, (sorted(registry - table), sorted(table - registry))


def test_readme_pattern_counts_match_the_registry():
    from slop_detector.patterns import get_all_patterns

    count = len(get_all_patterns())
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    stated = [int(n) for n in re.findall(r"(\d+) [Pp]attern [Cc]hecks", readme)]
    assert stated and all(n == count for n in stated), (stated, count)
