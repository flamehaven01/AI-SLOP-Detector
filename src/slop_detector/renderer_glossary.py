"""Shared, human-friendly descriptions of the project-level metrics.

One source of truth for the metric label, healthy direction, plain-language
meaning, and a health band (good/warn/bad). The rich / text / markdown renderers
all consume this so the explanation stays identical across every surface.

ASCII-only (cp949 safety): no emoji or non-ASCII characters in this module.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Deficit bands mirror the scoring model in README / SlopStatus.
DEFICIT_BANDS = "CLEAN <30  |  SUSPICIOUS 30-50  |  INFLATED 50-70  |  CRITICAL >=70"


def _deficit_health(value: float) -> str:
    # Lower is better. Bands follow the status thresholds.
    return "good" if value < 30 else "warn" if value < 50 else "bad"


def _ldr_health(value: float) -> str:
    # Logic density ratio (0-1); higher is better.
    return "good" if value >= 0.80 else "warn" if value >= 0.50 else "bad"


def _icr_health(value: float) -> str:
    # Inflation; lower is better. CI hard mode fails at >= 1.5.
    return "good" if value < 0.50 else "warn" if value < 1.50 else "bad"


def _ddc_health(value: float) -> str:
    # Dependency usage ratio (0-1); higher is better. CI hard mode fails < 0.5.
    return "good" if value >= 0.80 else "warn" if value >= 0.50 else "bad"


def project_metric_rows(result: Any) -> List[Dict[str, str]]:
    """Return ordered metric descriptors for a ProjectAnalysis result.

    Each row: label, value (display), direction ("Lower"/"Higher"), health
    ("good"/"warn"/"bad"), means (plain-language explanation).
    """
    return [
        {
            "label": "Average Deficit Score",
            "value": f"{result.avg_deficit_score:.1f}/100",
            "direction": "Lower",
            "health": _deficit_health(result.avg_deficit_score),
            "means": "Mean file risk; 0 is clean, 100 is severe.",
        },
        {
            "label": "Weighted Deficit Score",
            "value": f"{result.weighted_deficit_score:.1f}/100",
            "direction": "Lower",
            "health": _deficit_health(result.weighted_deficit_score),
            "means": "Same risk score, weighted by each file's lines of code.",
        },
        {
            "label": "Logic Density Ratio (LDR)",
            "value": f"{result.avg_ldr:.2%}",
            "direction": "Higher",
            "health": _ldr_health(result.avg_ldr),
            "means": "Share of code lines that contain real implementation.",
        },
        {
            "label": "Inflation-to-Code Ratio (ICR)",
            "value": f"{result.avg_inflation:.2f}x",
            "direction": "Lower",
            "health": _icr_health(result.avg_inflation),
            "means": "Unjustified jargon compared with average cyclomatic complexity.",
        },
        {
            "label": "Dependency Usage Ratio (DDC)",
            "value": f"{result.avg_ddc:.2%}",
            "direction": "Higher",
            "health": _ddc_health(result.avg_ddc),
            "means": "Imported libraries that are referenced by runtime code.",
        },
    ]
