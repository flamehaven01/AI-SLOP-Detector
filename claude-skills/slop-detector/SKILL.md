---
name: slop-detector
description: Structural review skill for AI-SLOP Detector. Use when asked to review AI-assisted code, inspect changed-code risk, prioritize structural hotspots, plan cleanup, verify governance, or run MCP/JSON-first workflows. Prefer the canonical CLI surfaces: scan, review, pulse, sweep, explain, verify-governance, and mcp. Treat review/pulse/sweep as the primary agent-facing surfaces; use scan for full baseline analysis.
---

# AI-SLOP Detector Skill

Use AI-SLOP Detector as a **structured review loop**, not as a last-minute lint
step.

The preferred flow is:

1. generate or edit code
2. run a structured review in JSON
3. inspect evidence and action classes
4. apply only bounded fixes
5. re-run review / health / cleanup
6. hand the result to a human with evidence

---

## Install

Python core:

```bash
pip install ai-slop-detector
pip install "ai-slop-detector[js]"   # optional JS/TS support
pip install "ai-slop-detector[go]"   # optional Go support
```

Optional Node-first wrapper:

```bash
npm install --save-dev ai-slop-detector
```

Verify:

```bash
slop-detector --version
npx ai-slop-detector --version
```

---

## Command Selection

Use the smallest surface that matches the job.

### `scan`

```bash
slop-detector scan . --format json
```

Use when you need:
- full single-file or project analysis
- baseline structural metrics
- complete pattern output

### `review`

```bash
slop-detector review . --format json
```

Use when you need:
- changed-code review
- introduced vs inherited attribution
- build/pass-fail guidance

Inspect first:
- `verdict`
- `should_fail_build`
- `attribution`
- `targets`
- `actions`
- `findings`

### `pulse`

```bash
slop-detector pulse . --format json
```

Use when you need:
- health summary
- hotspot prioritization
- next repair order

Inspect first:
- `summary`
- `targets`
- `signals`

### `sweep <family>`

```bash
slop-detector sweep dead-code . --format json
slop-detector sweep dupes . --format json
slop-detector sweep unused-deps . --format json
slop-detector sweep stale-suppressions . --format json
slop-detector sweep boundary-violations . --format json
```

Use when you need cleanup planning with:
- `issues`
- `confidence`
- `action_class`
- `evidence`

### `explain`

```bash
slop-detector explain empty_except --format json
```

Use when you need mitigation guidance for a pattern or finding.

### `verify-governance`

```bash
slop-detector verify-governance ./.cr-ep
```

Use when governance artifacts, not score output, are the enforcement boundary.

### `mcp`

```bash
slop-detector mcp
```

Use when the host tool already speaks MCP and wants the structured tool surface
directly.

---

## Recommended Agent Loop

### 1. Run changed-code review first

```bash
slop-detector review . --format json
```

If the task is PR-like or patch-like, this is the default entry point.

### 2. Inspect only bounded evidence

Safe agent targets:
- unused imports
- obvious duplicate functions
- placeholder branches
- stale suppressions

Unsafe without human confirmation:
- deleting `needs_review` cleanup findings automatically
- changing architecture boundaries
- removing high-churn files solely from cleanup heuristics

### 3. Use cleanup families intentionally

If review points at a cleanup class, run the narrow family:

```bash
slop-detector sweep dupes . --format json
slop-detector sweep dead-code . --format json
slop-detector sweep unused-deps . --format json
```

Do not treat `confidence` as permission. It is prioritization guidance.

### 4. Re-run health after edits

```bash
slop-detector pulse . --format json
```

Confirm that the hotspot moved, the score improved, or the finding count dropped.

### 5. Escalate with evidence

Human handoff should include:
- what changed
- what command was run
- what verdict / score / issue count changed
- what remains unfixed
- what the agent deliberately did **not** change

---

## Programmatic Node Surface

```ts
import {
  scanProject,
  reviewChanges,
  computeHealth,
  runCleanupFamily,
} from "ai-slop-detector";
```

Typed contracts:

```ts
import type {
  ScanOutput,
  ReviewOutput,
  HealthOutput,
  CleanupOutput,
} from "ai-slop-detector/types";
```

---

## Legacy Note

Older skill revisions used a `/slop`, `/slop-file`, `/slop-gate`, `/slop-delta`,
and `/slop-spar` framing. Those names are historical. Prefer the canonical
product surfaces:

- `scan`
- `review`
- `pulse`
- `sweep`
- `explain`
- `verify-governance`
- `mcp`

If a host environment adds slash aliases, they should delegate to those canonical
commands rather than documenting a separate behavior model.
