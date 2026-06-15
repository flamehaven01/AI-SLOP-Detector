# Claude Code Skill — AI-SLOP Detector

This document explains how to use AI-SLOP Detector as a Claude Code skill
without drifting into an older, pre-canonical CLI model.

The skill is most useful when it is treated as a **JSON-first structural review
loop**:

`generate/edit -> review -> inspect evidence -> apply bounded fixes -> pulse/sweep -> human handoff`

---

## Why Use the Skill

Running the CLI directly gives you raw text or JSON.

The skill adds the missing workflow layer:

| Raw CLI | With Skill |
|---|---|
| Raw output | Interpreted review loop |
| Single-shot execution | Re-run discipline after each patch |
| No fix boundary | Safe vs unsafe fix guidance |
| No prioritization advice | `review`, `pulse`, and `sweep` routed by job type |
| Easy to overreach | Explicit human handoff boundary |

This is the main value: the skill keeps the agent from treating static-analysis
output as permission for blind edits.

---

## Install

Skill files:

```bash
cp -r claude-skills/slop-detector ~/.claude/skills/
```

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

## Canonical Command Surface

The preferred stable CLI surface is:

```bash
slop-detector scan <target>
slop-detector review <target>
slop-detector pulse <target>
slop-detector sweep <family> <target>
slop-detector explain <identifier>
slop-detector verify-governance <target>
slop-detector mcp
```

Legacy forms such as `--project`, `audit`, `health`, or historical `/slop*`
framing may still appear in older docs, but they are not the preferred model for
new agent workflows.

---

## Recommended Agent Loop

### 1. Start with `review` for changed-code work

```bash
slop-detector review . --format json
```

Inspect first:
- `verdict`
- `should_fail_build`
- `attribution`
- `targets`
- `actions`
- `findings`

Use this when the task is:
- PR review
- patch validation
- “did my change make things worse?”

### 2. Use `pulse` for prioritization

```bash
slop-detector pulse . --format json
```

Inspect first:
- `summary`
- `targets`
- `signals`

Use this when the task is:
- backlog prioritization
- hotspot targeting
- deciding what to fix next

### 3. Use `sweep` for bounded cleanup planning

```bash
slop-detector sweep dead-code . --format json
slop-detector sweep dupes . --format json
slop-detector sweep unused-deps . --format json
slop-detector sweep stale-suppressions . --format json
slop-detector sweep boundary-violations . --format json
```

Inspect:
- `issues`
- `confidence`
- `action_class`
- `evidence`

Use this when the task is:
- staged cleanup
- dependency hygiene
- duplicate reduction
- boundary review

### 4. Use `scan` only when you need the full baseline

```bash
slop-detector scan . --format json
```

Use this when the task is:
- first-pass baseline analysis
- single-file investigation
- “show me everything” debugging

### 5. Re-run after changes

Never claim improvement without a second run:

```bash
slop-detector review . --format json
slop-detector pulse . --format json
```

The skill should treat the second run as required evidence, not optional polish.

---

## Safe vs Unsafe Fix Boundaries

Safe agent targets:
- remove unused imports
- reduce obvious duplicate functions
- simplify placeholder-only branches
- remove stale suppressions

Unsafe without human confirmation:
- deleting `needs_review` cleanup findings automatically
- rewriting architectural boundaries
- removing files based only on low coverage or low churn
- interpreting `clean` as “works correctly”

The product is deterministic in its core scoring path, but the skill must still
respect the difference between:
- **measurement**
- **action planning**
- **governance**

Those are separate layers by design.

---

## Node / MCP Surfaces

Node wrapper:

```bash
npx ai-slop-detector review . --format json
npx ai-slop-detector pulse . --format json
npx ai-slop-detector sweep dead-code . --format json
npx ai-slop-detector mcp
```

Programmatic Node API:

```ts
import {
  reviewChanges,
  computeHealth,
  runCleanupFamily,
  scanProject,
} from "ai-slop-detector";
```

Typed contracts:

```ts
import type {
  ReviewOutput,
  HealthOutput,
  CleanupOutput,
  ScanOutput,
} from "ai-slop-detector/types";
```

MCP:

```bash
slop-detector mcp
```

Use MCP when the host tool already expects a stdio tool surface and should not
shell out manually.

---

## Governance

Governance enforcement is a separate surface:

```bash
slop-detector verify-governance ./.cr-ep
```

The skill should never treat review or cleanup scores as governance by
themselves. Use the dedicated governance artifact path for that.

---

## Legacy Note

Older versions of this skill documented:
- `/slop`
- `/slop-file`
- `/slop-gate`
- `/slop-delta`
- `/slop-spar`

That older framing mixed current product behavior with historical workflow
aliases. The modern recommendation is simpler:

- `review` for changed-code evidence
- `pulse` for prioritization
- `sweep` for cleanup planning
- `scan` for full baseline analysis
- `verify-governance` for enforcement artifacts
- `mcp` for structured agent integration

If you still expose custom slash commands in a host tool, map them to those
canonical commands rather than documenting a separate behavior model.
