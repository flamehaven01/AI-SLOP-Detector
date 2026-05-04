# Runtime Schema Validation — Technical Reference

> **Version:** 3.7.2
> **Last Updated:** 2026-05-04

Three independent validation layers protect the analysis pipeline from malformed data
propagating silently into the GQG scorer, the LEDA calibration grid search, or the
VS Code extension UI.

---

## Why Runtime Validation

The GQG weighted geometric mean formula computes `log(max(1e-4, dim_i))` for each of the
four metric dimensions. If any dimension arrives as a wrong type or out-of-range value —
from a malformed `.slopconfig.yaml`, a calculation edge case, or a CLI version mismatch —
the formula either raises `TypeError` with no useful context or silently produces `NaN /
-inf`, which then corrupts every downstream output (deficit score, status classification,
history DB record, and LEDA calibration signal).

The three guards described below ensure that **by the time any value reaches the formula,
its range and type are structurally guaranteed.**

---

## Layer 1 — Config Boundary (`config.py`)

**Trigger:** `.slopconfig.yaml` load (or `$SLOP_CONFIG` env path).

**Implementation:** `_validate_yaml_config(raw: dict) -> None`

Validates the raw YAML dict *before* `_deep_update()` merges it into `DEFAULT_CONFIG`.
Raises `ValueError` with a human-readable message on the first invalid section.

### Schemas

**`_WeightsSchema`** — validates `weights:` block:

| Field | Type | Constraint |
|---|---|---|
| `ldr` | `float` | `0.0 ≤ x ≤ 1.0` |
| `inflation` | `float` | `0.0 ≤ x ≤ 1.0` |
| `ddc` | `float` | `0.0 ≤ x ≤ 1.0` |
| `purity` | `float` | `0.0 ≤ x ≤ 1.0` |

Extra keys are allowed (`extra = "allow"`) for forward compatibility.

**`_DomainOverrideSchema`** — validates each entry in `patterns.god_function.domain_overrides`:

| Field | Type | Constraint |
|---|---|---|
| `function_pattern` | `str` | fnmatch wildcard — must be a string |
| `complexity_threshold` | `int` | `≥ 1` |
| `lines_threshold` | `int` | `≥ 1` |

**`_GodFunctionSchema`** — wraps the `patterns.god_function:` block:

| Field | Type | Constraint |
|---|---|---|
| `complexity_threshold` | `int` | `≥ 1` |
| `lines_threshold` | `int` | `≥ 1` |
| `domain_overrides` | `list[DomainOverride]` | each entry validated above |

### Error Output

```
ValueError: .slopconfig.yaml validation failed:
  - weights: 1 validation error for _WeightsSchema
    ldr
      Input should be less than or equal to 1 [type=less_than_equal, input_value=2.5]
  - patterns.god_function: 1 validation error for _GodFunctionSchema
    domain_overrides.0.function_pattern
      Input should be a valid string [type=string_type, input_value=123]
```

All errors are collected before raising — the user sees every problem in one pass.

### What it Protects

- `get_weights()` return value used as `w_ldr / w_inf / w_ddc / w_purity` in GQG scorer
- `get_god_function_config()["domain_overrides"]` iterated by `fnmatch.fnmatch(name, pattern)`
- Both would produce unhelpful `TypeError` or `AttributeError` at an unrelated call site
  without this guard

---

## Layer 2 — Computed Metric Results (`models.py`)

**Trigger:** dataclass instantiation (`__post_init__`).

These guard *computed* values produced by the LDR, Inflation, and DDC calculators.
An out-of-range value here indicates a calculation bug — the guard clamps and logs
a `WARNING` so the analysis continues while the anomaly is observable.

### `LDRResult.__post_init__`

```
Condition:  ldr_score < 0.0 or ldr_score > 1.0
Action:     ldr_score = max(0.0, min(1.0, ldr_score))
Log:        WARNING  LDRResult.ldr_score 1.2300 out of [0,1] — clamped
```

**Why `[0, 1]`:** LDR is defined as `logic_lines / total_lines`. Values outside `[0, 1]`
are a calculation invariant violation. Unclamped, they produce `log(1.2) > 0`, which
makes GQG exceed 1.0 and drives `deficit_score` negative.

### `InflationResult.__post_init__`

```
Condition:  inflation_score < 0.0
Action:     inflation_score = 0.0
Log:        WARNING  InflationResult.inflation_score -0.0500 below 0 — clamped
```

**Why `[0, ∞)`:** Inflation is `jargon_count / (avg_complexity × 10)`. Negative values
are impossible by definition but can arise from edge cases in radon's complexity output.

### `DDCResult.__post_init__`

```
Condition:  usage_ratio < 0.0 or usage_ratio > 1.0
Action:     usage_ratio = max(0.0, min(1.0, usage_ratio))
Log:        WARNING  DDCResult.usage_ratio 1.0500 out of [0,1] — clamped
```

