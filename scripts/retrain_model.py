"""
LEDA Model Retraining Pipeline v1.1 — Flamehaven Sovereign Asset
================================================================

PURPOSE:
    Replaces initial synthetic baseline training data in models/ with real Dogfooding
    signals harvested from Extra Repo scan results.

    No external ML dependencies (sklearn not required).
    Uses a pure-Python weighted threshold classifier that matches the
    existing self_calibrator.py architecture.

    Overwrites:
        models/training_data.json       (was synthetic 300/300 baseline)
        models/pipeline_report.json     (was accuracy=1.0 baseline)
        models/slop_classifier.json     (JSON threshold model, schema: src/slop_detector/ml/threshold_model.py)

    Removes:
        models/training_data_real.json       (merged into training_data.json)
        models/pipeline_report_real.json     (superseded)
        models/slop_classifier_real.pkl      (superseded)

FEATURE VECTOR (16 dims):
    ldr_score, inflation_score, ddc_score,
    pattern_count_critical, pattern_count_high, pattern_count_medium, pattern_count_low,
    god_function_count, dead_code_count, deep_nesting_count,
    avg_complexity, cross_language_patterns, hallucination_count,
    total_lines, logic_lines, empty_lines

LABEL:
    deficit_score >= SLOP_FLOOR (25.0) -> "bad"
    deficit_score <  SLOP_FLOOR        -> "good"

USAGE:
    cd D:\\Sanctum\\ai-slop-detector
    python scripts\\retrain_model.py [--dry-run] [--extra-repos PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import random
from typing import Any, List, Tuple

# One contract for training and scoring: features, classifier and artifact schema.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from slop_detector.ml.threshold_model import (  # noqa: E402
    MODEL_TYPE,
    SCHEMA_VERSION,
    ThresholdClassifier,
    features_from_result,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SLOP_FLOOR = 25.0

ROOT            = Path(__file__).resolve().parent.parent
MODELS_DIR      = ROOT / "models"
DEFAULT_EXTRA   = Path(r"D:\Sanctum\Extra Repo")

OUT_DATA        = MODELS_DIR / "training_data.json"
OUT_REPORT      = MODELS_DIR / "pipeline_report.json"
OUT_MODEL       = MODELS_DIR / "slop_classifier.json"

BASELINES_TO_REMOVE = [
    MODELS_DIR / "training_data_real.json",
    MODELS_DIR / "pipeline_report_real.json",
    MODELS_DIR / "slop_classifier_real.pkl",
]


# ---------------------------------------------------------------------------
# Harvest
# ---------------------------------------------------------------------------

def harvest_from_scan(scan_path: Path) -> Tuple[List[dict], List[dict]]:
    """Extract good/bad feature vectors from a scan_final.json."""
    try:
        txt = scan_path.read_text(encoding="utf-8", errors="replace")
        lines = txt.splitlines()
        idx = next((i for i, l in enumerate(lines) if l.strip().startswith("{")), None)
        if idx is None:
            return [], []
        data = json.JSONDecoder().raw_decode("\n".join(lines[idx:]))[0]
    except Exception as exc:
        print(f"    [!] Failed to parse {scan_path.name}: {exc}")
        return [], []

    good_vecs, bad_vecs = [], []
    for fr in data.get("file_results", []):
        vec = features_from_result(fr)
        if vec is None:
            continue
        score = fr.get("deficit_score", 0)
        if score >= SLOP_FLOOR:
            bad_vecs.append(vec)
        else:
            good_vecs.append(vec)

    return good_vecs, bad_vecs


Row = Tuple[str, dict, int]  # (repository, feature vector, label: 1 = bad)


def harvest_all(extra_repos: Path) -> List[Row]:
    """Harvest scan_final.json / scan_1.json from Extra Repo subdirs, keeping each repository."""
    rows: List[Row] = []
    if not extra_repos.exists():
        print(f"[!] Extra repos path not found: {extra_repos}")
        return rows

    for repo in sorted(extra_repos.iterdir()):
        if not repo.is_dir():
            continue
        for scan_name in ["scan_final.json", "scan_1.json"]:
            sf = repo / "slop_reports" / scan_name
            if sf.exists():
                g, b = harvest_from_scan(sf)
                print(f"  {repo.name:<22} [{scan_name}]  good={len(g):>4}  bad={len(b):>4}")
                rows.extend((repo.name, v, 0) for v in g)
                rows.extend((repo.name, v, 1) for v in b)
                break

    return rows


def split_classes(rows: List[Row]) -> Tuple[List[dict], List[dict]]:
    """(good, bad) vectors, in harvest order."""
    return [v for _, v, y in rows if y == 0], [v for _, v, y in rows if y == 1]


# ---------------------------------------------------------------------------
# Evaluate: every fit here is scored only on rows it did not see
# ---------------------------------------------------------------------------

def _fit(rows: List[Row]) -> ThresholdClassifier:
    good, bad = split_classes(rows)
    return ThresholdClassifier().fit(good, bad)


def _predictions(clf: ThresholdClassifier, rows: List[Row]) -> List[Tuple[bool, int]]:
    return [(clf.predict(v) == "bad", y) for _, v, y in rows]


def _metrics(pairs: List[Tuple[bool, int]]) -> dict:
    tp = sum(1 for p, y in pairs if p and y)
    fp = sum(1 for p, y in pairs if p and not y)
    tn = sum(1 for p, y in pairs if not p and not y)
    fn = sum(1 for p, y in pairs if not p and y)
    n = len(pairs)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {
        "n": n,
        "accuracy": round((tp + tn) / n, 4) if n else 0.0,
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1_score": round(f1, 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def evaluate_random_holdout(rows: List[Row], seed: int = 42, test_fraction: float = 0.2) -> dict:
    """Shuffle, split, fit on the training part only, score the held-out part."""
    order = list(rows)
    random.Random(seed).shuffle(order)
    cut = int(len(order) * (1 - test_fraction))
    train_rows, test_rows = order[:cut], order[cut:]
    clf = _fit(train_rows)
    return {
        "seed": seed,
        "test_fraction": test_fraction,
        "metrics": _metrics(_predictions(clf, test_rows)),
        "test_rows": test_rows,
    }


def evaluate_leave_one_repository_out(rows: List[Row]) -> dict:
    """One fold per repository: fit on the others, score that repository."""
    folds = {}
    pooled: List[Tuple[bool, int]] = []
    for repo in sorted({r for r, _, _ in rows}):
        clf = _fit([row for row in rows if row[0] != repo])
        pairs = _predictions(clf, [row for row in rows if row[0] == repo])
        folds[repo] = _metrics(pairs)
        pooled.extend(pairs)
    return {"folds": folds, "pooled": _metrics(pooled)}


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def _repositories(rows: List[Row]) -> dict:
    out: dict = {}
    for repo, _, y in rows:
        counts = out.setdefault(repo, {"good": 0, "bad": 0})
        counts["bad" if y else "good"] += 1
    return out


def build_report(rows: List[Row], clf: ThresholdClassifier, holdout: dict, loro: dict) -> dict:
    good, bad = split_classes(rows)
    fi_sorted = sorted(clf.feature_importance.items(), key=lambda x: -x[1])
    return {
        "report_schema": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "scripts/retrain_model.py",
        "data_source": "dogfooding_real",
        "n_samples": len(rows),
        "class_balance": {"good": len(good), "bad": len(bad)},
        "training_repositories": _repositories(rows),
        "label_source": (
            f"the detector's own deficit_score on the same scans: >= {SLOP_FLOOR} is bad, "
            "below is good"
        ),
        "independent_ground_truth": False,
        "model_role": "secondary_rule_distillation_signal",
        "metrics_meaning": (
            "agreement with labels derived from the detector's own deficit_score; "
            "not slop-detection accuracy"
        ),
        "model_type": MODEL_TYPE,
        "schema_version": SCHEMA_VERSION,
        "model_path": "models/slop_classifier.json",
        "model_params": {"type": "pure_python", "no_sklearn": True},
        "final_model": "fit on all samples, after evaluation",
        "evaluation": {
            "protocols": ["random_holdout_split_before_fit", "leave_one_repository_out"],
            "random_holdout_split_before_fit": {
                k: holdout[k] for k in ("seed", "test_fraction", "metrics")
            },
            "leave_one_repository_out": loro,
            "baseline_always_bad_accuracy": round(len(bad) / len(rows), 4) if rows else 0.0,
        },
        "feature_importance": [[k, v] for k, v in fi_sorted],
        "key_thresholds": {
            feat: clf.thresholds[feat]
            for feat in ["ldr_score", "inflation_score", "ddc_score",
                         "god_function_count", "avg_complexity"]
        },
    }


def train(rows: List[Row]) -> Tuple[ThresholdClassifier, dict]:
    good, bad = split_classes(rows)
    print(f"  Training on {len(rows)} samples  (good={len(good)}, bad={len(bad)})")

    holdout = evaluate_random_holdout(rows)
    loro = evaluate_leave_one_repository_out(rows)
    m = holdout["metrics"]
    print(f"  random holdout (split before fit): accuracy={m['accuracy']:.4f}  f1={m['f1_score']:.4f}")
    m = loro["pooled"]
    print(f"  leave-one-repository-out pooled:   accuracy={m['accuracy']:.4f}  f1={m['f1_score']:.4f}")
    print("  (agreement with the detector's own deficit_score labels, not slop-detection accuracy)")

    clf = ThresholdClassifier().fit(good, bad)  # final model: all rows, after evaluation
    return clf, build_report(rows, clf, holdout, loro)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_artifacts(
    rows: List[Row],
    clf: ThresholdClassifier,
    report: dict,
    dry_run: bool,
) -> None:
    good, bad = split_classes(rows)
    training_data = {"good": good, "bad": bad}

    if dry_run:
        print("[DRY-RUN] Would write:")
        print(f"  {OUT_DATA}  ({len(rows)} samples)")
        print(f"  {OUT_REPORT}")
        print(f"  {OUT_MODEL}  (JSON threshold model)")
        for baseline in BASELINES_TO_REMOVE:
            if baseline.exists():
                print(f"  [DELETE] {baseline.name}")
        return

    OUT_DATA.write_text(
        json.dumps(training_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  [+] {OUT_DATA.name}  ({len(rows)} samples)")

    OUT_REPORT.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  [+] {OUT_REPORT.name}")

    OUT_MODEL.write_text(json.dumps(clf.to_dict(), indent=2) + "\n", encoding="utf-8")
    print(f"  [+] {OUT_MODEL.name}  (JSON threshold model, no pickle)")

    # Remove baseline files
    for baseline in BASELINES_TO_REMOVE:
        if baseline.exists():
            baseline.unlink()
            print(f"  [-] Removed baseline: {baseline.name}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="LEDA Model Retraining Pipeline v1.1 (no sklearn)"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--extra-repos", type=Path, default=DEFAULT_EXTRA)
    args = parser.parse_args()

    print("=" * 68)
    print("  LEDA MODEL RETRAINING PIPELINE  v1.1  (3.6.0 -> 3.7.1)")
    print("  Mode: Pure-Python ThresholdClassifier (no sklearn required)")
    print("=" * 68)

    # Harvest
    print(f"\n[STEP 1] Harvesting from: {args.extra_repos}\n")
    rows = harvest_all(args.extra_repos)
    good, bad = split_classes(rows)

    if not good and not bad:
        print("[!] No data harvested. Ensure leda_turbo.bat has been run on repos.")
        return 1

    print(f"\n  Total harvested: good={len(good)}  bad={len(bad)}")
    if len(bad) < 10:
        print("[!] WARNING: Fewer than 10 bad samples. Model will have low recall.")

    # Train
    print(f"\n[STEP 2] Training ThresholdClassifier (Gaussian NB, pure-Python)...\n")
    clf, report = train(rows)

    # Top features
    print("\n  Top-5 discriminative features:")
    fi = sorted(clf.feature_importance.items(), key=lambda x: -x[1])
    for feat, imp in fi[:5]:
        print(f"    {feat:<30} separation={imp:.4f}")

    # Key thresholds
    print("\n  Key thresholds (good/bad midpoint):")
    for feat in ["ldr_score", "inflation_score", "ddc_score", "god_function_count"]:
        print(f"    {feat:<30} threshold={clf.thresholds[feat]:.4f}")

    # Save
    print(f"\n[STEP 3] Saving artifacts {'[DRY-RUN]' if args.dry_run else '[LIVE]'}...\n")
    save_artifacts(rows, clf, report, args.dry_run)

    print()
    print("=" * 68)
    if args.dry_run:
        print("  [DRY-RUN] No files written. Remove --dry-run to apply.")
    else:
        print("  [+] Model retrained; review models/ and commit it with the script.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
