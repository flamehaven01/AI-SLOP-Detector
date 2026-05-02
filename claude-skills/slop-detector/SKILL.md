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

## Philosophy: Breaking the Self-Referential Bias

> *The problem isn't that AI writes code. The problem is the specific class of defects AI reliably introduces: unimplemented stubs, disconnected pipelines, phantom imports, and buzzword-heavy noise. The code speaks for itself.*

A common critique of using AI to fix AI-generated code is **self-referential bias**: doesn't the AI just validate its own preferences? To break this loop, AI-SLOP Detector is designed strictly as a **diagnostic instrument**, not an autonomous code generator. The developer and AI collaborate, but the human remains the oracle.

- **Evidence, not opinion.** All findings are backed by mathematical evidence: JSON output includes line numbers, AST-derived metrics, and formula derivation. Every score answers "why?" — LDR contributed X%, DDC Y%, purity Z%, pattern_penalty W points.
- **Developer-driven loop.** The `scan → patch → re-scan → gate` cycle is human-led. The developer reviews structured evidence, decides what to fix, and directs the AI on the patch. AI measures; the human judges.
- **Objective metrics.** LDR counts executable lines (AST). DDC resolves imports (`importlib.util.find_spec`). Cyclomatic complexity is computed by `radon`. These are structural facts, not stylistic preferences. AI cannot "hallucinate" its way out of a 300-line function with a complexity of 45.
- **Human-grounded calibration.** Self-calibration derives ground truth from human edit behavior (git commits), not AI judgment. A file the human fixes = improvement event. A flag the human ignores = false-positive candidate. The human's actions are the true anchor.
- **Auditable at every layer.** `--json` exposes the full evidence chain. `--self-calibrate` reports per-rule FP rates with confidence gaps. `--emit-leda-yaml` produces a review surface with redaction profiles. Nothing is a black box.


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
- `ddc usage_ratio < 0.50` -> "CRITICAL: More than half of imported modules are unused. Possible phantom imports."
- `ddc usage_ratio < 0.70` -> "WARNING: Low import usage detected."
- `purity < 0.60` -> "Multiple critical patterns detected. AND-gate score pulled down."

---

### /slop-gate — Gate Decision

Two distinct gate paths — choose based on context:

**Path A: SNP Gate (sr9/di2/jsd/ove metrics)**
```bash
slop-detector <file_or_dir> --gate
```
Produces a formal `SlopGateDecision` compatible with supreme-nexus-pipeline.
Metrics: `sr9` (LDR), `di2` (DDC ratio), `jsd` (1-inflation), `ove` (1-penalty/50).
Decision: `PASS` or `HALT`.

HALT thresholds:
- `ldr_score < 0.60`
- `ddc_ratio < 0.50`
- `inflation_score > 1.5`
- `pattern_penalty > 30.0`

**Path B: CI Hard Gate (deficit_score / pattern count)**
```bash
slop-detector --project . --ci-mode hard --ci-report
```
Standard CI integration gate. Exit 0 = PASS, non-zero = FAIL.

FAIL thresholds (hard mode — any one triggers failure):
- `deficit_score >= 70`
- `critical_pattern_count >= 3`
- `inflation_score >= 1.5`
- `ddc usage_ratio < 0.50`

**Workflow (either path):**
1. Run the command; capture exit code / decision field
2. Report: PASS/FAIL, blocking files, critical pattern counts
3. On FAIL/HALT: list offending files with their key metric
4. Suggest minimum fixes required to unblock

---

### /slop-spar — Adversarial Validation

> **External dependency:** `fhval` is a separate Flamehaven validation tool — NOT included in `ai-slop-detector`.
> Install separately before using this command.

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
1. Confirm `fhval` is installed (`fhval --version`)
2. Run full 3-layer check
3. Report any calibration drift detected
4. Flag dimensions where metric claims diverge from measured behavior
5. If drift found: recommend `slop-detector . --self-calibrate --apply-calibration`

---

## Status Interpretation

**File-level status** (per-file `deficit_score`):

