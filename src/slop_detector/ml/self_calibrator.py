"""
Self-Calibration Engine — adaptive weight optimization from usage history.

Algorithm (LEDA MetaLearning pattern + Copilot Guardian confidence gap):

1. Load all history runs from SQLite (file_path, ldr, inflation, ddc, deficit, timestamp)
2. Extract two event types per unique file:
   - improvement_event: deficit > SLOP_FLOOR in run[i], dropped > FIX_DELTA in run[i+1]
     -> current weights caught real slop (true positive candidate)
   - fp_candidate: deficit > SLOP_FLOOR in run[i], same file_hash in run[i+1], no change
     -> user never fixed it; may be a false positive for this codebase's style
3. Grid search over weight simplex {w_ldr + w_inflation + w_ddc = 1.0, wi >= MIN_W}
4. For each candidate weights, recompute base_deficit (metric-only, no pattern penalties)
   and score: FN_rate (missed real slops) + FP_rate (unnecessary alerts)
5. Copilot Guardian-style confidence gap: if winner margin < CONFIDENCE_GAP, more data needed
6. Return CalibrationResult; optionally write to .slopconfig.yaml via --apply-calibration

Labels are derived from USER BEHAVIOUR (did they edit the file?), not from formula outputs.
This breaks the tautology that afflicts the ML classifier.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

SLOP_FLOOR: float = 25.0  # min deficit to be considered "slop-flagged"
FIX_DELTA: float = 10.0  # score drop required to count as "user fixed it"
FP_STABLE_DELTA: float = 5.0  # max score change between runs to call it "stable / unfixed"
MIN_W: float = 0.10  # minimum allowed weight per dimension
MAX_W: float = 0.65  # maximum allowed weight per dimension
GRID_STEP: int = 20  # 1/GRID_STEP resolution -> 0.05 increments
CONFIDENCE_GAP: float = 0.10  # min score gap between #1 and #2 candidate (Guardian pattern)
MIN_EVENTS: int = 10  # minimum labeled events before calibration is meaningful


# ------------------------------------------------------------------
# Data structures
# ------------------------------------------------------------------


@dataclass
class CalibrationEvent:
    """A single labeled training event derived from history."""

    file_path: str
    ldr: float
    inflation: float  # raw inflation_score (not normalized)
    ddc: float  # usage_ratio
    label: str  # "improvement" | "fp_candidate"


@dataclass
class WeightCandidate:
    """One weight hypothesis with its scored performance."""

    w_ldr: float
    w_inflation: float
    w_ddc: float
    fn_rate: float = 0.0  # missed real slops (binary)
    fp_rate: float = 0.0  # unnecessary alerts (binary)
    combined_score: float = 0.0  # fn_rate + fp_rate (lower = better)
    tiebreak_score: float = 0.0  # continuous secondary: avg deficit gap (lower = better)


@dataclass
class CalibrationResult:
    """Output of the self-calibration run."""

    status: str  # "ok" | "insufficient_data" | "no_change"
    unique_files: int = 0
    improvement_events: int = 0
    fp_candidates: int = 0
    current_weights: Dict[str, float] = field(default_factory=dict)
    optimal_weights: Dict[str, float] = field(default_factory=dict)
    confidence_gap: float = 0.0
    fn_rate_before: float = 0.0
    fp_rate_before: float = 0.0
    fn_rate_after: float = 0.0
    fp_rate_after: float = 0.0
    top_candidates: List[WeightCandidate] = field(default_factory=list)
    message: str = ""


# ------------------------------------------------------------------
# Core engine
# ------------------------------------------------------------------


class SelfCalibrator:
    """
    Reads history.db and finds optimal ldr/inflation/ddc weights
    for the user's specific codebase via grid search over the weight simplex.
    """

    DEFAULT_DB = Path.home() / ".slop-detector" / "history.db"

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calibrate(
        self,
        current_weights: Optional[Dict[str, float]] = None,
        min_events: int = MIN_EVENTS,
    ) -> CalibrationResult:
        """Run self-calibration. Returns CalibrationResult with optimal weights."""
        cw = current_weights or {"ldr": 0.40, "inflation": 0.30, "ddc": 0.30}

        if not self.db_path.exists():
            return CalibrationResult(
                status="insufficient_data",
                current_weights=cw,
                message="No history database found. Run slop-detector on your files first.",
            )

        events, unique_files = self._extract_events()
        improvements = [e for e in events if e.label == "improvement"]
        fp_candidates = [e for e in events if e.label == "fp_candidate"]

        result = CalibrationResult(
            status="insufficient_data",
            unique_files=unique_files,
            improvement_events=len(improvements),
            fp_candidates=len(fp_candidates),
            current_weights=cw,
        )

        total_events = len(improvements) + len(fp_candidates)
        if total_events < min_events:
            result.message = (
                f"Need >= {min_events} labeled events; have {total_events}. "
                f"Keep using the tool — data accumulates automatically."
            )
            return result

        # Score current weights as baseline
        result.fn_rate_before, result.fp_rate_before, _ = self._score_weights(
            cw["ldr"], cw["inflation"], cw["ddc"], improvements, fp_candidates
        )

        # Grid search
        candidates = self._grid_search(improvements, fp_candidates)
        if not candidates:
            result.status = "no_change"
            result.message = "Grid search found no valid candidates."
            return result

        candidates.sort(key=lambda c: (c.combined_score, c.tiebreak_score))
        winner = candidates[0]
        result.top_candidates = candidates[:3]

        # Confidence gap check (Copilot Guardian pattern)
        # Uses tiebreak_score when primary scores are equal
        if len(candidates) >= 2:
            runner_up = candidates[1]
            primary_gap = runner_up.combined_score - winner.combined_score
            if abs(primary_gap) < 0.0001:
                # Tied on binary rate — use continuous tiebreak gap
                tiebreak_gap = runner_up.tiebreak_score - winner.tiebreak_score
                result.confidence_gap = round(
                    tiebreak_gap / max(1.0, abs(winner.tiebreak_score)), 4
                )
            else:
                result.confidence_gap = round(primary_gap, 4)
        else:
            result.confidence_gap = 1.0

        result.fn_rate_after = winner.fn_rate
        result.fp_rate_after = winner.fp_rate
        result.optimal_weights = {
            "ldr": winner.w_ldr,
            "inflation": winner.w_inflation,
            "ddc": winner.w_ddc,
        }

        if result.confidence_gap < CONFIDENCE_GAP:
            result.status = "insufficient_data"
            result.message = (
                f"Confidence gap {result.confidence_gap:.4f} < {CONFIDENCE_GAP}. "
                f"Candidates are too close — need more history data for reliable calibration."
            )
            return result

        # Check if winner is meaningfully different from current
        current_score = result.fn_rate_before + result.fp_rate_before
        winner_score = winner.combined_score
        if current_score - winner_score < 0.02:
            result.status = "no_change"
            result.optimal_weights = cw
            result.message = (
                f"Current weights already near-optimal for this codebase "
                f"(improvement margin: {(current_score - winner_score):.4f})."
            )
        else:
            result.status = "ok"
            result.message = (
                f"Calibration complete. Combined error reduced "
                f"{current_score:.4f} -> {winner_score:.4f} "
                f"(gap from #2: {result.confidence_gap:.4f})."
            )

        return result

    # ------------------------------------------------------------------
    # Event extraction (label derivation from user behaviour)
    # ------------------------------------------------------------------

    def _extract_events(self) -> Tuple[List[CalibrationEvent], int]:
        """
        Load history and derive labeled events.

        improvement: deficit was high, next run it dropped significantly
                     -> user edited the file; current weights correctly flagged it
        fp_candidate: deficit was high, same hash in next run, score barely moved
                     -> user saw the warning and ignored it; likely FP for this style
        """
        rows = self._load_history()

        # Group by file_path, sorted by timestamp ascending
        by_file: Dict[str, list] = {}
        for row in rows:
            by_file.setdefault(row["file_path"], []).append(row)
        for runs in by_file.values():
            runs.sort(key=lambda r: r["timestamp"])

        events: List[CalibrationEvent] = []
        unique_files = len(by_file)

        for file_path, runs in by_file.items():
            if len(runs) < 2:
                continue
            for i in range(len(runs) - 1):
                r_now = runs[i]
                r_next = runs[i + 1]

                if r_now["deficit_score"] <= SLOP_FLOOR:
                    continue  # was clean; not informative for slop calibration

                drop = r_now["deficit_score"] - r_next["deficit_score"]

                if drop >= FIX_DELTA:
                    # Score improved significantly -> user likely edited it
                    events.append(
                        CalibrationEvent(
                            file_path=file_path,
                            ldr=r_now["ldr_score"],
                            inflation=r_now["inflation_score"],
                            ddc=r_now["ddc_usage_ratio"],
                            label="improvement",
                        )
                    )
                elif r_now["file_hash"] == r_next["file_hash"] and abs(drop) < FP_STABLE_DELTA:
                    # Same content, same bad score, user did nothing
                    events.append(
                        CalibrationEvent(
                            file_path=file_path,
                            ldr=r_now["ldr_score"],
                            inflation=r_now["inflation_score"],
                            ddc=r_now["ddc_usage_ratio"],
                            label="fp_candidate",
                        )
                    )

        return events, unique_files

    # ------------------------------------------------------------------
    # Deficit recomputation
    # ------------------------------------------------------------------

    @staticmethod
    def _recompute_deficit(
        ldr: float,
        inflation: float,
        ddc: float,
        w_ldr: float,
        w_inflation: float,
        w_ddc: float,
    ) -> float:
        """
        Recompute base deficit score with candidate weights.
        Mirrors core.py _calculate_slop_score (metric component only).
        Pattern penalties are orthogonal to weight calibration and excluded.
        """
        inflation_normalized = min(inflation, 2.0) / 2.0 if inflation != float("inf") else 1.0
        base_quality = ldr * w_ldr + (1.0 - inflation_normalized) * w_inflation + ddc * w_ddc
        return min(100.0, 100.0 * (1.0 - base_quality))

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_weights(
        self,
        w_ldr: float,
        w_inflation: float,
        w_ddc: float,
        improvements: List[CalibrationEvent],
        fp_candidates: List[CalibrationEvent],
    ) -> Tuple[float, float, float]:
        """
        Score a weight set. Returns (fn_rate, fp_rate, tiebreak_score).

        fn_rate: fraction of improvement events where new weights score < SLOP_FLOOR (missed)
        fp_rate: fraction of fp_candidates where new weights still score >= SLOP_FLOOR (FP)
        tiebreak_score: continuous secondary metric for breaking ties in (fn+fp) rate.
            = avg recomputed deficit on FP candidates (lower = better, fewer over-detections)
              - avg margin above SLOP_FLOOR on improvement events (higher margin = better coverage)
            Combined: fp_avg_deficit - tp_avg_margin (lower = better)
        """
        fn_count = 0
        tp_margins: List[float] = []
        for ev in improvements:
            recomputed = self._recompute_deficit(
                ev.ldr, ev.inflation, ev.ddc, w_ldr, w_inflation, w_ddc
            )
            if recomputed < SLOP_FLOOR:
                fn_count += 1
            else:
                tp_margins.append(recomputed - SLOP_FLOOR)

        fp_count = 0
        fp_deficits: List[float] = []
        for ev in fp_candidates:
            recomputed = self._recompute_deficit(
                ev.ldr, ev.inflation, ev.ddc, w_ldr, w_inflation, w_ddc
            )
            fp_deficits.append(recomputed)
            if recomputed >= SLOP_FLOOR:
                fp_count += 1

        fn_rate = fn_count / len(improvements) if improvements else 0.0
        fp_rate = fp_count / len(fp_candidates) if fp_candidates else 0.0

        avg_fp_deficit = sum(fp_deficits) / len(fp_deficits) if fp_deficits else 0.0
        avg_tp_margin = sum(tp_margins) / len(tp_margins) if tp_margins else 0.0
        tiebreak = round(avg_fp_deficit - avg_tp_margin, 4)

        return round(fn_rate, 4), round(fp_rate, 4), tiebreak

    # ------------------------------------------------------------------
    # Grid search over simplex {w1+w2+w3=1, wi in [MIN_W, MAX_W]}
    # ------------------------------------------------------------------

    def _grid_search(
        self,
        improvements: List[CalibrationEvent],
        fp_candidates: List[CalibrationEvent],
    ) -> List[WeightCandidate]:
        """
        Exhaustive grid search over the weight simplex.
        Resolution: 1/GRID_STEP = 0.05 increments.
        Returns all valid candidates sorted ascending by combined score.
        """
        candidates: List[WeightCandidate] = []
        step = 1.0 / GRID_STEP

        # Enumerate integer grid (i + j + k = GRID_STEP, all >= MIN_W*GRID_STEP)
        min_i = int(MIN_W * GRID_STEP)
        max_i = int(MAX_W * GRID_STEP)

        for i in range(min_i, max_i + 1):
            for j in range(min_i, max_i + 1):
                k = GRID_STEP - i - j
                if k < min_i or k > max_i:
                    continue

                w_ldr = round(i * step, 4)
                w_inf = round(j * step, 4)
                w_ddc = round(k * step, 4)

                fn_rate, fp_rate, tiebreak = self._score_weights(
                    w_ldr, w_inf, w_ddc, improvements, fp_candidates
                )
                combined = round(fn_rate + fp_rate, 4)

                candidates.append(
                    WeightCandidate(
                        w_ldr=w_ldr,
                        w_inflation=w_inf,
                        w_ddc=w_ddc,
                        fn_rate=fn_rate,
                        fp_rate=fp_rate,
                        combined_score=combined,
                        tiebreak_score=tiebreak,
                    )
                )

        return candidates

    # ------------------------------------------------------------------
    # SQLite
    # ------------------------------------------------------------------

    def _load_history(self) -> List[Dict]:
        sql = """
        SELECT file_path, file_hash, timestamp,
               deficit_score, ldr_score, inflation_score, ddc_usage_ratio
        FROM history
        ORDER BY file_path, timestamp ASC
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(sql).fetchall()
        return [
            {
                "file_path": r[0],
                "file_hash": r[1],
                "timestamp": r[2],
                "deficit_score": r[3],
                "ldr_score": r[4],
                "inflation_score": r[5],
                "ddc_usage_ratio": r[6],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Apply to .slopconfig.yaml
    # ------------------------------------------------------------------

    @staticmethod
    def apply_to_config(
        weights: Dict[str, float],
        config_path: str = ".slopconfig.yaml",
    ) -> str:
        """
        Write calibrated weights into .slopconfig.yaml.
        Creates the file if it does not exist.
        Preserves all other keys.
        """
        import yaml  # already a required dep

        path = Path(config_path)
        data: Dict = {}

        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

        data.setdefault("weights", {})
        data["weights"]["ldr"] = weights["ldr"]
        data["weights"]["inflation"] = weights["inflation"]
        data["weights"]["ddc"] = weights["ddc"]

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        return str(path.resolve())
