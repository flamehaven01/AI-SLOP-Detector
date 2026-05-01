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
        models/slop_classifier.pkl      (JSON-serialized threshold model)

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
import math
import pickle
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SLOP_FLOOR = 25.0
FEATURES = [
    "ldr_score", "inflation_score", "ddc_score",
    "pattern_count_critical", "pattern_count_high",
    "pattern_count_medium", "pattern_count_low",
    "god_function_count", "dead_code_count", "deep_nesting_count",
    "avg_complexity", "cross_language_patterns", "hallucination_count",
    "total_lines", "logic_lines", "empty_lines",
]

ROOT            = Path(__file__).resolve().parent.parent
MODELS_DIR      = ROOT / "models"
DEFAULT_EXTRA   = Path(r"D:\Sanctum\Extra Repo")

OUT_DATA        = MODELS_DIR / "training_data.json"
OUT_REPORT      = MODELS_DIR / "pipeline_report.json"
OUT_PKL         = MODELS_DIR / "slop_classifier.pkl"

BASELINES_TO_REMOVE = [
    MODELS_DIR / "training_data_real.json",
    MODELS_DIR / "pipeline_report_real.json",
    MODELS_DIR / "slop_classifier_real.pkl",
]


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _extract_feature_vector(fr: dict) -> dict | None:
    """Map a file_result dict to a 16-dim feature vector.

    Handles actual nested scan JSON structure:
      fr["ldr"]["ldr_score"], fr["ldr"]["total_lines"], ...
      fr["inflation"]["inflation_score"], fr["inflation"]["avg_complexity"]
      fr["ddc"]["usage_ratio"]
      fr["pattern_issues"] list of {severity, pattern_id, ...}
    """
    # --- ldr block ---
    ldr_block = fr.get("ldr") or {}
    if isinstance(ldr_block, dict):
        ldr_score   = float(ldr_block.get("ldr_score", 0.0))
        total_lines = float(ldr_block.get("total_lines", 0))
        logic_lines = float(ldr_block.get("logic_lines", 0))
        empty_lines = float(ldr_block.get("empty_lines", 0))
    else:
        ldr_score   = float(ldr_block) if ldr_block else 0.0
        total_lines = logic_lines = empty_lines = 0.0

    # --- inflation block ---
    inf_block = fr.get("inflation") or {}
    if isinstance(inf_block, dict):
        inf_score = float(inf_block.get("inflation_score", 0.0))
        avg_cc    = float(inf_block.get("avg_complexity", 0.0))
    else:
        inf_score = float(inf_block) if inf_block else 0.0
        avg_cc    = 0.0

    # --- ddc block ---
    ddc_block = fr.get("ddc") or {}
    if isinstance(ddc_block, dict):
        ddc_score = float(ddc_block.get("usage_ratio", ddc_block.get("ddc_score", 0.0)))
    else:
        ddc_score = float(ddc_block) if ddc_block else 0.0

    # --- pattern_issues ---
    patterns = fr.get("pattern_issues") or []
    sev_counts: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    god_fn = dead = nesting = halluc = cross = 0
    for p in patterns:
        sev = (p.get("severity") or "low").lower()
        sev_counts[sev] = sev_counts.get(sev, 0) + 1
        pid = (p.get("pattern_id") or "").lower()
        if "god_function" in pid:
            god_fn += 1
        elif "dead_code" in pid:
            dead += 1
        elif "deep_nesting" in pid or "nested_complexity" in pid:
            nesting += 1
        elif "hallucin" in pid:
            halluc += 1
        elif "cross" in pid or "language" in pid:
            cross += 1

    # Skip empty files (binary, etc.)
    if ldr_score == 0 and inf_score == 0 and ddc_score == 0 and total_lines == 0:
        return None

    return {
        "ldr_score":               ldr_score,
        "inflation_score":         inf_score,
        "ddc_score":               ddc_score,
        "pattern_count_critical":  float(sev_counts.get("critical", 0)),
        "pattern_count_high":      float(sev_counts.get("high", 0)),
        "pattern_count_medium":    float(sev_counts.get("medium", 0)),
        "pattern_count_low":       float(sev_counts.get("low", 0)),
        "god_function_count":      float(god_fn),
        "dead_code_count":         float(dead),
        "deep_nesting_count":      float(nesting),
        "avg_complexity":          float(avg_cc),
        "cross_language_patterns": float(cross),
        "hallucination_count":     float(halluc),
        "total_lines":             total_lines,
        "logic_lines":             logic_lines,
        "empty_lines":             empty_lines,
    }


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
        vec = _extract_feature_vector(fr)
        if vec is None:
            continue
        score = fr.get("deficit_score", 0)
        if score >= SLOP_FLOOR:
            bad_vecs.append(vec)
        else:
            good_vecs.append(vec)

    return good_vecs, bad_vecs


