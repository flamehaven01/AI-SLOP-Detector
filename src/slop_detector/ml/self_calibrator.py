"""
Self-Calibration Engine — adaptive weight optimization from usage history.

Algorithm (LEDA MetaLearning pattern + Copilot Guardian confidence gap):

1. Load all history runs from SQLite (file_path, ldr, inflation, ddc, n_critical_patterns,
   deficit, timestamp)
2. Extract two event types per unique file:
   - improvement_event: deficit > SLOP_FLOOR in run[i], dropped > FIX_DELTA in run[i+1]
     -> current weights caught real slop (true positive candidate)
   - fp_candidate: deficit > SLOP_FLOOR in run[i], same file_hash in run[i+1], no change
     -> user never fixed it; may be a false positive for this codebase's style
3. Grid search over 4D weight simplex {w_ldr + w_inf + w_ddc + w_pur = 1.0, wi >= MIN_W}
4. For each candidate weights, recompute base_deficit (metric-only, no pattern penalties)
   including purity = exp(-0.5 * n_critical_patterns) for the purity dimension,
   and score: FN_rate (missed real slops) + FP_rate (unnecessary alerts)
5. Copilot Guardian-style confidence gap: if winner margin < CONFIDENCE_GAP, more data needed
6. Return CalibrationResult; optionally write to .slopconfig.yaml via --apply-calibration

Labels are derived from USER BEHAVIOUR (did they edit the file?), not from formula outputs.
This breaks the tautology that afflicts the ML classifier.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from math import exp, log
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
MAX_PURITY_WEIGHT: float = (
    0.25  # purity ceiling (v3.4.0): prevents one volatile dimension dominating
)
GRID_STEP: int = 20  # 1/GRID_STEP resolution -> 0.05 increments
CONFIDENCE_GAP: float = 0.10  # min score gap between #1 and #2 candidate (Guardian pattern)
# v3.2.1: per-class minimums replace single MIN_EVENTS=20.
# 4D model (+ continuous tiebreak) resolves candidates with fewer events than 3D binary-only.
# Safety gates (CONFIDENCE_GAP + no_change margin) prevent premature calibration.
MIN_IMPROVEMENTS: int = 5  # improvement events required (true positive class)
MIN_FP_CANDIDATES: int = 5  # fp_candidate events required (false positive class)
CALIBRATION_MILESTONE: int = MIN_IMPROVEMENTS + MIN_FP_CANDIDATES  # = 10
MIN_RULE_OCCURRENCES: int = 3  # min times a rule must fire to appear in per_rule_fp_rates
DOMAIN_TOLERANCE: float = 0.15  # P3: max per-dimension deviation from domain anchor in grid search


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
    n_critical_patterns: int  # CRITICAL-severity pattern count (purity dimension)
    label: str  # "improvement" | "fp_candidate"
    rule_ids: List[str] = field(default_factory=list)  # v3.4.0: pattern_ids that fired


@dataclass
class WeightCandidate:
    """One weight hypothesis with its scored performance."""

    w_ldr: float
    w_inflation: float
    w_ddc: float
    w_purity: float = 0.0
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
    per_rule_fp_rates: Dict[str, float] = field(default_factory=dict)  # v3.4.0: rule_id -> FP rate
    message: str = ""


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _parse_fired_rules(fired_rules_json: Optional[str]) -> List[str]:
    """Parse a fired_rules JSON string into a list of unique pattern_ids.

    fired_rules is stored as ``{"pattern_id": count, ...}`` in history.db.
    Returns an empty list for NULL / malformed entries (old rows pre-v3.4.0).
    """
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
        min_events: int = MIN_IMPROVEMENTS,  # per-class floor; applies to both improvement and fp_candidate classes
        project_id: Optional[str] = None,  # P1: restrict history to this project
        domain_anchor: Optional[Dict[str, float]] = None,  # P3: constrain grid to ±DOMAIN_TOLERANCE of anchor
    ) -> CalibrationResult:
        """Run self-calibration. Returns CalibrationResult with optimal weights.

        v3.2.1: per-class minimums replace total MIN_EVENTS threshold.
        min_events sets the per-class floor (applied independently to improvements and fp_candidates).
        Default is MIN_IMPROVEMENTS (5). To require stricter per-class quorum, pass higher value.

        v3.5.0:
          project_id — when provided, only history rows matching this project are used.
          domain_anchor — when provided, grid search is constrained to ±DOMAIN_TOLERANCE
            around each anchor dimension weight (prevents cross-domain calibration drift).
        """
        cw = (
            dict(current_weights)
            if current_weights
            else {"ldr": 0.40, "inflation": 0.30, "ddc": 0.30}
        )
        cw.setdefault("purity", 0.10)  # inject purity default for pre-v3.2.0 configs

        # per-class floors — caller can override via min_events (applies to both classes)
        min_imp = max(min_events, MIN_IMPROVEMENTS)
        min_fp = max(min_events, MIN_FP_CANDIDATES)

        if not self.db_path.exists():
            return CalibrationResult(
                status="insufficient_data",
                current_weights=cw,
                message="No history database found. Run slop-detector on your files first.",
            )

        events, unique_files = self._extract_events(project_id=project_id)
        improvements = [e for e in events if e.label == "improvement"]
        fp_candidates = [e for e in events if e.label == "fp_candidate"]

        result = CalibrationResult(
            status="insufficient_data",
            unique_files=unique_files,
            improvement_events=len(improvements),
            fp_candidates=len(fp_candidates),
            current_weights=cw,
        )

        # Per-class floor check: both classes must meet minimum independently
        if len(improvements) < min_imp or len(fp_candidates) < min_fp:
            result.message = (
                f"Need >= {min_imp} improvement events (have {len(improvements)}) "
                f"and >= {min_fp} FP candidates (have {len(fp_candidates)}). "
                f"Keep using the tool — data accumulates automatically."
            )
            return result

        # Score current weights as baseline (4D)
        result.fn_rate_before, result.fp_rate_before, _ = self._score_weights(
            cw["ldr"], cw["inflation"], cw["ddc"], cw["purity"], improvements, fp_candidates
        )

        # Grid search (P3: pass domain_anchor for constrained search)
        candidates = self._grid_search(improvements, fp_candidates, domain_anchor=domain_anchor)
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
            "purity": winner.w_purity,
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

        result.per_rule_fp_rates = self._calc_per_rule_fp_rates(improvements, fp_candidates)
        return result

    # ------------------------------------------------------------------
    # Event extraction (label derivation from user behaviour)
    # ------------------------------------------------------------------

    def _extract_events(
        self, project_id: Optional[str] = None
    ) -> Tuple[List[CalibrationEvent], int]:
        """
        Load history and derive labeled events (improvement / fp_candidate).
        Delegates to helpers to keep nesting shallow and each responsibility single.
        """
        rows = self._load_history(project_id=project_id)
        by_file = self._group_runs_by_file(rows)
        seen_fp_files: set = set()
        events: List[CalibrationEvent] = []
        for file_path, runs in by_file.items():
            for ev in self._classify_consecutive_runs(file_path, runs, seen_fp_files):
                events.append(ev)
        return events, len(by_file)

    @staticmethod
    def _group_runs_by_file(rows: list) -> Dict[str, list]:
        """Group history rows by file_path and sort each group by timestamp ascending."""
        by_file: Dict[str, list] = {}
        for row in rows:
            by_file.setdefault(row["file_path"], []).append(row)
        for runs in by_file.values():
            runs.sort(key=lambda r: r["timestamp"])
        return by_file

    @staticmethod
    def _classify_consecutive_runs(
        file_path: str, runs: list, seen_fp_files: set
    ) -> List[CalibrationEvent]:
        """
        Emit CalibrationEvents for consecutive run pairs on one file.

        improvement: deficit dropped > FIX_DELTA -> user edited the file (true positive)
        fp_candidate: same hash, score stable -> user ignored warning (false positive candidate)
        Each file contributes at most one fp_candidate to prevent consecutive-run bias.
        """
        if len(runs) < 2:
            return []
        events: List[CalibrationEvent] = []
        for i in range(len(runs) - 1):
            r_now, r_next = runs[i], runs[i + 1]
            if r_now["deficit_score"] <= SLOP_FLOOR:
                continue
            drop = r_now["deficit_score"] - r_next["deficit_score"]
            ev = SelfCalibrator._classify_run_pair(file_path, r_now, r_next, drop, seen_fp_files)
            if ev is not None:
                events.append(ev)
        return events

    @staticmethod
    def _classify_run_pair(
        file_path: str, r_now: dict, r_next: dict, drop: float, seen_fp_files: set
    ) -> Optional[CalibrationEvent]:
        """Classify a single (r_now, r_next) pair as improvement, fp_candidate, or None.

        v3.2.1 — git_commit used as noise filter (when available):
          improvement: if git commits are IDENTICAL, the score drop is measurement noise → skip.
          fp_candidate: if git commits DIFFER, the stable score is ambiguous
                        (user may have committed unrelated changes) → skip.
        When git info is absent (NULL), original hash-based heuristic applies unchanged.
        """
        git_now = r_now.get("git_commit")
        git_next = r_next.get("git_commit")
        has_git = bool(git_now and git_next)

        if drop >= FIX_DELTA:
            # Same commit: score drop within one commit is measurement noise, not a real fix
            if has_git and git_now == git_next:
                return None
            return CalibrationEvent(
                file_path=file_path,
                ldr=r_now["ldr_score"],
                inflation=r_now["inflation_score"],
                ddc=r_now["ddc_usage_ratio"],
                n_critical_patterns=r_now["n_critical_patterns"],
                label="improvement",
                rule_ids=_parse_fired_rules(r_now.get("fired_rules")),
            )
        if (
            file_path not in seen_fp_files
            and r_now["file_hash"] == r_next["file_hash"]
            and abs(drop) < FP_STABLE_DELTA
        ):
            # Different commits + stable hash: user committed something unrelated → ambiguous
            if has_git and git_now != git_next:
                return None
            seen_fp_files.add(file_path)
            return CalibrationEvent(
                file_path=file_path,
                ldr=r_now["ldr_score"],
                inflation=r_now["inflation_score"],
                ddc=r_now["ddc_usage_ratio"],
                n_critical_patterns=r_now["n_critical_patterns"],
                label="fp_candidate",
                rule_ids=_parse_fired_rules(r_now.get("fired_rules")),
            )
        return None

    # ------------------------------------------------------------------
    # Deficit recomputation
    # ------------------------------------------------------------------

    @staticmethod
    def _recompute_deficit(
        ldr: float,
        inflation: float,
        ddc: float,
        n_critical_patterns: int,
        w_ldr: float,
        w_inflation: float,
        w_ddc: float,
        w_purity: float,
    ) -> float:
        """
        Recompute base deficit score with candidate weights (4D GQG).
        Mirrors core.py _calculate_slop_score (metric component only, GQG geometric mean).
        Pattern penalties are orthogonal to weight calibration and excluded from FN/FP scoring.

        Purity dimension: purity_score = exp(-0.5 * n_critical_patterns)
          - 1.0 when no critical patterns (perfect purity)
          - Decays toward 0 as critical patterns accumulate
          - This raw count is stored in history.db (v3.2.0+); old rows default to 0.
        """
        inflation_normalized = min(inflation, 2.0) / 2.0
        purity_score = exp(-0.5 * n_critical_patterns)
        total_w = w_ldr + w_inflation + w_ddc + w_purity
        gqg = exp(
            (
                w_ldr * log(max(1e-4, ldr))
                + w_inflation * log(max(1e-4, 1.0 - inflation_normalized))
                + w_ddc * log(max(1e-4, ddc))
                + w_purity * log(max(1e-4, purity_score))
            )
            / total_w
        )
        return min(100.0, 100.0 * (1.0 - gqg))

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_weights(
        self,
        w_ldr: float,
        w_inflation: float,
        w_ddc: float,
        w_purity: float,
        improvements: List[CalibrationEvent],
        fp_candidates: List[CalibrationEvent],
    ) -> Tuple[float, float, float]:
        """
        Score a weight set (4D). Returns (fn_rate, fp_rate, tiebreak_score).

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
                ev.ldr,
                ev.inflation,
                ev.ddc,
                ev.n_critical_patterns,
                w_ldr,
                w_inflation,
                w_ddc,
                w_purity,
            )
            if recomputed < SLOP_FLOOR:
                fn_count += 1
            else:
                tp_margins.append(recomputed - SLOP_FLOOR)

        fp_count = 0
        fp_deficits: List[float] = []
        for ev in fp_candidates:
            recomputed = self._recompute_deficit(
                ev.ldr,
                ev.inflation,
                ev.ddc,
                ev.n_critical_patterns,
                w_ldr,
                w_inflation,
                w_ddc,
                w_purity,
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
    # Per-rule FP rate analysis (v3.4.0)
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_per_rule_fp_rates(
        improvements: List[CalibrationEvent],
        fp_candidates: List[CalibrationEvent],
    ) -> Dict[str, float]:
        """Compute per-rule FP rate from labeled events.

        For each pattern_id X:
            fp_rate_X = (fp_candidate events where X fired) / (all events where X fired)

        Only rules appearing in >= MIN_RULE_OCCURRENCES events are included.
        A rule with fp_rate >= 0.7 fires mostly on false positives for this codebase
        and is a candidate for suppression via .slopconfig.yaml.
        """
        rule_fp: Dict[str, int] = {}
        rule_total: Dict[str, int] = {}
        for ev in fp_candidates:
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

    # ------------------------------------------------------------------
    # Grid search over simplex {w1+w2+w3=1, wi in [MIN_W, MAX_W]}
    # ------------------------------------------------------------------

    def _grid_search(
        self,
        improvements: List[CalibrationEvent],
        fp_candidates: List[CalibrationEvent],
        domain_anchor: Optional[Dict[str, float]] = None,
    ) -> List[WeightCandidate]:
        """
        Exhaustive grid search over the 4D weight simplex.
        Resolution: 1/GRID_STEP = 0.05 increments.
        Constraint: w_ldr + w_inf + w_ddc + w_purity = 1.0, each in [MIN_W, MAX_W].
        Purity is additionally capped at MAX_PURITY_WEIGHT (v3.4.0) to prevent a
        volatile count-based dimension from dominating calibration.

        P3 (v3.5.0): when domain_anchor is provided, each dimension's search range is
        constrained to [anchor - DOMAIN_TOLERANCE, anchor + DOMAIN_TOLERANCE] (clipped to
        absolute MIN_W/MAX_W). This prevents calibration from drifting outside the
        domain's meaningful weight region (e.g. scientific projects keep inflation low).

        Returns all valid candidates sorted ascending by combined score.
        """
        candidates: List[WeightCandidate] = []
        step = 1.0 / GRID_STEP

        min_i = int(MIN_W * GRID_STEP)
        max_i = int(MAX_W * GRID_STEP)
        max_p = int(MAX_PURITY_WEIGHT * GRID_STEP)  # purity ceiling: 0.25 * 20 = 5

        if domain_anchor:
            def _dim_bounds(key: str, hard_max: int = max_i) -> Tuple[int, int]:
                anchor_v = domain_anchor.get(key, 0.30)
                lo = max(min_i, int(round(max(MIN_W, anchor_v - DOMAIN_TOLERANCE) * GRID_STEP)))
                hi = min(hard_max, int(round(min(MAX_W, anchor_v + DOMAIN_TOLERANCE) * GRID_STEP)))
                return lo, hi
            ldr_lo, ldr_hi = _dim_bounds("ldr")
            inf_lo, inf_hi = _dim_bounds("inflation")
            ddc_lo, ddc_hi = _dim_bounds("ddc")
            pur_lo, pur_hi = _dim_bounds("purity", hard_max=max_p)
        else:
            ldr_lo, ldr_hi = min_i, max_i
            inf_lo, inf_hi = min_i, max_i
            ddc_lo, ddc_hi = min_i, max_i
            pur_lo, pur_hi = min_i, max_p

        for i in range(ldr_lo, ldr_hi + 1):
            for j in range(inf_lo, inf_hi + 1):
                for p in range(pur_lo, pur_hi + 1):
                    k = GRID_STEP - i - j - p
                    if k < ddc_lo or k > ddc_hi:
                        continue

                    w_ldr = round(i * step, 4)
                    w_inf = round(j * step, 4)
                    w_ddc = round(k * step, 4)
                    w_pur = round(p * step, 4)

                    fn_rate, fp_rate, tiebreak = self._score_weights(
                        w_ldr, w_inf, w_ddc, w_pur, improvements, fp_candidates
                    )
                    combined = round(fn_rate + fp_rate, 4)

                    candidates.append(
                        WeightCandidate(
                            w_ldr=w_ldr,
                            w_inflation=w_inf,
                            w_ddc=w_ddc,
                            w_purity=w_pur,
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

    def _load_history(self, project_id: Optional[str] = None) -> List[Dict]:
        """Load history rows, optionally filtered by project_id (v3.5.0 P1)."""
        base_sql = """
        SELECT file_path, file_hash, timestamp,
               deficit_score, ldr_score, inflation_score, ddc_usage_ratio,
               COALESCE(n_critical_patterns, 0),
               git_commit,
               fired_rules
        FROM history
        {where}
        ORDER BY file_path, timestamp ASC
        """
        if project_id is not None:
            sql = base_sql.format(where="WHERE project_id = ?")
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(sql, (project_id,)).fetchall()
        else:
            sql = base_sql.format(where="")
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
                "n_critical_patterns": int(r[7]),
                "git_commit": r[8],  # v3.2.1: used as noise filter in _classify_run_pair
                "fired_rules": r[9],  # v3.4.0: JSON {pattern_id: count} or None
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
        Write calibrated weights into .slopconfig.yaml using in-place line replacement.

        Preserves all comments, domain_overrides, ignore patterns, and every other
        key in the file. Only the numeric values of the ldr / inflation / ddc lines
        inside the weights: block are rewritten.

        Creates a minimal config with just the weights block if the file does not exist.
        """
        import re

        path = Path(config_path)

        if not path.exists():
            lines = [
                "# Auto-generated by slop-detector --apply-calibration\n",
                "weights:\n",
                f"  ldr: {weights['ldr']}\n",
                f"  inflation: {weights['inflation']}\n",
                f"  ddc: {weights['ddc']}\n",
                f"  purity: {weights.get('purity', 0.10)}\n",
            ]
            path.write_text("".join(lines), encoding="utf-8")
            return str(path.resolve())

        text = path.read_text(encoding="utf-8")
        updated: set = set()

        def _rewrite_key(t: str, key: str, value: float) -> Tuple[str, bool]:
            # Matches "  ldr: 0.40  # optional comment" and replaces the numeric
            # value only, leaving whitespace and inline comments intact.
            pat = rf"^([ \t]*{re.escape(key)}:[ \t]+)\S+([ \t]*(?:#.*)?)$"
            new_t, n = re.subn(pat, rf"\g<1>{value}\g<2>", t, flags=re.MULTILINE)
            return new_t, n > 0

        for key in ("ldr", "inflation", "ddc", "purity"):
            val = weights.get(key, 0.10 if key == "purity" else weights.get("ldr", 0.0))
            text, replaced = _rewrite_key(text, key, val)
            if replaced:
                updated.add(key)

        missing = {"ldr", "inflation", "ddc", "purity"} - updated
        if missing:
            if re.search(r"^[ \t]*weights:\s*$", text, flags=re.MULTILINE):
                missing_block = "\n".join(
                    f"  {k}: {weights.get(k, 0.10 if k == 'purity' else 0.0)}"
                    for k in sorted(missing)
                )
                text = re.sub(
                    r"^([ \t]*weights:\s*)$",
                    rf"\g<1>\n{missing_block}",
                    text,
                    flags=re.MULTILINE,
                )
            else:
                # No weights block at all — append one
                if not text.endswith("\n"):
                    text += "\n"
                text += "\nweights:\n"
                for k in ("ldr", "inflation", "ddc", "purity"):
                    text += f"  {k}: {weights.get(k, 0.10 if k == 'purity' else 0.0)}\n"

        path.write_text(text, encoding="utf-8")
        return str(path.resolve())
