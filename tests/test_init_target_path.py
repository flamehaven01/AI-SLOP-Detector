"""`--init` writes to, and reads from, the path it is given.

`_run_init` hard-coded `Path(".")`: `slop-detector <repo> --init` analyzed
the working directory and wrote `.slopconfig.yaml` and `.gitignore` there,
not into `<repo>`. Every read and write of an init (config, `.gitignore`,
domain detection, adaptive signals, the existing-config merge) now uses the
given path; a path that does not exist or is a file is refused before
anything is written.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from slop_detector.cli import main


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (target / "app.py").write_text("import fastapi\nimport flask\n", encoding="utf-8")
    monkeypatch.chdir(cwd)
    return cwd, target


def _files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("order", ["path_first", "flag_first"])
def test_init_writes_into_the_target(dirs, order):
    cwd, target = dirs
    argv = [str(target), "--init"] if order == "path_first" else ["--init", str(target)]
    assert main(argv) == 0
    assert (target / ".slopconfig.yaml").exists()
    assert ".slopconfig.yaml" in (target / ".gitignore").read_text(encoding="utf-8")
    assert _files(cwd) == {}


def test_default_path_is_the_working_directory(dirs, monkeypatch):
    """Preservation: `--init` with no path still initializes the cwd."""
    _, target = dirs
    monkeypatch.chdir(target)
    assert main(["--init"]) == 0
    assert (target / ".slopconfig.yaml").exists()


def test_preview_analyzes_the_target_and_writes_nothing(dirs, capsys):
    cwd, target = dirs
    before = _files(target)
    assert main(["--init", "--adaptive-init", "--init-preview", str(target)]) == 0
    out = capsys.readouterr().out
    assert "Domain       : web/api" in out
    assert "'python': 1," in out  # adaptive signals: target/app.py, not the empty cwd
    assert _files(target) == before
    assert _files(cwd) == {}


def test_force_init_overwrites_only_the_target_config(dirs):
    cwd, target = dirs
    (target / ".slopconfig.yaml").write_text("# old target config\n", encoding="utf-8")
    (cwd / ".slopconfig.yaml").write_bytes(b"# cwd config\n")
    assert main(["--init", "--force-init", str(target)]) == 0
    assert (target / ".slopconfig.yaml").read_text(encoding="utf-8") != "# old target config\n"
    assert _files(cwd) == {".slopconfig.yaml": b"# cwd config\n"}


def test_adaptive_merge_reads_the_target_config(dirs, capsys):
    cwd, target = dirs
    (target / ".slopconfig.yaml").write_text("custom_key: kept\n", encoding="utf-8")
    argv = ["--init", "--adaptive-init", "--apply-init-suggestions", str(target)]
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "Domain detected: web/api" in out
    merged = yaml.safe_load((target / ".slopconfig.yaml").read_text(encoding="utf-8"))
    assert merged["custom_key"] == "kept"
    assert _files(cwd) == {}


def test_missing_target_is_refused(dirs, tmp_path, capsys):
    cwd, _ = dirs
    missing = tmp_path / "missing"
    assert main(["--init", str(missing)]) != 0
    assert "does not exist" in capsys.readouterr().err
    assert not missing.exists()
    assert _files(cwd) == {}


def test_file_target_is_refused(dirs, capsys):
    cwd, target = dirs
    before = _files(target)
    assert main(["--init", str(target / "app.py")]) != 0
    assert "not a directory" in capsys.readouterr().err
    assert _files(target) == before
    assert _files(cwd) == {}
