"""Pure scoring helpers used by the public :class:`SlopDetector` facade."""

from __future__ import annotations

from math import exp, log
from typing import Any, Dict, List, Mapping, Optional

from slop_detector.models import SlopStatus
from slop_detector.patterns.base import Issue


class SkipProxy:
    """Override a metric attribute without mutating the original result."""

    def __init__(self, wrapped: Any, **overrides: Any) -> None:
        self._wrapped = wrapped
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name in self._overrides:
            return self._overrides[name]
        return getattr(self._wrapped, name)


def compute_gqg(
    weights: Mapping[str, float], ldr: Any, inflation_normalized: float, ddc: Any, purity: float
) -> float:
    """Return the weighted geometric quality gate for the four score dimensions."""
    w_ldr = weights.get("ldr", 0.40)
    w_inf = weights.get("inflation", 0.30)
    w_ddc = weights.get("ddc", 0.20)
    w_pur = weights.get("purity", 0.10)
    total_w = w_ldr + w_inf + w_ddc + w_pur
    return exp(
        (
            w_ldr * log(max(1e-4, ldr.ldr_score))
            + w_inf * log(max(1e-4, 1.0 - inflation_normalized))
            + w_ddc * log(max(1e-4, ddc.usage_ratio))
            + w_pur * log(max(1e-4, purity))
        )
        / total_w
    )


def build_metric_warnings(
    ldr: Any, inflation: Any, ddc: Any, skip: frozenset = frozenset()
) -> List[str]:
    """Generate threshold warnings for metrics that apply to a file role."""
    warnings: List[str] = []
    if "ldr" not in skip:
        if ldr.ldr_score < 0.30:
            warnings.append(f"CRITICAL: Logic density only {ldr.ldr_score:.2%}")
        elif ldr.ldr_score < 0.60:
            warnings.append(f"WARNING: Low logic density {ldr.ldr_score:.2%}")
    if "inflation" not in skip:
        if inflation.inflation_score > 1.0:
            warnings.append(f"CRITICAL: Inflation ratio {inflation.inflation_score:.2f}")
        elif inflation.inflation_score > 0.5:
            warnings.append(f"WARNING: High inflation ratio {inflation.inflation_score:.2f}")
    if "ddc" not in skip:
        if ddc.usage_ratio < 0.50:
            warnings.append(f"CRITICAL: Only {ddc.usage_ratio:.2%} of imports used")
        elif ddc.usage_ratio < 0.70:
            warnings.append(f"WARNING: Low import usage {ddc.usage_ratio:.2%}")
        if ddc.fake_imports:
            warnings.append(f"FAKE IMPORTS: {', '.join(ddc.fake_imports)}")
    return warnings


def calculate_pattern_penalty(issues: List[Issue]) -> float:
    """Return the capped additive penalty for pattern severities."""
    severity_weights = {
        "critical": 10.0,
        "high": 5.0,
        "medium": 2.0,
        "low": 1.0,
    }
    return min(sum(severity_weights.get(issue.severity.value, 1.0) for issue in issues), 50.0)


def compute_deficit_breakdown(
    weights: Mapping[str, float],
    ldr: Any,
    inflation_normalized: float,
    ddc: Any,
    purity: float,
    base_deficit_score: float,
    deficit_score: float,
) -> Dict[str, float]:
    """Attribute a geometric deficit to score dimensions by log-loss share."""
    w_ldr = weights.get("ldr", 0.40)
    w_inf = weights.get("inflation", 0.30)
    w_ddc = weights.get("ddc", 0.20)
    w_pur = weights.get("purity", 0.10)
    total_w = w_ldr + w_inf + w_ddc + w_pur

    ldr_loss = -w_ldr * log(max(1e-4, ldr.ldr_score))
    inf_loss = -w_inf * log(max(1e-4, 1.0 - inflation_normalized))
    ddc_loss = -w_ddc * log(max(1e-4, ddc.usage_ratio))
    pur_loss = -w_pur * log(max(1e-4, purity))
    total_loss = (ldr_loss + inf_loss + ddc_loss + pur_loss) / total_w

    if total_loss > 1e-9:
        ldr_share = (ldr_loss / total_w) / total_loss
        inf_share = (inf_loss / total_w) / total_loss
        ddc_share = (ddc_loss / total_w) / total_loss
        pur_share = (pur_loss / total_w) / total_loss
    else:
        ldr_share = inf_share = ddc_share = pur_share = 0.0

    effective_pattern = max(0.0, deficit_score - base_deficit_score)
    return {
        "ldr_penalty": round(ldr_share * base_deficit_score, 4),
        "inflation_penalty": round(inf_share * base_deficit_score, 4),
        "ddc_penalty": round(ddc_share * base_deficit_score, 4),
        "purity_penalty": round(pur_share * base_deficit_score, 4),
        "pattern_hits": round(effective_pattern, 4),
        "total": round(deficit_score, 4),
    }


def calculate_slop_status(
    weights: Mapping[str, float],
    ldr: Any,
    inflation: Any,
    ddc: Any,
    pattern_issues: Optional[List[Issue]] = None,
    skip: frozenset = frozenset(),
) -> tuple[float, SlopStatus, List[str], Dict[str, float]]:
    """Calculate the deterministic score, status, warnings, and attribution."""
    pattern_issues = pattern_issues or []
    inflation_normalized = (
        min(inflation.inflation_score, 2.0) / 2.0
        if inflation.inflation_score != float("inf")
        else 1.0
    )
    if "inflation" in skip:
        inflation_normalized = 0.0

    critical_patterns = [issue for issue in pattern_issues if issue.severity.value == "critical"]
    high_patterns = [issue for issue in pattern_issues if issue.severity.value == "high"]
    purity = exp(-0.5 * len(critical_patterns))
    effective_ldr = SkipProxy(ldr, ldr_score=1.0) if "ldr" in skip else ldr
    effective_ddc = SkipProxy(ddc, usage_ratio=1.0) if "ddc" in skip else ddc

    gqg = compute_gqg(weights, effective_ldr, inflation_normalized, effective_ddc, purity)
    base_deficit_score = 100 * (1 - gqg)
    deficit_score = min(base_deficit_score + calculate_pattern_penalty(pattern_issues), 100.0)
    deficit_breakdown = compute_deficit_breakdown(
        weights,
        effective_ldr,
        inflation_normalized,
        effective_ddc,
        purity,
        base_deficit_score,
        deficit_score,
    )
    warnings = build_metric_warnings(ldr, inflation, ddc, skip=skip)
    if critical_patterns:
        warnings.append(f"PATTERNS: {len(critical_patterns)} critical issues found")
    if high_patterns:
        warnings.append(f"PATTERNS: {len(high_patterns)} high-severity issues found")

    if deficit_score >= 70:
        status = SlopStatus.CRITICAL_DEFICIT
    elif deficit_score >= 50:
        status = SlopStatus.INFLATED_SIGNAL
    elif deficit_score >= 30:
        status = SlopStatus.SUSPICIOUS
    else:
        status = SlopStatus.CLEAN

    if len(critical_patterns) >= 5 and status == SlopStatus.CLEAN:
        status = SlopStatus.SUSPICIOUS
    if (
        ddc.usage_ratio < 0.20
        and "ddc" not in skip
        and not critical_patterns
        and inflation.inflation_score <= 1.0
    ):
        status = SlopStatus.DEPENDENCY_NOISE

    return deficit_score, status, warnings, deficit_breakdown
