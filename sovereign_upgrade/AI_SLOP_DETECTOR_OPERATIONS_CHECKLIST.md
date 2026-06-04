# AI-SLOP Detector Operations Checklist

This checklist defines the next implementation ladder for output surfaces and
operational workflows. The goal is to make review, cleanup, and agent usage
more explicit without collapsing the scoring model into the enforcement model.

Use this document as the execution checklist for the next phases.

---

## P0 - Audit Entry Points and JSON Contract

### Additions

- `audit` as a first-class command with `pass / warn / fail` verdicts
- explicit `introduced` vs `inherited` attribution in JSON
- unified JSON shape for human and agent consumers
- shared command surface for `actions[]`, `verdict`, `attribution`, `targets`

### Risk

- Medium. This touches the primary PR-review path and the machine contract used
  by downstream tools.

### Benefit

- Reviewers get a single entry point for change review.
- Agents can consume one stable contract instead of inferring semantics from
  ad-hoc text.

### Test

- CLI contract tests for `audit --format json`
- regression tests for introduced vs inherited attribution
- report-parity tests across text and JSON output

### OK criteria

- `audit` is the default changed-code review gate
- JSON output exposes verdict, attribution, and actions consistently
- text and JSON reports describe the same decision

---

## P1 - Health, Hotspots, and Refactor Targets

### Additions

- stronger `health` output that surfaces the next fixes, not just the score
- explicit `hotspots` ranking with `refactor targets`
- clearer score-to-action mapping for cleanup, architecture, and dependency risk

### Risk

- Low to medium. This is mostly ranking and presentation, but it must not alter
  the underlying deficit score semantics.

### Benefit

- “What should I fix first?” becomes the primary answer, not a side effect.
- This is the closest user-facing competitor to a simplified Rust CLI.

### Test

- hotspot ordering tests
- target selection tests
- JSON and markdown parity tests for the same target list

### OK criteria

- `health` highlights actionable targets, not just metrics
- `hotspots` are stable under equivalent input
- target output remains consistent across text, markdown, and JSON

---

## P2 - Cleanup Families and Unified Command Grouping

### Additions

- grouped surface for:
  - `dead-code`
  - `dupes`
  - `unused-deps`
  - `stale-suppressions`
  - `boundary-violations`
- shared command help and output conventions for cleanup-related workflows

### Risk

- Medium. This spans multiple analyzers and can easily produce duplicated
  output or inconsistent verdict semantics if done piecemeal.

### Benefit

- The cleanup workflow becomes a single mental model.
- The repository’s strongest static-analysis signals are easier to explain and
  automate.

### Test

- command routing tests
- output-schema tests per subcommand
- regression tests for unified cleanup summaries

### OK criteria

- cleanup commands are discoverable as a set
- JSON fields remain stable across all cleanup commands
- stale suppressions and boundary violations surface in the same review flow

---

## P3 - Operational Loop and Evidence Quality

### Additions

- stronger `watch` loop for repeated scans
- more useful `fix` workflows and `explain` responses
- benchmark, fuzz, and self-dogfooding coverage for the CLI surface

### Risk

- Medium to high. These paths are user-facing and can affect trust if they are
  flaky or too slow.

### Benefit

- The tool becomes an operational system, not just an analyzer.
- Performance claims become evidence-backed rather than aspirational.

### Test

- watch-loop stability tests
- fix dry-run vs apply tests
- explain-response regression tests
- benchmark baselines and fuzz smoke tests

### OK criteria

- repeated use stays stable and predictable
- fixes are explainable before they are applied
- performance regressions are visible quickly

---

## P4 - Limited Rust Acceleration

### Additions

- Rust only for hot paths that are easy to isolate:
  - file walking
  - glob matching
  - large graph / duplicate candidate extraction

### Risk

- High if expanded too early, low if kept as a narrow accelerator.

### Benefit

- Performance-sensitive pieces can be accelerated without moving the product
  contract away from Python.

### Test

- benchmark comparison before and after each Rust candidate
- parity tests against the Python implementation
- packaging and fallback tests

### OK criteria

- Rust remains an accelerator, not the architecture
- no scoring or governance logic moves into Rust
- adoption is based on measured wins only

---

## P5 - Framework Boilerplate Masking

### Additions

- AST-level masking for framework boilerplate that should not count as slop
- framework-aware normalizers for repetitive scaffolding patterns
- masking that complements, rather than replaces, explicit suppression comments

### Risk

- Medium. Masking can hide real findings if the framework heuristics are too
  broad, so the rule boundary must stay explicit and test-covered.

### Benefit

- False positives drop without forcing users to litter code with suppressions.
- Framework-heavy repos become more accurate out of the box.

### Test

- framework fixture regression tests
- masking-vs-suppression precedence tests
- no-hide-critical-pattern tests

### OK criteria

- boilerplate patterns are masked deterministically
- critical findings are never hidden by masking
- masking behavior is documented and regression-covered

### Current implementation

- Python test files mask pytest no-op hook `pass_placeholder` before suppression matching.
- JS/TS test/spec files mask `js_console_log` and empty lifecycle hook arrows.
- `critical` findings remain visible by policy.

---

## P6 - Cleanup Families and Watch Loop

### Additions

- grouped cleanup surface for:
  - `dead-code`
  - `dupes`
  - `unused-deps`
  - `stale-suppressions`
  - `boundary-violations`
- `watch` loop for incremental feedback during local development
- a clearer "what can I delete?" workflow

### Risk

- Medium. These features touch a lot of existing command surfaces and can
  become noisy if their summaries are inconsistent.

### Benefit

- The tool becomes a day-to-day cleanup assistant, not just a scanner.
- Users get a direct refactoring loop instead of a pile of isolated reports.

### Test

- command grouping tests
- `watch` refresh/stability tests
- cleanup summary schema tests

### OK criteria

- cleanup commands are discoverable as a family
- `watch` produces stable repeated output
- cleanup summaries are actionable and consistent

---

## P7 - MCP Wrapper

### Additions

- a real MCP server wrapper on top of the existing agent-native JSON surface
- tool metadata and prompts that expose the same semantics as the CLI
- direct agent-friendly query/action routing

### Risk

- Medium to high. MCP surface area is easy to overbuild, and protocol drift can
  create support burden if the wrapper diverges from the JSON contract.

### Benefit

- Agent integrations become first-class instead of adapter-only.
- The JSON surface can be consumed by standard agent tooling without custom glue.

### Test

- MCP contract tests
- tool schema tests
- end-to-end agent query/response parity tests

### OK criteria

- MCP responses map cleanly to existing JSON outputs
- no duplicated analysis semantics appear in the wrapper
- the wrapper stays thin and protocol-compliant

---

## P8 - Rust Hot-Path Acceleration

### Additions

- Rust acceleration only for measured hot paths:
  - file walking
  - glob matching
  - large-graph / duplicate-candidate extraction

### Risk

- High if expanded too early, lower if kept narrowly scoped.

### Benefit

- Performance-critical pieces get faster without moving the product contract
  away from Python.

### Test

- benchmark comparisons before and after each candidate
- Python-vs-Rust parity tests
- packaging and fallback tests

### OK criteria

- Rust remains an accelerator, not the architecture
- no scoring, governance, or reporting semantics move into Rust
- each Rust addition is justified by measured wins
