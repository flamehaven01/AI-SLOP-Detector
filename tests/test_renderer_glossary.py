"""Tests for the shared project-metrics glossary used by all renderers."""

from types import SimpleNamespace

from slop_detector.renderer_glossary import DEFICIT_BANDS, project_metric_rows


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
