# LEDA Calibration Engine — Technical Document & Dogfooding History

> **Status:** 1st Dogfooding Complete | Global Weight Injection Complete
> **Engine Version:** LEDA v3.5 | self_calibrator.py v3.5.0 | global_injector.py v1.0
> **Last Updated:** 2026-05-01

---

## 0. Quick Start (For AI Context Recovery)

```bash
# Single Repo Dogfooding (Entry Point)
D:\Sanctum\ai-slop-detector\scripts\leda_turbo.bat "D:\Sanctum\Extra Repo\<REPO>" <N>

# Global Weight Re-injection (After adding 3+ new repos)
D:\Sanctum\ai-slop-detector\.venv\Scripts\python.exe scripts\global_injector.py

# Dry-run (Check synthesized values without modifying source code)
... global_injector.py --dry-run
```

---

## 1. File Map (Current Confirmed Structure)

```
D:\Sanctum\ai-slop-detector\
├── scripts\                          ← [SOVEREIGN ASSET] All LEDA automation tools
│   ├── leda_turbo.bat                ← v3.5  Turbo Protocol entry point (BAT wrapper)
│   ├── leda_helper.py                ← v3.4  Python automation engine (select/fixloop/compare/delta/gapcheck)
│   ├── global_injector.py            ← v1.0  Global weight synthesis + source code injection ★
│   ├── injection_report.json         ← Audit trail of the last injection (auto-generated)
│   └── generate_download_chart.py    ← (Legacy script, unrelated to LEDA)
│
├── src\slop_detector\
│   ├── config.py                     ← [Injection Target] DEFAULT_CONFIG + DOMAIN_PROFILES
│   └── ml\
│       └── self_calibrator.py        ← [Injection Target + LEDA Algorithm Core]
│
└── docs\
    └── LEDA_CALIBRATION.md           ← This document
```

> **[!] Legacy root files cleaned up:**
> `D:\Sanctum\ai-slop-detector\leda_helper.py` — Deleted 2026-05-01
> `D:\Sanctum\leda_turbo.bat` — Migrated to `scripts\leda_turbo.bat`

---

## 2. System Architecture Overall Flow

```
[External Repo Dogfooding]
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  scripts\leda_turbo.bat  (LEDA TURBO PROTOCOL v3.5) │
│                                                     │
│  STEP 0: Config check (Ensure .slopconfig.yaml)     │
│  STEP 1: Baseline Scan                              │
│    → scan_1.json, leda_1.yaml, calibration_1.txt    │
│  STEP 2: File Selection (By fixable_ratio)          │
│    leda_helper.py select                            │
│    ├── Files with AUTOFIX patterns prioritized      │
│    ├── Structural Ceiling files deprioritized       │
│    └── → selected_files.txt                         │
│  STEP 3: Auto Fix Loop (--auto unattended mode)     │
│    leda_helper.py fixloop --auto                    │
│    ├── bare_except, mutable_default_arg applied     │
│    ├── dry-run → "Would fix 0" → AUTO-SKIP          │
│    └── pre/post scan → REGRESSED → Warning printed  │
│  STEP 4: Final Scan                                 │
│    → scan_final.json, leda_final.yaml               │
│  STEP 5: LEDA Compare + Score Delta                 │
│    leda_helper.py compare + delta                   │
│  STEP 6: Calibration Gate                           │
│    confidence_gap >= 0.10 → --apply-calibration     │
│    < 0.10 → "signal accumulating" + injector hint   │
└─────────────────────────────────────────────────────┘
        │  leda_final.yaml (Accumulated across all targets)
        ▼
┌─────────────────────────────────────────────────────┐
│  scripts\global_injector.py  (v1.0)                 │
│                                                     │
│  STEP 1: Harvest                                    │
│    D:\Sanctum\Extra Repo\*\slop_reports\            │
│    Parse all leda_final.yaml files                  │
│  STEP 2: Filter & Synthesize                        │
│    Quality Gate: confidence_gap >= 0.05 + events >= 50 │
│    Fallback: All possessing valid optimal_weights   │
│    vote_weight = improvement_events × (1 + gap)     │
│    → Weighted Average → Clamp[0.10,0.65] → Normalize │
│  STEP 3: Inject                                     │
│    config.py L199: DOMAIN_PROFILES["general"]       │
│    self_calibrator.py L174: calibrate() fallback    │
│    (DEFAULT_CONFIG["weights"] is NOT modified —     │
│     it is the canonical fallback; dogfooding values │
│     belong only in DOMAIN_PROFILES["general"])      │
│  STEP 4: Report                                     │
│    → scripts\injection_report.json                  │
└─────────────────────────────────────────────────────┘
```

---

## 3. Core Algorithm: LEDA Weight Calibration

