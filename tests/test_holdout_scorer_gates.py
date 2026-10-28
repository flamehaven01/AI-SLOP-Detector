"""Hold-out scorers never take a failed CLI run, or a degenerate bootstrap, as a measurement."""

import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score_v2 = _load("holdout_v2_score", "benchmarks/holdout_v2/score.py")
fast_replay = _load("fast_replay_for_exit", "scripts/dev/fast_replay.py")

COMPLETE_JSON = json.dumps(
    {"file_results": [], "scan_coverage": {"measurement_state": "COMPLETE"}}
).encode()


def _fake_run(returncode):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout=COMPLETE_JSON, stderr=b"boom")

    return run


def test_v2_scan_nonzero_exit_is_env_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(score_v2.subprocess, "run", _fake_run(1))
    assert score_v2.scan(tmp_path)["state"] == "ENV_BLOCKED"


def test_v2_scan_zero_exit_keeps_reported_state(monkeypatch, tmp_path):
    monkeypatch.setattr(score_v2.subprocess, "run", _fake_run(0))
    assert score_v2.scan(tmp_path)["state"] == "COMPLETE"


def test_fast_replay_nonzero_exit_is_not_complete(monkeypatch, tmp_path):
    monkeypatch.setattr(fast_replay.subprocess, "run", _fake_run(2))
    _, files, state = fast_replay._full_pipeline("src", tmp_path, {"ignored_parameter"})
    assert state != "COMPLETE" and files == 0


def _rows(flags):
    return [{"repo": f"r{i % 3}", "f": bool(x)} for i, x in enumerate(flags)]


def test_bootstrap_with_no_observed_flags_is_not_informative():
    result = score_v2._bootstrap(_rows([0, 0, 0, 0]), "f")
    assert result["ci95"] is None and "not informative" in result["note"]


def test_bootstrap_with_all_flagged_is_not_informative():
    assert score_v2._bootstrap(_rows([1, 1, 1]), "f")["ci95"] is None


def test_bootstrap_with_mixed_flags_has_an_interval():
    lo, hi = score_v2._bootstrap(_rows([1, 0, 0, 1, 0, 0]), "f")["ci95"]
    assert 0.0 <= lo <= hi <= 1.0
