"""A verification oracle for self-calibration: synthetic history with a known answer.

Ground truth is a weight vector TRUE_WEIGHTS: a file is real slop when its
metric-only deficit under TRUE_WEIGHTS reaches the canonical band threshold.
The detector's current weights (the defaults) disagree with it, so they flag
some clean files (false positives) and miss some slop (false negatives).

Each file gets two scans. Between them a simulated user acts only on what
the current weights flag:
- real slop, fixed (probability `fix_rate`): new bytes, clean metrics;
- real slop, left as it is: the same bytes again (an unresolved real warning);
- a false positive, declared with `fp:` (probability `declare_rate`): new
  bytes (the comment), the same metrics;
- a false positive left as it is: the same bytes again;
- anything not flagged: the same bytes again.

Files are split by index: two thirds are written to a history database and
calibrated on, one third is held out. On the held-out files, the false
positive rate and the false negative rate of the current and the recommended
weights are measured against the truth, each on its own.

Nothing here is a claim about real projects: the oracle shows what the
learner does when its labels are, or are not, what they are taken to mean.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Tuple

from slop_detector import __version__
from slop_detector.config import Config
from slop_detector.diagnostic_bands import SUSPICIOUS_AT
from slop_detector.history import HistoryEntry, HistoryTracker
from slop_detector.ml.self_calibrator import SelfCalibrator, metric_only_deficit

ROOT = "/oracle"
CURRENT_WEIGHTS = dict(Config.DEFAULT_CONFIG["weights"])
# On the learner's grid (0.05 steps, each learned weight in 0.10..0.65, purity held).
TRUE_WEIGHTS = {"ldr": 0.20, "inflation": 0.50, "ddc": 0.20, "purity": 0.10}
CLEAN_METRICS = (0.95, 0.0, 1.0)


@dataclass
class OracleRun:
    """What the oracle wrote, what the learner chose and recommended, and how each scores.

    `winner` is the learner's best candidate; `recommended` is what the report
    recommends (the winner only when status is "ok", else the current weights:
    the confidence gate withheld it)."""

    status: str
    confidence_gap: float
    winner: Dict[str, float]
    recommended: Dict[str, float]
    train_files: int
    held_out_files: int
    labels: Dict[str, int] = field(default_factory=dict)  # true count of each user action
    before: Dict[str, float] = field(default_factory=dict)  # held-out fp_rate / fn_rate
    after_winner: Dict[str, float] = field(default_factory=dict)
    after_recommended: Dict[str, float] = field(default_factory=dict)


def _flagged(metrics: Tuple[float, float, float], weights: Dict[str, float]) -> bool:
    return metric_only_deficit(*metrics, weights) >= SUSPICIOUS_AT


def _population(rng: random.Random, files: int) -> List[Tuple[float, float, float]]:
    return [
        (round(rng.uniform(0.25, 1.0), 3), round(rng.uniform(0.0, 1.6), 3),
         round(rng.uniform(0.35, 1.0), 3))
        for _ in range(files)
    ]


def _row(tracker: HistoryTracker, rel: str, ts: str, file_hash: str, metrics) -> None:
    entry = HistoryEntry(
        timestamp=ts,
        file_path=f"{ROOT}/{rel}",
        file_hash=file_hash,
        deficit_score=metric_only_deficit(*metrics, CURRENT_WEIGHTS),
        ldr_score=metrics[0],
        inflation_score=metrics[1],
        ddc_usage_ratio=metrics[2],
        pattern_count=0,
        withheld_evidence=json.dumps(
            {"suppressed": [], "unmeasured": [], "masked": [], "ignored": []}
        ),
    )
    entry.detector_version = __version__
    entry.measurement_fingerprint = "oracle"
    entry.weights_vector = json.dumps(CURRENT_WEIGHTS, sort_keys=True)
    entry.project_root = ROOT
    entry.file_rel_path = rel
    entry.provenance_state = "v7"
    entry.language = "python"
    entry.parser_mode = "python_ast"
    tracker._insert(entry)


def _action(rng, metrics, fix_rate: float, declare_rate: float) -> str:
    if not _flagged(metrics, CURRENT_WEIGHTS):
        return "not_flagged"
    if _flagged(metrics, TRUE_WEIGHTS):
        return "fixed" if rng.random() < fix_rate else "unresolved_real_warning"
    return "declared_false_positive" if rng.random() < declare_rate else "false_positive_left"


def _rates(population, weights: Dict[str, float]) -> Dict[str, float]:
    slop = [m for m in population if _flagged(m, TRUE_WEIGHTS)]
    clean = [m for m in population if not _flagged(m, TRUE_WEIGHTS)]
    false_pos = sum(1 for m in clean if _flagged(m, weights))
    false_neg = sum(1 for m in slop if not _flagged(m, weights))
    return {
        "fp_rate": round(false_pos / len(clean), 4) if clean else 0.0,
        "fn_rate": round(false_neg / len(slop), 4) if slop else 0.0,
    }


def run_oracle(db: Path, seed: int, files: int, fix_rate: float, declare_rate: float) -> OracleRun:
    """Write the training history to `db`, calibrate, score both weight sets held out."""
    rng = random.Random(seed)
    population = _population(rng, files)
    train = [m for i, m in enumerate(population) if i % 3]
    held_out = [m for i, m in enumerate(population) if not i % 3]
    tracker = HistoryTracker(db_path=db)
    labels: Dict[str, int] = {}
    for i, metrics in enumerate(train):
        action = _action(rng, metrics, fix_rate, declare_rate)
        labels[action] = labels.get(action, 0) + 1
        rel = f"f{i}.py"
        _row(tracker, rel, "2026-11-01T00:00:00", f"{i}-a", metrics)
        if action == "fixed":
            _row(tracker, rel, "2026-11-02T00:00:00", f"{i}-b", CLEAN_METRICS)
        elif action == "declared_false_positive":
            _row(tracker, rel, "2026-11-02T00:00:00", f"{i}-b", metrics)
        else:
            _row(tracker, rel, "2026-11-02T00:00:00", f"{i}-a", metrics)
    result = SelfCalibrator(db_path=db).calibrate(
        current_weights=dict(CURRENT_WEIGHTS), project_root=ROOT
    )
    winner = dict(result.optimal_weights) or dict(CURRENT_WEIGHTS)
    recommended = winner if result.status == "ok" else dict(CURRENT_WEIGHTS)
    return OracleRun(
        status=result.status,
        confidence_gap=result.confidence_gap,
        winner=winner,
        recommended=recommended,
        train_files=len(train),
        held_out_files=len(held_out),
        labels=labels,
        before=_rates(held_out, CURRENT_WEIGHTS),
        after_winner=_rates(held_out, winner),
        after_recommended=_rates(held_out, recommended),
    )