### 3.1 4D Weight Structure (GQG Geometric Mean)

```python
# GQG = Geometric Quality Grade
deficit_score = 100 × (1 - GQG)

GQG = exp(
    (w_ldr   × log(max(1e-4, LDR))
   + w_inf   × log(max(1e-4, 1.0 - inflation_normalized))
   + w_ddc   × log(max(1e-4, DDC_usage_ratio))
   + w_pur   × log(max(1e-4, purity)))
    / (w_ldr + w_inf + w_ddc + w_pur)
)
# max(1e-4, ...) prevents log(0) = -inf collapsing the entire score.
# purity = exp(-0.5 × n_critical_patterns)
# inflation_normalized = min(inflation_score, 2.0) / 2.0
```

### 3.2 Event Labeling (User Behaviour Based, Anti-Tautology)

```
improvement_event  → deficit[i] > 25.0 AND drop >= 10.0 AND git_commit altered
fp_candidate       → deficit[i] > 25.0 AND file_hash unchanged AND |delta| < 5.0
                     AND git_commit unchanged(or no git) AND 1 per file
```

### 3.3 Confidence Gap (Copilot Guardian Pattern)

```
gap = candidates[1].combined - candidates[0].combined
gap < 0.0001: replaced with tiebreak
gap < CONFIDENCE_GAP(0.10): weight update blocked → insufficient_data
```

### 3.4 fixable_ratio Selector (Ceiling Evasion Core)

```python
AUTOFIX   = {bare_except, pass_placeholder, mutable_default_arg, ...}
UNFIXABLE = {god_function, function_clone_cluster, nested_complexity}

fixable_ratio = len(AUTOFIX_patterns) / max(total_patterns, 1)
structural_ceiling = len(unfixable) > 2 OR (unfixable+manual) > fixable*3

# Sorting Priority:
# 1. has_autofix (True first)
# 2. no_ceiling (False first)
# 3. fixable_ratio DESC
# 4. deficit_score DESC
```

---

## 4. Dogfooding History (2026-05-01, 1st Calibration)

### 4.1 Target Repositories

| Repo | Size | avg_deficit | confidence_gap | optimal_weights (ldr/inf/ddc/pur) |
|------|------|------------|----------------|----------------------------------|
| AI-Scientist | 128 files | high | 0.0076 | 0.15/0.10/0.65/0.10 |
| LMCache | 334 files | med | 0.0269 | 0.15/0.10/0.65/0.10 |
| minGPT | 7 files | 53 | 0.0076 | 0.15/0.10/0.65/0.10 |
| OpenMythos | 8 files | med | 0.0076 | 0.15/0.10/0.65/0.10 |
| sloppylint | 14 files | 16.89 | 0.0019 | 0.15/0.20/0.55/0.10 |
| unsloth | 160 files | ~49 | 0.0019 | 0.15/0.20/0.55/0.10 |
| unstructured | 133 files | 16 | 0.0073 | 0.15/0.10/0.65/0.10 |

### 4.2 Observed Weight Drift

```
[unsloth, N=6 run]
  inflation: opt 0.10 → 0.20  (+0.10)  Reason: ML code bare_except density
  ddc:       opt 0.65 → 0.55  (-0.10)  Reason: LMCache over-calibration self-recovery

[sloppylint post-structural refactoring]
  hallucinations.py → Extracted PlaceholderPatternBase base class
  helpers.py        → Removed deep nesting
  → Confirmed significant deficit score drop
```

### 4.3 Global Injection Results (Applied 2026-05-01)

**Synthesized Global Weights (7 repos, vote-weight weighted average):**

```
  ldr         0.1500  ######
  inflation   0.1285  #####
  ddc         0.6215  ########################
  purity      0.1000  ####
```

**Drift Interpretation:**

| Dimension | Before¹ | After | Change | Interpretation |
|------|------|------|------|------|
| ldr | 0.40 | **0.15** | -62.5% | Simple Logic Density is the main cause of excessive FP |
| inflation | 0.30 | **0.13** | -57% | ML/OS code bare_except excessive penalty |
| ddc | 0.20² | **0.62** | +210% | Dependency usage ratio is the core metric of actual Slop |
| purity | 0.10 | **0.10** | 0% | Stable — No change |

> ¹ "Before" = `DEFAULT_CONFIG["weights"]` (canonical fallback, not modified by injector).
> ² Post-3.7.0 canonical value. At dogfooding time (2026-05-01) `ddc` was `0.30` in the pre-3.7.0 config.
> The injector no longer writes to `DEFAULT_CONFIG`; dogfooding values go only to `DOMAIN_PROFILES["general"]`.

---

## 5. Three Runtime Schema Guards (v3.7.2)

