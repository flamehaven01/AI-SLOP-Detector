# Claude Code Skill — AI-SLOP Detector

Integrates AI-SLOP Detector into Claude Code as a persistent quality-control loop:
`scan → diagnose → patch → re-scan → gate → calibrate`.

---

## Why a Skill Instead of a Raw CLI

Running `slop-detector` directly gives you raw JSON and CLI output.
The skill adds the missing layer:

| Raw CLI | With Skill |
|---|---|
| Raw JSON / text output | Interpreted findings with per-pattern explanations |
| Single-shot execution | Stateful scan → diagnose → patch → re-scan → gate → calibrate loop |
| No fix guidance | Per-pattern patch suggestions with priority ordering |
| No context carry-over | Triage baseline held as session context for delta tracking |
| Manual gate decision | Explicit PASS/FAIL with blocking file list and minimum fix to unblock |

> "It felt like the missing piece in my workflow — code quality tightened up almost immediately."
>
> A real user integrated AI-SLOP Detector into Claude Code as a skill and reported:
> context burn dropped, review criteria held across sessions, and code quality improved immediately.
> The win was not that the agent became smarter — it was that the review loop stopped drifting.

---

## Philosophy: Breaking the Self-Referential Bias

> *The problem isn't that AI writes code. The problem is the specific class of defects AI reliably introduces: unimplemented stubs, disconnected pipelines, phantom imports, and buzzword-heavy noise. The code speaks for itself.*

A common critique of using AI to fix AI-generated code is **self-referential bias**: doesn't the AI just validate its own preferences? To break this loop, AI-SLOP Detector is designed strictly as a **diagnostic instrument**, not an autonomous code generator. The developer and AI collaborate, but the human remains the oracle.

- **Evidence, not opinion.** All findings are backed by mathematical evidence: JSON output includes line numbers, AST-derived metrics, and formula derivation. Every score answers "why?"
- **Developer-driven loop.** The `scan → diagnose → patch → re-scan → gate → calibrate` cycle is human-led. The developer reviews structured evidence, decides what to fix, and directs the AI on the patch. AI measures; the human judges.
- **Objective metrics.** LDR counts executable lines (AST). DDC resolves imports (`importlib.util.find_spec`). Cyclomatic complexity is computed by `radon`. These are structural facts, not stylistic preferences.
- **Human-grounded calibration.** Self-calibration derives ground truth from human edit behavior (git commits), not AI judgment. A file the human fixes = improvement event. A flag the human ignores = false-positive candidate.

---

## Installation

```bash
# Option A: standard Claude Code skills path
cp -r claude-skills/slop-detector ~/.claude/skills/

# Option B: Claude Code plugin marketplace path
cp -r claude-skills/slop-detector ~/.claude/plugins/marketplaces/anthropics-skills/
```

Restart Claude Code, then verify the skill is loaded:
```
/slop --version   # should show ai-slop-detector 3.x.x
```

**Prerequisites:**
```bash
pip install ai-slop-detector            # core
pip install "ai-slop-detector[js]"      # optional: JS/TS support
pip install "ai-slop-detector[go]"      # optional: Go support
```

---

## Execution Model: 3-Phase Pipeline

Every `/slop` command runs in three phases. **Never skip to Phase 3 without completing Phases 1 and 2.**

```
Phase 1 — Triage      classify all files; surface CRITICAL instantly
Phase 2 — Deep-Dive   explain WHY; only for files requiring action
Phase 3 — Action Plan ordered fixes; explicit → Next: step
```

### Confidence Routing

Phase 2 depth is determined by the file's status band:

| Status | Score | Phase 2 action |
|---|---|---|
| `CRITICAL_DEFICIT` | ≥ 70 | Immediate — explain all issues, full patch guidance |
| `INFLATED_SIGNAL` | 50–70 | Full deep-dive — action required before merge |
| `SUSPICIOUS` | 30–50 | Run `/slop-file` on top 2 files first; confirm before escalating |
| `DEPENDENCY_NOISE` | varies | Audit DDC section only — `/slop-file` with `--json` |
| `CLEAN` | < 30 | Skip Phase 2 — report clean, propose gate |

The Phase 1 triage table is stored as the **session baseline** for `/slop-delta` comparisons.

---

## Commands

### `/slop` — Full Project Scan

```bash
slop-detector --project . --json
```

**Phase 1 — Triage (always shown first):**

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

**Phase 2 — Deep-Dive (per Confidence Routing):**

For each file requiring action:
1. WHY the score is what it is — metric breakdown (LDR X%, DDC Y%, purity Z%)
2. Each pattern with line reference, severity, and concrete fix from the Patch Reference
3. SUSPICIOUS files: run `/slop-file <file>` inline before including in the action list

**Phase 3 — Action Plan:**

```
[ACTION PLAN]
1. cli_commands.py L215 — empty_except → add specific exception + debug log
2. ddc.py L160 — lint_escape (confirmed FP) → monitor, not block
Gate readiness: project avg 12.4 → target < 30 for CLEAN
```

**→ Next:** apply top fix → `/slop-file <highest-score-file>` to verify → `/slop-delta`

---

### `/slop-file [path]` — Single File Analysis

```bash
slop-detector <path> --json
```

**Phase 1 — Triage:**
Report: status, deficit_score, LDR / Inflation / DDC / Purity in one line.

**Phase 2 — Deep-Dive:**
For each pattern issue: severity, line reference, WHY it triggered, concrete fix.

**Metric explanation thresholds:**

