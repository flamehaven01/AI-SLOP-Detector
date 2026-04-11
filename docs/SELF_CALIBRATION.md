# Self-Calibration Engine

> **The tool learns your codebase. The longer you use it, the better it fits.**

---

## The Problem with Universal Weights

The default scoring formula is:

```
deficit_score = w_ldr × (1 − ldr) + w_inflation × icr_norm + w_ddc × (1 − ddc) + pattern_penalty
```

With default weights:

```yaml
weights:
  ldr: 0.40
  inflation: 0.30
  ddc: 0.30
  purity: 0.10
```

These numbers were tuned against Flamehaven's internal codebase and hardcoded.
They work well for what we build. For a framework like Django or Spring — where
boilerplate is structurally required, not developer-chosen — the `ldr` weight
of 0.40 will generate false positives on legitimate code.

The mitigation exists: `.slopconfig.yaml` lets you adjust weights per project.
But the burden was on the user to know they need to, and to know what to set.

**Self-calibration removes that burden.** It reads your actual usage history and
finds the weights that minimize both missed detections and unnecessary alerts —
for your codebase specifically.

---

## How It Works

### 1. Data Source: History Database

Every `slop-detector` run is automatically recorded to
`~/.slop-detector/history.db` (SQLite). Each record stores:

```
file_path | file_hash | timestamp | deficit_score | ldr_score | inflation_score | ddc_usage_ratio | n_critical_patterns | pattern_count | grade
```

This accumulates silently as you use the tool. No configuration required.

### 2. Label Derivation from User Behaviour

The calibration engine extracts two event types from consecutive run pairs
for each unique file:

**`improvement_event`** — deficit was high, next run it dropped significantly.
The user edited the file after being warned. This is confirmed real slop.

```
run[i]:   deficit=47, file_hash=abc123
run[i+1]: deficit=12, file_hash=def456   <- different hash = user edited it
```
→ Label: `improvement` (true positive — current weights correctly flagged it)

**`fp_candidate`** — deficit was high, but the next run shows the same file
hash and no meaningful score change. The user saw the warning and ignored it.

