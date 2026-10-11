# History Tracking

**Current contract:** v3.9.3. Historical version markers below
explain when fields were introduced; they are not a separate active protocol.

AI-SLOP Detector records every analysis run to a local SQLite database,
unless the run uses `--no-history` or `--read-only`.
Run it repeatedly on the same codebase and the accumulated data becomes
a continuous quality signal — showing which files improved, which degraded,
and which patterns keep recurring.

---

## Storage

```
~/.slop-detector/history.db   (SQLite, auto-created on first run)
```

Shared across all projects on the machine. Each file is identified by its
absolute path. Since v3.10 (schema v6) every row also records what measured it
and which project it belongs to: the detector version, a measurement
fingerprint (detector + analysis engine + the whole effective configuration),
the weights, the canonical project root (the scanned directory for a project
scan; the nearest project marker, else the parent, for a single file) and the
file's path under it. Calibration compares only rows with the same project
root and fingerprint. The v3.5.0 `project_id` (SHA-256[:12] of the working
directory) is still written for old readers but is not evidence: it grouped
projects scanned from one directory together.

The schema migrates in place when columns are added; existing rows are never
rewritten (pre-v6 rows keep `provenance_state = NULL` and count as legacy).

### Schema (v6 — v3.10)

| Column | Type | Added | Description |
|---|---|---|---|
| `timestamp` | TEXT | v2.9.0 | ISO-8601 datetime of the run |
| `file_path` | TEXT | v2.9.0 | Absolute path of the analyzed file |
| `file_hash` | TEXT | v2.9.0 | SHA256 prefix of file content (change detection) |
| `deficit_score` | REAL | v2.9.0 | Primary slop score (0–100, lower is better) |
| `ldr_score` | REAL | v2.9.0 | Logic Density Ratio (0–1, higher is better) |
| `inflation_score` | REAL | v2.9.0 | Jargon inflation score (0–10, lower is better) |
| `ddc_usage_ratio` | REAL | v2.9.0 | Dependency usage ratio (0–1, higher is better) |
| `pattern_count` | INTEGER | v2.9.0 | Number of pattern issues detected |
| `grade` | TEXT | v2.9.0 | Status label (clean / suspicious / inflated_signal / critical_deficit) |
| `git_commit` | TEXT | v3.2.1 | Current HEAD commit SHA (when available; NULL for non-git projects) |
| `git_branch` | TEXT | v3.2.1 | Current branch name (when available) |
| `n_critical_patterns` | INTEGER | v3.2.0 | Count of CRITICAL-severity pattern issues in this run |
| `fired_rules` | TEXT | v3.4.0 | JSON object `{"pattern_id": count, ...}` — validated on write since v3.7.2 |
| `project_id` | TEXT | v3.5.0 | SHA-256[:12] of resolved scan cwd (legacy; not used by calibration) |
| `detector_version` | TEXT | **v3.10** | Release that measured the row |
| `measurement_fingerprint` | TEXT | **v3.10** | SHA-256 of detector version + engine version + effective configuration |
| `weights_vector` | TEXT | **v3.10** | Weights the scan used (JSON) |
| `project_root` | TEXT | **v3.10** | Canonical project root of the scan |
| `file_rel_path` | TEXT | **v3.10** | File path under `project_root` |
| `base_deficit` | REAL | **v3.10** | Score before the pattern penalty |
| `pattern_penalty` | REAL | **v3.10** | Additive pattern penalty |
| `provenance_state` | TEXT | **v3.10** | `v6` on rows written with provenance; NULL on legacy rows |

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

`--read-only` also records nothing (it writes no history, cache, impact, or
telemetry state, and refuses options that would).

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

## Input Integrity Guards (v3.7.2)

`HistoryEntry.__post_init__` fires before every `_insert()` call:

| Field | Guard | Rationale |
|---|---|---|
| `deficit_score` | `max(0.0, x)` | GQG construction guarantees non-negative |
| `ldr_score` | `max(0.0, min(1.0, x))` | ratio — impossible outside [0, 1] |
| `inflation_score` | `max(0.0, x)` | non-negative by definition |
| `ddc_usage_ratio` | `max(0.0, min(1.0, x))` | ratio — impossible outside [0, 1] |
| `n_critical_patterns` | `max(0, x)` | count cannot be negative |
| `pattern_count` | `max(0, x)` | count cannot be negative |

`fired_rules` is validated as parseable JSON at write time. Prior to v3.7.2 a
malformed string returned `None` on the next calibration read, silently dropping
all FP candidate events for that file — biasing the per-rule FP rate tracker.
Now it raises `ValueError: HistoryEntry.fired_rules must be valid JSON: ...`
immediately at insertion so corruption is caught before it enters the DB.

See [docs/SCHEMA_VALIDATION.md](SCHEMA_VALIDATION.md) for the full Layer 3 spec.

---

## Why This Matters

The history log is a foundation for **repository-local operational
calibration** (see [SELF_CALIBRATION.md](SELF_CALIBRATION.md)). It is not
independent ML training data and it is not external validation.

The current ML pipeline uses rule-based `deficit_score` to generate training
labels — creating a circular dependency where the ML model just learns the rules.
The history tracker breaks this cycle:

```
Daily runs accumulate history (per project root and measurement)
    ↓
Files that score 42 → 18 → 0 across runs
    = a flagged file was changed and its local score moved
    = operational evidence for local review tuning, not confirmed ground truth
    ↓
Longitudinal label: "this file improved" = confirmed slop
Files that stay at 8 across 50 runs
    = stable, possibly a locally noisy alert
    ↓
Repository-local signal for calibration only
```

`--self-calibrate` reads this history to report weights that would reduce missed
improvement signals and unnecessary alerts. The report is advisory: nothing writes
the weights, and scans never run it. It uses only v6 rows of one project root,
compares only runs with the same measurement fingerprint, and counts an
improvement only when the file itself changed. Even so it describes local review
behaviour; it does not establish false-positive rates.

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

# Files scanned more than once under a legacy project_id (informational;
# scans no longer trigger calibration, see SELF_CALIBRATION.md)
project_id = "abc123def456"  # sha256[:12] of cwd
repeat_files = tracker.count_files_with_multiple_runs(project_id=project_id)
print(f"Files with multiple runs: {repeat_files}")

# Export
count = tracker.export_jsonl("history.jsonl")
print(f"Exported {count} records")
```