def harvest_all(extra_repos: Path) -> Tuple[List[dict], List[dict]]:
    """Harvest all scan_final.json / scan_1.json from Extra Repo subdirs."""
    all_good, all_bad = [], []
    if not extra_repos.exists():
        print(f"[!] Extra repos path not found: {extra_repos}")
        return [], []

    for repo in sorted(extra_repos.iterdir()):
        if not repo.is_dir():
            continue
        for scan_name in ["scan_final.json", "scan_1.json"]:
            sf = repo / "slop_reports" / scan_name
            if sf.exists():
                g, b = harvest_from_scan(sf)
                print(f"  {repo.name:<22} [{scan_name}]  good={len(g):>4}  bad={len(b):>4}")
                all_good.extend(g)
                all_bad.extend(b)
                break

    return all_good, all_bad


# ---------------------------------------------------------------------------
# Pure-Python Threshold Classifier (no sklearn dependency)
# ---------------------------------------------------------------------------

def _mean(vals: List[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0

def _stdev(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


class ThresholdClassifier:
    """
    Lightweight threshold classifier — no external dependencies.

    Strategy: For each feature, compute per-class mean/stdev from training data.
    At inference time, score a sample via a Naive Bayes-style log-likelihood
    (Gaussian assumption) and pick the class with higher score.

    Additionally derives optimal scalar thresholds per key feature for
    interpretability and config injection compatibility.
    """

    def __init__(self) -> None:
        self.class_stats: Dict[str, Dict[str, Dict[str, float]]] = {}
        self.class_priors: Dict[str, float] = {}
        self.thresholds: Dict[str, float] = {}
        self.feature_importance: Dict[str, float] = {}

    def fit(self, good: List[dict], bad: List[dict]) -> "ThresholdClassifier":
        n_good = len(good)
        n_bad  = len(bad)
        n_total = n_good + n_bad

        # Priors (balanced)
        self.class_priors = {"good": 0.5, "bad": 0.5}

        # Per-class per-feature stats
        for label, vecs in [("good", good), ("bad", bad)]:
            self.class_stats[label] = {}
            for feat in FEATURES:
                vals = [v[feat] for v in vecs]
                self.class_stats[label][feat] = {
                    "mean":  _mean(vals),
                    "stdev": max(_stdev(vals), 1e-6),  # avoid zero division
                }

        # Feature importance: |mean_bad - mean_good| / (stdev_good + stdev_bad)
        for feat in FEATURES:
            g_mean = self.class_stats["good"][feat]["mean"]
            b_mean = self.class_stats["bad"][feat]["mean"]
            g_std  = self.class_stats["good"][feat]["stdev"]
            b_std  = self.class_stats["bad"][feat]["stdev"]
            sep = abs(b_mean - g_mean) / (g_std + b_std + 1e-9)
            self.feature_importance[feat] = round(sep, 6)

        # Per-feature optimal thresholds (midpoint between class means)
        for feat in FEATURES:
            g_m = self.class_stats["good"][feat]["mean"]
            b_m = self.class_stats["bad"][feat]["mean"]
            self.thresholds[feat] = round((g_m + b_m) / 2, 4)

        return self

    def _log_likelihood(self, x: float, mean: float, stdev: float) -> float:
        """Gaussian log-likelihood."""
        return -0.5 * math.log(2 * math.pi * stdev ** 2) - (x - mean) ** 2 / (2 * stdev ** 2)

    def predict_proba(self, vec: dict) -> Dict[str, float]:
        """Return {good: p, bad: p} probabilities."""
        scores = {}
        for label in ("good", "bad"):
            log_p = math.log(self.class_priors[label])
            for feat in FEATURES:
                x = vec.get(feat, 0.0)
                m = self.class_stats[label][feat]["mean"]
                s = self.class_stats[label][feat]["stdev"]
                log_p += self._log_likelihood(x, m, s)
            scores[label] = log_p

        # Softmax
        max_s = max(scores.values())
        exp_s = {k: math.exp(v - max_s) for k, v in scores.items()}
        total = sum(exp_s.values())
        return {k: v / total for k, v in exp_s.items()}

    def predict(self, vec: dict) -> str:
        proba = self.predict_proba(vec)
        return max(proba, key=proba.__getitem__)

    def to_dict(self) -> dict:
        return {
            "type":              "threshold_classifier",
            "version":           "1.0",
            "class_priors":      self.class_priors,
            "class_stats":       self.class_stats,
            "thresholds":        self.thresholds,
            "feature_importance": self.feature_importance,
            "features":          FEATURES,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ThresholdClassifier":
        obj = cls()
        obj.class_priors      = d["class_priors"]
        obj.class_stats       = d["class_stats"]
        obj.thresholds        = d["thresholds"]
        obj.feature_importance = d.get("feature_importance", {})
        return obj


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

def evaluate(clf: ThresholdClassifier, good: List[dict], bad: List[dict]) -> dict:
    """Compute accuracy, precision, recall, f1 on a held-out 20% split."""
    import random
    random.seed(42)

    all_vecs = [(v, 0) for v in good] + [(v, 1) for v in bad]
    random.shuffle(all_vecs)

    split = int(len(all_vecs) * 0.8)
    test  = all_vecs[split:]

    tp = fp = tn = fn = 0
    for vec, true_label in test:
        pred = 1 if clf.predict(vec) == "bad" else 0
        if pred == 1 and true_label == 1:
            tp += 1
        elif pred == 1 and true_label == 0:
            fp += 1
        elif pred == 0 and true_label == 0:
            tn += 1
        else:
            fn += 1

    acc  = (tp + tn) / len(test) if test else 0.0
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec  = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0.0

    print(f"  accuracy={acc:.4f}  precision={prec:.4f}  recall={rec:.4f}  f1={f1:.4f}")
    print(f"  tp={tp}  fp={fp}  tn={tn}  fn={fn}  test_n={len(test)}")
    return {"accuracy": round(acc, 4), "precision": round(prec, 4),
            "recall": round(rec, 4), "f1_score": round(f1, 4)}


# ---------------------------------------------------------------------------
# Train
# ---------------------------------------------------------------------------

def train(good: List[dict], bad: List[dict]) -> Tuple[ThresholdClassifier, dict]:
    n_good = len(good)
    n_bad  = len(bad)
    print(f"\n  Training on {n_good + n_bad} samples  (good={n_good}, bad={n_bad})")
    print(f"  Class balance: {n_bad / (n_good + n_bad):.1%} bad")

    clf = ThresholdClassifier().fit(good, bad)
    metrics = evaluate(clf, good, bad)

    # Feature importance sorted
    fi_sorted = sorted(clf.feature_importance.items(), key=lambda x: -x[1])

    report = {
        "version":      "3.7.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source":  "dogfooding_real",
        "n_samples":    n_good + n_bad,
        "class_balance": {"good": n_good, "bad": n_bad},
        "model_type":   "threshold_classifier_gaussian_nb",
        "model_params": {"type": "pure_python", "no_sklearn": True},
        "metrics":      {"threshold_classifier": metrics},
        "model_path":   "models\\slop_classifier.pkl",
        "feature_importance": [[k, v] for k, v in fi_sorted],
        "key_thresholds": {
            feat: clf.thresholds[feat]
            for feat in ["ldr_score", "inflation_score", "ddc_score",
                         "god_function_count", "avg_complexity"]
        },
    }

    return clf, report


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def save_artifacts(
    good: List[dict],
    bad: List[dict],
    clf: ThresholdClassifier,
    report: dict,
    dry_run: bool,
) -> None:
    training_data = {"good": good, "bad": bad}

    if dry_run:
        print("\n[DRY-RUN] Would write:")
        print(f"  {OUT_DATA}  ({len(good)+len(bad)} samples)")
        print(f"  {OUT_REPORT}")
        print(f"  {OUT_PKL}  (JSON-serialized ThresholdClassifier)")
        for baseline in BASELINES_TO_REMOVE:
            if baseline.exists():
                print(f"  [DELETE] {baseline.name}")
        return

    OUT_DATA.write_text(
        json.dumps(training_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  [+] {OUT_DATA.name}  ({len(good)+len(bad)} samples)")

    OUT_REPORT.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  [+] {OUT_REPORT.name}")

    # Serialize as JSON-in-pickle for portability (no sklearn required to load)
    with open(OUT_PKL, "wb") as f:
        pickle.dump(clf.to_dict(), f)
    print(f"  [+] {OUT_PKL.name}  (ThresholdClassifier — no sklearn needed)")

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
    print("  LEDA MODEL RETRAINING PIPELINE  v1.1  (3.6.0 -> 3.7.0)")
    print("  Mode: Pure-Python ThresholdClassifier (no sklearn required)")
    print("=" * 68)

    # Harvest
    print(f"\n[STEP 1] Harvesting from: {args.extra_repos}\n")
    good, bad = harvest_all(args.extra_repos)

    if not good and not bad:
        print("[!] No data harvested. Ensure leda_turbo.bat has been run on repos.")
        return 1

    print(f"\n  Total harvested: good={len(good)}  bad={len(bad)}")
    if len(bad) < 10:
        print("[!] WARNING: Fewer than 10 bad samples. Model will have low recall.")

    # Train
    print(f"\n[STEP 2] Training ThresholdClassifier (Gaussian NB, pure-Python)...\n")
    clf, report = train(good, bad)

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
    save_artifacts(good, bad, clf, report, args.dry_run)

    print()
    print("=" * 68)
    if args.dry_run:
        print("  [DRY-RUN] No files written. Remove --dry-run to apply.")
    else:
        print("  [+] Model retrained on real Dogfooding data (v3.7.0).")
        print("  Next steps:")
        print("    git add models/ scripts/retrain_model.py")
        print("    git commit -m 'feat(ml): retrain on real dogfooding data (v3.7.0)'")
        print("    git tag v3.7.0")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
