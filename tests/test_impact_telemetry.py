import json
from pathlib import Path

from slop_detector.cli import main
from slop_detector.impact import ImpactTracker
from slop_detector.models import DDCResult, FileAnalysis, InflationResult, LDRResult, SlopStatus
from slop_detector.telemetry import TelemetryManager


def _file_result(score: float = 12.5, status: SlopStatus = SlopStatus.CLEAN) -> FileAnalysis:
    return FileAnalysis(
        file_path="src/example.py",
        ldr=LDRResult(100, 80, 20, 0.8, "A"),
        inflation=InflationResult(3, 1.5, 0.4, "PASS", [], []),
        ddc=DDCResult(["json"], ["json"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=score,
        status=status,
        pattern_issues=[],
    )


def test_impact_tracker_enable_record_and_summary(tmp_path: Path):
    tracker = ImpactTracker(tmp_path)

    tracker.enable()
    tracker.record("scan", _file_result(score=18.0, status=SlopStatus.SUSPICIOUS))
    tracker.record("scan", _file_result(score=11.0, status=SlopStatus.CLEAN))

    summary = tracker.summary()

    assert summary["enabled"] is True
    assert summary["runs_recorded"] == 2
    assert summary["direction"] == "improved"
    assert summary["score_delta"] == -7.0
    assert tracker.impact_path.exists()


def test_telemetry_manager_enable_and_capture(tmp_path: Path):
    config_path = tmp_path / "telemetry.json"
    queue_path = tmp_path / "telemetry-events.jsonl"
    manager = TelemetryManager(config_path=config_path, queue_path=queue_path)

    status = manager.enable()
    assert status["enabled"] is True

    payload = manager.capture(
        "scan", _file_result(score=22.0, status=SlopStatus.SUSPICIOUS), tmp_path
    )
    assert payload is not None
    queued = queue_path.read_text(encoding="utf-8").splitlines()
    assert len(queued) == 1
    parsed = json.loads(queued[0])
    assert parsed["command"] == "scan"
    assert parsed["analysis"]["weighted_deficit_score"] == 22.0


def test_telemetry_manager_inspect_mode_does_not_queue(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "telemetry.json"
    queue_path = tmp_path / "telemetry-events.jsonl"
    manager = TelemetryManager(config_path=config_path, queue_path=queue_path)

    manager.enable()
    monkeypatch.setenv("AI_SLOP_DETECTOR_TELEMETRY", "inspect")
    payload = manager.capture(
        "review",
        _file_result(score=19.0, status=SlopStatus.SUSPICIOUS),
        tmp_path,
    )

    assert payload is not None
    assert payload["command"] == "review"
    assert not queue_path.exists()


def test_telemetry_manager_example_payload():
    payload = TelemetryManager(
        config_path=Path("telemetry.json"), queue_path=Path("events.jsonl")
    ).example_payload()
    assert payload["event"] == "analysis_run"
    assert payload["analysis"]["project_mode"] is True


def test_cli_impact_enable_and_summary_json(tmp_path: Path, capsys):
    assert main(["impact", "enable", str(tmp_path), "--json"]) == 0
    enable_out = json.loads(capsys.readouterr().out)
    assert enable_out["enabled"] is True

    tracker = ImpactTracker(tmp_path)
    tracker.record("scan", _file_result(score=17.0, status=SlopStatus.SUSPICIOUS))

    assert main(["impact", "summary", str(tmp_path), "--json"]) == 0
    summary_out = json.loads(capsys.readouterr().out)
    assert summary_out["runs_recorded"] == 1
    assert summary_out["latest_run"]["command"] == "scan"


def test_cli_telemetry_enable_and_inspect_json(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("AI_SLOP_DETECTOR_HOME", str(tmp_path / "home"))

    assert main(["telemetry", "enable", "--json"]) == 0
    enable_out = json.loads(capsys.readouterr().out)
    assert enable_out["enabled"] is True

    assert main(["telemetry", "inspect", "--example", "--json"]) == 0
    inspect_out = json.loads(capsys.readouterr().out)
    assert inspect_out["event"] == "analysis_run"
