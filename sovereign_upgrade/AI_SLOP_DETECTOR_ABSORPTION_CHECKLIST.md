# AI-SLOP-DETECTOR Absorption Checklist

This checklist starts a new chapter.

The goal is not to copy an external analyzer. The goal is to absorb the parts
that strengthen `AI-SLOP-DETECTOR` after they pass our own cleaning, code
sanity, and contract checks.

Execution rule:

- finish one phase
- run the listed diagnosis
- mark the phase `OK`, `HOLD`, or `ROLLBACK`
- only then move to the next phase

---

## Intake Rules

Every candidate feature must be processed through these gates before code work:

1. identify the external capability in concrete terms
2. map it to our existing model, CLI, and output contracts
3. reject direct naming or command imitation
4. reject any import that weakens our governance or mathematical boundaries
5. define the smallest internal implementation that preserves the value

---

## P0 - Capability Inventory and Boundary Check

### Target

Produce a grounded inventory of absorbable capabilities from the external code,
not just README claims.

### Scope

- cleanup depth
- dependency hygiene breadth
- architecture graph depth
- runtime evidence overlay
- typed output contracts
- npm wrapper surface
- editor and agent surfaces

### Risk

Low. This is a classification phase, but a bad inventory will distort all later
work.

### Benefit

- separates real code-backed capabilities from marketing surface
- prevents us from solving the wrong problem first

### Diagnosis

- confirm the capability exists in actual code, packaging, or tests
- classify each item as:
  - `direct absorb`
  - `re-design absorb`
  - `defer`
- record why it belongs in that class

### OK Criteria

- the inventory is code-backed
- each item has a boundary decision
- next implementation phase is prioritized by gap, not novelty

### Current Decision

- `cleanup confidence planning`: re-design absorb
- `dependency hygiene breadth`: direct absorb
- `architecture depth`: re-design absorb
- `runtime evidence overlay`: defer extension
- `typed output contract`: direct absorb
- `npm wrapper`: direct absorb
- `editor/LSP expansion`: defer

### Diagnosis Result

- cleanup is currently a candidate list in `build_cleanup_payload`, not a
  confidence-ranked plan
- dependency hygiene is currently file-level only, not manifest-level
- architecture evidence is currently cycle-oriented and shallow
- typed command contracts already exist and should be extended, not replaced
- npm delivery is still missing and should stay a thin wrapper over the Python
  product contract

Status: `OK`

---

## P1 - Cleanup Confidence Plan

### Target

Upgrade cleanup from candidate listing to confidence-ranked removal planning.

### Scope

- `dead-code`
- `dupes`
- `unused-deps`
- `stale-suppressions`
- `boundary-violations`

### Required Additions

- per-item confidence score
- `safe_review`, `needs_review`, `unsafe_auto_remove` style action class
- dependency/evidence summary explaining why the item is removable or risky
- `introduced` vs `inherited` carry-through where applicable

### Modeling Rules

- do not invent a detached scoring model for cleanup confidence
- reuse existing signals first:
  - `deficit_score`
  - churn
  - coverage
  - existing cleanup evidence such as duplicate family membership or stale
    suppression state
- high churn must reduce automatic-removal confidence
- low churn plus low coverage plus strong dead-code evidence may raise removal
  confidence

### Contract Rules

- extend the existing `build_cleanup_payload` JSON shape
- do not fork cleanup into a separate incompatible schema
- add fields such as `confidence`, `action_class`, and `evidence` inside the
  existing per-issue structure

### Risk

Medium to high. Cleanup advice becomes more operational, so false confidence is
more dangerous than missing a candidate.

### Benefit

- makes cleanup outputs directly usable by humans and agents
- closes a major product gap without touching the scoring core

### Diagnosis

- verify confidence ordering is stable on equivalent input
- verify duplicate families and dead-code candidates expose reasons
- verify no existing cleanup command loses findings during ranking
- verify JSON/text/markdown keep the same action semantics

### OK Criteria

- cleanup output is a plan, not a pile
- each top item explains why it is safe or unsafe to touch
- confidence is evidence-backed, not hardcoded cosmetic ranking