**Why `[0, 1]`:** DDC is `actually_used / total_imported`. Values > 1 are impossible
(more used than imported) but can appear when annotation-only import accounting has a
rounding edge case. `log(1.05)` in GQG produces a positive contribution, distorting the
score upward.

---

## Layer 3 — History DB Insertion (`history.py`)

**Trigger:** `HistoryEntry.__post_init__` — fires before `_insert()` writes to SQLite.

The history database is the primary input for LEDA's calibration grid search. A single
out-of-range record can shift the optimal weight candidate, causing the calibrator to
apply incorrect weights across all future scans.

### Field-Level Guards

| Field | Guard | Rationale |
|---|---|---|
| `deficit_score` | `max(0.0, x)` | Score is always non-negative by GQG construction |
| `ldr_score` | `max(0.0, min(1.0, x))` | Same as Layer 2 |
| `inflation_score` | `max(0.0, x)` | Non-negative by definition |
| `ddc_usage_ratio` | `max(0.0, min(1.0, x))` | Ratio, always `[0, 1]` |
| `n_critical_patterns` | `max(0, x)` | Count cannot be negative |
| `pattern_count` | `max(0, x)` | Count cannot be negative |

### `fired_rules` JSON Validation

```python
# fired_rules: Optional[str] = None
# Format: '{"pattern_id": count, ...}'
```

`fired_rules` is stored as a JSON string and parsed on read by the per-rule FP rate
tracker in LEDA. If the string is malformed (e.g., truncated by an earlier crash), silent
`None` on read would drop all FP candidate events for that file — skewing calibration.

**Guard:** `json.loads(self.fired_rules)` is called in `__post_init__`. Raises
`ValueError: HistoryEntry.fired_rules must be valid JSON: ...` at insertion time so the
problem is caught immediately, not silently swallowed on the next calibration run.

---

## Layer 4 — VS Code Extension Boundary (`schema.ts`)

**Trigger:** After `JSON.parse(stdout)` in `runSlopDetector()` — before any field access.

**Implementation:** `parseSlopReport(data: unknown): ParseResult<ISlopReport>`

Returns a discriminated union — never throws:

```typescript
type ParseResult<T> =
    | { ok: true;  value: T }
    | { ok: false; error: SchemaError };

interface SchemaError { field: string; expected: string; got: string; }
```

`runSlopDetector()` calls `parseSlopReport()` and throws a `Error` on `ok: false` with
the exact field path, expected type, and actual type — surfaced as a VS Code error
notification with a version-check hint.

### Validated Fields

| Field | Validation |
|---|---|
| `file_path` | `typeof === "string"` |
| `deficit_score` | `typeof === "number"` |
| `status` | membership in `Set<SlopStatus>` (5 known values) |
| `ldr` / `inflation` / `ddc` | non-null object |
| `ldr.ldr_score` | `typeof === "number"` (protects `.toFixed()` in UI) |
| `warnings` / `pattern_issues` | `Array.isArray()` |
| `pattern_issues[i].{pattern_id,severity,message}` | `typeof === "string"` |
| `pattern_issues[i].line` | `typeof === "number"` |

Optional fields (`docstring_inflation`, `ml_score`, `dcf`, etc.) are preserved as
`unknown` — the extension already accesses them with `?.` optional chaining.

### No External Library

`parseSlopReport()` uses only handwritten type predicate helpers (`checkString`,
`checkNumber`, `checkArray`, `checkObject`, `typeTag`). Zero new npm dependencies.

---

## Interaction with LEDA Calibration

```
FileAnalysis produced
        │
        ▼
Layer 2 guards fire (LDR / DDC / Inflation __post_init__)
        │
        ▼
HistoryTracker.record(file_analysis) called
        │
        ▼
Layer 3 guard fires (HistoryEntry.__post_init__)
        │  all fields clamped; fired_rules validated
        ▼
_insert(entry) → SQLite history.db
        │
        ▼
SelfCalibrator.calibrate() reads history
  → improvement_event / fp_candidate labeling
  → 4D grid search over validated records only
  → confidence_gap >= 0.10 → weight update
```

Layer 2 and 3 together guarantee that no record with impossible metric values (`ldr > 1`,
`ddc < 0`, malformed `fired_rules`) enters the training set for LEDA's grid search.

---

## Adding New Validated Fields

**Config additions** — extend `_WeightsSchema` or add a new schema class in `config.py`,
then call it inside `_validate_yaml_config()`. No changes needed elsewhere.

**Model additions** — if a new metric result dataclass is added to `models.py`, add a
`__post_init__` method that clamps any float field that feeds into GQG or LEDA.

**VS Code additions** — add the new field to `ISlopReport` in `schema.ts`. Add a
`checkNumber` / `checkString` / `checkObject` call inside `parseSlopReport()` if the
field is required. Optional fields need no guard (they are `unknown` and accessed via
`?.`).
