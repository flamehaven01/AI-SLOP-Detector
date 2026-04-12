"""Tests for LEDA injection emission."""

from unittest.mock import patch

import yaml

from slop_detector.leda_injection import build_leda_injection, write_leda_injection
from slop_detector.models import DDCResult, FileAnalysis, InflationResult, LDRResult, SlopStatus


def _sample_file_result() -> FileAnalysis:
    return FileAnalysis(
        file_path="/tmp/model.py",
        ldr=LDRResult(100, 70, 30, 0.70, "A"),
        inflation=InflationResult(3, 2.0, 0.4, "PASS", ["bounded"], []),
        ddc=DDCResult(["math"], ["math"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=22.0,
        status=SlopStatus.CLEAN,
        warnings=[],
    )


def test_build_leda_injection_has_expected_sections(tmp_path):
    result = _sample_file_result()
    fake_tracker = type(
        "Tracker",
        (),
        {"db_path": tmp_path / "history.db", "count_total_records": lambda self: 0},
    )()
    fake_calibration = type(
        "Calibration",
        (),
        {
            "status": "insufficient_data",
            "unique_files": 0,
            "improvement_events": 0,
            "fp_candidates": 0,
            "confidence_gap": 0.0,
            "current_weights": {"ldr": 0.4, "inflation": 0.3, "ddc": 0.3},
            "optimal_weights": {},
        },
    )()

    with (
        patch("slop_detector.leda_injection.HistoryTracker", return_value=fake_tracker),
        patch("slop_detector.leda_injection.SelfCalibrator") as calibrator_cls,
    ):
        calibrator_cls.return_value.calibrate.return_value = fake_calibration
        payload = build_leda_injection(result, path=str(tmp_path))

    assert payload["version"] == "0.1"
    assert payload["source"]["analyzer"] == "LEDA"
    assert payload["analysis"]["mode"] == "file"
    assert "maturity" in payload
    assert "spar_review_hints" in payload


def test_write_leda_injection_writes_yaml(tmp_path):
    fake_tracker = type(
        "Tracker",
        (),
        {"db_path": tmp_path / "history.db", "count_total_records": lambda self: 0},
    )()
    fake_calibration = type(
        "Calibration",
        (),
        {
            "status": "insufficient_data",
            "unique_files": 0,
            "improvement_events": 0,
            "fp_candidates": 0,
            "confidence_gap": 0.0,
            "current_weights": {"ldr": 0.4, "inflation": 0.3, "ddc": 0.3},
            "optimal_weights": {},
        },
    )()
    with (
        patch("slop_detector.leda_injection.HistoryTracker", return_value=fake_tracker),
        patch("slop_detector.leda_injection.SelfCalibrator") as calibrator_cls,
    ):
        calibrator_cls.return_value.calibrate.return_value = fake_calibration
        payload = build_leda_injection(_sample_file_result(), path=str(tmp_path))

    output = write_leda_injection(tmp_path / "reports" / "leda_injection.yaml", payload)

    assert output.exists()
    loaded = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert loaded["project"]["name"] == tmp_path.name
    assert loaded["source"]["analyzer"] == "LEDA"


def test_build_leda_injection_public_profile_redacts_sensitive_fields(tmp_path):
    fake_tracker = type(
        "Tracker",
        (),
        {"db_path": tmp_path / "history.db", "count_total_records": lambda self: 0},
    )()
    fake_calibration = type(
        "Calibration",
        (),
        {
            "status": "ok",
            "unique_files": 1,
            "improvement_events": 1,
            "fp_candidates": 1,
            "confidence_gap": 0.2,
            "current_weights": {"ldr": 0.4, "inflation": 0.3, "ddc": 0.3},
            "optimal_weights": {"ldr": 0.45, "inflation": 0.25, "ddc": 0.2},
        },
    )()
    with (
        patch("slop_detector.leda_injection.HistoryTracker", return_value=fake_tracker),
        patch("slop_detector.leda_injection.SelfCalibrator") as calibrator_cls,
    ):
        calibrator_cls.return_value.calibrate.return_value = fake_calibration
        payload = build_leda_injection(_sample_file_result(), path=str(tmp_path), profile="public")

    assert payload["security"]["classification"] == "public"
    assert payload["security"]["ingestible_by_spar"] is False
    assert payload["project"].get("root") is None
    assert payload["source"]["config_path"] is None
    assert payload["source"]["history_db"] is None
    assert payload["claim_risk"] == []
    assert payload["claim_risk_summary"]["total"] >= 0
    assert payload["calibration"].get("current_weights") is None
    assert payload["calibration"].get("optimal_weights") is None
    assert payload["spar_review_hints"]["preferred_layers"] == []
