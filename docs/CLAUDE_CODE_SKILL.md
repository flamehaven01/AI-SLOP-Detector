# Claude Code Skill — AI-SLOP Detector

Integrates AI-SLOP Detector into Claude Code as a persistent quality-control loop:
`scan -> diagnose -> patch -> re-scan -> gate -> calibrate`.

---

## Why a Skill Instead of a Raw CLI

Running `slop-detector` directly gives you raw JSON and CLI output.
The skill adds the missing layer:

| Raw CLI | With Skill |
|---|---|
| Raw JSON / text output | Interpreted findings with per-pattern explanations |
| Single-shot execution | Stateful scan -> diagnose -> patch -> re-scan -> gate -> calibrate loop |
| No fix guidance | Per-pattern patch suggestions |
| No context carry-over | Review criteria held across sessions |
| Manual gate decision | Explicit PASS/FAIL with blocking file list |

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
- **Objective metrics.** LDR counts executable lines (AST). DDC resolves imports (`importlib.util.find_spec`). Cyclomatic complexity is computed by `radon`. These are structural facts, not stylistic preferences. AI cannot "hallucinate" its way out of a 300-line function with a complexity of 45.
- **Human-grounded calibration.** Self-calibration derives ground truth from human edit behavior (git commits), not AI judgment. A file the human fixes = improvement event. A flag the human ignores = false-positive candidate. The human's actions are the true anchor.

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

## Commands

### `/slop` — Full Project Scan

Runs `slop-detector --project . --json`, interprets all findings, and produces a prioritized action plan.

**Output:**
```
[SCAN RESULTS]
Project: ./  |  Status: CLEAN  |  Files: 51  |  Flagged: 7

CRITICAL_DEFICIT (2):
  cli_commands.py  score=81.3  patterns: [god_function, dead_code]  ldr=0.42 ddc=0.99
  ddc.py           score=78.3  patterns: [not_implemented]          ldr=0.38 ddc=0.97

SUSPICIOUS (5):
  cross_file.py    score=42.1  ...
  ...

Recommended fixes: [ordered by impact]
1. cli_commands.py — god_function: decompose into focused units
2. ddc.py — not_implemented: implement stub or remove
```

---

### `/slop-file [path]` — Single File Analysis

Runs `slop-detector <path> --json`. Reports status, all four metric scores, and per-pattern fix guidance.

**Metric explanations:**

| Condition | Meaning |
|---|---|
| `ldr_score < 0.30` | Less than 30% of lines are executable logic — heavy padding or empty stubs |
| `ldr_score < 0.60` | Low logic density — likely AI-generated boilerplate |
| `inflation_score > 1.0` | Jargon density exceeds threshold — unjustified quality claims |
| `ddc usage_ratio < 0.50` | Over half of imported modules unused — possible phantom imports |
| `purity < 0.60` | Multiple critical patterns — AND-gate score pulled down |

**Example:**
```
/slop-file src/pipeline.py

[FILE] src/pipeline.py
Status: INFLATED_SIGNAL  |  deficit_score: 52.4
LDR: 0.41  Inflation: 1.2  DDC: 0.94  Purity: 0.61

Patterns:
  [HIGH]     todo_comment        x3  — resolve or file a tracked issue
  [CRITICAL] phantom_import      x1  — remove or install the actual package
  [MEDIUM]   deep_nesting        x1  — flatten with early returns
```

---

### `/slop-gate` — CI Gate Decision

Runs `slop-detector --project . --ci-mode hard --ci-report`. Returns explicit PASS or FAIL.

**Gate thresholds (hard mode):**
- `deficit_score >= 70` on any file → FAIL
- `critical_pattern_count >= 3` on any file → FAIL
- `inflation_score >= 1.5` on any file → FAIL
- `ddc_usage_ratio < 0.50` on any file → FAIL

**Output:**
```
[GATE] HARD — FAIL

Blocking files:
  cli_commands.py  score=81.3  (threshold: 70)
  ddc.py           score=78.3  (threshold: 70)

Minimum fixes to unblock:
  1. cli_commands.py: reduce god_function (currently 148 lines, threshold 60)
  2. ddc.py: implement 3 not_implemented stubs
```

Other modes: `--ci-mode soft` (informational, never fails) · `--ci-mode quarantine` (escalates repeat offenders)

---

### `/slop-spar` — Adversarial Validation

Runs `fhval spar`. Verifies that each metric measures what it claims — catches calibration drift before it reaches production.

```bash
fhval spar              # full 3-layer check
fhval spar --layer a    # known-pattern ground-truth anchors
fhval spar --layer b    # peer challenge probes
fhval spar --layer c    # existence probes
```

**Score interpretation:**

| SPAR Score | Grade | Action |
|---|---|---|
| >= 80 | PASS | Calibration healthy |
| 60-79 | WARN | Review blind spots |
| < 60 | FAIL | Run self-calibration |

On FAIL or anomalies detected:
```bash
slop-detector . --self-calibrate --apply-calibration
```

---

## The Quality Loop

```
1. /slop                  scan: baseline scan — identify top offenders
2. review findings        diagnose: explain each metric, prioritize CRITICAL_DEFICIT files
3. apply patches          patch: use per-pattern fix guidance; human decides what to fix
4. /slop-file <path>      re-scan: verify each patched file individually
5. /slop                  re-scan: confirm project aggregate improved
6. /slop-gate             gate: PASS/FAIL decision before merge
7. (auto) calibrate       calibrate: LEDA registers improvement events; weights auto-tune at milestone
```

**Delta tracking:** After re-scan, the skill compares `deficit_score` before vs. after for each patched file and reports the delta.

**Session persistence:** Review criteria (patterns, thresholds, gate mode) are encoded in the skill layer — not in the prompt. They hold across sessions without re-explanation.

---

## Patch Reference

| Pattern | Fix |
|---|---|
| `not_implemented` / `pass_placeholder` | Implement the function body or remove the stub |
| `phantom_import` | Remove import; install the actual package if needed |
| `empty_except` | Replace `except:` with specific exception type + handling |
| `god_function` | Decompose into focused units (<= 50 lines each) |
| `function_clone_cluster` | Extract shared logic into a single helper |
| `dead_code` | Delete unreachable branches |
| `todo_comment` / `fixme_comment` | Resolve inline or file a tracked issue |
| `star_import` | Replace with explicit named imports |
| `placeholder_variable_naming` | Rename single-letter params to descriptive names |
| `return_constant_stub` | Return computed value or raise `NotImplementedError` |
| `bare_except` | Replace with `except Exception as e:` minimum |
| `deep_nesting` | Flatten with early returns or extracted helpers |
| `lint_escape` | Remove `# noqa` suppression; fix the underlying issue |

---

## Self-Calibration

The skill's scoring weights auto-tune via two gates: (1) every 10 multi-run files milestone the calibrator fires automatically; (2) weights only update when >= 5 improvement events AND >= 5 fp_candidate events have accumulated per class — insufficient signal returns `insufficient_data` without changing anything.
To manually trigger or inspect:

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
