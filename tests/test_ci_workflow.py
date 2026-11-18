"""The CI workflow keeps the two decisions the repository's memory records about it.

- Lint (memory DI-013): black 24.8.0, then ruff, then mypy, on the paths a
  local run checks. The job stops at the first failure, so all three must
  pass locally before a push.
- Tests (memory DI-014): the Python 3.8-3.12 matrix runs on ubuntu-24.04;
  actions/setup-python cannot install 3.8 or 3.9 on ubuntu-latest (Ubuntu
  26.04), and the package still supports Python 3.8.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _runs(job: str) -> list:
    return [step.get("run", "") for step in WORKFLOW["jobs"][job]["steps"]]


def test_lint_runs_black_24_8_then_ruff_then_mypy():
    runs = _runs("lint")
    assert any("black==24.8.0" in run for run in runs), "black is not pinned to 24.8.0"
    order = [
        next(i for i, run in enumerate(runs) if pattern.search(run))
        for pattern in (
            re.compile(r"black --check src/ tests/"),
            re.compile(r"ruff check src/ tests/"),
            re.compile(r"mypy src/"),
        )
    ]
    assert order == sorted(order), order


def test_the_python_matrix_runs_on_ubuntu_24_04_from_python_3_8():
    job = WORKFLOW["jobs"]["test"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["strategy"]["matrix"]["python-version"] == ["3.8", "3.9", "3.10", "3.11", "3.12"]
    pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^requires-python = ">=3\.8"', pyproject, re.M)
