"""RED for T-1: the shipped model cannot be loaded, and the failure is hidden.

Two separate defects are proven here:
  1. models/slop_classifier.pkl has a different schema than SlopClassifier.load()
  2. the loader swallows that failure and the scan still reports CLEAN / PASS

Run:  python patch/repro/red_t1_ml_schema.py
Exit: 1 while RED (defect present), 0 once GREEN.
"""

import pickle
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

MODEL = REPO / "models" / "slop_classifier.pkl"
LOADER_EXPECTS = ["model_type", "rf_model", "xgb_model"]

red = False

print("== T-1a: schema of the shipped model vs what load() reads ==")
if not MODEL.exists():
    print(f"  model not found: {MODEL}")
    sys.exit(1)

with open(MODEL, "rb") as fh:
    data = pickle.load(fh)

keys = sorted(data) if isinstance(data, dict) else []
print(f"  file keys      : {keys}")
print(f"  load() expects : {LOADER_EXPECTS}")
missing = [k for k in LOADER_EXPECTS if k not in keys]
if missing:
    red = True
    print(f"  RED: load() would KeyError on {missing[0]!r}; missing {missing}")
else:
    print("  GREEN: every key load() reads is present")

print()
print("== T-1b: does a failed ML load change the reported status? ==")
from slop_detector.ml.scorer import MLScorer  # noqa: E402

scorer = MLScorer.from_model(MODEL)
print(f"  MLScorer.from_model(...) -> {scorer!r}")
if scorer is None:
    print("  ML scoring is DISABLED for every scan on this checkout.")
    print("  RED unless the report marks the run as degraded -- check that a")
    print("  scan of any file prints a non-CLEAN status or an ml_scoring field.")
    red = True
else:
    print("  GREEN: scorer loaded")

sys.exit(1 if red else 0)
