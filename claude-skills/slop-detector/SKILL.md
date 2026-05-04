---
name: slop-detector
description: Structural risk scanner for AI-assisted code using AI-SLOP Detector CLI. Triggers on /slop (full project scan), /slop-file [path] (single file), /slop-gate (CI hard gate), /slop-delta (before/after comparison), /slop-spar (adversarial validation). Interprets findings, prioritizes fixes, and drives the scan -> diagnose -> patch -> re-scan -> gate -> calibrate quality loop. Use when asked to check code quality, detect AI slop, validate imports, review structural integrity, or run a quality gate on Python/JS/Go files.
---

# AI-SLOP Detector Skill

Structural risk scanner for AI-assisted code. Runs `slop-detector` CLI commands, interprets 4D scoring output (LDR + ICR + DDC + Purity), and drives the `scan -> diagnose -> patch -> re-scan -> gate -> calibrate` quality loop.

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
- **Developer-driven loop.** The `scan → diagnose → patch → re-scan → gate → calibrate` cycle is human-led. The developer reviews structured evidence, decides what to fix, and directs the AI on the patch. AI measures; the human judges.
- **Objective metrics.** LDR counts executable lines (AST). DDC resolves imports (`importlib.util.find_spec`). Cyclomatic complexity is computed by `radon`. These are structural facts, not stylistic preferences.
- **Human-grounded calibration.** Self-calibration derives ground truth from human edit behavior (git commits), not AI judgment.
- **Auditable at every layer.** `--json` exposes the full evidence chain. Nothing is a black box.

---

## Execution Model: 3-Phase Pipeline

Every `/slop` command executes in three phases. Never skip to Phase 3 without completing Phase 1 and 2.

```
Phase 1 — Triage      (classify all files; surface CRITICAL instantly)
Phase 2 — Deep-Dive   (explain WHY; only for files requiring action)
Phase 3 — Action Plan (ordered fixes; explicit next step)
```

**Confidence Routing** (determines Phase 2 depth):

| Status | Score | Phase 2 action |
|---|---|---|
| `CRITICAL_DEFICIT` | ≥ 70 | Immediate — explain all issues, full patch guidance |
| `INFLATED_SIGNAL` | 50–70 | Full deep-dive — action required before merge |
| `SUSPICIOUS` | 30–50 | Run `/slop-file` on top 2 files first; confirm before escalating |
| `DEPENDENCY_NOISE` | varies | Audit DDC section only — `/slop-file` with `--json` |
| `CLEAN` | < 30 | Skip Phase 2 — report clean, propose gate |

Store the Phase 1 triage table in session context as the **baseline** for `/slop-delta` comparison later.

---

## Commands

### /slop — Full Project Scan

```bash
slop-detector --project . --json
```

**Phase 1 — Triage (always show first):**

Parse JSON → build triage table sorted by `deficit_score` descending:

```
[TRIAGE]
File                    │ Score │ Status            │ Top Issue
────────────────────────┼───────┼───────────────────┼──────────────────
cli_commands.py         │  45.2 │ SUSPICIOUS        │ empty_except
ddc.py                  │  38.1 │ SUSPICIOUS        │ lint_escape
────────────────────────┴───────┴───────────────────┴──────────────────
Project: SUSPICIOUS  avg=12.4  14 files  2 flagged  Gate track: PASS
```

**Phase 2 — Deep-Dive (per Confidence Routing above):**

For each file requiring action, explain:
1. WHY the score is what it is — metric breakdown (LDR X%, DDC Y%, purity Z%)
2. Each pattern issue with line reference, severity, and concrete fix from Patch Guidance
3. SUSPICIOUS files: run `/slop-file <file>` inline before including in action list

**Phase 3 — Action Plan:**

```
[ACTION PLAN]
1. cli_commands.py L215 — empty_except → add specific exception + debug log
2. ddc.py L160 — lint_escape FP → (confirmed SUSPICIOUS; monitor, not block)
Gate readiness: project avg 12.4 → target < 30 for CLEAN
```

