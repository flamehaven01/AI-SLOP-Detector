"""`--ci-mode` adds an exit policy to a normal scan; `--ci-report` asks for the gate report.

Since the v2.9.1 refactor (2a87d03) and the exit-code fix (0d67997), any CI
option returned from main() right after the gate: `--ci-mode hard` printed
nothing (text, --json, and --output alike) and skipped the rest of the scan
(history, optional features). The shipped pre-commit "warn" hook, described as
"reports findings", was silent. And `--ci-report --output FILE` wrote no file.

Contract:
  --ci-mode (without --ci-report): the normal scan, output, and post-analysis
    pipeline, then the gate's exit code.
  --ci-report: only the gate report (text, or JSON with --json), to --output
    when given (nothing duplicated on stdout), else stdout; the gate's exit code.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from slop_detector.cli import main

CLEAN = "def add(a, b):\n    return a + b\n"
FAILING = "".join(
    f"def f{i}(x):\n    try:\n        return int(x)\n    except:\n        pass\n\n\n"
    for i in range(4)
)
GATE_MARKER = "AI Code Quality Report"


@pytest.fixture
def clean(tmp_path):
    path = tmp_path / "clean.py"
    path.write_text(CLEAN, encoding="utf-8")
    return path


@pytest.fixture
def failing(tmp_path):
    path = tmp_path / "failing.py"
    path.write_text(FAILING, encoding="utf-8")
    return path


def _run(capsys, *args):
    code = main([*map(str, args)])
    out = capsys.readouterr().out
    return code, out


# ---------------------------------------------------------------------------
# --ci-mode: normal scan + exit policy
# ---------------------------------------------------------------------------


def test_soft_mode_prints_the_normal_report(capsys, clean):
    code, out = _run(capsys, clean, "--ci-mode", "soft", "--no-history", "--no-color")
    assert code == 0
    assert "clean.py" in out and GATE_MARKER not in out


def test_hard_mode_on_a_passing_file_prints_the_report_and_exits_zero(capsys, clean):
    code, out = _run(capsys, clean, "--ci-mode", "hard", "--no-history", "--no-color")
    assert code == 0
    assert "clean.py" in out


def test_hard_mode_on_a_failing_file_prints_the_report_and_exits_one(capsys, failing):
    code, out = _run(capsys, failing, "--ci-mode", "hard", "--no-history", "--no-color")
    assert code == 1
    assert "failing.py" in out


def test_hard_mode_json_is_the_normal_analysis_json(capsys, failing):
    code, out = _run(capsys, failing, "--ci-mode", "hard", "--json", "--no-history")
    assert out.strip(), "no JSON printed"
    payload = json.loads(out)
    assert code == 1
    assert "ldr" in payload and "verdict" not in payload


def test_hard_mode_output_file_holds_the_normal_report(capsys, tmp_path, failing):
    report = tmp_path / "report.txt"
    code, _ = _run(capsys, failing, "--ci-mode", "hard", "--output", report, "--no-history")
    assert code == 1
    assert report.exists() and "failing.py" in report.read_text(encoding="utf-8")


def test_ci_mode_keeps_the_post_analysis_pipeline(capsys, clean):
    with patch("slop_detector.cli._record_history") as history:
        code, _ = _run(capsys, clean, "--ci-mode", "soft", "--no-color")
    assert code == 0
    history.assert_called_once()


def test_claims_strict_alone_prints_the_normal_report(capsys, clean):
    code, out = _run(capsys, clean, "--ci-claims-strict", "--json", "--no-history")
    assert out.strip(), "no JSON printed"
    assert "ldr" in json.loads(out)
    assert code == 0


# ---------------------------------------------------------------------------
# --ci-report: the gate report
# ---------------------------------------------------------------------------


def test_ci_report_prints_the_gate_report(capsys, clean):
    code, out = _run(capsys, clean, "--ci-report", "--no-history")
    assert code == 0
    assert GATE_MARKER in out


def test_ci_report_output_file_holds_the_gate_report_only(capsys, tmp_path, clean):
    gate = tmp_path / "gate.txt"
    code, out = _run(capsys, clean, "--ci-report", "--output", gate, "--no-history")
    assert code == 0
    assert gate.exists(), "no gate report file"
    assert GATE_MARKER in gate.read_text(encoding="utf-8")
    assert GATE_MARKER not in out


def test_ci_report_json_output_file_and_exit_code(capsys, tmp_path, failing):
    gate = tmp_path / "gate.json"
    code, out = _run(
        capsys,
        failing,
        "--ci-mode",
        "hard",
        "--ci-report",
        "--json",
        "--output",
        gate,
        "--no-history",
    )
    assert gate.exists(), "no gate report file"
    payload = json.loads(gate.read_text(encoding="utf-8"))
    assert code == 1
    assert payload["verdict"] == "fail" and payload["mode"] == "hard"
    assert '"verdict"' not in out


def test_output_help_says_how_json_is_selected():
    from slop_detector.cli_parsers import _build_arg_parser

    help_text = " ".join(_build_arg_parser().format_help().split())
    assert "JSON requires --json or --format json" in help_text