```
run[i]:   deficit=38, file_hash=abc123
run[i+1]: deficit=36, file_hash=abc123   <- same hash = file untouched
```
→ Label: `fp_candidate` (likely false positive for this codebase's style)

**Why this breaks the tautology:**

The ML classifier had a circular labeling problem: labels were derived from
`deficit_score >= 30`, and features were the components of `deficit_score`.
The model learned to approximate the formula, not to detect anything independently.

Self-calibration labels come from **user behaviour** — did they edit the file?
This signal is completely independent of the formula's output.

### 3. Grid Search over the Weight Simplex

With labeled events, the engine searches all weight combinations where:
- `w_ldr + w_inflation + w_ddc + w_purity = 1.0`
- Each weight: `0.10 ≤ w ≤ 0.65`
- Resolution: 0.05 increments
- **Purity dimension:** `purity_score = exp(-0.5 * n_critical_patterns)` — 1.0 when no critical patterns, decays toward 0 as critical patterns accumulate

For each candidate weight set, two rates are computed:

| Rate | Definition |
|---|---|
| **FN rate** | Fraction of `improvement_event` files that the new weights would score below the slop floor — missed real slop |
| **FP rate** | Fraction of `fp_candidate` files that the new weights still score above the slop floor — unnecessary alerts |

Optimization target: minimize `FN_rate + FP_rate`.

No new dependencies. Pure Python + sqlite3.

### 4. Tiebreaker: Continuous Secondary Score

When multiple weight sets produce the same binary FN+FP rate (common at 0.05
resolution), a continuous secondary metric breaks ties:

```
tiebreak = avg_deficit(fp_candidates) − avg_margin_above_floor(improvement_events)
```

- Lower `avg_deficit` on FP candidates → fewer over-detections
- Higher margin on improvement events → clearer signal on true positives

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

**Result:** Fewer labeled events, but higher-fidelity signal. This is critical for
the 5+5 per-class threshold (see below) to remain statistically sound.

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
│ Improvement events (true positives)  │     62 │
│ FP candidates (flagged, never fixed) │    176 │
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

### Apply calibrated weights

```bash
# Write to default .slopconfig.yaml in current directory
slop-detector . --self-calibrate --apply-calibration

# Write to a specific config file
slop-detector . --self-calibrate --apply-calibration path/to/.slopconfig.yaml
```

The engine only writes when `status = ok` (confident result).
If `status = insufficient_data`, `--apply-calibration` is skipped with a warning.

### Adjust the minimum event threshold

```bash
# Require at least 8 events per class before calibration runs
slop-detector . --self-calibrate --min-history 8
```

Default: 5 events **per class** (improvements + FP candidates each independently).
Total minimum is 10 records (5+5). The 4D model's continuous tiebreak signal
makes 5+5 statistically reliable; 3D required 10+10 (binary-only scoring).
Increase `--min-history` for stricter confidence requirements.

### Auto-calibration at milestone (v3.2.1)

Starting from v3.2.1, calibration runs **automatically** at every
`CALIBRATION_MILESTONE` (10 records). No manual command required.

```
[*] Auto-calibration (10 records): weights updated -> .slopconfig.yaml
    ldr: 0.40 -> 0.45
    ddc: 0.30 -> 0.25
```

- Only writes when `status == "ok"` (CONFIDENCE_GAP + no_change gates fire first).
- Only writes when `.slopconfig.yaml` already exists in the project (no silent creation).
- Prints exactly what changed for full auditability.
- Manual `--self-calibrate --apply-calibration` still available for explicit control.

---

## Status Codes

| Status | Meaning |
|---|---|
| `ok` | Calibration succeeded with confident winner. `--apply-calibration` will write. |
| `no_change` | Current weights are already near-optimal (improvement margin < 2%). No write. |
| `insufficient_data` | Too few events, or confidence gap below threshold. No write. |

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
ddc:  0.30 → 0.65   (+0.35)
```

This means the codebase has many files with low LDR that users never fixed
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
- It does not guarantee universal validity. Calibrated weights are optimized
  for *your* history. If your team's style changes significantly, recalibrate.

---

## Architecture

```
src/slop_detector/ml/self_calibrator.py
    SelfCalibrator
    ├── calibrate(current_weights, min_events) -> CalibrationResult
    ├── _extract_events() -> (List[CalibrationEvent], unique_file_count)
    │   ├── improvement_event: high deficit + score dropped + hash changed
    │   ├── fp_candidate:      high deficit + same hash + score stable
    │   ├── _group_runs_by_file(rows) -> Dict[str, list]
    │   ├── _classify_consecutive_runs(file_path, runs, seen_fp_files) -> List[CalibrationEvent]
    │   └── _classify_run_pair(file_path, r_now, r_next, drop, seen_fp_files) -> Optional[CalibrationEvent]
    ├── _score_weights(w_ldr, w_inf, w_ddc, w_purity, improvements, fp_candidates)
    │   -> (fn_rate, fp_rate, tiebreak_score)
    ├── _grid_search(improvements, fp_candidates) -> List[WeightCandidate]
    │   4D simplex: w_ldr + w_inf + w_ddc + w_purity = 1.0
    │   sort key: (combined_score, tiebreak_score)
    └── apply_to_config(weights, config_path) -> str
```

**Dependencies:** `sqlite3` (stdlib), `yaml` (already required by core).
No new packages required.

---

## Related

- [History Tracking](HISTORY_TRACKING.md) — the data source for calibration
- [Configuration Guide](CONFIGURATION.md) — manual weight tuning, `.slopconfig.yaml` structure
- [Scoring Model](MATH_MODELS.md) — mathematical specification of the deficit formula
- [ML Pipeline](HOW_IT_WORKS.md) — how the experimental ML layer relates to calibration
