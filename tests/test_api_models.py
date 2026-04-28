from slop_detector import __version__
from slop_detector.api.models import AnalysisResponse, TrendResponse
from slop_detector.auth import __version__ as auth_version
from slop_detector.models import DDCResult, FileAnalysis, InflationResult, LDRResult, SlopStatus


def test_analysis_response_maps_current_file_analysis_shape():
    result = FileAnalysis(
        file_path="/tmp/demo.py",
        ldr=LDRResult(10, 8, 2, 0.8, "A"),
        inflation=InflationResult(2, 1.0, 0.2, "PASS", ["ai"]),
        ddc=DDCResult(["json"], ["json"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=12.5,
        status=SlopStatus.CLEAN,
        warnings=[],
        pattern_issues=[],
    )

    payload = AnalysisResponse.from_result(result)

    assert payload.file_path == "/tmp/demo.py"
    assert payload.slop_score == 12.5
    assert payload.grade == "clean"
    assert payload.ldr_score == 0.8
    assert payload.bcr_score == 0.2
    assert payload.ddc_score == 1.0


def test_trend_response_maps_history_payload():
    payload = TrendResponse.from_history(
        "/tmp/project",
        {
            "period_days": 7,
            "daily_trends": [
                {"date": "2026-04-25", "avg_deficit": 12.0},
                {"date": "2026-04-24", "avg_deficit": 20.0},
            ],
        },
    )

    assert payload.project_path == "/tmp/project"
    assert payload.period_days == 7
    assert payload.average_score == 16.0
    assert payload.trend_direction == "improving"
    assert payload.regression_count == 0


def test_auth_module_version_tracks_package_version():
    assert auth_version == __version__