**→ Next:** apply top fix, then `/slop-file <highest-score-file>` to verify, then `/slop-delta`

---

### /slop-file [path] — Single File Analysis

```bash
slop-detector <path> --json
```

**Phase 1 — Triage:**
Report: status, deficit_score, LDR / Inflation / DDC / Purity in one line.

**Phase 2 — Deep-Dive:**
For each pattern issue:
- Severity, line reference, and WHY it triggered
- Concrete fix (see Patch Guidance)

Metric explanation thresholds:
- `ldr_score < 0.30` → "Less than 30% of lines are executable logic. Heavy padding or empty stubs."
- `inflation_score > 1.0` → "Jargon density exceeds threshold. Unjustified quality claims detected."
- `ddc usage_ratio < 0.50` → "CRITICAL: More than half of imported modules are unused. Possible phantom imports."
- `ddc usage_ratio < 0.70` → "WARNING: Low import usage detected."
- `purity < 0.60` → "Multiple critical patterns detected. AND-gate score pulled down."

**Phase 3 — Action Plan:**
List fixes in priority order (CRITICAL → HIGH → MEDIUM). One concrete action per issue.

**→ Next:** apply fixes → `/slop-file <path>` again → compare score → if clean, proceed to `/slop-gate`

---

### /slop-gate — Gate Decision

Two distinct gate paths — choose based on context:

**Path A: SNP Gate (sr9/di2/jsd/ove metrics)**
```bash
slop-detector <file_or_dir> --gate
```
Produces a formal `SlopGateDecision`. Metrics: `sr9` (LDR), `di2` (DDC ratio), `jsd` (1-inflation), `ove` (1-penalty/50).
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
Exit 0 = PASS, non-zero = FAIL.

FAIL thresholds (hard mode — any one triggers failure):
- `deficit_score >= 70`
- `critical_pattern_count >= 3`
- `inflation_score >= 1.5`
- `ddc usage_ratio < 0.50`

**Workflow:**
1. Run command; capture exit code / decision field
2. Report: PASS/FAIL, blocking files, critical pattern counts
3. On FAIL/HALT: list offending files with key metric and minimum fix to unblock
4. On PASS: confirm gate cleared, ready to merge

**→ Next:** PASS → merge | FAIL → fix blocking files → `/slop-file <blocking>` → re-run gate

---

### /slop-delta — Before/After Comparison

Run after patches to measure improvement against the session baseline (Phase 1 triage stored earlier).

```bash
slop-detector --project . --json   # re-scan after patches
```

Compare each file's current `deficit_score` against the baseline triage:

```
[DELTA]
File                    │ Before │ After  │ Change  │ Result
────────────────────────┼────────┼────────┼─────────┼────────────
cli_commands.py         │   45.2 │   22.1 │  -23.1  │ CLEAN ✓
ddc.py                  │   38.1 │   35.4 │   -2.7  │ SUSPICIOUS
────────────────────────┼────────┼────────┼─────────┼────────────
Project avg             │   12.4 │   10.8 │   -1.6  │ CLEAN ✓
```

Classify each file's outcome: improved / regressed / unchanged.
If any file regressed (score increased), flag immediately and explain possible cause.

**→ Next:** all targets CLEAN → `/slop-gate` | still SUSPICIOUS → `/slop-file <file>` → repeat

---

### /slop-spar — Adversarial Validation

> **External dependency:** `fhval` is a separate Flamehaven validation tool — NOT included in `ai-slop-detector`.