| Status | Score | Trigger | Action |
|---|---|---|---|
| `CLEAN` | < 30 | — | No action needed |
| `SUSPICIOUS` | 30-50 | deficit or >= 5 critical patterns | Review flagged patterns; low urgency |
| `INFLATED_SIGNAL` | 50-70 | deficit primary | Fix before merge; likely AI padding |
| `DEPENDENCY_NOISE` | varies | DDC < 20% AND no critical patterns AND inflation <= 1.0 | Audit imports; remove phantom or unused deps |
| `CRITICAL_DEFICIT` | >= 70 | deficit primary | Block merge; structural issue confirmed |

> `DEPENDENCY_NOISE` overrides score-based status when DDC is the dominant failure axis. Score alone does not surface this class.

**DDC threshold zones** (three distinct bands — not to be confused):

| DDC usage_ratio | Effect |
|---|---|
| < 0.20 | `DEPENDENCY_NOISE` status (if no critical patterns AND inflation ≤ 1.0) |
| < 0.50 | `CRITICAL` warning in file output; CIGate HARD mode FAIL |
| < 0.70 | `WARNING` in file output; no gate action |

> A file in the 0.20–0.50 band gets a CRITICAL warning and can fail CI, but does NOT become `DEPENDENCY_NOISE` (because other failure modes may be dominant). A file below 0.20 with clean patterns and low inflation IS reclassified to `DEPENDENCY_NOISE`.

**Project-level status** (per-project `weighted_deficit_score = 0.6 * min + 0.4 * mean`):

| Status | Threshold | Note |
|---|---|---|
| `CLEAN` | < 30 | |
| `SUSPICIOUS` | 30-50 | |
| `CRITICAL_DEFICIT` | >= 50 | Lower than file-level threshold — aggregate penalizes distribution |

> `INFLATED_SIGNAL` and `DEPENDENCY_NOISE` are **file-level only**. Project-level status has three states: CLEAN / SUSPICIOUS / CRITICAL_DEFICIT.

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

Triggers automatically after **5 improvement events + 5 false-positive candidate events** (10 total, per-class balanced). An improvement event is recorded when a file's score improves after a fix; an fp_candidate event when a flagged file is not fixed (user signal). Domain-anchored (+-0.15 from profile baseline). Use when false-positive rate feels high for your project type.

---

## Domain Profiles

```bash
slop-detector --init                        # auto-detect domain
slop-detector --init --domain data_science  # explicit override
```

Profiles (use exact key strings):
`general`, `scientific/ml`, `scientific/numerical`, `web/api`, `library/sdk`, `cli/tool`, `bio`, `finance`

`domain_overrides` in `.slopconfig.yaml` configures **per-function pattern exemptions** (not metric thresholds):
```yaml
patterns:
  god_function:
    domain_overrides:
      - function_pattern: "validate_*"
        complexity_threshold: 20
        lines_threshold: 100
```

---

## Additional CLI Options

```bash
# LEDA injection (SPAR-adjacent review surface)
slop-detector --project . --emit-leda-yaml
slop-detector --project . --emit-leda-yaml --leda-output reports/leda.yaml --leda-profile public
# --leda-profile choices: internal | restricted | public (default: restricted)

# Cross-file analysis (dependency graph + clone clusters across files)
slop-detector src/ --cross-file

# Governance artifacts (CR-EP session output)
slop-detector src/ --governance

# ML score (requires history: run >= 10 times to accumulate)
slop-detector --project . --json   # field: ml_score in output when history present
```

---

## Scoring Model Reference

```
purity        = exp(-0.5 x n_critical_patterns)
GQG           = exp( sum(w_i * ln(dim_i)) / total_w )   -- weighted geometric mean
deficit_score = 100 * (1 - GQG) + pattern_penalty
total_w       = w_ldr + w_inflation + w_ddc + w_purity  -- self-normalizing
```

Default weights: `ldr=0.40, inflation=0.30, ddc=0.20, purity=0.10` (sum=1.00; normalized by total_w)
Project aggregation: `0.6 * min + 0.4 * mean` (SR9 conservative)
