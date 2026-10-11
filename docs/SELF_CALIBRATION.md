# Self-Calibration (Calibration v2)

> **Status (v3.10): advisory only.** `--self-calibrate` reports which
> ldr / inflation / ddc weights the comparable history of one project suggests.
> Nothing writes weights: scans do not calibrate, and `--apply-calibration`
> writes nothing and exits 2. To change weights, edit the `weights:` block of
> `.slopconfig.yaml` yourself.

## Why v2

Before v3.10 the history did not record what measured a row (detector version,
configuration, project root), so a score change was not proof that the code
changed. Measured on 29,303 real history rows (26 working directories, 8,556
files): 241 of the 301 "improvement" pairs (80%) had an unchanged file; 61% of
flagged rows were flagged by pattern penalties that no weight can move; and
rows were grouped by working directory, so projects scanned from one directory
shared them.

Calibration v2 learns only from evidence it can compare. On a copy of a real
history database (31,065 rows) the old algorithm reported 364 improvements,
289 of them (79%) with an unchanged file; v2 reports every one of those rows as
legacy, uses none of them, and starts from new scans.

---

## The Problem with Universal Weights

The score combines four dimensions with a weighted geometric mean (GQG):

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

Default weights (`Config.DEFAULT_CONFIG`): `ldr 0.40 · inflation 0.30 ·
ddc 0.20 · purity 0.10`. They were tuned on one family of codebases; in a
framework where boilerplate is structurally required, the `ldr` weight can
raise noisy alerts on legitimate code. `.slopconfig.yaml` lets a project set
its own weights; the report suggests where to look.

---

## Validation Boundary

Self-calibration is **operational calibration**, not external validation.

It does:

- report the ldr / inflation / ddc weights that one project's comparable
  history favours (purity is held at its current weight)
- return a reproducible recommendation from explicit rules and thresholds

It does **not**:

- write weights, run during scans, or mix projects
- prove that `deficit_score` measures one validated latent condition
- replace blinded review, out-of-sample benchmarking, or independent validation

---

## What Counts as Evidence

Every scan writes history schema v6 rows (`~/.slop-detector/history.db`,
migrated in place; old rows are never rewritten). A v6 row records:

| Field | Meaning |
|---|---|
| detector version | the release that measured the file |
| measurement fingerprint | detector version + analysis engine version + the whole effective configuration (weights, thresholds, ignore rules, disabled patterns, runtime overrides) |
| weights | the weights the scan used |
| project root | the scanned directory for a project scan; the nearest project marker (else the parent directory) for a single file |
| relative path | the file's path under that root |
| base deficit, pattern penalty | the two parts of the stored score |

The calibrator reads only v6 rows of the project root it is asked about.
Older rows are counted as `legacy` and are never evidence.

## How It Works

1. **Comparable runs.** Rows are grouped per file and per measurement
   fingerprint, so only runs measured the same way are compared. A change of
   detector, engine or configuration starts a new group.
2. **Labels.** Each pair of consecutive comparable runs gives at most one
   label, judged by the *metric-only deficit*: the canonical quality gate
   (`compute_gqg`) of ldr, inflation and ddc with purity fixed at 1.0, so a
   pattern penalty, which no weight can move, never decides a label.
   - `improvement`: the file changed (its hash differs) and its metric-only
     deficit fell by at least `FIX_DELTA = 10` from at least `SUSPICIOUS_AT = 30`;
   - `stable_flag_candidate`: the metric-only deficit is at least 30 and the
     file did not change; counted once per file.
3. **Grid search.** ldr, inflation and ddc move on a 0.05 grid (each between
   0.10 and 0.65) summing to `1 − purity`; purity keeps its current weight.
   Each candidate is scored on the labelled events by recomputing the
   metric-only deficit against the canonical band threshold:
   `fn_rate` = improvements it would not flag, `fp_rate` = stable flags it
   would still flag, ranked by `fn_rate + fp_rate`, then by a continuous
   tiebreak (mean stable-flag deficit minus mean improvement margin).
4. **Confidence.** The gap between the best two candidates must be at least
   `CONFIDENCE_GAP = 0.10`; otherwise the report asks for more evidence. A
   best candidate within 0.02 of the current weights' combined error is
   `no_change`.
5. **Per-rule diagnostics.** Patterns that fired on labelled files (at least
   3 times) get a noisy-alert rate (share of stable flags). Rates of 50% or
   more are listed. They inform review; they never change weights.
6. **Drift warning.** An optimal weight more than `DOMAIN_DRIFT_LIMIT = 0.25`
   from the current weight is reported as a warning.

