"""
Self-Calibration Engine v2 — advisory weight tuning from comparable history.

Evidence (history schema v6 only; legacy rows are counted and ignored):

1. Rows of one project root (the canonical scan root), grouped per file and
   per measurement fingerprint (detector version + engine + configuration):
   only runs measured the same way are compared.
2. Consecutive comparable runs of a file give at most one label:
   - improvement: the file changed (file hash differs) and its metric-only
     deficit dropped by FIX_DELTA from at least SUSPICIOUS_AT;
   - stable_flag_candidate: metric-only deficit at least SUSPICIOUS_AT and
     the file unchanged; once per file.
   The metric-only deficit is the canonical quality gate (compute_gqg) with
   purity fixed at 1.0: pattern findings feed per-rule diagnostics, never the
   weights, since no weight can move a pattern penalty.
3. Grid search over ldr/inflation/ddc with purity held at its current weight;
   each candidate is scored by recomputing the metric-only deficit with the
   canonical scoring function and the canonical band threshold.
4. Confidence gap between the best two candidates; below CONFIDENCE_GAP the
   result asks for more evidence.

The result is a report. Nothing writes calibrated weights (applying them is
a separate, later decision).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Mapping, Optional, Tuple

from slop_detector.core_scoring import compute_gqg
from slop_detector.diagnostic_bands import SUSPICIOUS_AT
from slop_detector.history import PROVENANCE_V6, HistoryTracker

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

FIX_DELTA: float = 10.0  # metric-only drop that counts as a fix
MIN_W: float = 0.10  # minimum allowed weight per learned dimension
MAX_W: float = 0.65  # maximum allowed weight per learned dimension
GRID_STEP: int = 20  # 1/GRID_STEP resolution -> 0.05 increments
CONFIDENCE_GAP: float = 0.10  # min score gap between #1 and #2 candidate
MIN_IMPROVEMENTS: int = 5  # improvement events required
MIN_STABLE_FLAGS: int = 5  # stable_flag_candidate events required
MIN_RULE_OCCURRENCES: int = 3  # min times a rule must fire to appear in per_rule_fp_rates
DOMAIN_TOLERANCE: float = 0.15  # max per-dimension deviation from a domain anchor
DOMAIN_DRIFT_LIMIT: float = 0.25  # warn when optimal weight drifts this far
LEARNED = ("ldr", "inflation", "ddc")


def _default_weights() -> Dict[str, float]:
    from slop_detector.config import Config

    return dict(Config.DEFAULT_CONFIG["weights"])


def metric_only_deficit(
    ldr: float, inflation: float, ddc: float, weights: Mapping[str, float]
) -> float:
    """The canonical weighted deficit of the metrics alone (purity fixed at 1.0)."""
    gqg = compute_gqg(
        weights,
        SimpleNamespace(ldr_score=ldr),
        min(inflation, 2.0) / 2.0,
        SimpleNamespace(usage_ratio=ddc),
        1.0,
    )
    return min(100.0, 100.0 * (1.0 - gqg))


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------


@dataclass
class CalibrationEvent:
    """A single labeled calibration event derived from comparable history."""

    file_path: str
    ldr: float
    inflation: float  # raw inflation_score (not normalized)
    ddc: float  # usage_ratio
    label: str  # "improvement" | "stable_flag_candidate"
    rule_ids: List[str] = field(default_factory=list)


@dataclass
class WeightCandidate:
    """One weight hypothesis with its scored performance."""

    w_ldr: float
    w_inflation: float
    w_ddc: float
    w_purity: float = 0.0
    fn_rate: float = 0.0  # improvements the candidate would not flag
    fp_rate: float = 0.0  # stable flags the candidate would still flag
    combined_score: float = 0.0  # fn_rate + fp_rate (lower = better)
    tiebreak_score: float = 0.0  # continuous secondary (lower = better)


@dataclass
class CalibrationResult:
    """Output of a repository-local self-calibration run."""

    status: str  # "ok" | "insufficient_data" | "no_change"
    project_root: str = ""
    unique_files: int = 0
    comparable_pairs: int = 0
    legacy_rows_ignored: int = 0
    improvement_events: int = 0
    stable_flag_candidates: int = 0
    current_weights: Dict[str, float] = field(default_factory=dict)
    optimal_weights: Dict[str, float] = field(default_factory=dict)
    confidence_gap: float = 0.0
    fn_rate_before: float = 0.0
    fp_rate_before: float = 0.0
    fn_rate_after: float = 0.0
    fp_rate_after: float = 0.0
    top_candidates: List[WeightCandidate] = field(default_factory=list)
    per_rule_fp_rates: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    message: str = ""


def _parse_fired_rules(fired_rules_json: Optional[str]) -> List[str]:
    """Pattern ids of a fired_rules JSON ({"pattern_id": count}); [] when absent."""
    if not fired_rules_json:
        return []
    try:
        data = json.loads(fired_rules_json)
        return list(data.keys()) if isinstance(data, dict) else []
    except (json.JSONDecodeError, ValueError):
        return []


# ------------------------------------------------------------------
# Core engine
# ------------------------------------------------------------------


class SelfCalibrator:
    """Reads history.db and recommends ldr/inflation/ddc weights for one project root."""

    DEFAULT_DB = Path.home() / ".slop-detector" / "history.db"

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB

    def calibrate(
        self,
        current_weights: Optional[Dict[str, float]] = None,
        min_events: int = MIN_IMPROVEMENTS,
        project_root: Optional[str] = None,
        domain_anchor: Optional[Dict[str, float]] = None,
    ) -> CalibrationResult:
        """Recommend weights from the comparable evidence of one project root."""
        cw = dict(current_weights) if current_weights else _default_weights()
        cw.setdefault("purity", _default_weights()["purity"])
        result = CalibrationResult(
            status="insufficient_data", project_root=project_root or "", current_weights=cw
        )
        if not project_root:
            result.message = "Calibration v2 needs a project root: evidence is per project."
            return result
        if not self.db_path.exists():
            result.message = "No history database found. Run slop-detector on your files first."
            return result

        events = self._extract_events(project_root, result)
        improvements = [e for e in events if e.label == "improvement"]
        stable_flags = [e for e in events if e.label == "stable_flag_candidate"]
        result.improvement_events = len(improvements)
        result.stable_flag_candidates = len(stable_flags)

        min_imp = max(min_events, MIN_IMPROVEMENTS)
        min_stable = max(min_events, MIN_STABLE_FLAGS)
        if len(improvements) < min_imp or len(stable_flags) < min_stable:
            result.message = (
                f"Need >= {min_imp} improvement events (have {len(improvements)}) and "
                f">= {min_stable} stable flagged files (have {len(stable_flags)}) from "
                f"{result.comparable_pairs} comparable run pairs; "
                f"{result.legacy_rows_ignored} legacy rows are not evidence."
            )
            return result

        self._recommend(result, cw, improvements, stable_flags, domain_anchor)
        return result

    # ------------------------------------------------------------------
    # Recommendation
    # ------------------------------------------------------------------

    def _recommend(
        self,
        result: CalibrationResult,
        cw: Dict[str, float],
        improvements: List[CalibrationEvent],
        stable_flags: List[CalibrationEvent],
        domain_anchor: Optional[Dict[str, float]],
    ) -> None:
        result.fn_rate_before, result.fp_rate_before, _ = self._score_weights(
            cw, improvements, stable_flags
        )
        candidates = self._grid_search(improvements, stable_flags, cw, domain_anchor)
        if not candidates:
            result.status = "no_change"
            result.message = "Grid search found no valid candidates."
            return
        candidates.sort(key=lambda c: (c.combined_score, c.tiebreak_score))
        winner = candidates[0]
        result.top_candidates = candidates[:3]
        result.confidence_gap = self._confidence_gap(candidates)
        result.fn_rate_after = winner.fn_rate
        result.fp_rate_after = winner.fp_rate
        result.optimal_weights = {
            "ldr": winner.w_ldr,
            "inflation": winner.w_inflation,
            "ddc": winner.w_ddc,
            "purity": winner.w_purity,
        }
        result.per_rule_fp_rates = self._calc_per_rule_fp_rates(improvements, stable_flags)
        if result.confidence_gap < CONFIDENCE_GAP:
            result.message = (
                f"Confidence gap {result.confidence_gap:.4f} < {CONFIDENCE_GAP}: "
                "candidates are too close, more comparable evidence is needed."
            )
            return
        current_score = result.fn_rate_before + result.fp_rate_before
        if current_score - winner.combined_score < 0.02:
            result.status = "no_change"
            result.optimal_weights = dict(cw)
            result.message = "Current weights already near-optimal for this project."
            return
        result.status = "ok"
        result.message = (
            f"Combined error {current_score:.4f} -> {winner.combined_score:.4f} "
            f"(gap from #2: {result.confidence_gap:.4f}). Advisory only."
        )
        reference = domain_anchor or cw
        for dim in LEARNED:
            drift = abs(result.optimal_weights[dim] - reference.get(dim, 0.0))
            if drift > DOMAIN_DRIFT_LIMIT:
                result.warnings.append(
                    f"{dim}: optimal {result.optimal_weights[dim]:.2f} drifted {drift:.2f} "
                    f"from {reference.get(dim, 0.0):.2f}; exceeds DOMAIN_DRIFT_LIMIT={DOMAIN_DRIFT_LIMIT}."
                )

    @staticmethod
    def _confidence_gap(candidates: List[WeightCandidate]) -> float:
        if len(candidates) < 2:
            return 1.0
        winner, runner_up = candidates[0], candidates[1]
        primary_gap = runner_up.combined_score - winner.combined_score
        if abs(primary_gap) >= 0.0001:
            return round(primary_gap, 4)
        tiebreak_gap = runner_up.tiebreak_score - winner.tiebreak_score
        return round(tiebreak_gap / max(1.0, abs(winner.tiebreak_score)), 4)

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _extract_events(
        self, project_root: str, result: CalibrationResult
    ) -> List[CalibrationEvent]:
        rows, legacy = self._load_history(project_root)
        result.legacy_rows_ignored = legacy
        groups: Dict[Tuple[str, str], List[dict]] = {}
        for row in rows:
            groups.setdefault((row["file_rel_path"], row["measurement_fingerprint"]), []).append(
                row
            )
        result.unique_files = len({rel for rel, _ in groups})
        events: List[CalibrationEvent] = []
        stable_seen: set = set()
        for (rel, _fingerprint), runs in groups.items():
            for now, nxt in zip(runs, runs[1:]):
                result.comparable_pairs += 1
                event = self._classify_pair(rel, now, nxt, stable_seen)
                if event is not None:
                    events.append(event)
        return events

    @staticmethod
    def _classify_pair(
        rel: str, now: dict, nxt: dict, stable_seen: set
    ) -> Optional[CalibrationEvent]:
        weights = now["weights"]
        before = metric_only_deficit(now["ldr"], now["inflation"], now["ddc"], weights)
        if before < SUSPICIOUS_AT:
            return None
        if now["file_hash"] != nxt["file_hash"]:
            after = metric_only_deficit(nxt["ldr"], nxt["inflation"], nxt["ddc"], weights)
            if before - after < FIX_DELTA:
                return None
            label = "improvement"
        elif rel in stable_seen:
            return None
        else:
            stable_seen.add(rel)
            label = "stable_flag_candidate"
        return CalibrationEvent(
            file_path=rel,
            ldr=now["ldr"],
            inflation=now["inflation"],
            ddc=now["ddc"],
            label=label,
            rule_ids=_parse_fired_rules(now["fired_rules"]),
        )

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_weights(
        self,
        weights: Mapping[str, float],
        improvements: List[CalibrationEvent],
        stable_flags: List[CalibrationEvent],
    ) -> Tuple[float, float, float]:
        """(fn_rate, fp_rate, tiebreak) of one weight set on the labeled events."""
        tp_margins: List[float] = []
        fn_count = 0
        for ev in improvements:
            recomputed = metric_only_deficit(ev.ldr, ev.inflation, ev.ddc, weights)
            if recomputed < SUSPICIOUS_AT:
                fn_count += 1
            else:
                tp_margins.append(recomputed - SUSPICIOUS_AT)
        stable_deficits = [
            metric_only_deficit(ev.ldr, ev.inflation, ev.ddc, weights) for ev in stable_flags
        ]
        fp_count = sum(1 for value in stable_deficits if value >= SUSPICIOUS_AT)
        fn_rate = fn_count / len(improvements) if improvements else 0.0
        fp_rate = fp_count / len(stable_flags) if stable_flags else 0.0
        avg_fp = sum(stable_deficits) / len(stable_deficits) if stable_deficits else 0.0
        avg_tp = sum(tp_margins) / len(tp_margins) if tp_margins else 0.0
        return round(fn_rate, 4), round(fp_rate, 4), round(avg_fp - avg_tp, 4)

    @staticmethod
    def _calc_per_rule_fp_rates(
        improvements: List[CalibrationEvent], stable_flags: List[CalibrationEvent]
    ) -> Dict[str, float]:
        """Per pattern: share of its labeled events that were stable flags."""
        rule_fp: Dict[str, int] = {}
        rule_total: Dict[str, int] = {}
        for ev in stable_flags:
            for rid in ev.rule_ids:
                rule_fp[rid] = rule_fp.get(rid, 0) + 1
                rule_total[rid] = rule_total.get(rid, 0) + 1
        for ev in improvements:
            for rid in ev.rule_ids:
                rule_total[rid] = rule_total.get(rid, 0) + 1
        return {
            rid: round(rule_fp.get(rid, 0) / total, 3)
            for rid, total in rule_total.items()
            if total >= MIN_RULE_OCCURRENCES
        }

    def _grid_search(
        self,
        improvements: List[CalibrationEvent],
        stable_flags: List[CalibrationEvent],
        current_weights: Mapping[str, float],
        domain_anchor: Optional[Dict[str, float]] = None,
    ) -> List[WeightCandidate]:
        """ldr/inflation/ddc on a 1/GRID_STEP grid summing to 1 - purity; purity held."""
        purity = round(float(current_weights.get("purity", 0.10)), 4)
        steps = int(round((1.0 - purity) * GRID_STEP))
        bounds = {dim: self._bounds(dim, domain_anchor) for dim in LEARNED}
        candidates: List[WeightCandidate] = []
        for i in range(bounds["ldr"][0], bounds["ldr"][1] + 1):
            for j in range(bounds["inflation"][0], bounds["inflation"][1] + 1):
                k = steps - i - j
                if not bounds["ddc"][0] <= k <= bounds["ddc"][1]:
                    continue
                weights = {
                    "ldr": round(i / GRID_STEP, 4),
                    "inflation": round(j / GRID_STEP, 4),
                    "ddc": round(k / GRID_STEP, 4),
                    "purity": purity,
                }
                fn_rate, fp_rate, tiebreak = self._score_weights(
                    weights, improvements, stable_flags
                )
                candidates.append(
                    WeightCandidate(
                        w_ldr=weights["ldr"],
                        w_inflation=weights["inflation"],
                        w_ddc=weights["ddc"],
                        w_purity=purity,
                        fn_rate=fn_rate,
                        fp_rate=fp_rate,
                        combined_score=round(fn_rate + fp_rate, 4),
                        tiebreak_score=tiebreak,
                    )
                )
        return candidates

    @staticmethod
    def _bounds(dim: str, domain_anchor: Optional[Dict[str, float]]) -> Tuple[int, int]:
        lo, hi = MIN_W, MAX_W
        if domain_anchor:
            anchor = domain_anchor.get(dim, 0.30)
            lo, hi = max(MIN_W, anchor - DOMAIN_TOLERANCE), min(MAX_W, anchor + DOMAIN_TOLERANCE)
        return int(round(lo * GRID_STEP)), int(round(hi * GRID_STEP))

    # ------------------------------------------------------------------
    # SQLite
    # ------------------------------------------------------------------

    def _load_history(self, project_root: str) -> Tuple[List[dict], int]:
        """v6 rows of one project root in run order, and the count of legacy rows."""
        # A database last written by an older release has no v6 columns yet:
        # the tracker's migration adds them (it never rewrites rows).
        HistoryTracker(db_path=self.db_path)
        sql = """
        SELECT file_rel_path, measurement_fingerprint, file_hash, ldr_score,
               inflation_score, ddc_usage_ratio, fired_rules, weights_vector
        FROM history
        WHERE provenance_state = ? AND project_root = ? AND file_rel_path IS NOT NULL
        ORDER BY file_rel_path, measurement_fingerprint, timestamp, id
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql, (PROVENANCE_V6, project_root)).fetchall()
            legacy = conn.execute(
                "SELECT COUNT(*) FROM history WHERE provenance_state IS NULL"
            ).fetchone()[0]
        return [
            {
                "file_rel_path": r[0],
                "measurement_fingerprint": r[1],
                "file_hash": r[2],
                "ldr": r[3],
                "inflation": r[4],
                "ddc": r[5],
                "fired_rules": r[6],
                "weights": json.loads(r[7]),
            }
            for r in rows
        ], int(legacy)
