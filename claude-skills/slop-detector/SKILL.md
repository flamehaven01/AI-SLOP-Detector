---
name: slop-detector
description: Structural review skill for AI-SLOP Detector. Use when asked to review AI-assisted code, inspect changed-code risk, prioritize structural hotspots, plan cleanup, verify governance, or run JSON-first workflows. Prefer the canonical CLI surfaces: scan, review, pulse, sweep, explain and verify-governance. Treat review/pulse/sweep as the primary agent-facing surfaces; use scan for full baseline analysis.
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
pip install "ai-slop-detector[js]"   # optional JS/TS tree-sitter parsing (Python 3.10+)
pip install "ai-slop-detector[go]"   # installs tree-sitter-go (Python 3.10+); the Go analyzer does not use it yet
pip install "ai-slop-detector[rust]" # optional Rust tree-sitter parsing (Python 3.10+; .rs files are scanned without it)
```

The CLI analyzes one JS/TS, Go or Rust file directly (`slop-detector scan lib.rs`).

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

Before acting on a project scan, inspect:
- `finding_summary` for total and severity counts
- `scan_coverage` for analyzed, excluded, and unsupported files
- `ml_scoring` for the optional ML capability state

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

### `mcp` (do not use)

`slop-detector mcp` frames each message with a `Content-Length` header; the MCP
specification's stdio transport is newline-delimited JSON, so a client that
follows the specification gets no reply. Use the CLI commands above with
`--format json` instead. A server on the official MCP SDK is planned for 3.19.

---

## Working findings one at a time: the AI work order

To fix findings, read the work order rather than the full scan JSON: it is several
times smaller and binds every item to its file's SHA-256.

```bash
slop-detector scan . --format ai-md --ai-mode auditor -o work-order.md  # read-only: verify each item
slop-detector scan . --format ai -o report.jsonl                         # the same items as JSON Lines
slop-detector explain <rule>                                             # what the rule asks, when to ACK or REJECT
```

For each item, answer the rule's VERIFY question, then ACK (fix) or REJECT it with
the reason; a REJECT with evidence is a result, not a failure. After a fix, re-scan
and read the item again. A finding that disappears is not proof of a fix: a
suppression comment, an `fp:` declaration, a disabled rule, an ignored file or a
file that no longer parses removes it too. Never install or declare a package
because of an import finding alone. Details: [AI_WORK_ORDER.md](https://github.com/flamehaven01/AI-SLOP-Detector/blob/main/docs/AI_WORK_ORDER.md).

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
- treating `clean` as proof that no findings exist or all files were analyzed
- treating an unavailable ML capability as a passing ML signal

Use `--include-tests` only when test-file findings are in scope. It includes
built-in test-file exclusions only; configured ignores and artifacts remain
excluded.

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

If a host environment adds slash aliases, they should delegate to those canonical
commands rather than documenting a separate behavior model.
