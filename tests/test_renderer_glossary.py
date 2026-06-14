"""Tests for the shared project-metrics glossary used by all renderers."""

from types import SimpleNamespace

from slop_detector.renderer_glossary import (
    DEFICIT_BANDS,
    clone_metric_row,
    file_metric_rows,
    next_steps,
    project_metric_rows,
)


def _result(**overrides):
    base = dict(
        avg_deficit_score=0.0,
        weighted_deficit_score=0.0,
        avg_ldr=1.0,
        avg_inflation=0.0,
        avg_ddc=1.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_project_metric_rows_shape_and_directions():
    rows = project_metric_rows(_result())
    assert [r["label"] for r in rows] == [
        "Average Deficit Score",
        "Weighted Deficit Score",
        "Logic Density Ratio (LDR)",
        "Inflation-to-Code Ratio (ICR)",
        "Dependency Usage Ratio (DDC)",
    ]
    assert [r["direction"] for r in rows] == ["Lower", "Lower", "Higher", "Lower", "Higher"]
    for r in rows:
        assert r["health"] in {"good", "warn", "bad"}
        assert r["means"]  # every metric has a plain-language explanation


def test_health_bands_good_and_bad():
    clean = {r["label"]: r["health"] for r in project_metric_rows(_result(avg_deficit_score=5.0))}
    assert clean["Average Deficit Score"] == "good"

    bad = {
        r["label"]: r["health"]
        for r in project_metric_rows(
            _result(
                avg_deficit_score=80.0,
                weighted_deficit_score=80.0,
                avg_ldr=0.20,
                avg_inflation=2.0,
                avg_ddc=0.30,
            )
        )
    }
    assert bad["Average Deficit Score"] == "bad"
    assert bad["Logic Density Ratio (LDR)"] == "bad"
    assert bad["Inflation-to-Code Ratio (ICR)"] == "bad"
    assert bad["Dependency Usage Ratio (DDC)"] == "bad"


def test_deficit_bands_legend_is_ascii():
    assert DEFICIT_BANDS.isascii()
    assert "CLEAN" in DEFICIT_BANDS and "CRITICAL" in DEFICIT_BANDS


def test_next_steps_clean_project_says_no_action():
    steps = next_steps(_result(deficit_files=0, priority_hotspots=[]))
    assert len(steps) == 1
    assert "no action needed" in steps[0]


def test_next_steps_healthy_averages_with_flagged_files_does_not_crash():
    # Regression: project averages all healthy (no bad/warn metric) but some
    # files are flagged (deficit_files > 0) must not IndexError on (bad or warn)[0].
    steps = next_steps(_result(deficit_files=3, priority_hotspots=[]))
    assert 1 <= len(steps) <= 3
    assert any("flagged" in s for s in steps)


def test_next_steps_deficit_recommends_dead_code_sweep():
    hot = SimpleNamespace(file_path="x/worst.py", deficit_score=72.0)
    steps = next_steps(
        _result(
            avg_deficit_score=72.0,
            weighted_deficit_score=72.0,
            avg_ldr=0.3,
            deficit_files=4,
            priority_hotspots=[hot],
        )
    )
    assert 1 <= len(steps) <= 3
    assert steps[0].startswith("Top concern: Average Deficit Score")
    assert any("sweep dead-code" in s for s in steps)
    assert any("worst.py" in s for s in steps)


def test_file_metric_rows_shape_and_shared_bands():
    fr = SimpleNamespace(
        deficit_score=72.0,
        ldr=SimpleNamespace(ldr_score=0.30),
        inflation=SimpleNamespace(inflation_score=2.0),
        ddc=SimpleNamespace(usage_ratio=0.30),
        pattern_issues=[],
    )
    rows = file_metric_rows(fr)
    assert [r["label"] for r in rows][0] == "Deficit Score"
    assert {
        "Logic Density Ratio (LDR)",
        "Inflation-to-Code Ratio (ICR)",
        "Dependency Usage Ratio (DDC)",
    } <= {r["label"] for r in rows}
    # Same health classifiers as the project rows -> all bad for these values.
    assert all(r["health"] == "bad" for r in rows)


def test_clone_metric_row_distinguishes_exact_duplicate_pair():
    issue = SimpleNamespace(
        pattern_id="exact_duplicate_pair",
        severity=SimpleNamespace(value="high"),
    )
    row = clone_metric_row(SimpleNamespace(pattern_issues=[issue]))
    assert row is not None
    assert row["label"] == "Clone Detection"
    assert "exact duplicate functions" in row["value"]
    assert "normalizing local names" in row["means"]


def test_clone_metric_row_distinguishes_clone_cluster():
    issue = SimpleNamespace(
        pattern_id="function_clone_cluster",
        severity=SimpleNamespace(value="critical"),
    )
    row = clone_metric_row(SimpleNamespace(pattern_issues=[issue]))
    assert row is not None
    assert "near-identical function cluster" in row["value"]
    assert "AST structure" in row["means"]
    assert row["health"] == "bad"


def test_next_steps_ddc_concern_recommends_unused_deps():
    steps = next_steps(_result(avg_ddc=0.30, deficit_files=1, priority_hotspots=[]))
    assert any("unused-deps" in s for s in steps)
