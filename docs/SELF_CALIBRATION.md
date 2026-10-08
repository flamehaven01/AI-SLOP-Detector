# Self-Calibration Engine

> **Status (v3.9.2): advisory only.** `--self-calibrate` reports what the local
> history suggests; nothing writes weights. Scans no longer run calibration, and
> `--apply-calibration` is disabled (it writes nothing and exits 2).
>
> Why: the legacy history does not record the detector version, the
> configuration, or the project root, so a score change is not proof that the
> code changed. Measured on 29,303 real history rows (26 working directories,
> 8,556 files): 241 of the 301 "improvement" pairs (80%) had an unchanged file;
> 61% of flagged rows (stored deficit > 25) were flagged by pattern penalties
> that the weights cannot move; and rows are grouped by working directory, so
> projects scanned from one directory share them. A provenance-stable
> Calibration v2 (separate measurement and weight provenance, events compared
> under one reference weight vector, legacy rows excluded) is planned for v3.10.
> The rest of this document describes the legacy algorithm the report uses.

---

## The Problem with Universal Weights

The default scoring formula is a **weighted geometric mean (GQG)**:

```
GQG = exp(
    (w_ldr    × log(max(1e-4, ldr))
   + w_inf    × log(max(1e-4, 1 − inflation_norm))
   + w_ddc    × log(max(1e-4, ddc))
   + w_purity × log(max(1e-4, purity_score)))
   / (w_ldr + w_inf + w_ddc + w_purity)
)
deficit_score = 100 × (1 − GQG) + pattern_penalty
```

With default weights (`DEFAULT_CONFIG`, v3.7.0+):

```yaml
weights:
  ldr: 0.40
  inflation: 0.30
  ddc: 0.20
  purity: 0.10
```

These numbers were tuned against Flamehaven's internal codebase and hardcoded.
They work well for what we build. For a framework like Django or Spring — where
boilerplate is structurally required, not developer-chosen — the `ldr` weight
of 0.40 can generate noisy findings on legitimate code.

The mitigation exists: `.slopconfig.yaml` lets you adjust weights per project.
But the burden was on the user to know they need to, and to know what to set.

**Self-calibration can reduce that burden.** It reads repository-local usage
history and searches for weights that reduce both missed improvement signals and
persistently noisy alerts for one codebase.

---

## Validation Boundary

Self-calibration is **operational calibration**, not independent external
validation.

What it does:

- reports the 4D weights that local run history would favour (advisory)
- keeps the search domain-anchored
- returns a reproducible recommendation from explicit rules and thresholds

What it does not do (v3.9.2): write weights, run during scans, or separate
history by project root (records are grouped by working directory).

What it does **not** do:

- prove that `deficit_score` measures one validated latent condition
- act as an external governance control by itself
- replace blinded review, out-of-sample benchmarking, or independent validation

Use the report as a lead for review. Do not treat it as proof that the score is
universally validated, or as a setting to apply.

---

## How It Works

### 1. Data Source: History Database

Every `slop-detector` run is automatically recorded to
`~/.slop-detector/history.db` (SQLite). Each record stores:

```
file_path | file_hash | timestamp | deficit_score | ldr_score | inflation_score | ddc_usage_ratio | n_critical_patterns | pattern_count | grade
```

This accumulates silently as you use the tool. No configuration required.

This history stays on the local machine unless a user separately exports it.
It can contain repository-relative file paths and git context, so treat the
database as local operational metadata on shared machines. It is not uploaded
or used as evidence of external validity.

### 2. Label Derivation from User Behaviour

The calibration engine extracts two event types from consecutive run pairs
for each unique file:

**`improvement_event`** — deficit was high, next run it dropped significantly.
The user edited the file after a prior flagged run. This is an operational
signal that the earlier warning was followed by a meaningful change.

```
run[i]:   deficit=47, file_hash=abc123
run[i+1]: deficit=12, file_hash=def456   <- different hash = user edited it
```
→ Label: `improvement` (calibration signal for a previously flagged file that was changed)

**`fp_candidate`** — deficit was high, but the next run shows the same file
hash and no meaningful score change. The file stayed stable after the prior
flagged run.