LEDA's calibration accuracy depends entirely on the quality of data flowing into the
grid search. Three guards — introduced in v3.7.2 — close the gap between "valid by
Python types" and "valid by algorithm invariants."

```
.slopconfig.yaml          Calculators          HistoryTracker.record()
      │                      │                        │
      ▼                      ▼                        ▼
_validate_yaml_config()  __post_init__()        __post_init__()
  Pydantic schemas         LDR:  [0,1]           deficit ≥ 0
  weights range            DDC:  [0,1]           ldr ∈ [0,1]
  domain_overrides types   Inf:  ≥ 0             ddc ∈ [0,1]
      │                      │                   fired_rules JSON
      ▼                      ▼                        ▼
ValueError (clear msg)   WARNING + clamp         ValueError or
before GQG formula       score continues         blocked insert
```

### Why This Matters for LEDA

**Grid search input corruption** — The 4D calibration grid search evaluates
`combined_score` over `(ldr, inflation, ddc, purity)` weight candidates.
A single `HistoryEntry` with `ddc_usage_ratio = 1.05` (impossible ratio) shifts
the `ddc`-heavy candidate upward artificially, potentially flipping the optimal
weight selection. The `HistoryEntry.__post_init__` clamp prevents this.

**`fired_rules` silent loss** — The per-rule FP rate tracker reads `fired_rules`
as JSON on each calibration pass. A malformed string previously returned `None`
(silently dropping all FP candidate events for that file), biasing the
`fp_candidate_count` denominator. The JSON validation guard surfaces the
corruption at insertion time.

**Config weight corruption** — If a user manually edits `.slopconfig.yaml` and
sets `weights.ddc: 2.5`, GQG computes `log(ddc_ratio) × 2.5`, which dominates
all other dimensions and makes every file appear `CRITICAL_DEFICIT`. Previously
this produced a confusing, un-diagnosable result. Now it raises:
```
ValueError: .slopconfig.yaml validation failed:
  - weights: ddc Input should be less than or equal to 1
```

### Monitoring

Warning-level log messages from Layer 2 guards indicate a calculation edge case:
```
WARNING  LDRResult.ldr_score 1.2300 out of [0,1] — clamped
WARNING  DDCResult.usage_ratio -0.0100 out of [0,1] — clamped
```
These should be investigated — they signal a real bug in the metric calculators.

Full specification: [docs/SCHEMA_VALIDATION.md →](SCHEMA_VALIDATION.md)

---

## 6. leda_helper.py Command Reference

```bash
python scripts\leda_helper.py select   <scan.json> [N]
python scripts\leda_helper.py fixloop  <selected.txt> <python> [cfg] [--auto]
python scripts\leda_helper.py compare  <leda_1.yaml> <leda_final.yaml>
python scripts\leda_helper.py delta    <scan_1.json> <scan_final.json>
python scripts\leda_helper.py gapcheck <leda_final.yaml>
  → stdout: "OK" | "LOW 0.0019"
```

## 7. global_injector.py Command Reference

```bash
# Default execution (Harvest all Extra Repos → Inject)
python scripts\global_injector.py

# Check synthesis results without modification
python scripts\global_injector.py --dry-run

# Specify a different Extra Repos directory
python scripts\global_injector.py --extra-repos "E:\OtherRepos"
```

**Output File:** `scripts\injection_report.json`

---

## 8. Slop Report Output Explanation

```
<TARGET>\slop_reports\
  scan_1.json            ← Baseline full scan (JSON)
  leda_1.yaml            ← Baseline LEDA state (includes calibration)
  calibration_1.txt      ← Baseline calibration text
  selected_files.txt     ← Auto-selected Fix target file list
  <file>_before.json     ← Pre-fix scan per file
  <file>_after.json      ← Post-fix scan per file
  <file>_fix_preview.txt ← dry-run preview
  <file>_fix.txt         ← Actual Fix log
  scan_final.json        ← Final full scan
  leda_final.yaml        ← Final LEDA state ★ (Input for global_injector)
  calibration_final.txt  ← Final calibration text
  gap_check.txt          ← "OK" or "LOW 0.XXXX"
```

---

## 9. Next Actions

1. **Additional Dogfooding to breach 0.10 confidence_gap:**
   - Scan additional small-scale, high-density repos (50~100 files).
   - Secure improvement_events density with N=20~30 runs.
   - Currently, LMCache is closest with gap=0.0269 → Focus recommended.

2. **global_injector.py re-execution criteria:**
   - Upon adding 3 or more new Dogfooding targets.
   - Upon emergence of the first trusted signal (gap >= 0.05 + events >= 50).

3. **Sentinel V-Engine Integration:**
   - Update `SENTINEL_CERT.md` after confirming weight stabilization.
   - `git commit -am 'feat(leda): inject dogfooding-calibrated global weights v2'`
