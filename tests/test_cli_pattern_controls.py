"""Controls for --patterns-only and --disable.

--patterns-only: LDR, inflation and DDC are still reported but do not count
toward deficit_score, which then comes from pattern findings alone.
--disable ID: that pattern does not run; an unknown ID is an error, not a
silent no-op. Both are part of the analysis cache key.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")

# Signal on every metric axis (LDR, inflation via jargon comments, DDC via unused
# imports) plus exactly one HIGH placeholder finding (penalty 5).
_JARGON = (
    "Enterprise-grade scalable production-ready robust optimized cutting-edge state-of-the-art"
)
SOURCE = (
    "import json\nimport os\n\n\n"
    f"# {_JARGON}\n# {_JARGON}\n"
    "def helper(x):\n    return x * 2\n\n\ndef todo_later():\n    pass\n"
)


def _cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONPATH=REPO_SRC)
    return subprocess.run(
        [sys.executable, "-m", "slop_detector.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


def _scan(home: Path, target: Path, *flags: str) -> dict:
    result = _cli(home, "scan", str(target), "--json", *flags)
    assert result.returncode in (0, 1), result.stderr[-400:]
    return json.loads(result.stdout)


def _ids(payload: dict) -> List[str]:
    return sorted(i["pattern_id"] for i in payload.get("pattern_issues", []))


@pytest.fixture
def target(tmp_path):
    path = tmp_path / "proj" / "m.py"
    path.parent.mkdir()
    path.write_text(SOURCE, encoding="utf-8")
    return path


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


# ---------------------------------------------------------------------------
# --patterns-only
# ---------------------------------------------------------------------------


def test_fixture_has_metric_and_pattern_signal(home, target):
    """Acceptance: without flags every metric axis contributes and one pattern fires."""
    plain = _scan(home, target, "--read-only")
    assert _ids(plain) == ["pass_placeholder"]
    breakdown = plain["deficit_breakdown"]
    for key in ("ldr_penalty", "inflation_penalty", "ddc_penalty"):
        assert breakdown[key] > 0.5, (key, breakdown)
    assert plain["deficit_score"] > 5.0 + 1e-6, plain["deficit_score"]


def test_patterns_only_scores_pattern_findings_alone(home, target):
    out = _scan(home, target, "--read-only", "--patterns-only")
    assert _ids(out) == _ids(_scan(home, target, "--read-only"))
    assert out["deficit_score"] == pytest.approx(5.0)  # one HIGH finding
    breakdown = out["deficit_breakdown"]
    for key in ("ldr_penalty", "inflation_penalty", "ddc_penalty"):
        assert breakdown[key] == pytest.approx(0.0), (key, breakdown)
    assert "ldr" in out and "ddc" in out, "metrics are still reported"


def test_patterns_only_applies_to_every_file_of_a_project(home, target):
    (target.parent / "n.py").write_text(SOURCE, encoding="utf-8")
    result = _cli(home, "scan", str(target.parent), "--json", "--read-only", "--patterns-only")
    assert result.returncode in (0, 1), result.stderr[-400:]
    files = json.loads(result.stdout)["file_results"]
    assert len(files) == 2
    assert all(f["deficit_score"] == pytest.approx(5.0) for f in files)


# ---------------------------------------------------------------------------
# --disable
# ---------------------------------------------------------------------------


def test_disable_removes_the_pattern_and_its_penalty(home, target):
    plain = _scan(home, target, "--read-only")
    out = _scan(home, target, "--read-only", "--disable", "pass_placeholder")
    assert "pass_placeholder" not in _ids(out)
    # The score is capped at 100, so compare against the pattern share actually applied.
    applied = plain["deficit_breakdown"]["pattern_hits"]
    assert applied > 0
    assert out["deficit_breakdown"]["pattern_hits"] == pytest.approx(0.0)
    assert out["deficit_score"] == pytest.approx(plain["deficit_score"] - applied)


def test_disable_can_be_repeated(home, target):
    path = target.parent / "two.py"
    path.write_text("def a():\n    pass\n\n\ndef b():\n    ...\n", encoding="utf-8")
    plain = _ids(_scan(home, path, "--read-only"))
    assert {"pass_placeholder", "ellipsis_placeholder"} <= set(plain)
    out = _ids(
        _scan(
            home,
            path,
            "--read-only",
            "--disable",
            "pass_placeholder",
            "-d",
            "ellipsis_placeholder",
        )
    )
    assert "pass_placeholder" not in out and "ellipsis_placeholder" not in out


def test_unknown_pattern_id_is_an_error(home, target):
    result = _cli(home, "scan", str(target), "--read-only", "--disable", "pass_placeholdr")
    assert result.returncode == 2
    assert "pass_placeholdr" in result.stderr and "--list-patterns" in result.stderr


# ---------------------------------------------------------------------------
# Cache key
# ---------------------------------------------------------------------------


def test_flags_are_part_of_the_cache_key(home, target):
    """With the cache on, a run with flags never reuses a run without them, and back."""
    first = _scan(home, target)
    only = _scan(home, target, "--patterns-only")
    disabled = _scan(home, target, "--disable", "pass_placeholder")
    again = _scan(home, target)
    assert only["deficit_score"] == pytest.approx(5.0)
    assert "pass_placeholder" not in _ids(disabled)
    assert again["deficit_score"] == pytest.approx(first["deficit_score"])
    assert "pass_placeholder" in _ids(again)
