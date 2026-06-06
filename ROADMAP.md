# AI-SLOP Detector Roadmap

> Last updated: 2026-06-05

This roadmap tracks the path that matters for `AI-SLOP-DETECTOR`.
The goal is not feature parity theater. The goal is a cleaner, more governable,
more agent-ready structural review system.

---

## Now

Concrete work scoped to the next one or two minor releases.

### Post-v3.8.2 self-dogfood cleanup

The current bottleneck is no longer product surface availability. It is the
truthfulness and maintainability of the analyzer against its own codebase.

Immediate targets:

- reduce remaining top self-dogfood hotspots:
  - `patterns/python_imports.py`
  - `metrics/inflation.py`
  - `metrics/ddc.py`
  - `languages/js_analyzer.py`
  - `cli_history.py`
  - `core.py`
- keep shrinking monolithic helpers in:
  - `operations.py`
  - `cli_history.py`
  - `core.py`
- narrow dead-code false positives in `scripts/`
- investigate persistent ML loader warning:
  - `[MLScorer] Failed to load model: 'model_type'`

Target outcome: self-dogfood becomes a reliable release gate rather than a
noisy reminder that the analyzer still misreads parts of its own surface.

### Coverage climb to 90%+

Lift test depth where product risk is highest:

- `operations.py`
- `cli.py` and handler split modules
- governance verification
- MCP wrapper
- Rust scan adapter
- impact / telemetry

Target outcome: higher confidence for release gating and less regression risk
after refactors like the recent CLI split and cleanup planner extraction.

### Docs site

Move the core docs into a dedicated public docs surface:

- getting started
- math model boundary
- governance verification
- CLI and cleanup workflows
- configuration examples
- MCP integration

Target outcome: the project is understandable without reading the repository in
chronological order.

---

## Next

Broader work that should follow once the current release surface is stable.

### Cleanup planner depth

Push cleanup from file-level candidates into stronger removal planning:

- symbol reachability
- stronger duplicate family evidence
- stale suppression narrowing
- safer `safe_review` vs `needs_review` boundaries
- script / utility awareness so dead-code review is less noisy on operational
  helper files

### Dependency hygiene breadth

Extend project-level hygiene beyond current manifest checks:

- dev/prod misuse
- undeclared transitive dependency hints
- monorepo package boundary awareness

### Architecture graph depth

Grow from cycles + layered preset into broader system review:

- richer graph export
- package/module grouping
- custom layer policies
- re-export chain visibility

### Model loader hardening

The scoring path itself is stable, but the optional ML path still emits a
warning during self-dogfood:

- normalize model metadata expectations
- make missing / legacy model schemas degrade cleanly
- decide whether the default path should silently disable ML scoring or
  surface a structured warning in JSON outputs

### Report surface expansion

Done: project and file reports now explain every metric (value / healthy
direction / meaning) with a deficit-band legend and deterministic Next Steps,
shared across the rich / text / markdown renderers.

Still open:

- stronger markdown packet
- PDF export
- HTML only when an interactive workflow is clearly justified

### VS Code extension

Shipped: the extension consumes the `ai-slop-detector` npm API + typed contracts
(no hand-rolled subprocess calls), a getting-started walkthrough, state-aware
empty states, and four webview surfaces — 4D `deficit_breakdown`, confidence-
ranked cleanup plan, pulse health dashboard, and diff-aware changed-code review.

Still open:

- per-pattern / per-category mute UX (suppression policy + editor action +
  affordance — its own chapter)
- schema-driven TypeScript codegen and a test suite (vitest + test-electron)
- optional LSP server for real-time push diagnostics

---

## Vision

Longer-horizon bets that should reinforce the core rather than distract from it.

### Agent-driven cleanup loop

Structured outputs already exist across JSON, API, and MCP. The next step is a
review workflow where an agent can:

- identify cleanup candidates
- explain evidence
- propose a patch
- return the change to a human reviewer

The product should remain review-first, not blind-auto-fix-first.

### Codebase health program

Turn static scans into a stable long-term operating signal:

- health snapshots
- regression diffs
- governance record continuity
- trend-aware cleanup targets

### Native acceleration on measured hot paths

Keep Python as the product core. Use Rust only where benchmarks prove it helps:

- file walking
- glob matching
- large graph extraction

No policy, math, or governance logic should move native without a strong reason.

---

## Guardrails

These rules stay fixed while the roadmap evolves.

- Keep the math model and enforcement policy separate.
- Prefer extending existing JSON and CLI contracts over inventing parallel ones.
- Add opt-in architecture and cleanup intelligence carefully; false confidence is worse than missing a candidate.
- Preserve canonical CLI simplicity: `scan`, `review`, `pulse`, `sweep`.
- Use native acceleration only for measured hot paths, not as a branding exercise.
- Treat self-dogfood regressions as product regressions, not as internal-only noise.