```bash
fhval spar
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

**→ Next:** drift detected → self-calibrate → re-run `/slop` with new weights

---

## Status Interpretation

**File-level status:**

| Status | Score | Action |
|---|---|---|
| `CLEAN` | < 30 | No action needed — report clean |
| `SUSPICIOUS` | 30–50 | Second-pass `/slop-file`; confirm before escalating |
| `INFLATED_SIGNAL` | 50–70 | Fix before merge; likely AI padding |
| `DEPENDENCY_NOISE` | varies | DDC < 20% with clean patterns; audit imports |
| `CRITICAL_DEFICIT` | ≥ 70 | Block merge; fix now |

**DDC threshold zones:**

| DDC usage_ratio | Effect |
|---|---|
| < 0.20 | `DEPENDENCY_NOISE` (if no critical patterns AND inflation ≤ 1.0) |
| < 0.50 | `CRITICAL` warning; CIGate HARD mode FAIL |
| < 0.70 | `WARNING`; no gate action |

**Project-level status** (`weighted_deficit_score = 0.6 * min + 0.4 * mean`):

| Status | Threshold |
|---|---|
| `CLEAN` | < 30 |
| `SUSPICIOUS` | 30–50 |
| `CRITICAL_DEFICIT` | ≥ 50 |

---

## Patch Guidance — Per Pattern

| Pattern | Fix |
|---|---|
| `not_implemented` / `pass_placeholder` | Implement the function body or remove the stub |
| `phantom_import` | Remove import; if needed, install the actual package |
| `empty_except` | Add specific exception type and handling logic |
| `god_function` | Decompose into focused units (≤ 50 lines each) |
| `function_clone_cluster` | Extract shared logic into a single helper |
| `dead_code` | Delete unreachable branches |
| `todo_comment` / `fixme_comment` | Resolve or file a tracked issue; remove inline comment |
| `star_import` | Replace with explicit named imports |
| `placeholder_variable_naming` | Rename single-letter params to descriptive names |
| `return_constant_stub` | Return computed value or raise NotImplementedError |
| `lint_escape` | Fix underlying lint error; if suppression unavoidable, add `# noqa: CODE` |

---

## Scan → Diagnose → Patch → Re-scan → Gate → Calibrate Loop

```
Step 1  /slop              scan:     3-Phase baseline; store triage as session baseline
Step 2  Review Phase 2     diagnose: explain each metric; prioritize CRITICAL_DEFICIT
Step 3  Apply patches      patch:    use Patch Guidance; developer decides what to fix
Step 4  /slop-file <path>  re-scan:  verify each patched file individually
Step 5  /slop-delta        compare:  before/after table; confirm improvement
Step 6  /slop              re-scan:  confirm project aggregate improved
Step 7  /slop-gate         gate:     PASS/FAIL decision before merge
Step 8  (auto) calibrate   calibrate: LEDA registers improvement events; weights auto-tune
```

**Delta rule:** After re-scan (Step 4–5), always report the `deficit_score` change: `before → after (Δ)`. Never say "fixed" without a measured delta.

---

## Self-Calibration (when scores seem off)

```bash
slop-detector . --self-calibrate                       # preview recommended weights
slop-detector . --self-calibrate --apply-calibration   # write to .slopconfig.yaml
```

Two-gate auto-trigger: (1) outer — every 10 multi-run files milestone; (2) inner floor — ≥ 5 improvement events AND ≥ 5 fp_candidate events per class required (insufficient signal returns `insufficient_data`). Domain-anchored (±0.15 from profile baseline).

---

## Domain Profiles

```bash
slop-detector --init                        # auto-detect domain
slop-detector --init --domain data_science  # explicit override
```

Profiles: `general`, `scientific/ml`, `scientific/numerical`, `web/api`, `library/sdk`, `cli/tool`, `bio`, `finance`

---

## Additional CLI Options

```bash
slop-detector --project . --emit-leda-yaml                         # LEDA review surface
slop-detector --project . --emit-leda-yaml --leda-profile public   # public redaction
slop-detector src/ --cross-file                                    # dependency + clone graph
slop-detector src/ --governance                                    # CR-EP session artifacts
slop-detector --project . --json   # ml_score present when ≥10 history runs
```

---

## Scoring Model Reference

```
purity        = exp(-0.5 × n_critical_patterns)
GQG           = exp( Σ(w_i × ln(max(1e-4, dim_i))) / Σw_i )   -- weighted geometric mean
deficit_score = 100 × (1 - GQG) + pattern_penalty
```

Default weights: `ldr=0.40, inflation=0.30, ddc=0.20, purity=0.10`
Project aggregation: `0.6 × min + 0.4 × mean` (SR9 conservative)
