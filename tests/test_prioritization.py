from pathlib import Path
from types import SimpleNamespace

from coverage import CoverageData

from slop_detector.models import DDCResult, FileAnalysis, InflationResult, LDRResult, SlopStatus
from slop_detector.prioritization import ProjectPrioritizer


def _file_result(path: Path, deficit_score: float, status: SlopStatus) -> FileAnalysis:
    return FileAnalysis(
        file_path=str(path),
        ldr=LDRResult(100, 50, 20, 0.50, "B"),
        inflation=InflationResult(5, 1.0, 0.4, "PASS", []),
        ddc=DDCResult(["os"], ["os"], [], [], [], 1.0, "EXCELLENT"),
        deficit_score=deficit_score,
        status=status,
    )


def test_prioritize_project_ranks_high_churn_low_coverage_high_deficit_first(tmp_path, monkeypatch):
    prioritizer = ProjectPrioritizer(
        SimpleNamespace(
            get_hotspot_weights=lambda: {"deficit": 0.5, "churn": 0.3, "coverage_gap": 0.2},
            get_hotspot_limit=lambda: 10,
            get_churn_commit_window=lambda: 200,
            get_coverage_data_file=lambda: ".coverage",
        )
    )

    a_path = tmp_path / "a.py"
    b_path = tmp_path / "b.py"
    a_path.write_text("def a():\n    return 1\n", encoding="utf-8")
    b_path.write_text("def b():\n    return 2\n", encoding="utf-8")
    high_risk = _file_result(a_path, 80.0, SlopStatus.CRITICAL_DEFICIT)
    lower_risk = _file_result(b_path, 55.0, SlopStatus.INFLATED_SIGNAL)

    monkeypatch.setattr(
        prioritizer,
        "_load_git_churn",
        lambda *args, **kwargs: {str(a_path.resolve()): 12, str(b_path.resolve()): 2},
    )
    monkeypatch.setattr(
        prioritizer,
        "_load_coverage_ratios",
        lambda *args, **kwargs: {str(a_path.resolve()): 0.10, str(b_path.resolve()): 0.85},
    )

    hotspots, churn_available, coverage_available = prioritizer.prioritize_project(
        str(tmp_path), [high_risk, lower_risk]
    )

    assert churn_available is True
    assert coverage_available is True
    assert hotspots[0].file_path == str(a_path)
    assert "critical deficit" in hotspots[0].reasons
    assert "high churn" in hotspots[0].reasons
    assert "low coverage" in hotspots[0].reasons
    assert hotspots[0].priority_score > hotspots[1].priority_score


def test_compute_priority_score_contract():
    prioritizer = ProjectPrioritizer(
        SimpleNamespace(
            get_hotspot_weights=lambda: {"deficit": 0.5, "churn": 0.3, "coverage_gap": 0.2},
            get_hotspot_limit=lambda: 10,
            get_churn_commit_window=lambda: 200,
            get_coverage_data_file=lambda: ".coverage",
        )
    )

    score = prioritizer._compute_priority_score(
        deficit_score=80.0,
        churn_score=0.75,
        coverage_gap=0.80,
        weights={"deficit": 0.5, "churn": 0.3, "coverage_gap": 0.2},
    )

    expected = 100.0 * ((0.5 * 0.8 + 0.3 * 0.75 + 0.2 * 0.80) / (0.5 + 0.3 + 0.2))

    assert score == expected


def test_load_coverage_ratios_reads_coverage_data(tmp_path):
    config = SimpleNamespace(
        get_hotspot_weights=lambda: {"deficit": 0.5, "churn": 0.3, "coverage_gap": 0.2},
        get_hotspot_limit=lambda: 10,
        get_churn_commit_window=lambda: 200,
        get_coverage_data_file=lambda: ".coverage",
    )
    prioritizer = ProjectPrioritizer(config)

    file_path = tmp_path / "pkg.py"
    file_path.write_text(
        "def add(a, b):\n" "    total = a + b\n" "    return total\n",
        encoding="utf-8",
    )

    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.add_lines({str(file_path.resolve()): {1, 2}})
    data.write()

    ratios = prioritizer._load_coverage_ratios(str(tmp_path), [file_path])

    assert str(file_path.resolve()) in ratios
    assert 0.0 < ratios[str(file_path.resolve())] < 1.0


def test_estimate_executable_lines_skips_non_list_ast_bodies(tmp_path):
    config = SimpleNamespace(
        get_hotspot_weights=lambda: {"deficit": 0.5, "churn": 0.3, "coverage_gap": 0.2},
        get_hotspot_limit=lambda: 10,
        get_churn_commit_window=lambda: 200,
        get_coverage_data_file=lambda: ".coverage",
    )
    prioritizer = ProjectPrioritizer(config)

    file_path = tmp_path / "lambda_case.py"
    file_path.write_text(
        "f = lambda x: x + 1\n" "def keep():\n" "    return f(1)\n",
        encoding="utf-8",
    )

    executable = prioritizer._estimate_executable_lines(file_path)

    assert executable
    assert 1 in executable
    assert 3 in executable


def test_load_git_churn_counts_recent_touches(tmp_path, monkeypatch):
    config = SimpleNamespace(
        get_hotspot_weights=lambda: {"deficit": 0.5, "churn": 0.3, "coverage_gap": 0.2},
        get_hotspot_limit=lambda: 10,
        get_churn_commit_window=lambda: 25,
        get_coverage_data_file=lambda: ".coverage",
    )
    prioritizer = ProjectPrioritizer(config)

    file_path = tmp_path / "src" / "hot.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("x = 1\n", encoding="utf-8")

    calls = {"count": 0}

    def fake_run(cmd, cwd, capture_output, text, check):
        calls["count"] += 1
        if "rev-parse" in cmd:
            return SimpleNamespace(stdout=str(tmp_path), returncode=0)
        return SimpleNamespace(stdout="src/hot.py\nsrc/hot.py\n", returncode=0)

    monkeypatch.setattr("slop_detector.prioritization.subprocess.run", fake_run)

    counts = prioritizer._load_git_churn(str(tmp_path), [file_path])

    assert calls["count"] == 2
    assert counts[str(file_path.resolve())] == 2