```
run[i]:   deficit=38, file_hash=abc123
run[i+1]: deficit=36, file_hash=abc123   <- same hash = file untouched
```
→ Label: `fp_candidate` (candidate noisy alert for this codebase's style)

**Why this reduces circularity:**

The ML classifier had a circular labeling problem: labels were derived from
`deficit_score >= 30`, and features were the components of `deficit_score`.
The model learned to approximate the formula, not to add an independent signal.

Self-calibration labels come from **observed repository behaviour** — was the
flagged file changed, or did it remain stable? That breaks the direct
label-from-score loop, but it still remains an internal operational signal, not
external validation.

### 3. Grid Search over the Weight Simplex

With labeled events, the engine searches all weight combinations where:
- `w_ldr + w_inflation + w_ddc + w_purity = 1.0`
- Each weight: `0.10 ≤ w ≤ 0.65`
- Resolution: 0.05 increments
- **Purity dimension:** `purity_score = exp(-0.5 * n_critical_patterns)` — 1.0 when no critical patterns, decays toward 0 as critical patterns accumulate

**v3.5.0 — Domain-anchored search (P3):** When `domain_anchor` is provided
(the removed scan-time path passed the current config weights; the advisory
`--self-calibrate` report passes none and searches `[MIN_W, MAX_W]`), each
dimension's search range is constrained to `[anchor ± DOMAIN_TOLERANCE(0.15)]`
clipped to absolute `[MIN_W=0.10, MAX_W=0.65]`. This prevents calibration from
drifting outside the domain's meaningful weight region (e.g. a `scientific/ml`
project keeps `inflation` weight low). Manual `--self-calibrate` explores the
full unconstrained grid.

For each candidate weight set, two rates are computed:

| Rate | Definition |
|---|---|
| **FN rate** | Fraction of `improvement_event` files that the new weights would score below the slop floor — missed improvement signals |
| **FP rate** | Fraction of `fp_candidate` files that the new weights still score above the slop floor — persistently noisy alerts |

Optimization target: minimize `FN_rate + FP_rate`.

No new dependencies. Pure Python + sqlite3.

### 4. Tiebreaker: Continuous Secondary Score

When multiple weight sets produce the same binary FN+FP rate (common at 0.05
resolution), a continuous secondary metric breaks ties:

```
tiebreak = avg_deficit(fp_candidates) − avg_margin_above_floor(improvement_events)
```

- Lower `avg_deficit` on FP candidates → fewer over-detections
- Higher margin on improvement events → clearer signal on files that were changed after a prior flag

Sort key: `(combined_score, tiebreak_score)` — lower is better.

### 5. Confidence Gap (Copilot Guardian Pattern)

Borrowed from multi-hypothesis reasoning: if the gap between the top candidate
and the runner-up is too small, the data does not cleanly support one winner.

```
confidence_gap = score(rank_2) − score(rank_1)
```

When primary scores are tied, the gap is computed from tiebreak scores
(normalized). If `confidence_gap < 0.10`, the engine returns
`status = insufficient_data` rather than applying a weakly-supported result.

---

## Git Integration (v3.2.1)

Every scan now captures the current `git commit (short SHA)` and `branch` and
stores them alongside each file result. The calibration engine uses this as a
**noise filter**:

| Signal | Git condition | Action |
|--------|--------------|--------|
| Apparent improvement | same commit before + after score drop | Skip — measurement noise within one commit |
| Apparent FP candidate | different commit + stable file hash | Skip — user may have committed unrelated changes |

When `git_commit` is `NULL` (non-git projects), the original hash-based heuristic
applies unchanged. Backward compatible.

**Result:** Fewer labeled events, but higher-fidelity operational signal. This is critical for
the 5+5 per-class threshold (see below) to remain statistically sound.

---

## Project Scoping (v3.5.0 — P1)

The global `~/.slop-detector/history.db` is shared across all projects. Before
v3.5.0, a `scientific/ml` project and a `web/api` project on the same machine
would pollute each other's calibration signal.

Since v3.5.0, every `record()` call tags the row with
`project_id = sha256(cwd)[:12]`. Calibration only loads rows matching the
current project's `project_id`. Old rows (`project_id = NULL`) are excluded
from per-project calibration — clean separation with no contamination.

```python
# Internally: _compute_project_id()
import hashlib
from pathlib import Path
project_id = hashlib.sha256(Path.cwd().resolve().__str__().encode()).hexdigest()[:12]
```

---

## Domain-Drift Warning (v3.5.0 — P4)

After a successful calibration, `calibrate()` compares each optimal weight
against the reference anchor (or current config weights as fallback). Any
dimension that drifts more than `DOMAIN_DRIFT_LIMIT = 0.25` emits a warning:

```
[!] ldr: optimal 0.10 drifted 0.30 from domain anchor (0.40); exceeds DOMAIN_DRIFT_LIMIT=0.25.
```

Warnings appear in `--self-calibrate` output (yellow `[!]` in rich terminals,
plain `[!]` otherwise) and are available programmatically via
`CalibrationResult.warnings: List[str]`.

---

## Bootstrap

Before scanning for the first time, run:

```bash
slop-detector --init           # generate .slopconfig.yaml + secure .gitignore
slop-detector --init --force-init   # overwrite existing config
```

This generates a fully documented `.slopconfig.yaml` tailored to your project type
(python/javascript/go) and automatically adds `.slopconfig.yaml` to `.gitignore`.

---

## Usage

### Check calibration status

```bash
slop-detector . --self-calibrate
```

Output:
```
┌─────────────────────────────────────────────────────────────┐
│ Self-Calibration — OK                                       │
└─────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────┬────────┐
│ Metric                               │  Value │
├──────────────────────────────────────┼────────┤
│ Unique files in history              │    180 │
│ Improvement events (flag followed by change) │     62 │
│ FP candidates (flag followed by stable file) │    176 │
│ Confidence gap                       │ 0.1088 │
└──────────────────────────────────────┴────────┘
┌───────────┬─────────┬─────────┬───────┐
│ Dimension │ Current │ Optimal │ Delta │
├───────────┼─────────┼─────────┼───────┤
│ ldr       │    0.40 │    0.10 │ -0.30 │
│ inflation │    0.30 │    0.25 │ -0.05 │
│ ddc       │    0.30 │    0.65 │ +0.35 │
└───────────┴─────────┴─────────┴───────┘

Combined error: 1.1069 -> 0.9985  (FN 0.9194->0.7258,  FP 0.1875->0.2727)
```

### Applying weights (disabled)

`--apply-calibration` writes nothing: it prints why to stderr and exits 2. To
change weights, edit the `weights:` block of `.slopconfig.yaml` yourself.

### Adjust the minimum event threshold

```bash
# Require at least 8 events per class before calibration runs
slop-detector . --self-calibrate --min-history 8
```

Default: 5 events **per class** (improvements + FP candidates each independently).
Total minimum is 10 records (5+5). The 4D model's continuous tiebreak signal
makes 5+5 statistically reliable; 3D required 10+10 (binary-only scoring).
Increase `--min-history` for stricter confidence requirements.

### Scans no longer calibrate (v3.9.2)

Until v3.9.1, each scan with history checked a local milestone and could
rewrite the weights of an existing `.slopconfig.yaml`. The v3.5.0 table here
described the trigger as `count_files_with_multiple_runs(project_id) >= 10`,
but the code also required an exact multiple of 10, so a project whose count
jumped past 10 (12 files scanned twice) never calibrated, and `project_id` came
from the working directory. With the evidence problems above, v3.9.2 removes
the scan-time path entirely: scans record history and nothing else.

---

## Status Codes

| Status | Meaning |
|---|---|
| `ok` | The legacy algorithm produced a confident recommendation. Advisory only: nothing writes it. |
| `no_change` | Current weights are already near-optimal (improvement margin < 2%). |
| `insufficient_data` | Too few events, or confidence gap below threshold. |

---

## How Much History Is Needed?

| Events | Reliability |
|---|---|
| < 5 per class | Too sparse — calibration skipped (per-class floor: 5 improvements + 5 FP candidates) |
| 10–50 | First confident signal (4D tiebreak resolves ties early) |
| 50–200 | Reliable for most codebases |
| 200+ | High confidence; recalibrate periodically as codebase evolves |

History accumulates automatically on every run. You do not need to do anything
special to collect it — just use the tool.

To check how much history you have:

```bash
slop-detector . --history-trends
slop-detector --export-history data.jsonl  # full export with counts
```

---

## Interpreting Results

### High FN rate

```
FN rate: 0.9194 -> 0.7258
```

A high false-negative rate against metric-only recomputed deficits means
**pattern penalties are the primary driver of deficit scores in this codebase**.

The scoring formula is:
```
deficit_score = base_metric_deficit + pattern_penalty
```

Self-calibration optimizes `base_metric_deficit` (the weighted combination of
ldr/inflation/ddc). If most files are flagged because of `phantom_import`,
`god_function`, or `lint_escape` patterns — not because of metric scores — the
metric weights have limited effect on the outcome. The calibrated weights are
still valid for the metric component; they just operate on a smaller fraction
of the total score.

### Dramatic weight shifts

```
ldr:  0.40 → 0.10   (-0.30)
ddc:  0.20 → 0.65   (+0.45)
```

This means the codebase has many files with low LDR that remained unchanged
(FP candidates). The tool was over-penalizing low logic density in this
context — possibly because the codebase uses a framework with structural
boilerplate, or because the coding style is comment-heavy and documentation-rich.

Reducing `ldr` weight and increasing `ddc` weight tells the engine:
dependency usage ratio is a stronger quality signal here than logic density.

---

## What Self-Calibration Does NOT Do

