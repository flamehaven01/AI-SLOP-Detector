# AI-SLOP-DETECTOR Adaptive Init Checklist

This checklist governs the next chapter after `v3.8.1`.

The goal is not to make `--init` more verbose. The goal is to make it
materially more useful on first contact with a real repository.

Execution rule:

- finish one phase
- run the listed diagnosis
- mark the phase `OK`, `HOLD`, or `ROLLBACK`
- only then move to the next phase

---

## Target Outcome

`slop-detector --init` should evolve from:

```text
domain-aware template generation
```

into:

```text
safe baseline generation
-> lightweight repository scan
-> evidence-backed config suggestions
-> optional writeback / merge
```

The output should reduce onboarding friction without silently overfitting a
repository.

---

## Guardrails

Every phase in this checklist must preserve these rules:

1. do not mutate scoring semantics during `--init`
2. keep generated config safe-by-default
3. suggestions must be evidence-backed, not decorative
4. architecture review stays opt-in unless evidence is extremely strong
5. no hidden “magic rewrite” of an existing `.slopconfig.yaml`

---

## P0 - Current Init Boundary Diagnosis

### Target

Pin the exact current behavior of `--init` and identify what is missing before
adding a second stage.

### What Exists Today

- `_detect_project_type()` distinguishes:
  - `package.json` -> `javascript`
  - `go.mod` -> `go`
  - fallback -> `python`
- `detect_domain()` scans Python imports and ranks domain profiles by trigger
  hits
- `generate_slopconfig_template()` emits:
  - weights
  - ignore defaults
  - domain-specific `ignore_extra`
  - pattern thresholds
  - empty `domain_overrides` slots
- `_run_init()` is idempotent by default and only overwrites on `--force-init`
- `.slopconfig.yaml` is injected into `.gitignore` for safety

### Missing Capabilities

- no stage-2 repository scan after template generation
- no suggestion engine for repository-specific ignore patterns
- no `god_function.domain_overrides` synthesis from observed code
- no architecture opt-in hints from actual package/module layout
- no cleanup-family tuning hints derived from scan evidence
- no preview/merge mode for existing configs
- tests cover domain detection and template generation, but not adaptive
  suggestion behavior

### Risk

Low. This is a diagnosis phase, but if the current behavior is misread then all
later adaptive work will drift.

### Benefit

- gives the next phases a precise scope
- prevents building a “smart init” that is only marketing language

### Diagnosis

- confirm current `--init` is still baseline-template-first
- confirm all adaptive goals are genuinely absent rather than hidden elsewhere
- identify which suggestions can be derived from already-available signals

### OK Criteria

- current init behavior is pinned
- missing adaptive features are explicitly named
- next phases are ordered by onboarding value, not feature novelty

### Diagnosis Result

- current `--init` is strong at safe baseline generation
- current `--init` is weak at repository-specific adaptation
- the best next step is not more domain profiles
- the best next step is a second stage that reuses existing signals to suggest:
  - ignore refinements
  - `god_function.domain_overrides`
  - architecture opt-in hints
  - cleanup tuning hints

Status: `OK`

---

## P1 - Repository Signal Collection

### Target

Collect the minimum repository signals needed for adaptive suggestions without
turning `--init` into a full project scan clone.

### Required Inputs

- file layout and high-noise directories
- project manifest presence
- dominant language/project type
- high-complexity functions worth domain override consideration
- package/module layout strong enough to justify architecture hints
- cleanup-family evidence that can inform default tuning

### Risk

Medium. If signal collection is too shallow, suggestions become useless. If it
is too heavy, `--init` becomes slow and surprising.

### Benefit

- turns onboarding into a repository-aware flow
- reuses evidence the system already knows how to produce

### Diagnosis

- verify collection can run quickly on medium repos
- verify missing optional signals degrade cleanly
- verify no suggestion depends on private or unstable internals

### OK Criteria

- signals are sufficient for suggestion synthesis
- collection is cheaper than a normal full review workflow
- missing signals fail soft, not loud

### Current implementation

- `collect_init_signals(project_path)` now gathers:
  - `project_type`
  - domain detection path / triggers / confidence
  - manifest presence
  - language counts
  - high-noise directory markers
  - bounded Python complexity candidates
  - architecture layout markers
  - cleanup-oriented repository markers
- the signal layer is intentionally lightweight and does **not** rewrite
  `.slopconfig.yaml` yet
- tests now pin:
  - manifest detection
  - language counting
  - noise-directory discovery
  - complexity-candidate collection
  - architecture-marker collection

Status: `OK`

---

## P2 - Suggestion Synthesis Engine

### Target

Convert repository signals into bounded, explainable config suggestions.

### Required Outputs