### Current implementation

- cleanup issues now keep the existing JSON payload shape and extend `issues[]`
  with:
  - `confidence`
  - `action_class`
  - `evidence`
- confidence currently reuses:
  - `deficit_score`
  - churn from priority hotspots
  - coverage from priority hotspots
  - cleanup-local evidence such as placeholder detection, duplicate similarity,
    and stale suppression state
- high churn lowers cleanup confidence by policy

Status: `OK`

---

## P2 - Dependency Hygiene Breadth

### Target

Expand from file-level unused signals to project-level dependency hygiene.

### Required Additions

- unused package dependencies
- undeclared imports
- prod vs dev dependency misuse
- manifest-aware review of root package metadata

### Risk

Medium. Package-manager and manifest rules vary across ecosystems.

### Benefit

- closes one of the clearest current gaps
- creates high-value cleanup output with strong CI usefulness

### Diagnosis

- verify package-level issues are not duplicated as file-level noise
- verify manifest parsing degrades cleanly when no JS package files exist
- verify cross-command output contract remains stable

### OK Criteria

- project-level dependency issues are first-class outputs
- non-JS repos do not fail or emit nonsense
- cleanup and review commands can both surface the same evidence coherently

### Current implementation

- `unused-deps` now includes project-level manifest hygiene for:
  - `pyproject.toml`
  - `package.json`
- added issue types:
  - `manifest_unused_dependency`
  - `undeclared_import`
- Python manifest hygiene reuses analyzed import evidence and distribution-name
  normalization
- JS manifest hygiene uses a lightweight bare-import scan and degrades cleanly
  when no package manifest exists

Status: `OK`

---

## P3 - Architecture Graph and Boundary Presets

### Target

Grow architecture analysis from cycle detection into rule-based graph review.

### Required Additions

- layer/boundary presets
- package/module graph reporting
- re-export chain awareness
- stronger `boundary-violations` evidence

### Risk

High. Bad defaults will over-report and erode trust quickly.

### Benefit

- pushes the tool from file checker into system reviewer
- strengthens both cleanup planning and changed-code review

### Diagnosis

- verify presets are opt-in or safely defaulted
- verify boundary findings explain importer, importee, and violated rule
- verify cycle-only behavior remains available for minimal configs

### OK Criteria

- architecture output is explainable and scoped
- presets do not create noisy false positives on generic repos
- graph evidence is consumable in JSON and human reports

### Current implementation

- `boundary-violations` still reports import cycles by default
- architecture boundary review is now opt-in through config:
  - `architecture.enabled`
  - `architecture.preset`
  - `architecture.layers`
- layered preset currently adds allow-list based layer review for common paths
- explicit boundary findings are emitted as `layer_boundary_violation`
- cycle-only behavior remains intact when architecture review is disabled

Status: `ACTIVE`

---

## P4 - Adaptive Init and NPM Surface

### Target

Make adoption easier without diluting the Python core.

### Required Additions

- 2-stage `--init`
  - stage 1: template generation
  - stage 2: repo scan for `ignore` and `domain_overrides` suggestions
- thin npm wrapper
  - canonical CLI entry
  - JSON passthrough
  - optional MCP entry

### Risk

Medium. Packaging and bootstrap flows can become brittle if mixed with core
analysis semantics.

### Benefit

- lowers adoption friction sharply
- improves parity with modern multi-surface developer tooling

### Diagnosis

- verify generated config is a valid start, not an overfit guess
- verify second-stage suggestions are separable from committed config
- verify npm wrapper does not fork output semantics from PyPI CLI

### OK Criteria

- `--init` produces a useful first config plus reviewable suggestions
- npm users hit the same product contract as Python users
- agent and CLI surfaces stay semantically aligned

Status: `PENDING`

---

## Phase Order

1. `P0` capability inventory and boundary check
2. `P1` cleanup confidence plan
3. `P2` dependency hygiene breadth
4. `P3` architecture graph and boundary presets
5. `P4` adaptive init and npm surface

Move only after the previous phase is diagnosed and accepted.
