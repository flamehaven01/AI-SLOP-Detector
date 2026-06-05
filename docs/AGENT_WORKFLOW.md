# Agent Workflow

AI-SLOP-DETECTOR is most useful to agents when it is treated as a structured
review loop, not as a last-minute lint step.

The goal is simple:

1. generate or edit code
2. run a structured review
3. inspect evidence and action classes
4. apply safe changes
5. hand the result to a human reviewer with better context

---

## Recommended Loop

### 1. Generate or edit code

An agent writes or modifies code in the target repository.

### 2. Run a project review in JSON

Use the canonical review surface:

```bash
slop-detector review . --format json
```

Node-first workflows can use:

```bash
npx ai-slop-detector review . --format json
```

Or the programmatic API:

```ts
import { reviewChanges } from "ai-slop-detector";

const review = await reviewChanges(process.cwd());
```

### 3. Inspect the returned evidence

For changed-code review, agents should prioritize:

- `verdict`
- `attribution.introduced_files`
- `targets`
- `actions`
- `findings`

For cleanup workflows, inspect:

- `issues`
- `confidence`
- `action_class`
- `evidence`

### 4. Apply only bounded fixes

Safe examples:

- remove unused imports
- reduce obvious duplication
- simplify placeholder branches
- remove stale suppressions

Unsafe examples:

- changing architectural boundaries without context
- deleting high-churn files solely from low-coverage heuristics
- treating `needs_review` findings as auto-fixable

### 5. Re-run health or cleanup

After a patch, the agent should confirm the effect:

```bash
slop-detector pulse . --format json
slop-detector sweep dead-code . --format json
```

Programmatic API:

```ts
import { computeHealth, runCleanupFamily } from "ai-slop-detector";

const health = await computeHealth(process.cwd());
const deadCode = await runCleanupFamily("dead-code", process.cwd());
```

### 6. Escalate with evidence

The final handoff to a human reviewer should include:

- what changed
- what command was run
- what verdict or score changed
- which findings remain
- which findings were intentionally not auto-fixed

---

## Command Selection

Use the smallest surface that matches the job:

- `scan`
  - full file/project analysis
  - use when the agent needs the complete core report
- `review`
  - changed-code review
  - use for PR-oriented workflows
- `pulse`
  - health and next-action targeting
  - use when the agent asks “what should I fix first?”
- `sweep <family>`
  - cleanup-family focused action planning
  - use for dead code, duplication, dependency hygiene, or boundaries
- `explain`
  - mitigation text
  - use when the agent needs human-readable remediation guidance
- `mcp`
  - stdio agent integration
  - use when the host tool already speaks MCP

---

## Recommended JSON-First Paths

### Review path

```bash
slop-detector review . --format json
```

Best when:

- patch review
- CI evidence
- agent-generated code validation

### Health path

```bash
slop-detector pulse . --format json
```

Best when:

- backlog prioritization
- hotspot targeting
- deciding next repair order

### Cleanup path

```bash
slop-detector sweep dead-code . --format json
slop-detector sweep dupes . --format json
slop-detector sweep unused-deps . --format json
```

Best when:

- planned cleanup passes
- staged refactors
- repository hygiene maintenance

---

## Agent Rules

- Prefer `--format json` or `--json` for machine consumption.
- Treat `confidence` as prioritization guidance, not permission for blind
  deletion.
- Respect the boundary between scoring and governance.
- Re-run after modifications instead of assuming the first diagnosis remains
  correct.
- Do not infer that `clean` means “complete” or “safe”; it only means the
  measured structural signals are currently acceptable.

---

## Minimal Example

```ts
import {
  reviewChanges,
  computeHealth,
  runCleanupFamily,
} from "ai-slop-detector";

const review = await reviewChanges(process.cwd());
if (review.verdict !== "pass") {
  const cleanup = await runCleanupFamily("dead-code", process.cwd());
  const health = await computeHealth(process.cwd());
  console.log({
    reviewVerdict: review.verdict,
    cleanupIssues: cleanup.summary.issue_count,
    nextTargets: health.targets.slice(0, 3),
  });
}
```