- It does not retrain the ML classifier. Weight calibration and ML training are
  separate concerns. The ML layer remains EXPERIMENTAL and operates independently.
- It does not adjust pattern detection thresholds. Patterns fire based on AST
  analysis, not on metric weights.
- It does not override `patterns.disabled` in your config. Pattern suppression
  remains under manual control via `.slopconfig.yaml`.
- It does not prove that the score is an externally validated governance
  control. Calibration only tunes repository-local review sensitivity.
- It does not guarantee universal validity. Calibrated weights are optimized
  for *your* history. If your team's style changes significantly, recalibrate.

---

## Architecture

```
src/slop_detector/ml/self_calibrator.py
    SelfCalibrator
    ├── calibrate(current_weights, project_id, min_events, domain_anchor) -> CalibrationResult
    │   ├── _extract_events(project_id) -> (List[CalibrationEvent], unique_file_count)
    │   │   ├── improvement_event: high deficit + score dropped + hash changed
    │   │   ├── fp_candidate:      high deficit + same hash + score stable
    │   │   ├── _group_runs_by_file(rows) -> Dict[str, list]
    │   │   ├── _classify_consecutive_runs(file_path, runs, seen_fp_files) -> List[CalibrationEvent]
    │   │   └── _classify_run_pair(file_path, r_now, r_next, drop, seen_fp_files) -> Optional[CalibrationEvent]
    │   ├── _score_weights(w_ldr, w_inf, w_ddc, w_purity, improvements, fp_candidates)
    │   │   -> (fn_rate, fp_rate, tiebreak_score)
    │   ├── _grid_search(improvements, fp_candidates, domain_anchor) -> List[WeightCandidate]
    │   │   4D simplex: w_ldr + w_inf + w_ddc + w_purity = 1.0
    │   │   Constrained to [anchor ± DOMAIN_TOLERANCE(0.15)] per dimension when anchor supplied
    │   │   sort key: (combined_score, tiebreak_score)
    │   └── _check_domain_drift(optimal_weights, anchor) -> List[str]
    │       Emits warning if any dimension drifts > DOMAIN_DRIFT_LIMIT(0.25) from anchor
    │
    CalibrationResult
    ├── status: str            # "ok" | "no_change" | "insufficient_data"
    ├── optimal_weights: dict  # {"ldr": float, "inflation": float, "ddc": float, "purity": float}
    ├── fn_rate: float
    ├── fp_rate: float
    ├── confidence_gap: float
    └── warnings: List[str]    # drift warnings (v3.5.0 — P4)
    │
    └── apply_to_config(weights, config_path) -> str
```

**Dependencies:** `sqlite3` (stdlib), `yaml` (already required by core).
No new packages required.

**Constants:**
- `DOMAIN_TOLERANCE = 0.15` — per-dimension grid search radius around anchor
- `DOMAIN_DRIFT_LIMIT = 0.25` — drift threshold for post-calibration warning

---

## Input Integrity Guarantees (v3.7.2)

Grid search accuracy depends on the quality of `HistoryEntry` records fed to it.
Since v3.7.2, `HistoryEntry.__post_init__` clamps six numeric fields before
every SQLite write:

| Field | Guard |
|---|---|
| `deficit_score` | `max(0.0, x)` |
| `ldr_score` | `max(0.0, min(1.0, x))` |
| `inflation_score` | `max(0.0, x)` |
| `ddc_usage_ratio` | `max(0.0, min(1.0, x))` |
| `n_critical_patterns` | `max(0, x)` |
| `pattern_count` | `max(0, x)` |

`fired_rules` is also validated as parseable JSON at write time — a malformed
string previously returned `None` on read, silently dropping all FP candidate
events for that file and biasing the per-rule FP rate tracker.

A single `ddc_usage_ratio = 1.05` (impossible value, calculation edge case)
would shift the ddc-heavy weight candidate upward artificially and potentially
flip the optimal weight selection. The `__post_init__` clamp prevents this.

Full specification: [docs/SCHEMA_VALIDATION.md](SCHEMA_VALIDATION.md)

---

## Related

- [History Tracking](HISTORY_TRACKING.md) — the data source for calibration
- [Configuration Guide](CONFIGURATION.md) — manual weight tuning, `.slopconfig.yaml` structure
- [Scoring Model](MATH_MODELS.md) — mathematical specification of the deficit formula
- [Schema Validation](SCHEMA_VALIDATION.md) — three-layer runtime guards that protect calibration input
- [ML Pipeline](HOW_IT_WORKS.md) — how the experimental ML layer relates to calibration
- [Validation Boundary](VALIDATION.md) — what the tool does and does not claim today
