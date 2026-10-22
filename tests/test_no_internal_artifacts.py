"""No internal review artifact is tracked in this public repository.

.gitignore does not stop `git add -f` or a file tracked before the rule existed;
this check runs in CI against what git actually tracks.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Mirrors the internal-artifact rules in .gitignore.
INTERNAL = (".internal/*", "*ENGINE_EXECUTION_*.json", "*TOOL_REGISTRY.yaml")
INTERNAL_FILES = ("docs/V3_10_SCOPE_LOCK.md",)


def _tracked() -> list:
    """Tracked paths; a git failure in a checkout fails the test (no silent skip)."""
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout (sdist)")
    # safe.directory: a test HOME without the user's git config is not "dubious".
    out = subprocess.run(
        ["git", "-c", f"safe.directory={REPO.as_posix()}", "-C", str(REPO), "ls-files", "-z"],
        capture_output=True,
        check=True,
        timeout=60,
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def test_no_internal_artifact_is_tracked():
    tracked = _tracked()
    leaked = sorted(
        p
        for p in tracked
        if p in INTERNAL_FILES or any(fnmatch.fnmatch(p, pat) for pat in INTERNAL)
    )
    assert leaked == []


def test_the_check_matches_what_it_guards():
    assert fnmatch.fnmatch(".internal/notes.md", INTERNAL[0])
    assert fnmatch.fnmatch("reports/ENGINE_EXECUTION_SEAL.json", INTERNAL[1])
    assert not fnmatch.fnmatch("docs/internal.md", INTERNAL[0])
