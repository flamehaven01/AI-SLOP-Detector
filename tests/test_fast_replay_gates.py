"""scripts/dev/fast_replay.py never reports an incomplete measurement as success."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "dev" / "fast_replay.py"
spec = importlib.util.spec_from_file_location("fast_replay", SCRIPT)
fast_replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fast_replay)

FINDING = {"file": "a.py", "line": 3, "pattern": "ignored_parameter", "message": "m"}
FULL = {("a.py", 3, "ignored_parameter", "m")}


def _repo(state="COMPLETE", files=2):
    return {"repo": "r", "coverage_state": state, "analyzed_files": files, "findings": [FINDING]}


def test_parity_matches_only_when_both_sides_complete_and_agree():
    assert fast_replay.parity_state(_repo(), FULL, 2, "COMPLETE") == "MATCH"


def test_parity_incomplete_fast_side_is_not_a_match():
    assert fast_replay.parity_state(_repo("PARTIAL"), FULL, 2, "COMPLETE") == "INCOMPLETE"


def test_parity_incomplete_full_side_is_not_a_match():
    assert fast_replay.parity_state(_repo(), FULL, 2, "PARTIAL") == "INCOMPLETE"


def test_parity_different_file_count_is_a_mismatch():
    assert fast_replay.parity_state(_repo(files=1), FULL, 2, "COMPLETE") == "MISMATCH"


def test_run_exits_non_zero_on_any_incomplete_repo():
    complete, partial = _repo(), _repo("PARTIAL")
    assert fast_replay.run_exit({"repos": [complete, complete]}) == 0
    assert fast_replay.run_exit({"repos": [complete, partial]}) == 1
    assert fast_replay.run_exit({"repos": [_repo("NO_MEASUREMENT")]}) == 1


@pytest.fixture
def scan_env(monkeypatch, tmp_path):
    """Restore HOME, USERPROFILE and sys.path that _scan_repo changes."""
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(tmp_path / "real_home"))
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    home = tmp_path / "replay_home"
    home.mkdir()
    monkeypatch.setattr(fast_replay.tempfile, "mkdtemp", lambda prefix: str(home))
    return home


def test_temp_home_removed_after_scan(monkeypatch, scan_env):
    monkeypatch.setattr(fast_replay, "_scan", lambda repo, patterns: {})
    result = fast_replay._scan_repo(("src", "repo", {"ignored_parameter"}))
    assert not scan_env.exists() and result["temp_home_left"] is False


def test_temp_home_removed_when_scan_raises(monkeypatch, scan_env):
    def boom(repo, patterns):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(fast_replay, "_scan", boom)
    with pytest.raises(RuntimeError):
        fast_replay._scan_repo(("src", "repo", {"ignored_parameter"}))
    assert not scan_env.exists()


@pytest.mark.parametrize("patterns", ["no_such_pattern", ""])
def test_unknown_or_empty_pattern_ids_refused(monkeypatch, tmp_path, patterns):
    src = str(SCRIPT.parents[2] / "src")
    monkeypatch.setattr(sys, "path", list(sys.path))
    out = str(tmp_path / "x.json")
    argv = ["fast_replay.py", "run", "--src", src, "--repos", str(tmp_path), "--out", out]
    monkeypatch.setattr(sys, "argv", argv + ["--patterns", patterns, "r"])
    with pytest.raises(SystemExit) as exc:
        fast_replay.main()
    assert exc.value.code == 2