- suggested ignore patterns
- suggested `god_function.domain_overrides`
- suggested architecture opt-in or “stay disabled” recommendation
- suggested cleanup tuning hints

### Rules

- do not emit a suggestion without evidence
- every suggestion should be traceable to one or more observed repository facts
- prefer under-suggestion to noisy over-suggestion

### Risk

High. This is where “adaptive” can easily degrade into pseudo-intelligence.

### Benefit

- makes `--init` feel like repository onboarding rather than template dumping
- reduces manual config archaeology

### Diagnosis

- verify the same repo produces stable suggestions
- verify weak evidence does not escalate to strong config changes
- verify outputs can be explained in plain text

### OK Criteria

- suggestion output is stable
- every suggestion has a reason
- defaults stay conservative

### Current implementation

- `synthesize_init_suggestions(signals)` now emits:
  - `ignore_patterns`
  - `god_function_domain_overrides`
  - `architecture`
  - `cleanup_hints`
- ignore suggestions only appear when a repository noise directory is **not**
  already covered by baseline init defaults or profile-specific ignore patterns
- `god_function.domain_overrides` suggestions are intentionally narrow:
  - exact function name only
  - capped to three entries
  - only emitted for strong excess over baseline thresholds
- architecture stays conservative:
  - `enable_layered_preset` only when `src` layout and layered markers are both
    strong
  - otherwise `stay_disabled`
- cleanup hints remain advisory and evidence-backed rather than silently
  changing scoring or config
- tests now pin:
  - stable repeated suggestions
  - weak evidence staying conservative
  - plain-text explainability of reasons

Status: `OK`

---

## P3 - Safe Writeback and Merge UX

### Target

Make adaptive init safe for both new and existing repositories.

### Required Modes

- baseline-only generation
- preview of adaptive suggestions
- optional writeback for new config
- optional merge/update path for existing config

### Rules

- never silently rewrite an existing `.slopconfig.yaml`
- preserve hand-written sections unless the user explicitly accepts changes
- generated comments should explain where adaptive suggestions came from

### Risk

High. Unsafe writeback would damage trust immediately.

### Benefit

- makes adaptive init usable in real teams
- reduces fear around adopting the feature on an existing repository

### Diagnosis

- verify new-project and existing-project flows remain distinct
- verify rerunning `--init` stays idempotent unless the user opts into rewrite
- verify merge behavior preserves unknown/custom keys

### OK Criteria

- no silent destructive changes
- preview and write paths are clearly separated
- idempotency guarantee remains intact

### Current implementation

- new CLI controls now exist:
  - `--adaptive-init`
  - `--init-preview`
  - `--apply-init-suggestions`
- preview mode is now safe-by-default:
  - no `.slopconfig.yaml` write
  - no existing-config rewrite
  - prints baseline/adaptive preview only
- existing config flow stays distinct from new-config flow:
  - plain `--init` on initialized repos remains a no-op success
  - adaptive preview can still run without mutation
  - merge only happens with explicit `--apply-init-suggestions`
- adaptive merge is bounded:
  - appends new ignore patterns only when missing
  - appends `god_function.domain_overrides` only when absent
  - only enables layered architecture when recommendation is strong
  - leaves unrelated handwritten sections intact
- written configs now include an explanatory comment header when adaptive
  suggestions are applied
- tests now pin:
  - preview mode does not write config
  - explicit adaptive merge updates existing config while preserving custom keys
  - parser accepts the new adaptive-init flags

Status: `OK`

---

## P4 - Validation, Docs, and Release Surface

### Target

Lock adaptive init into tests and document it as a first-class onboarding flow.

### Required Coverage

- unit tests for signal collection
- unit tests for suggestion synthesis
- idempotency regression
- existing-config preview/merge behavior
- docs and examples showing:
  - baseline-only init
  - adaptive suggestion preview
  - accepted writeback

### Risk

Medium. A feature like this is easy to demo and easy to misunderstand without
tight tests and docs.

### Benefit

- makes the feature teachable
- makes regressions much harder to reintroduce

### Diagnosis

- verify docs match actual CLI behavior
- verify tests lock the conservative-default posture
- verify rollout does not imply unsupported “auto-governance”

### OK Criteria

- tests lock the adaptive flow
- docs explain the safety model
- release messaging stays precise

### Current implementation

- tests now lock:
  - signal collection
  - suggestion synthesis stability
  - idempotent baseline init
  - preview-without-write behavior
  - explicit merge behavior for existing configs
  - parser support for adaptive-init flags
- docs now distinguish three onboarding paths:
  - baseline init
  - adaptive preview
  - adaptive apply
- release messaging stays conservative:
  - no “auto-governance” claim
  - no silent rewrite claim
  - adaptive init is described as evidence-backed onboarding, not autonomous tuning

Status: `OK`
