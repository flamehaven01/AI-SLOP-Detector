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
from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence, Tuple

from slop_detector.core_scoring import calculate_pattern_penalty

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
    status: str  # "PASS" | "HALT"
    halt_reason: Optional[str]
    failed_conditions: Tuple[str, ...]
    metrics_snapshot: Mapping[str, float]  # sr9, di2, jsd, ove required
    audit_hash: str  # sha256 of metrics payload
    recommendation: Optional[str] = None
    contract_version: str = "1.0"
    # Snapshot keys that stand for no measurement (their value is neutral and
    # was not judged): "di2" and "jsd" when no Python file has those metrics,
    # every key when nothing was measured.
    not_measured: Tuple[str, ...] = ()

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
            "not_measured": list(self.not_measured),
        }

    def is_pass(self) -> bool:
        return self.allowed and self.status == "PASS"


def _build_audit_hash(metrics: Mapping[str, float], not_measured: Tuple[str, ...] = ()) -> str:
    """A decision on measured values hashes as before; an unmeasured key is
    named in the payload, so its neutral value is not taken for a measured one."""
    payload = "|".join(f"{k}={v:.6f}" for k, v in sorted(metrics.items()))
    if not_measured:
        payload += "|not_measured=" + ",".join(sorted(not_measured))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_jsd(inflation_score: float) -> float:
    """Inflation score -> jsd key (lower inflation = higher value = better).

    NOTE: Despite the key name "jsd" (required by SNP contract interface),
    this is NOT information-theoretic Jensen-Shannon Divergence.
    It is a linear rescaling of the inflation score:
        jsd = 1 - min(inflation_score / 2.0, 1.0)
    The key name is preserved for backward compatibility with the SNP contract.
    True DCF-JSD (sqrt-JSD over AST node type distributions) is computed at
    the FileAnalysis level (v3.0+) and available via FileAnalysis.dcf.
    """
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
        ldr_score: Optional[float],
        ddc_ratio: Optional[float],
        inflation_score: Optional[float],
        pattern_penalty: Optional[float],
        context: Optional[str] = None,
        blocking: Sequence[str] = (),
    ) -> SlopGateDecision:
        """
        Evaluate slop metrics and return a gate decision.

        A metric given as None was not measured (DDC and inflation are Python
        metrics; a project with nothing analyzed has none): it is not judged,
        its snapshot value is neutral (1.0), and the decision names its key in
        `not_measured`. A neutral value is never a measurement.

        Args:
            ldr_score:       Logic Density Ratio [0.0-1.0]
            ddc_ratio:       DDC usage ratio [0.0-1.0]
            inflation_score: BCR/inflation score [0.0+]
            pattern_penalty: Accumulated pattern penalty [0-50]
            context:         Optional file/project label for audit
            blocking:        Conditions outside the four metrics that fail the
                             gate (nothing measured, an incomplete scan)

        Returns:
            SlopGateDecision with PASS or HALT verdict.
        """
        given = {"sr9": ldr_score, "di2": ddc_ratio, "jsd": inflation_score, "ove": pattern_penalty}
        not_measured: Tuple[str, ...] = tuple(key for key, value in given.items() if value is None)
        metrics: Mapping[str, float] = {
            "sr9": 1.0 if ldr_score is None else round(max(0.0, min(1.0, ldr_score)), 6),
            "di2": 1.0 if ddc_ratio is None else round(max(0.0, min(1.0, ddc_ratio)), 6),
            "jsd": 1.0 if inflation_score is None else _normalize_jsd(inflation_score),
            "ove": 1.0 if pattern_penalty is None else _normalize_ove(pattern_penalty),
        }
        audit_hash = _build_audit_hash(metrics, not_measured)

        failed: List[str] = []
        if ldr_score is not None and ldr_score < self.ldr_threshold:
            failed.append(f"ldr={ldr_score:.3f} < threshold={self.ldr_threshold}")
        if ddc_ratio is not None and ddc_ratio < self.ddc_threshold:
            failed.append(f"ddc={ddc_ratio:.3f} < threshold={self.ddc_threshold}")
        if (
            inflation_score is not None
            and math.isfinite(inflation_score)
            and inflation_score > self.inflation_threshold
        ):
            failed.append(f"inflation={inflation_score:.3f} > threshold={self.inflation_threshold}")
        if pattern_penalty is not None and pattern_penalty > self.pattern_threshold:
            failed.append(
                f"pattern_penalty={pattern_penalty:.1f} > threshold={self.pattern_threshold}"
            )

        if failed or blocking:
            conditions = tuple(blocking) + tuple(failed)
            halt_reason = f"Gate HALT [{context or 'file'}]: " + "; ".join(conditions)
            recommendation = (
                (
                    "Reduce empty/placeholder code (LDR), "
                    "remove unused imports (DDC), "
                    "eliminate buzzword inflation (jsd), "
                    "fix structural patterns (ove)."
                )
                if failed
                else "Fix what stopped the measurement (see scan coverage), then run the gate again."
            )
            return SlopGateDecision(
                allowed=False,
                status="HALT",
                halt_reason=halt_reason,
                failed_conditions=conditions,
                metrics_snapshot=metrics,
                audit_hash=audit_hash,
                recommendation=recommendation,
                not_measured=not_measured,
            )

        return SlopGateDecision(
            allowed=True,
            status="PASS",
            halt_reason=None,
            failed_conditions=(),
            metrics_snapshot=metrics,
            audit_hash=audit_hash,
            recommendation=None,
            not_measured=not_measured,
        )

    def evaluate_from_file_analysis(self, file_analysis) -> SlopGateDecision:
        """Convenience: evaluate directly from a FileAnalysis object."""
        ldr = getattr(file_analysis.ldr, "ldr_score", 0.0)
        ddc = getattr(file_analysis.ddc, "usage_ratio", 0.0)
        inflation = getattr(file_analysis.inflation, "inflation_score", 0.0)

        pattern_penalty = calculate_pattern_penalty(getattr(file_analysis, "pattern_issues", []))

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
