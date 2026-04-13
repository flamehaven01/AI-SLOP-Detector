# Mathematical Models Reference — AI-SLOP Detector v3.5.0

> **Audience:** Contributors, researchers, and integrators who need to understand
> the precise scoring formulas and algorithmic decisions behind each metric.

---

## Table of Contents

1. [Logic Density Ratio (LDR)](#1-logic-density-ratio-ldr)
2. [Inflation-to-Code Ratio (ICR) — v2.8.0 Redesign](#2-inflation-to-code-ratio-icr)
3. [Deep Dependency Check (DDC)](#3-deep-dependency-check-ddc)
4. [Deficit Score Composition](#4-deficit-score-composition)
5. [Status Determination — Monotonic Axis](#5-status-determination)
6. [Project-Level Aggregation (SR9)](#6-project-level-aggregation-sr9)
7. [Python Advanced Patterns — AST Models](#7-python-advanced-patterns)
8. [Function-Scoped Justification](#8-function-scoped-justification)
9. [ML Feature Vector](#9-ml-feature-vector)
10. [ML Secondary Signal (MLScore)](#10-ml-secondary-signal)

---

## 1. Logic Density Ratio (LDR)

**Purpose:** Measures how much of a file is actual executable logic versus blank
lines, comments, and structural boilerplate.

### Formula

```
ldr_score = logic_lines / total_lines        (if total_lines > 0, else 0.0)
```

Where:
- `total_lines` = all non-empty lines (blank lines counted separately)
- `logic_lines` = lines that are not blank, not pure comments, not docstrings,
  not structural tokens (class/def/pass/return alone, etc.)

### Grade Table

| Grade | Condition      | Interpretation                        |
|-------|----------------|---------------------------------------|
| A     | ldr >= 0.60    | High density — substantial logic      |
| B     | ldr >= 0.45    | Adequate density                      |
| C     | ldr >= 0.30    | Low density — likely padded           |
| D     | ldr < 0.30     | Very low density — probable slop      |

### Special Exemptions

Files flagged as `is_abc_interface = True` (ABC base classes with abstract-only
methods) or `is_type_stub = True` (`.pyi` files) receive reduced penalty weight,
since structural boilerplate is expected.

---

## 2. Inflation-to-Code Ratio (ICR)

> **v2.8.0 major redesign.** Prior to v2.8.0, complexity *divided* the penalty
> (rewarding overly complex code). The new model treats complexity as an
> **amplifier** — a jargon-heavy complex function is penalized more than a
> jargon-heavy simple one.

### Formula

```
density            = unjustified_jargon_count / max(logic_lines, 1)
complexity_modifier = max(1.0, 1.0 + (avg_complexity - 3.0) / 10.0)
inflation_score    = min(density * complexity_modifier * 10.0, 10.0)
```

### Complexity Modifier Behaviour

| avg_complexity | modifier | Effect                                    |
|---------------|----------|-------------------------------------------|
| <= 3          | 1.0x     | No amplification (simple code baseline)   |
| 6             | 1.3x     | Moderate amplification                    |
| 10            | 1.7x     | Significant amplification                 |
| 13            | 2.0x     | Double penalty                            |
| 23            | 3.0x     | Triple penalty                            |

**Key property:** `complexity_modifier` is clamped to `[1.0, +inf)`. Complexity
can only increase the penalty — never reduce it. This prevents a complex god
function from hiding behind its own algorithmic weight.

### Score Interpretation

| Range    | Status      |
|----------|-------------|
| 0.0–1.0  | Low         |
| 1.0–3.0  | Moderate    |
| 3.0–6.0  | High        |
| 6.0–10.0 | Extreme     |

### Prior Formula (deprecated v2.7.x)

```
# OLD — complexity wrongly divided the penalty:
inflation_score = jargon_count * weight / (avg_complexity + 1)
```

---

## 3. Deep Dependency Check (DDC)

**Purpose:** Measures what fraction of imported modules are actually used.

### Formula

```
usage_ratio = len(actually_used) / len(imported)    (if imported else 1.0)
```

Where `actually_used` is the intersection of imported names with names found
in the AST body (function calls, attribute accesses, type annotations).

### Grade Table

| Grade | Condition         | Interpretation              |
|-------|-------------------|-----------------------------|
| A     | ratio >= 0.80     | Imports well-used           |
| B     | ratio >= 0.60     | Some unused, acceptable     |
| C     | ratio >= 0.40     | Significant dead imports    |
| D     | ratio < 0.40      | Likely hallucinated imports |

**Supplementary signal:** `fake_imports` — imports that are in the AST but
resolve to no known purpose (ML, HTTP, DB libs imported then never referenced
in any call expression). These are surfaced separately as `hallucination_deps`.

---

## 4. Deficit Score Composition

**Purpose:** Single composite score [0, 100] summarising all signals.
Higher = more deficit (worse quality).

### Formula

```
base_deficit = 100 × (1 − GQG_4D)

GQG_4D = exp( (w_ldr × log(ldr) + w_inf × log(1 − icr_norm) + w_ddc × log(ddc) + w_purity × log(purity_score)) / total_w )

purity_score = exp(−0.5 × n_critical_patterns)
total_w = w_ldr + w_inflation + w_ddc + w_purity

pattern_penalty = Sigma(severity_weight[sev] * count[sev])

deficit_score = base_deficit + pattern_penalty
```

### Default Weights

| Signal    | Weight (w) | Source                              |
|-----------|------------|-------------------------------------|
| ldr       | 0.40       | `.slopconfig.yaml` `weights.ldr`    |
| inflation | 0.30       | `.slopconfig.yaml` `weights.inflation` |
| ddc       | 0.30       | `.slopconfig.yaml` `weights.ddc`    |
| purity    | 0.10       | `.slopconfig.yaml` `weights.purity` |

`w_ldr + w_inflation + w_ddc + w_purity = 1.10` (normalization uses `total_w`, so the sum need not equal 1.0 exactly).

### Pattern Severity Penalties (added after weighted sum, before x100)

| Severity | Penalty per occurrence |
|----------|------------------------|
| critical | 0.10                   |
| high     | 0.05                   |
| medium   | 0.02                   |
| low      | 0.01                   |

The sum is capped internally so that extreme pattern counts cannot push the
score above 100.

---

## 5. Status Determination

> **v2.8.0 redesign.** Prior versions had multi-axis branching (separate LDR,
> DDC, pattern-count branches) that could produce inconsistent status for
> identical deficit scores. v2.8.0 uses a **single monotonic axis** on
> `deficit_score`, with two explicit supplementary overrides.

### Primary Axis

```
deficit_score >= 70  -->  CRITICAL_DEFICIT
deficit_score >= 50  -->  INFLATED_SIGNAL
deficit_score >= 30  -->  SUSPICIOUS
else                 -->  CLEAN
```

### Supplementary Overrides (applied after primary axis)

```
IF critical_pattern_count >= 5 AND status == CLEAN:
    status = SUSPICIOUS

IF ddc_usage_ratio < 0.20 AND status in {CLEAN, SUSPICIOUS}:
    status = DEPENDENCY_NOISE
```

**Key property:** Overrides can only *raise* status, never lower it.
A file already at `INFLATED_SIGNAL` or `CRITICAL_DEFICIT` is unaffected.

### Status Semantics

| Status             | Meaning                                          |
|--------------------|--------------------------------------------------|
| CLEAN              | No significant quality issues detected           |
| SUSPICIOUS         | Marginal quality — review recommended            |
| INFLATED_SIGNAL    | High jargon or low logic density — likely AI pad |
| CRITICAL_DEFICIT   | Severe multi-dimensional deficit                 |
| DEPENDENCY_NOISE   | Import graph dominated by unused dependencies    |

---

## 6. Project-Level Aggregation (SR9)

**Purpose:** Aggregate per-file LDR scores into a single project-level metric
without allowing a majority of clean files to mask a critically degraded one.

### Formula

```
project_ldr = 0.6 * min(file_ldr_scores) + 0.4 * mean(file_ldr_scores)
```

### Rationale

This is derived from the **SR9 conservative aggregation principle** (TOE
Sovereign Resonance protocol), where:

- `min` captures the worst-case file (weighted 60%)
- `mean` captures the central tendency (weighted 40%)

Contrast with naive mean: a project with 99 clean files (LDR=0.8) and one
empty wrapper file (LDR=0.05) would score 0.795 under mean — appearing healthy.
Under SR9, it scores 0.6 * 0.05 + 0.4 * 0.795 = 0.348 — correctly flagging
the dragging file.

### Other Project Aggregations

```
avg_deficit_score        = mean(file.deficit_score for file in project)
weighted_deficit_score   = sum(file.deficit_score * file.total_lines)
                           / sum(file.total_lines)   [line-weighted mean]
avg_inflation            = mean(file.inflation.inflation_score)
avg_ddc                  = mean(file.ddc.usage_ratio)
```

---

## 7. Python Advanced Patterns

> New in v2.8.0. Uses Python `ast` module for precise scope-aware detection.

### 7.1 Cyclomatic Complexity

```
complexity(fn) = 1 + count(
    If, IfExp,
    For, While, ExceptHandler,
    With,
    BoolOp[op=And], BoolOp[op=Or]
)
```

This is a simplified McCabe metric implemented over the AST. Each branching
node adds 1 to the base complexity of 1.

### 7.2 God Function

**Triggered when:** `logic_lines > 50 OR complexity > 10`

```
is_god_function = (
    count_logic_lines(fn) > 50
    OR cyclomatic_complexity(fn) > 10
)
```

Logic lines within a function are counted the same way as file-level LDR:
executable statements excluding blank lines and pure comments.

**Severity:** HIGH

### 7.3 Deep Nesting

```
depth(node):
    if node has no control-flow children: return 0
    return 1 + max(depth(child) for child in control_flow_children(node))

control_flow_children = bodies of: If, For, While, With, Try
                        (orelse branches counted at same depth as main body)
```

**Alert:** `depth(fn) > 4`

**Severity:** HIGH

Example — depth 5 (triggers):
```python
def f():
    for x in items:           # depth 1
        if x > 0:             # depth 2
            while True:       # depth 3
                try:          # depth 4
                    if cond:  # depth 5  <-- triggers
                        pass
```

### 7.4 Dead Code (Unreachable Statements)

```
is_terminal(stmt) = isinstance(stmt, (Return, Raise, Break, Continue))

dead_code_in_block(stmts):
    terminal_seen = False
    for stmt in stmts:
        if terminal_seen: yield stmt  # unreachable
        if is_terminal(stmt): terminal_seen = True
    recurse into: orelse, finalbody, handlers
```

**Scope:** Applied recursively to function bodies, orelse blocks, finally
blocks, and exception handler bodies. Dead code inside nested functions is
attributed to the innermost function.

**Severity:** MEDIUM

---

## 8. Function-Scoped Justification

> **v2.8.0 redesign.** Previously, a single `import torch` at the top of a
> file would justify all AI jargon anywhere in the file. Now each function
> must contain (or be decorated by) its own justifier.

### Scope Definition

```
scope_start(fn) = min(decorator.lineno for decorator in fn.decorator_list,
                      default fn.lineno)
scope_end(fn)   = fn.end_lineno
```

The decorator's `lineno` is included so that `@torch.jit.script` above a
function is correctly counted as part of that function's justification scope.

### Justification Check

```
justified(jargon_at_line L, fn) =
    any(
        justifier_line in [scope_start(fn), scope_end(fn)]
        for justifier_line in justifier_lines_in_file
    )
```

Where `justifier_lines` includes:
- Import statements that import a known domain library
- Decorator lines referencing domain-specific decorators
- Function-body usage of domain APIs

### Example

```python
import torch  # line 1 — file-scope; does NOT justify line 20

def encode(data):          # scope [10, 18]
    return base64(data)    # line 12: "encode" jargon here IS NOT justified
                           # (torch import is outside scope)

@torch.jit.script          # line 20 — inside scope [20, 28]
def transform(tensor):     # line 21
    return tensor * 2.0    # line 23: "transform" jargon IS justified
                           # (decorator at line 20 is in scope)
```

---

## 9. ML Feature Vector

> ML scoring is an **optional secondary signal**. No model file = no scoring.
> The rule-based `deficit_score` remains the authoritative primary signal.

### Feature Vector (17 dimensions)

| # | Feature Name              | Source                                  | Range     |
|---|---------------------------|-----------------------------------------|-----------|
| 1 | `ldr_score`               | LDR result                              | [0, 1]    |
| 2 | `inflation_score`         | ICR result (normalized: /10 internally) | [0, 10]   |
| 3 | `ddc_score`               | DDC usage_ratio                         | [0, 1]    |
| 4 | `pattern_count_critical`  | pattern_issues count by severity        | [0, +inf) |
| 5 | `pattern_count_high`      | pattern_issues count by severity        | [0, +inf) |
| 6 | `pattern_count_medium`    | pattern_issues count by severity        | [0, +inf) |
| 7 | `pattern_count_low`       | pattern_issues count by severity        | [0, +inf) |
| 8 | `god_function_count`      | v2.8.0 pattern (Section 7.2)            | [0, +inf) |
| 9 | `dead_code_count`         | v2.8.0 pattern (Section 7.4)            | [0, +inf) |
|10 | `deep_nesting_count`      | v2.8.0 pattern (Section 7.3)            | [0, +inf) |
|11 | `avg_complexity`          | radon cyclomatic mean over file         | [1, +inf) |
|12 | `cross_language_patterns` | patterns from wrong-language idioms     | [0, +inf) |
|13 | `hallucination_count`     | pattern_id contains "hallucin"          | [0, +inf) |
|14 | `total_lines`             | LDR result                              | [0, +inf) |
|15 | `logic_lines`             | LDR result                              | [0, +inf) |
|16 | `empty_lines`             | LDR result                              | [0, +inf) |

### Training Label

```
label = 1 (slop)   if deficit_score >= 30.0
label = 0 (clean)  if deficit_score <  30.0
```

The threshold of 30 corresponds to the SUSPICIOUS boundary on the primary
status axis (Section 5).

### Supported Model Types

| Type            | Identifier        | Backend                    |
|-----------------|-------------------|----------------------------|
| Random Forest   | `random_forest`   | `sklearn.ensemble`         |
| XGBoost         | `xgboost`         | `xgboost.XGBClassifier`    |
| Ensemble (soft) | `ensemble`        | RF + XGB probability mean  |

---

## 10. ML Secondary Signal (MLScore)

### Output

```python
@dataclass
class MLScore:
    slop_probability: float   # [0, 1] — probability this file is slop
    confidence: float         # [0, 1] — max class probability (model certainty)
    model_type: str           # "random_forest" | "xgboost" | "ensemble"
    agreement: bool           # True if rule-based and ML agree (see below)
    features_used: int        # always 16 in v2.8.0
```

### Label Thresholds

```
label = "slop"      if slop_probability >= 0.70
label = "uncertain" if slop_probability >= 0.40
label = "clean"     if slop_probability <  0.40
```

### Agreement Computation

```
rule_is_slop = (deficit_score >= 30.0)
ml_is_slop   = (slop_probability >= 0.40)
agreement    = (rule_is_slop == ml_is_slop)
```

Agreement is **informational only** — it does not affect the primary
`deficit_score` or `status`. When the two signals disagree, the rule-based
score takes precedence.

### Confidence Interpretation

| Confidence | Interpretation                                        |
|------------|-------------------------------------------------------|
| >= 0.90    | High certainty — model strongly separates this sample |
| 0.70–0.90  | Moderate certainty                                    |
| < 0.70     | Low certainty — borderline case, rule-based is primary|

### Synthetic Training Data (v2.8.0 Generator)

The built-in `synthetic_generator.py` produces labelled samples for bootstrap
training without requiring a real codebase:

**Slop sample construction:**
- 5–15 unused imports (hallucination pattern)
- 3–8 empty functions with jargon names and jargon docstrings
- 1 god function template (150+ lines, complexity > 12)
- `bare_except` and dead-code-after-return blocks
- mutable default argument

**Clean sample construction:**
- 12 diverse utility functions (clamp, deduplicate, truncate, chunk, retry, etc.)
- All imports used, meaningful docstrings only where warranted
- Complexity <= 5, nesting depth <= 3, no dead code

**Reported accuracy on synthetic set (600 samples, 70/30 split):**
- Random Forest: 1.000 train / ~0.98 test
- Top discriminating features: `deep_nesting_count` (#1), `ldr_score` (#2),
  `dead_code_count` (#5)

> **Warning:** Models trained exclusively on synthetic data will overfit to
> synthetic patterns. For production use, supplement with real codebase samples
> via the manual label pipeline (`pipeline.py`).

---

## Appendix A: Formula Change History

| Version | Signal    | Change                                                  |
|---------|-----------|---------------------------------------------------------|
| v3.5.0  | Calibr.   | P1: project_id scoping in history.db (Schema v5)        |
| v3.5.0  | Calibr.   | P2: milestone trigger = count_files_with_multiple_runs  |
| v3.5.0  | Calibr.   | P3: domain-anchored ±0.15 grid search bounds            |
| v3.5.0  | Calibr.   | P4: DOMAIN_DRIFT_LIMIT=0.25 divergence warning          |
| v3.4.0  | Pattern   | JS/TS 4 patterns + Go 4 patterns added                  |
| v3.1.0  | Pattern   | Clone/naming/stub patterns added                        |
| v2.9.0  | Pattern   | phantom_import (hallucinated package detection)         |
| v2.8.0  | ICR       | Complexity now amplifies penalty (was: divided penalty) |
| v2.8.0  | Status    | Single monotonic axis replaces multi-axis branching     |
| v2.8.0  | LDR (proj)| SR9 conservative aggregation: 0.6*min + 0.4*mean       |
| v2.8.0  | Justif.   | Function-scoped (was: file-scoped)                      |
| v2.8.0  | ML        | 16 features (was: 13; added god/dead/nesting counts)    |
| v2.7.0  | DDC       | Fake import detection added                             |
| v2.6.3  | Pattern   | @slop.ignore decorator support                          |
| v2.2.0  | ICR       | Docstring inflation added as sub-signal                 |
| v2.1.0  | Patterns  | Cross-language pattern catalog added                    |

---

## Appendix B: Configuration Overrides

All weights and thresholds are overridable via `.slopconfig.yaml`:

```yaml
weights:
  ldr: 0.40
  inflation: 0.30
  ddc: 0.30
  purity: 0.10

thresholds:
  deficit:
    suspicious: 30
    inflated: 50
    critical: 70
  ldr:
    grade_a: 0.60
    grade_b: 0.45
    grade_c: 0.30

pattern_penalties:
  critical: 0.10
  high: 0.05
  medium: 0.02
  low: 0.01
```

---

*This document reflects the implementation in `src/slop_detector/` as of v3.5.0.
For source-level detail, see the inline docstrings in `metrics/inflation.py`,
`core.py`, `patterns/python_advanced.py`, and `ml/scorer.py`.*
