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
