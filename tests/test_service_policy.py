"""Pure scan policy shared by the CLI and ScanService.

Config path resolution, target routing, gate evaluation and exit policy lived
inside cli.main. They are now functions with no output and no writes (except
the quarantine gate, which keeps its file and is refused under read-only).

Behavior change: --fail-threshold treated a scan whose every file failed as a
0.0 score and passed it. It now fails; a scan with nothing to measure (no
eligible or only excluded files) is not evaluated and does not fail.
"""

from __future__ import annotations

import pytest

from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.service.policy import (
    evaluate_gate,
    gate_exit_code,
    resolve_config_path,
    threshold_breach,
)
from slop_detector.service.targets import target_kind

CODE = "def f(x):\n    return x + 1\n"


def _fail_all_analysis(monkeypatch) -> None:
    def build(*args, **kwargs):
        raise AttributeError("analysis raised")

    monkeypatch.setattr(SlopDetector, "_build_file_analysis", build)


# -- config path ------------------------------------------------------------


def test_explicit_config_wins(tmp_path):
    (tmp_path / ".slopconfig.yaml").write_text("", encoding="utf-8")
    assert resolve_config_path(tmp_path, True, "other.yaml") == "other.yaml"


def test_project_config_is_found_in_the_project_root(tmp_path):
    (tmp_path / ".slopconfig.yaml").write_text("", encoding="utf-8")
    assert resolve_config_path(tmp_path, True, None) == str(tmp_path / ".slopconfig.yaml")


def test_file_config_is_found_next_to_the_file(tmp_path):
    (tmp_path / ".slopconfig.yaml").write_text("", encoding="utf-8")
    target = tmp_path / "m.py"
    assert resolve_config_path(target, False, None) == str(tmp_path / ".slopconfig.yaml")


def test_no_config_found(tmp_path):
    assert resolve_config_path(tmp_path, True, None) is None


# -- target routing -----------------------------------------------------------


@pytest.mark.parametrize(
    "name, project, kind",
    [
        ("m.py", False, "python_file"),
        ("app.js", False, "source_file"),
        ("view.tsx", False, "source_file"),
        ("main.go", False, "source_file"),
        ("m.py", True, "project"),
    ],
)
def test_target_kind(tmp_path, name, project, kind):
    assert target_kind(tmp_path / name, project) == kind


# -- gate -------------------------------------------------------------------------


def test_no_gate_requested():
    assert evaluate_gate(object(), mode=None, claims_strict=False, read_only=False) is None


def test_quarantine_is_refused_under_read_only(tmp_path):
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    with pytest.raises(ValueError, match="quarantine"):
        evaluate_gate(result, mode="quarantine", claims_strict=False, read_only=True)


def test_hard_gate_writes_nothing_under_read_only(tmp_path, monkeypatch):
    project = tmp_path / "p"
    project.mkdir()
    (project / "m.py").write_text(CODE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = SlopDetector(read_only=True).analyze_project(str(project))
    before = sorted(p.name for p in tmp_path.rglob("*"))
    gate = evaluate_gate(result, mode="hard", claims_strict=False, read_only=True)
    assert gate is not None and gate_exit_code(gate) in (0, 1)
    assert sorted(p.name for p in tmp_path.rglob("*")) == before


# -- fail threshold --------------------------------------------------------------


def test_threshold_breach_on_a_measured_score(tmp_path):
    (tmp_path / "m.py").write_text(CODE, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    result.weighted_deficit_score = 80.0
    assert threshold_breach(result, 70.0) is not None
    assert threshold_breach(result, 80.0) is None  # equal to the threshold passes
    assert threshold_breach(result, 90.0) is None
    assert threshold_breach(result, None) is None


def test_threshold_fails_when_every_file_failed(tmp_path, monkeypatch):
    (tmp_path / "m.py").write_text(CODE, encoding="utf-8")
    _fail_all_analysis(monkeypatch)
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    assert "no file could be analyzed" in threshold_breach(result, 70.0)


def test_threshold_does_not_fail_with_nothing_to_measure(tmp_path):
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    assert threshold_breach(result, 70.0) is None


def test_cli_fail_threshold_exit_codes(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main([str(empty), "--fail-threshold", "70", "--no-history"]) == 0
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "m.py").write_text(CODE, encoding="utf-8")
    _fail_all_analysis(monkeypatch)
    assert main([str(broken), "--fail-threshold", "70", "--no-history"]) == 1


def test_threshold_uses_the_file_score_for_a_file(tmp_path):
    path = tmp_path / "m.py"
    path.write_text(CODE, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    result.deficit_score = 80.0
    assert threshold_breach(result, 70.0) is not None


def test_policy_module_does_not_print(tmp_path, capsys):
    """The functions return decisions; the CLI prints them."""
    (tmp_path / "m.py").write_text(CODE, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    evaluate_gate(result, mode="hard", claims_strict=False, read_only=True)
    threshold_breach(result, 0.0)
    resolve_config_path(tmp_path, True, None)
    assert capsys.readouterr() == ("", "")