| Condition | Meaning |
|---|---|
| `ldr_score < 0.30` | Less than 30% of lines are executable logic — heavy padding or empty stubs |
| `ldr_score < 0.60` | Low logic density — likely AI-generated boilerplate |
| `inflation_score > 1.0` | Jargon density exceeds threshold — unjustified quality claims |
| `ddc usage_ratio < 0.50` | CRITICAL: over half of imported modules unused — possible phantom imports |
| `ddc usage_ratio < 0.70` | WARNING: low import usage detected |
| `purity < 0.60` | Multiple critical patterns — AND-gate score pulled down |

**Phase 3 — Action Plan:**
Fixes in priority order (CRITICAL → HIGH → MEDIUM). One concrete action per issue.

**→ Next:** apply fixes → `/slop-file <path>` again → compare score → if clean, proceed to `/slop-gate`

---

### `/slop-gate` — Gate Decision

Two distinct gate paths — choose based on context:

**Path A: SNP Gate**
```bash
slop-detector <file_or_dir> --gate
```
Produces a formal `SlopGateDecision`. Decision: `PASS` or `HALT`.

HALT thresholds:
- `ldr_score < 0.60`
- `ddc_ratio < 0.50`
- `inflation_score > 1.5`
- `pattern_penalty > 30.0`

**Path B: CI Hard Gate**
```bash
slop-detector --project . --ci-mode hard --ci-report
```
Exit 0 = PASS, non-zero = FAIL.

FAIL thresholds (any one triggers failure):
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

### `/slop-delta` — Before/After Comparison

Run after patches to measure improvement against the session baseline stored in Phase 1.

```bash
slop-detector --project . --json   # re-scan after patches
```

Compare each file's current `deficit_score` against the Phase 1 triage baseline:

```
[DELTA]
File                    │ Before │ After  │ Change  │ Result
────────────────────────┼────────┼────────┼─────────┼────────────
cli_commands.py         │   45.2 │   22.1 │  -23.1  │ CLEAN
ddc.py                  │   38.1 │   35.4 │   -2.7  │ SUSPICIOUS
────────────────────────┼────────┼────────┼─────────┼────────────
Project avg             │   12.4 │   10.8 │   -1.6  │ CLEAN
```

Classify each file: improved / regressed / unchanged. If any file **regressed** (score increased), flag immediately and explain the possible cause.

**Delta rule:** Never say "fixed" without a measured delta. Always report `before → after (Δ)`.

**→ Next:** all targets CLEAN → `/slop-gate` | still SUSPICIOUS → `/slop-file <file>` → repeat

---

### `/slop-spar` — Adversarial Validation

> **External dependency:** `fhval` is a separate Flamehaven validation tool — NOT included in `ai-slop-detector`.

```bash
fhval spar              # full 3-layer check
fhval spar --layer a    # known-pattern ground-truth anchors
fhval spar --layer b    # metric boundary probes
fhval spar --layer c    # existence probes
```

**Workflow:**
1. Confirm `fhval` is installed (`fhval --version`)
2. Run full 3-layer check; report any calibration drift
3. Flag dimensions where metric claims diverge from measured behavior

On drift detected:
```bash
slop-detector . --self-calibrate --apply-calibration
```

**→ Next:** drift detected → self-calibrate → re-run `/slop` with new weights

---

## The Quality Loop

```
Step 1  /slop              scan:     3-Phase baseline; store triage as session baseline
Step 2  Review Phase 2     diagnose: explain each metric; prioritize CRITICAL_DEFICIT
Step 3  Apply patches      patch:    use Patch Reference; developer decides what to fix
Step 4  /slop-file <path>  re-scan:  verify each patched file individually
Step 5  /slop-delta        compare:  before/after table; confirm improvement (delta rule)
Step 6  /slop              re-scan:  confirm project aggregate improved
Step 7  /slop-gate         gate:     PASS/FAIL decision before merge
Step 8  (auto) calibrate   calibrate: LEDA registers improvement events; weights auto-tune
```

**Session persistence:** The Phase 1 triage baseline is held in session context — `/slop-delta` uses it automatically without re-running the initial scan.

---

## Patch Reference

| Pattern | Fix |
|---|---|
| `not_implemented` / `pass_placeholder` | Implement the function body or remove the stub |
| `phantom_import` | Remove import; install the actual package if needed |
| `empty_except` | Replace `except:` with specific exception type + handling + debug log |
| `god_function` | Decompose into focused units (<= 50 lines each) |
| `function_clone_cluster` | Extract shared logic into a single helper |
| `dead_code` | Delete unreachable branches |
| `todo_comment` / `fixme_comment` | Resolve inline or file a tracked issue; remove comment |
| `star_import` | Replace with explicit named imports |
| `placeholder_variable_naming` | Rename single-letter params to descriptive names |
| `return_constant_stub` | Return computed value or raise `NotImplementedError` |
| `bare_except` | Replace with `except Exception as e:` minimum |
| `deep_nesting` | Flatten with early returns or extracted helpers |
| `lint_escape` | Fix underlying lint error; if suppression unavoidable, add `# noqa: CODE` |

---

## Self-Calibration

The scoring weights auto-tune via two gates:
1. Every 10 multi-run files milestone the calibrator fires automatically
2. Weights only update when >= 5 improvement events AND >= 5 fp_candidate events per class have accumulated

```bash
slop-detector . --self-calibrate                      # preview recommendations
slop-detector . --self-calibrate --apply-calibration  # write to .slopconfig.yaml
```

Domain-anchored: grid search stays within +-0.15 of the domain baseline.
Drift warnings fire when any dimension shifts > 0.25 from anchor.

---

## Skill Source

[`claude-skills/slop-detector/SKILL.md`](../claude-skills/slop-detector/SKILL.md)

For the scoring math behind the metrics: [MATH_MODELS.md](MATH_MODELS.md)
For pattern details: [PATTERNS.md](PATTERNS.md)
For CI/CD integration: [CI_CD.md](CI_CD.md)
