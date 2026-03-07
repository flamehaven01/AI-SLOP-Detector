"""
SlopGate - SNP-compatible gate contract for slop analysis.

Maps slop metrics to the SNP GateDecision interface:
  sr9 = LDR score       (semantic resonance = logic density)
  di2 = DDC ratio       (dependency integrity)
  jsd = 1 - inflation   (JS-divergence from clean baseline)
  ove = 1 - pattern/50  (overshoot violation entropy)

Optionally bridges to supreme-nexus-pipeline GateDecision if installed.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import List, Mapping, Optional, Tuple


HALT_THRESHOLD_LDR = 0.60
HALT_THRESHOLD_DDC = 0.50
HALT_THRESHOLD_INFLATION = 1.5
HALT_THRESHOLD_PATTERN_PENALTY = 30.0


@dataclass(frozen=True)
class SlopGateDecision:
    """
    Formal gate contract for a slop analysis result.

    Compatible with supreme-nexus-pipeline GateDecision interface.
    Fields: allowed, status, halt_reason, failed_conditions,
            metrics_snapshot{sr9, di2, jsd, ove}, audit_hash.
    """

    allowed: bool
    status: str                          # "PASS" | "HALT"
    halt_reason: Optional[str]
    failed_conditions: Tuple[str, ...]
    metrics_snapshot: Mapping[str, float]  # sr9, di2, jsd, ove required
    audit_hash: str                       # sha256 of metrics payload
    recommendation: Optional[str] = None
    contract_version: str = "1.0"

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "HALT"}:
            raise ValueError("status must be PASS or HALT")
        required = {"sr9", "di2", "jsd", "ove"}
        missing = required - set(self.metrics_snapshot.keys())
        if missing:
            raise ValueError(f"metrics_snapshot missing keys: {missing}")

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "status": self.status,
            "halt_reason": self.halt_reason,
            "failed_conditions": list(self.failed_conditions),
            "metrics_snapshot": dict(self.metrics_snapshot),
            "audit_hash": self.audit_hash,
            "recommendation": self.recommendation,
            "contract_version": self.contract_version,
        }

    def is_pass(self) -> bool:
        return self.allowed and self.status == "PASS"


def _build_audit_hash(metrics: Mapping[str, float]) -> str:
    payload = "|".join(f"{k}={v:.6f}" for k, v in sorted(metrics.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_jsd(inflation_score: float) -> float:
    """Inflation score -> jsd (lower inflation = higher jsd = better)."""
    if not math.isfinite(inflation_score):
        return 0.0
    normalized = min(inflation_score / 2.0, 1.0)
    return round(1.0 - normalized, 6)


def _normalize_ove(pattern_penalty: float) -> float:
    """Pattern penalty [0-50] -> ove (lower penalty = higher ove = better)."""
    ratio = min(pattern_penalty / 50.0, 1.0)
    return round(1.0 - ratio, 6)


class SlopGate:
    """
    Evaluates slop analysis results against gate thresholds
    and produces a formal SlopGateDecision.
    """

    def __init__(
        self,
        ldr_threshold: float = HALT_THRESHOLD_LDR,
        ddc_threshold: float = HALT_THRESHOLD_DDC,
        inflation_threshold: float = HALT_THRESHOLD_INFLATION,
        pattern_threshold: float = HALT_THRESHOLD_PATTERN_PENALTY,
    ) -> None:
        self.ldr_threshold = ldr_threshold
        self.ddc_threshold = ddc_threshold
        self.inflation_threshold = inflation_threshold
        self.pattern_threshold = pattern_threshold

    def evaluate(
        self,
        ldr_score: float,
        ddc_ratio: float,
        inflation_score: float,
        pattern_penalty: float,
        context: Optional[str] = None,
    ) -> SlopGateDecision:
        """
        Evaluate slop metrics and return a gate decision.

        Args:
            ldr_score:       Logic Density Ratio [0.0-1.0]
            ddc_ratio:       DDC usage ratio [0.0-1.0]
            inflation_score: BCR/inflation score [0.0+]
            pattern_penalty: Accumulated pattern penalty [0-50]
            context:         Optional file/project label for audit

        Returns:
            SlopGateDecision with PASS or HALT verdict.
        """
        sr9 = round(max(0.0, min(1.0, ldr_score)), 6)
        di2 = round(max(0.0, min(1.0, ddc_ratio)), 6)
        jsd = _normalize_jsd(inflation_score)
        ove = _normalize_ove(pattern_penalty)

        metrics: Mapping[str, float] = {
            "sr9": sr9,
            "di2": di2,
            "jsd": jsd,
            "ove": ove,
        }
        audit_hash = _build_audit_hash(metrics)

        failed: List[str] = []
        if ldr_score < self.ldr_threshold:
            failed.append(f"ldr={ldr_score:.3f} < threshold={self.ldr_threshold}")
        if ddc_ratio < self.ddc_threshold:
            failed.append(f"ddc={ddc_ratio:.3f} < threshold={self.ddc_threshold}")
        if math.isfinite(inflation_score) and inflation_score > self.inflation_threshold:
            failed.append(
                f"inflation={inflation_score:.3f} > threshold={self.inflation_threshold}"
            )
        if pattern_penalty > self.pattern_threshold:
            failed.append(
                f"pattern_penalty={pattern_penalty:.1f} > threshold={self.pattern_threshold}"
            )

        if failed:
            halt_reason = f"Gate HALT [{context or 'file'}]: " + "; ".join(failed)
            recommendation = (
                "Reduce empty/placeholder code (LDR), "
                "remove unused imports (DDC), "
                "eliminate buzzword inflation (jsd), "
                "fix structural patterns (ove)."
            )
            return SlopGateDecision(
                allowed=False,
                status="HALT",
                halt_reason=halt_reason,
                failed_conditions=tuple(failed),
                metrics_snapshot=metrics,
                audit_hash=audit_hash,
                recommendation=recommendation,
            )

        return SlopGateDecision(
            allowed=True,
            status="PASS",
            halt_reason=None,
            failed_conditions=(),
            metrics_snapshot=metrics,
            audit_hash=audit_hash,
            recommendation=None,
        )

    def evaluate_from_file_analysis(self, file_analysis) -> SlopGateDecision:
        """Convenience: evaluate directly from a FileAnalysis object."""
        ldr = getattr(file_analysis.ldr, "ldr_score", 0.0)
        ddc = getattr(file_analysis.ddc, "usage_ratio", 0.0)
        inflation = getattr(file_analysis.inflation, "inflation_score", 0.0)

        pattern_penalty = sum(
            {"critical": 10.0, "high": 5.0, "medium": 2.0, "low": 1.0}.get(
                getattr(i.severity, "value", "low"), 1.0
            )
            for i in getattr(file_analysis, "pattern_issues", [])
        )
        pattern_penalty = min(pattern_penalty, 50.0)

        return self.evaluate(
            ldr_score=ldr,
            ddc_ratio=ddc,
            inflation_score=inflation if math.isfinite(inflation) else 2.0,
            pattern_penalty=pattern_penalty,
            context=str(getattr(file_analysis, "file_path", "unknown")),
        )


def try_bridge_snp(gate_decision: SlopGateDecision):
    """
    Optionally convert to supreme-nexus-pipeline GateDecision if SNP is installed.
    Returns SNP GateDecision if available, else returns the SlopGateDecision as-is.
    """
    try:
        from supreme_nexus_pipeline.contracts import GateDecision  # type: ignore

        return GateDecision(
            allowed=gate_decision.allowed,
            status=gate_decision.status,
            halt_reason=gate_decision.halt_reason,
            failed_conditions=gate_decision.failed_conditions,
            metrics_snapshot=dict(gate_decision.metrics_snapshot),
            audit_hash=gate_decision.audit_hash,
            recommendation=gate_decision.recommendation,
            contract_version=gate_decision.contract_version,
        )
    except ImportError:
        return gate_decision
