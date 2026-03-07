# History Tracking (v2.9.0)

AI-SLOP Detector records every analysis run to a local SQLite database.
Run it repeatedly on the same codebase and the accumulated data becomes
a continuous quality signal — showing which files improved, which degraded,
and which patterns keep recurring.

---

## Storage

```
~/.slop-detector/history.db   (SQLite, auto-created on first run)
```

Global across all projects. Each file is identified by its absolute path.
Schema migrates automatically when new fields are introduced.

### Schema

| Column | Type | Description |
|---|---|---|
| `timestamp` | TEXT | ISO-8601 datetime of the run |
| `file_path` | TEXT | Absolute path of the analyzed file |
| `file_hash` | TEXT | SHA256 prefix of file content (change detection) |
| `deficit_score` | REAL | Primary slop score (0–100, lower is better) |
| `ldr_score` | REAL | Logic Density Ratio (0–1, higher is better) |
| `inflation_score` | REAL | Jargon inflation score (0–10, lower is better) |
| `ddc_usage_ratio` | REAL | Dependency usage ratio (0–1, higher is better) |
| `pattern_count` | INTEGER | Number of pattern issues detected |
| `grade` | TEXT | Status label (clean / suspicious / inflated_signal / critical_deficit) |
| `git_commit` | TEXT | Current HEAD commit (when available) |
| `git_branch` | TEXT | Current branch (when available) |

---

## CLI Commands

### Per-file trend

```bash
slop-detector myfile.py --show-history
```

Output:
```
History: /project/src/myfile.py
  DB: /Users/you/.slop-detector/history.db
----------------------------------------------------------------------
  Timestamp                Deficit    LDR Patterns  Grade
----------------------------------------------------------------------
  2026-03-06T09:12:43         42.0  0.631        7  suspicious
  2026-03-07T11:03:21         18.0  0.812        3  clean
  2026-03-08T14:55:09          0.0  1.000        0  clean
----------------------------------------------------------------------
  Trend (3 runs): improved  delta=-42.0
```

### Project-wide daily trends

```bash
slop-detector --history-trends
```

Output:
```
Project Trends (last 7 days)
----------------------------------------------------------------------
  Date         Avg Deficit  Avg LDR  Patterns  Files
----------------------------------------------------------------------
  2026-03-08         12.3    0.871       14     22
  2026-03-07         19.7    0.812       31     18
  2026-03-06         34.1    0.701       58     15
```

### Opt-out (single run)

```bash
slop-detector myfile.py --no-history
```

### Export for ML training

```bash
slop-detector --export-history training_data.jsonl
```

The exported JSONL is directly compatible with `DatasetLoader.load_jsonl()`:

```python
from slop_detector.ml.pipeline import MLPipeline

pipeline = MLPipeline(output_dir="models")
report = pipeline.run_on_real_data(
    dataset="jsonl",
    jsonl_path="training_data.jsonl",
    max_samples=10_000,
)
print(report.summary())
```

---

## Why This Matters

The history log is the foundation for **independent ML training data**.

The current ML pipeline uses rule-based `deficit_score` to generate training
labels — creating a circular dependency where the ML model just learns the rules.
The history tracker breaks this cycle:

```
Daily runs accumulate history
    ↓
Files that score 42 → 18 → 0 across runs
    = user actually fixed them
    = those were real slop signals
    ↓
Longitudinal label: "this file improved" = confirmed slop
Files that stay at 8 across 50 runs
    = stable, possibly rule false-positive
    ↓
Independent signal for ML training
```

Future: `slop-detector feedback <file> --fp` to explicitly mark false positives,
creating a labeled dataset for personalized threshold calibration per project.

---

## Programmatic Access

```python
from slop_detector.history import HistoryTracker

tracker = HistoryTracker()  # uses ~/.slop-detector/history.db
# or: HistoryTracker(db_path="./local.db")

# File trend
history = tracker.get_file_history("src/myfile.py", limit=20)

# Regression check
reg = tracker.detect_regression("src/myfile.py", current_score=55.0)
if reg and reg["is_regression"]:
    print(f"REGRESSION: +{reg['delta']:.1f} vs recent avg {reg['recent_average']:.1f}")

# Project trends
trends = tracker.get_project_trends(days=7)

# Export
count = tracker.export_jsonl("history.jsonl")
print(f"Exported {count} records")
```
