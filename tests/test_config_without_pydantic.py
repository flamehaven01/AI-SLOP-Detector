"""Config validation does not depend on pydantic.

Validation used pydantic, and a named config that could not be validated was
refused. In an environment without pydantic (a stripped or engine-local
install) every project with a .slopconfig.yaml then failed to start, which a
CI or Inspector run reports as a process failure. The validator now uses the
standard library only: same strictness, same messages, any environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_SRC = str(Path(__file__).resolve().parents[1] / "src")

# Runs argv[1:] as the CLI, or loads argv[2] as a Config, with pydantic unimportable.
BLOCKED = """
import runpy, sys
sys.modules["pydantic"] = None
if sys.argv[1] == "config":
    from slop_detector.config import Config
    try:
        Config(sys.argv[2])
        print("LOADED")
    except ValueError as exc:
        print("REFUSED", exc)
else:
    sys.argv = ["slop_detector.cli"] + sys.argv[1:]
    runpy.run_module("slop_detector.cli", run_name="__main__")
"""


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    script = tmp_path / "blocked.py"
    script.write_text(BLOCKED, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=REPO_SRC, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, env=env, timeout=180
    )


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".slopconfig.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_config_loads_without_pydantic(tmp_path):
    path = _config(
        tmp_path, "weights:\n  ldr: 0.5\npatterns:\n  god_function:\n    lines_threshold: 60\n"
    )
    assert _run(tmp_path, "config", str(path)).stdout.strip() == "LOADED"


def test_invalid_config_is_still_refused_without_pydantic(tmp_path):
    path = _config(tmp_path, 'thresholds:\n  ldr:\n    good: "x"\n')
    out = _run(tmp_path, "config", str(path)).stdout
    assert out.startswith("REFUSED") and "thresholds.ldr.good" in out


def test_inspector_scan_of_a_configured_project_runs_without_pydantic(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    _config(project, "patterns:\n  god_function:\n    lines_threshold: 60\n")
    result = _run(
        tmp_path,
        "scan",
        str(project),
        "--project",
        "--json",
        "--no-history",
        "--inspector-read-only",
    )
    assert result.returncode == 0, result.stderr[-400:]
