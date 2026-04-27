---
name: slop-detector
description: Structural risk scanner for AI-assisted code using AI-SLOP Detector CLI. Triggers on /slop (full project scan), /slop-file [path] (single file), /slop-gate (CI hard gate), /slop-spar (adversarial validation). Interprets findings, prioritizes fixes, and drives the scan -> patch -> re-scan -> gate quality loop. Use when asked to check code quality, detect AI slop, validate imports, review structural integrity, or run a quality gate on Python/JS/Go files.
---

# AI-SLOP Detector Skill

Structural risk scanner for AI-assisted code. Runs `slop-detector` CLI commands, interprets 4D scoring output (LDR + ICR + DDC + Purity), and drives the `scan -> patch -> re-scan -> gate` quality loop.

## Prerequisites

```bash
pip install ai-slop-detector          # core
pip install "ai-slop-detector[js]"    # optional: JS/TS
pip install "ai-slop-detector[go]"    # optional: Go
```

Verify: `slop-detector --version`

---

## Commands

### /slop — Full Project Scan

```bash
slop-detector --project . --json
```

**Workflow:**
1. Run the command above from the project root
2. Parse JSON: iterate `file_results[]`
3. Group by `status`: CRITICAL_DEFICIT first, then INFLATED_SIGNAL, SUSPICIOUS
4. For each flagged file: report path, deficit_score, top pattern issues, metric warnings
5. Show project aggregate: overall status, avg_ldr, avg_ddc, structural_coherence
6. Propose a prioritized patch plan (see Patch Guidance below)

**Output format:**
```
[SCAN RESULTS]
Project: <path> | Status: <OVERALL> | Files: <N> | Flagged: <M>

CRITICAL_DEFICIT (<count>):
  <file> | score: <X> | patterns: <list> | ldr: <X> ddc: <X>

INFLATED_SIGNAL (<count>):
  ...

Recommended fixes: [ordered list]
```

---

### /slop-file [path] — Single File Analysis

```bash
slop-detector <path> --json
```

**Workflow:**
1. Run on the specified file
2. Report: status, deficit_score, ldr_score, inflation_score, ddc usage_ratio
3. List each pattern issue with severity and line reference if available
4. Explain WHY each metric is flagged (not just the score)
5. Provide concrete fix for each HIGH/CRITICAL pattern

**Explain metrics:**
- `ldr_score < 0.30` -> "Less than 30% of lines are executable logic. Heavy padding or empty stubs."
- `inflation_score > 1.0` -> "Jargon density exceeds threshold. Unjustified quality claims detected."
- `ddc usage_ratio < 0.50` -> "More than half of imported modules are unused. Possible phantom imports."
- `purity < 0.60` -> "Multiple critical patterns detected. AND-gate score pulled down."

---

### /slop-gate — CI Gate Decision

```bash
slop-detector --project . --ci-mode hard --ci-report
```

**Workflow:**
1. Run the command; capture exit code
2. Exit 0 = PASS. Exit non-zero = FAIL.
3. Report: PASS/FAIL, files exceeding threshold, critical pattern counts
4. On FAIL: list blocking files with deficit_score >= 70 or critical_patterns >= 3
5. Suggest minimum fixes required to unblock the gate

**Gate thresholds (hard mode):**
- deficit_score >= 70 -> blocks
- critical_pattern_count >= 3 -> blocks

---

### /slop-spar — Adversarial Validation

```bash
fhval spar
```

Options:
```bash
fhval spar --layer a    # known-pattern anchors
fhval spar --layer b    # metric boundary probes
fhval spar --layer c    # existence probes
```

**Workflow:**
1. Run full 3-layer check
2. Report any calibration drift detected
3. Flag dimensions where metric claims diverge from measured behavior
4. If drift found: recommend `slop-detector . --self-calibrate --apply-calibration`

---

## Status Interpretation

| Status | Score | Action |
|---|---|---|
| `CLEAN` | < 30 | No action needed |
| `SUSPICIOUS` | 30-50 | Review flagged patterns; low urgency |
| `INFLATED_SIGNAL` | 50-70 | Fix before merge; likely AI padding |
| `CRITICAL_DEFICIT` | >= 70 | Block merge; structural issue confirmed |

---

## Patch Guidance — Per Pattern

| Pattern | Fix |
|---|---|
| `not_implemented` / `pass_placeholder` | Implement the function body or remove the stub |
| `phantom_import` | Remove import; if needed, install the actual package |
| `empty_except` | Add specific exception type and handling logic |
| `god_function` | Decompose into focused units (<= 50 lines each) |
| `function_clone_cluster` | Extract shared logic into a single helper |
| `dead_code` | Delete unreachable branches |
| `todo_comment` / `fixme_comment` | Resolve or file a tracked issue; remove inline comment |
| `star_import` | Replace with explicit named imports |
| `placeholder_variable_naming` | Rename single-letter params to descriptive names |
| `return_constant_stub` | Return computed value or raise NotImplementedError |

---

## Scan -> Patch -> Re-scan Loop

```
1. /slop               -- baseline scan; identify top offenders
2. Review findings     -- prioritize CRITICAL_DEFICIT files
3. Apply patches       -- use Patch Guidance above
4. /slop-file <path>   -- verify each patched file
5. /slop               -- confirm project aggregate improved
6. /slop-gate          -- gate decision before merge
```

**Delta reporting:** After re-scan, compare `deficit_score` before vs. after for each patched file. Report improvement or regression.

---

## Self-Calibration (when scores seem off)

```bash
slop-detector . --self-calibrate               # preview recommended weights
slop-detector . --self-calibrate --apply-calibration  # write to .slopconfig.yaml
```

Triggers automatically after 10 re-scanned files per project. Domain-anchored (+-0.15 from profile baseline). Use when false-positive rate feels high for your project type.

---

## Domain Profiles

```bash
slop-detector --init                        # auto-detect domain
slop-detector --init --domain data_science  # explicit override
```

Profiles: `general`, `web_frontend`, `data_science`, `cli_tool`, `library`, `ml_research`, `backend_api`, `scientific`

---

## Scoring Model Reference

```
purity        = exp(-0.5 x n_critical_patterns)
GQG           = exp( sum(w_i * ln(dim_i)) / total_w )   -- weighted geometric mean
deficit_score = 100 * (1 - GQG) + pattern_penalty
total_w       = w_ldr + w_inflation + w_ddc + w_purity  -- self-normalizing
```

Default weights: `ldr=0.40, inflation=0.30, ddc=0.30, purity=0.10` (sum=1.10; normalized by total_w)
Project aggregation: `0.6 * min + 0.4 * mean` (SR9 conservative)
