"""The SNP gate (`--gate`) judges only what was measured.

DDC is a Python metric. A project without a Python file has no DDC; its stored
average is 0.0, and the gate read that as `ddc=0.000 < threshold=0.5`: HALT,
for a project of Rust and JS/TS files, on a metric nobody measured. The CI
gate already follows the rule (an unmeasured metric is never judged).

- no Python file with DDC: DDC is not judged, and the decision says so;
- the other metrics are still judged;
- a Python project whose imports are unused still halts on DDC (positive control);
- a decision on measured values is unchanged, hash included.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from slop_detector.cli_commands import _run_gate
from slop_detector.core import SlopDetector
from slop_detector.gate.slop_gate import SlopGate

RUST_CLEAN = "pub fn add(a: u8, b: u8) -> u8 {\n    a + b\n}\n"
PY_ALL_IMPORTS_UNUSED = (
    "import json\nimport csv\nimport sqlite3\n\n\n"
    "def total(values):\n    result = 0\n    for value in values:\n        result += value\n"
    "    return result\n"
)


def _scan(root: Path, files: dict):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(root))


def test_python_project_with_unused_imports_still_halts_on_ddc(tmp_path, capsys):
    """Positive control: a measured DDC below the threshold halts."""
    _run_gate(_scan(tmp_path, {"pkg/calc.py": PY_ALL_IMPORTS_UNUSED}))
    out = capsys.readouterr().out
    assert "Status   : HALT" in out, out
    assert "ddc=0.000 < threshold=0.5" in out, out
    assert "Not judged" not in out, out


def test_project_without_python_is_not_halted_on_ddc(tmp_path, capsys):
    _run_gate(_scan(tmp_path, {"src/lib.rs": RUST_CLEAN}))
    out = capsys.readouterr().out
    assert "ddc=" not in out, out
    assert "Status   : PASS" in out, out
    assert "Not judged: di2" in out, out
    assert "di2=n/a" in out, out


def test_the_other_metrics_are_still_judged_without_ddc():
    decision = SlopGate().evaluate(0.30, None, 0.0, 0.0, "project")
    assert decision.status == "HALT"
    assert decision.failed_conditions == ("ldr=0.300 < threshold=0.6",)
    assert decision.not_measured == ("di2",)


def test_an_unmeasured_ddc_is_recorded_and_hashed_apart_from_a_measured_one():
    gate = SlopGate()
    unmeasured = gate.evaluate(0.9, None, 0.0, 0.0)
    measured = gate.evaluate(0.9, 1.0, 0.0, 0.0)
    assert unmeasured.status == measured.status == "PASS"
    assert unmeasured.not_measured == ("di2",) and measured.not_measured == ()
    assert unmeasured.to_dict()["not_measured"] == ["di2"]
    assert unmeasured.audit_hash != measured.audit_hash


def test_a_decision_on_measured_values_keeps_its_hash():
    """The audit hash of a fully measured decision is what it was before."""
    decision = SlopGate().evaluate(0.9, 0.8, 0.4, 5.0)
    payload = "di2=0.800000|jsd=0.800000|ove=0.900000|sr9=0.900000"
    assert decision.audit_hash == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert decision.to_dict()["not_measured"] == []


# --- Inspector INS-3161-01..03: nothing measured, an incomplete scan, inflation ---

PY_CLEAN = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"


def _fail_analysis_of(monkeypatch, name: str) -> None:
    original = SlopDetector._build_file_analysis

    def build(self, file_path, *args, **kwargs):
        if Path(file_path).name == name:
            raise AttributeError("analysis raised")
        return original(self, file_path, *args, **kwargs)

    monkeypatch.setattr(SlopDetector, "_build_file_analysis", build)


def test_a_clean_python_project_is_still_called_healthy_and_passes(tmp_path, capsys):
    """Positive control for the three rules below."""
    from slop_detector.renderer_glossary import next_steps

    result = _scan(tmp_path, {"pkg/calc.py": PY_CLEAN})
    assert "All metrics are healthy" in next_steps(result)[0]
    _run_gate(result)
    out = capsys.readouterr().out
    assert "Status   : PASS" in out and "Not judged" not in out, out
    assert "jsd=1.0000" in out, out  # inflation was measured: 0.0


def test_a_project_with_nothing_measured_is_not_called_healthy(tmp_path):
    """INS-3161-01: the score reads NOT EVALUATED; the advice must not read "healthy"."""
    from slop_detector.renderer_glossary import next_steps

    result = _scan(tmp_path, {})
    assert result.scan_coverage["score_valid"] is False
    steps = next_steps(result)
    assert len(steps) == 1 and steps[0].startswith("Not evaluated"), steps
    assert "healthy" not in steps[0] and "no action needed" not in steps[0]
    assert result.to_dict()["next_steps"] == steps


def test_the_gate_does_not_pass_or_judge_a_project_with_nothing_measured(tmp_path, capsys):
    """INS-3161-02: no measurement is not a decision on `ldr=0.000`."""
    _run_gate(_scan(tmp_path, {}))
    out = capsys.readouterr().out
    assert "Status   : HALT" in out, out
    assert "not evaluated" in out and "ldr=" not in out, out
    assert "sr9=n/a  di2=n/a  jsd=n/a  ove=n/a" in out, out


def test_the_gate_does_not_pass_an_incomplete_scan(tmp_path, capsys, monkeypatch):
    """INS-3161-02: a file that could not be analyzed fails the gate closed."""
    _fail_analysis_of(monkeypatch, "broken.py")
    result = _scan(tmp_path, {"pkg/calc.py": PY_CLEAN, "pkg/broken.py": PY_CLEAN})
    assert result.scan_coverage["complete"] is False
    _run_gate(result)
    out = capsys.readouterr().out
    assert "Status   : HALT" in out, out
    assert "analysis incomplete: 1 file(s) could not be analyzed" in out, out


def test_inflation_nobody_measured_is_not_recorded_as_a_good_value(tmp_path, capsys):
    """INS-3161-03: inflation is a Python metric too; `jsd=1.0000` was a made-up best value."""
    _run_gate(_scan(tmp_path, {"src/lib.rs": RUST_CLEAN}))
    out = capsys.readouterr().out
    assert "jsd=n/a" in out and "di2=n/a" in out, out
    assert "Not judged: di2, jsd" in out, out
    assert "Status   : PASS" in out, out


def test_a_measured_inflation_is_still_judged():
    gate = SlopGate()
    assert gate.evaluate(0.9, 0.9, 2.0, 0.0).failed_conditions == (
        "inflation=2.000 > threshold=1.5",
    )
    unmeasured = gate.evaluate(0.9, 0.9, None, 0.0)
    assert unmeasured.status == "PASS" and unmeasured.not_measured == ("jsd",)
