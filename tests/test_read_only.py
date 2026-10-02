"""Controls for `--read-only`: a scan that leaves no change in the target or in the
detector's own persistent state.

The contract is narrower than "no byte is written anywhere": the detector writes
nothing to the analyzed project and creates or modifies none of its own state
(history, impact, telemetry, analysis cache). Write-capable options are refused.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from slop_detector.cli import main
from slop_detector.core import SlopDetector

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")

State = Dict[str, Tuple[int, str, int]]


def _state(*roots: Path) -> State:
    """relative path -> (size, sha256, mtime_ns) for every file under the roots."""
    snapshot: State = {}
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            data = path.read_bytes()
            key = f"{root.name}/{path.relative_to(root).as_posix()}"
            snapshot[key] = (len(data), hashlib.sha256(data).hexdigest(), path.stat().st_mtime_ns)
    return snapshot


def _cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the CLI in a child process whose HOME is `home` (state paths bind at import)."""
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONPATH=REPO_SRC)
    return subprocess.run(
        [sys.executable, "-m", "slop_detector.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
    )


def _project(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "p"\nversion = "0"\n', encoding="utf-8")
    (root / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    return root


def _main(argv: List[str], capsys) -> Tuple[object, str]:
    """Run main() and return (exit code, stderr); argparse exits via SystemExit."""
    try:
        code: object = main(argv)
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr().err


def _diff(before: State, after: State) -> List[str]:
    created = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return (
        [f"created {k}" for k in created]
        + [f"removed {k}" for k in removed]
        + [f"modified {k}" for k in changed]
    )


# ---------------------------------------------------------------------------
# Acceptance: nothing is created or changed
# ---------------------------------------------------------------------------


def test_read_only_scan_creates_nothing_in_a_fresh_home(tmp_path):
    home, project = tmp_path / "home", _project(tmp_path / "proj")
    home.mkdir()
    before = _state(home, project)
    result = _cli(home, "scan", str(project), "--read-only", "--json")
    assert result.returncode == 0, result.stderr[-400:]
    assert _diff(before, _state(home, project)) == []


def test_read_only_scan_leaves_existing_state_untouched_even_for_a_new_file(tmp_path):
    """Seed history, cache and impact with a normal run, then scan a NEW file read-only.

    A new file is a cache miss, so a cache that is merely consulted (not disabled)
    would write; the project's enabled impact tracking would record a run.
    """
    home, project = tmp_path / "home", _project(tmp_path / "proj")
    home.mkdir()
    assert _cli(home, "impact", "enable", str(project)).returncode == 0
    seed = _cli(home, "scan", str(project), "--json")
    assert seed.returncode == 0, seed.stderr[-400:]
    (project / "extra.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    before = _state(home, project)
    assert any("analysis_cache.db" in k for k in before), "seed did not create the cache"
    assert any("history.db" in k for k in before), "seed did not create history"

    result = _cli(
        home, "scan", str(project), "--read-only", "--json", "--cross-file", "--gate", "--js"
    )
    assert result.returncode == 0, result.stderr[-400:]
    assert _diff(before, _state(home, project)) == []


def test_without_the_flag_the_same_run_does_write_state(tmp_path):
    """Negative control: the acceptance checks above can fail."""
    home, project = tmp_path / "home", _project(tmp_path / "proj")
    home.mkdir()
    before = _state(home, project)
    assert _cli(home, "scan", str(project), "--json").returncode == 0
    assert _diff(before, _state(home, project)), "a normal run left no trace; the control is blind"


# ---------------------------------------------------------------------------
# The engine is built read-only: the cache must not exist at all
# ---------------------------------------------------------------------------


def test_detector_read_only_builds_no_analysis_cache(tmp_path):
    assert "read_only" in inspect.signature(SlopDetector).parameters, "no read_only parameter"
    cache_db = tmp_path / "state" / "cache.db"
    config = tmp_path / "c.yaml"
    config.write_text(
        f'advanced:\n  analysis_cache_db: "{cache_db.as_posix()}"\n', encoding="utf-8"
    )
    detector = SlopDetector(config_path=str(config), read_only=True)
    assert detector._analysis_cache is None
    assert not cache_db.parent.exists()


def test_detector_default_still_builds_the_cache(tmp_path):
    """Preservation: only read-only mode removes the cache."""
    cache_db = tmp_path / "state" / "cache.db"
    config = tmp_path / "c.yaml"
    config.write_text(
        f'advanced:\n  analysis_cache_db: "{cache_db.as_posix()}"\n', encoding="utf-8"
    )
    detector = SlopDetector(config_path=str(config))
    assert detector._analysis_cache is not None and cache_db.exists()


# ---------------------------------------------------------------------------
# Refusal of write-capable options
# ---------------------------------------------------------------------------

WRITE_OPTIONS = [
    ["--output", "out.json"],
    ["--fix"],
    ["--governance"],
    ["--emit-leda-yaml"],
    ["--show-history"],
    ["--history-trends"],
    ["--export-history", "h.jsonl"],
    ["--self-calibrate"],
    ["--apply-calibration", "x"],
    ["--init"],
    ["--ci-mode", "soft"],
    ["--ci-report"],
]


@pytest.mark.parametrize("option", WRITE_OPTIONS, ids=lambda o: o[0])
def test_read_only_refuses_write_capable_options(tmp_path, capsys, option):
    code, err = _main(["scan", str(_project(tmp_path / "p")), "--read-only", *option], capsys)
    assert code == 2
    assert "--read-only is incompatible with" in err and option[0] in err


def test_help_documents_the_read_only_flag():
    from slop_detector.cli_parsers import _build_arg_parser

    assert "--read-only" in _build_arg_parser().format_help()
