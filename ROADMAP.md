# AI-SLOP Detector Roadmap

> Last updated: 2026-10-05

This roadmap tracks the path that matters for `AI-SLOP-DETECTOR`.
The goal is not feature parity theater. The goal is a cleaner, more governable,
more agent-ready structural review system.

---

## Now

Concrete work scoped to the next one or two minor releases.

### Post-v3.8.2 self-dogfood cleanup

The current bottleneck is no longer product surface availability. It is the
truthfulness and maintainability of the analyzer against its own codebase.

Recent 3.8.6-progress work already closed:

- strict same-file duplicate detection now reaches cleanup output
- dead-code cleanup semantics now require real dead-code evidence
- clone wording is aligned across code, output, and docs
- `operations.py` has been split into payload / cleanup / architecture /
  manifest / render modules
- Claude skill guidance has been refreshed to the canonical CLI and JSON-first
  agent loop

Immediate targets:

- reduce remaining top self-dogfood hotspots:
  - `patterns/python_imports.py`
  - `metrics/inflation.py`
  - `metrics/ddc.py`
  - `languages/js_analyzer.py`
  - `cli_history.py`
  - `core.py`
- keep shrinking monolithic helpers in:
  - `cli_history.py`
  - `core.py`
- complete `3.8.6` strictness stabilization:
  - clone-family threshold review
  - cleanup-family confidence review
  - remaining wording drift cleanup
- narrow dead-code false positives in `scripts/`
- ~~investigate persistent ML loader warning~~ closed by `5e8c7bc`: no model is
  read unless a path is given, so self-dogfood no longer loads one

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

### Rust Accelerator — v3.10 Performance Architecture

Rust is already connected as an optional file-discovery helper, but it is not
yet a proven end-user accelerator. The current project scan still performs the
Python discovery path for parity before accepting the Rust result, and project
coverage performs its own Python tree walk. The Python package also does not
currently ship a compiled Rust binary by default.

The v3.10 goal is therefore not to move analyzer semantics into Rust. It is to
remove repeated filesystem traversal while preserving one semantic authority.

**Authority boundary**

Rust may own fast filesystem enumeration. Python remains authoritative for:

- ignore and exclusion policy
- language classification
- canonical root-relative path ordering
- scan-coverage semantics
- AST analysis and pattern detection
- phantom-import and dependency evidence
- scoring, diagnostic bands, findings, and status
- report and JSON contracts

Rust must never become an independent source of scoring or policy truth.

**R0 — Benchmark the current path**

Measure before changing architecture:

- helper absent vs helper present
- cold and warm filesystem runs
- small, medium, and large repositories
- discovery time separately from total scan time
- repeated runs to distinguish filesystem noise from stable improvement

No acceleration claim should be made from implementation alone.

**R1 — Introduce a canonical project file manifest in Python**

First refactor the existing Python path without changing behavior. A single
project discovery result should feed:

- Python files
- JavaScript / TypeScript files
- Go files
- excluded supported files
- unsupported source files
- scan coverage

This removes duplicate traversal as an architecture change before Rust becomes
the preferred backend. The acceptance criterion is output parity with the
current Python-only behavior.

**R2 — Add Rust as the enumeration backend**

When the helper is available, perform one Rust filesystem walk and pass the
root-relative file inventory back to Python. Python then applies the canonical
classification and policy layers.

Required behavior:

- helper unavailable -> Python fallback
- helper failure -> Python fallback
- no Rust toolchain required at runtime for ordinary Python use
- canonical root-relative POSIX ordering before downstream analysis
- no change to findings, scores, status, or report semantics merely because the
  helper is present

**R3 — Determinism and parity gate**

Rust-present and Rust-absent runs over the same tree must produce the same
semantic result. Verify at least:

- analyzed file set and order
- excluded and unsupported coverage
- Python / JS / TS / Go file partitioning
- findings and severities
- per-file and project scores
- structural-coherence inputs and output
- serialized JSON apart from explicitly documented volatile fields

Exercise path separators, hidden directories, symlinks, duplicate include
patterns, ignore patterns, Unicode paths, and platform-specific path behavior.

**R4 — Packaging and distribution**

The current Python packaging does not include the compiled helper. Before
defaulting to Rust acceleration, choose and verify a distribution model such as
platform wheels or another optional binary delivery path.

Distribution must remain fail-open to the Python fallback: absence of a Rust
binary is not a product failure.

**R5 — Performance promotion gate**

Enable Rust as the preferred discovery backend only after benchmarks show a
repeatable end-to-end benefit on realistic repositories. If the gain is
negligible, keep Rust as an optional parity/test backend rather than adding
distribution complexity for branding value.

**Non-goals**

This roadmap does not move the following into Rust:

- AST semantics
- pattern or claim detection
- dependency-resolution policy
- scoring mathematics
- CI gate policy
- governance or release decisions

Any future native migration beyond filesystem enumeration requires a separate
evidence-backed design and parity program.

**Release boundary**

This work is intentionally outside the v3.9.x stabilization scope. v3.9.x keeps
the current verified fallback/parity model; the architectural acceleration work
begins only after the release candidate is closed.

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

### Model loader hardening (closed)

Closed by `5e8c7bc`: one JSON model contract (`ml/threshold_model.py`), read
only from an explicit path, validated field by field (invalid models are
`unavailable`); no default path, so ML scoring is `disabled` unless asked for.
Model reports state that their numbers are agreement with the detector's own
deficit-score labels, not independent accuracy.

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

Keep Python as the product core. The concrete v3.10 Rust acceleration plan is
tracked under **Rust Accelerator — v3.10 Performance Architecture** above.
Future native work remains benchmark-gated and must preserve Python semantic
authority unless a separate evidence-backed migration justifies changing it.

Potential later hot paths may include large graph extraction, but no policy,
scoring mathematics, or governance logic should move native merely for
implementation novelty.

---

## Guardrails

These rules stay fixed while the roadmap evolves.

- Keep the math model and enforcement policy separate.
- Prefer extending existing JSON and CLI contracts over inventing parallel ones.
- Add opt-in architecture and cleanup intelligence carefully; false confidence is worse than missing a candidate.
- Preserve canonical CLI simplicity: `scan`, `review`, `pulse`, `sweep`.
- Use native acceleration only for measured hot paths, not as a branding exercise.
- Treat self-dogfood regressions as product regressions, not as internal-only noise.
