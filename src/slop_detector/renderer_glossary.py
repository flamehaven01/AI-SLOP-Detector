"""Shared, human-friendly descriptions of the project-level metrics.

One source of truth for the metric label, healthy direction, plain-language
meaning, and a health band (good/warn/bad). The rich / text / markdown renderers
all consume this so the explanation stays identical across every surface.

ASCII-only (cp949 safety): no emoji or non-ASCII characters in this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

# Deficit bands mirror the scoring model in README / SlopStatus.
DEFICIT_BANDS = "CLEAN <30  |  SUSPICIOUS 30-50  |  INFLATED 50-70  |  CRITICAL >=70"

# Plain-language meanings shared by project- and file-level metric rows.
_MEANS_LDR = "Share of code lines that contain real implementation."
_MEANS_ICR = "Unjustified jargon compared with average cyclomatic complexity."
_MEANS_DDC = "Imported libraries that are referenced by runtime code."


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
            "means": _MEANS_LDR,
        },
        {
            "label": "Inflation-to-Code Ratio (ICR)",
            "value": f"{result.avg_inflation:.2f}x",
            "direction": "Lower",
            "health": _icr_health(result.avg_inflation),
            "means": _MEANS_ICR,
        },
        {
            "label": "Dependency Usage Ratio (DDC)",
            "value": f"{result.avg_ddc:.2%}",
            "direction": "Higher",
            "health": _ddc_health(result.avg_ddc),
            "means": _MEANS_DDC,
        },
    ]


def file_metric_rows(fr: Any) -> List[Dict[str, str]]:
    """Per-file metric descriptors (reuses the project-level health bands and
    meanings). A single file has no weighted aggregate, so only the four core
    dimensions are reported."""
    return [
        {
            "label": "Deficit Score",
            "value": f"{fr.deficit_score:.1f}/100",
            "direction": "Lower",
            "health": _deficit_health(fr.deficit_score),
            "means": "This file's risk; 0 is clean, 100 is severe.",
        },
        {
            "label": "Logic Density Ratio (LDR)",
            "value": f"{fr.ldr.ldr_score:.2%}",
            "direction": "Higher",
            "health": _ldr_health(fr.ldr.ldr_score),
            "means": _MEANS_LDR,
        },
        {
            "label": "Inflation-to-Code Ratio (ICR)",
            "value": f"{fr.inflation.inflation_score:.2f}x",
            "direction": "Lower",
            "health": _icr_health(fr.inflation.inflation_score),
            "means": _MEANS_ICR,
        },
        {
            "label": "Dependency Usage Ratio (DDC)",
            "value": f"{fr.ddc.usage_ratio:.2%}",
            "direction": "Higher",
            "health": _ddc_health(fr.ddc.usage_ratio),
            "means": _MEANS_DDC,
        },
    ]


def next_steps(result: Any) -> List[str]:
    """Deterministic, 1-3 actionable next steps based on the metrics.

    Turns analysis into action: name the top concern, recommend the matching
    cleanup command, then point at where to start. Rule-based, not heuristic
    guessing, so the same result always yields the same advice.
    """
    rows = project_metric_rows(result)
    bad = [r for r in rows if r["health"] == "bad"]
    warn = [r for r in rows if r["health"] == "warn"]
    deficit_files = getattr(result, "deficit_files", 0) or 0
    hotspots = getattr(result, "priority_hotspots", []) or []

    if not bad and not warn and deficit_files == 0:
        return [
            "All metrics are healthy - no action needed. "
            "Add `slop-detector --project . --ci-mode hard` to CI to keep it that way."
        ]

    steps: List[str] = []
    concern = (bad or warn)[0] if (bad or warn) else None

    if concern is None:
        # Project averages are all healthy, but some individual files are flagged
        # (deficit_files > 0). Point at those files rather than a project metric.
        label = ""
        steps.append(
            f"Project averages are healthy, but {deficit_files} file(s) are "
            "flagged. The hotspots below are pulling specific files down."
        )
        steps.append(
            "Run `slop-detector sweep dead-code .` for placeholder/dead files, "
            "then `slop-detector sweep dupes .` for duplicated logic."
        )
    else:
        label = concern["label"]
        steps.append(
            f"Top concern: {label} = {concern['value']} "
            f"({concern['direction']} is healthier). {concern['means']}"
        )
        if "Dependency Usage" in label:
            steps.append(
                "Run `slop-detector sweep unused-deps .` to list imports and "
                "dependencies that are declared but never used."
            )
        elif "Inflation" in label:
            steps.append(
                "High jargon density has no auto-fix: open the top file below and "
                "replace marketing terms with concrete behavior."
            )
        else:  # deficit or logic-density concern
            steps.append(
                "Run `slop-detector sweep dead-code .` for placeholder/dead files, "
                "then `slop-detector sweep dupes .` for duplicated logic."
            )

    if hotspots:
        top = hotspots[0]
        steps.append(
            f"Start with `{Path(top.file_path).name}` (deficit "
            f"{getattr(top, 'deficit_score', 0.0):.1f}); use `slop-detector review .` "
            "to scope this to changed code only."
        )
    elif deficit_files > 0:
        steps.append(
            "Run `slop-detector review .` to focus on slop introduced in your "
            "changed files only."
        )

    return steps[:3]