---

## Usage

```bash
slop-detector . --self-calibrate                 # report for this project root
slop-detector . --self-calibrate --min-history 8 # need 8 events per class
```

The report shows:

| Row | Meaning |
|---|---|
| Project root | the root whose history was read |
| Files with comparable runs | files with at least two runs under one fingerprint |
| Comparable run pairs | consecutive pairs examined |
| Legacy rows (not evidence) | pre-v6 rows of this root |
| Improvements | flagged files that changed and whose metric score fell |
| Stable flags | flagged files left unchanged |
| Confidence gap | distance between the best two candidates |

and a current / optimal / delta table for ldr, inflation, ddc and purity, the
combined error before and after (status `ok` only), drift warnings, and the
per-rule rates.

## Status Codes

| Status | Meaning |
|---|---|
| `ok` | A confident recommendation. Advisory only: nothing writes it. |
| `no_change` | The current weights are within 0.02 of the best combined error, or no candidate was valid. |
| `insufficient_data` | No project root, no history database, fewer than the required events, or a confidence gap below 0.10. |

## How Much History Is Needed?

At least 5 `improvement` events **and** 5 `stable_flag_candidate` files
(`--min-history` raises both). Both need comparable runs: the same file scanned
at least twice under one detector, engine and configuration. Upgrading the
detector or editing `.slopconfig.yaml` starts a new comparison group, so a
fresh project, or a project right after an upgrade, reports
`insufficient_data` until new scans accumulate.

## Interpreting Results

- **A high fn_rate** at the current weights means files that were flagged and
  then fixed would not have been flagged: the metric dimensions that changed
  most in those fixes deserve more weight.
- **A high fp_rate** means files flagged on metrics stayed unchanged: either
  the team accepts them (a weight is too strong for this codebase) or the
  review has not happened yet. The report cannot tell these apart.
- **Large shifts** (drift warnings) deserve a look at the labelled files before
  any manual change; a few files can dominate a small history.

---

## What Self-Calibration Does NOT Do

- It does not retrain the ML classifier (a separate, experimental layer).
- It does not change pattern thresholds or `patterns.disabled`; patterns fire
  from AST analysis, not from weights.
- It does not learn the purity weight: purity measures pattern findings, which
  the metric-only deficit leaves out by design.
- It does not prove external validity. Weights fit to *your* history.

---

## Architecture

```
src/slop_detector/ml/self_calibrator.py
    metric_only_deficit(ldr, inflation, ddc, weights)   canonical GQG, purity = 1.0
    SelfCalibrator(db_path=None)                        default ~/.slop-detector/history.db
    └── calibrate(current_weights, min_events, project_root, domain_anchor) -> CalibrationResult
        ├── _extract_events(project_root)   v6 rows, grouped by (file, measurement fingerprint)
        │   └── _classify_pair(...)         improvement | stable_flag_candidate | none
        ├── _grid_search(...)               ldr / inflation / ddc on a 0.05 grid, purity held
        ├── _score_weights(...)             (fn_rate, fp_rate, tiebreak)
        └── _calc_per_rule_fp_rates(...)    per-pattern noisy-alert rates

    CalibrationResult
        status, project_root, unique_files, comparable_pairs, legacy_rows_ignored,
        improvement_events, stable_flag_candidates, current_weights, optimal_weights,
        confidence_gap, fn/fp rates before and after, top_candidates,
        per_rule_fp_rates, warnings, message

src/slop_detector/history.py
    MeasurementProvenance, measurement_provenance(config, project_root)
    history_project_root(path, is_project)
```

Dependencies: `sqlite3` (stdlib). No new packages.

---

## Input Integrity Guarantees

`HistoryEntry.__post_init__` clamps numeric fields before every SQLite write
(`deficit_score`, `inflation_score` >= 0; `ldr_score`, `ddc_usage_ratio` in
[0, 1]; pattern counts >= 0) and rejects a `fired_rules` value that is not
valid JSON, so one malformed row cannot bias the grid search or drop a file's
events silently. Full specification:
[docs/SCHEMA_VALIDATION.md](SCHEMA_VALIDATION.md).

---

## Related

- [History Tracking](HISTORY_TRACKING.md) — the data source for calibration
- [Configuration Guide](CONFIGURATION.md) — manual weight tuning, `.slopconfig.yaml` structure
- [Scoring Model](MATH_MODELS.md) — mathematical specification of the deficit formula
- [Schema Validation](SCHEMA_VALIDATION.md) — runtime guards that protect calibration input
- [Validation Boundary](VALIDATION.md) — what the tool does and does not claim today
