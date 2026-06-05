# AI-SLOP-DETECTOR NPM Thin Wrapper Checklist

This checklist governs the Node distribution chapter after adaptive `--init`.

The goal is not to rewrite the product in JavaScript. The goal is to expose the
existing Python product contract to Node-first teams with minimal semantic drift.

Execution rule:

- finish one phase
- run the listed diagnosis
- mark the phase `OK`, `HOLD`, or `ROLLBACK`
- only then move to the next phase

---

## Target Outcome

`npm` / `npx` users should be able to run:

```text
npx ai-slop-detector scan .
npx ai-slop-detector review .
npx ai-slop-detector pulse .
npx ai-slop-detector sweep dead-code .
```

without learning a second product surface and without the wrapper inventing its
own semantics.

---

## Guardrails

Every phase in this checklist must preserve these rules:

1. Python remains the product core
2. the npm layer is a transport/distribution wrapper, not a reimplementation
3. JSON and exit-code semantics must match the Python CLI
4. wrapper behavior must degrade clearly when Python is missing
5. no hidden command renaming beyond the already-canonical CLI surface

---

## P0 - Distribution Boundary Diagnosis

### Target

Pin the exact current state of Python packaging, CLI entrypoints, and existing
Node-facing assets before adding a wrapper.

### What Exists Today

- Python package name: `ai-slop-detector`
- Python scripts:
  - `slop-detector`
  - `ai-slop-detector`
  - `slop-api`
  - `slop-mcp`
- canonical CLI surface already exists:
  - `scan`
  - `review`
  - `pulse`
  - `sweep`
- there is no top-level npm distribution wrapper yet
- existing `package.json` files are product-adjacent only:
  - `remotion/package.json`
  - `vscode-extension/package.json`

### Missing Capabilities

- no `npm` package for the CLI itself
- no `npx ai-slop-detector ...` surface
- no Node launcher that resolves Python runtime and forwards arguments
- no wrapper-focused docs or install guidance
- no CI check for wrapper behavior

### Risk

Low. This is a diagnosis phase, but if the wrapper scope is misread then later
work will either overbuild or drift from the Python contract.

### Benefit

- keeps the wrapper thin
- makes semantic alignment a first-class acceptance criterion

### Diagnosis

- confirm the wrapper can be built around the existing canonical CLI surface
- confirm wrapper scope does not include scoring, parsing, or report logic
- identify the minimum install/runtime assumptions the wrapper must declare

### OK Criteria

- Python core / npm wrapper boundary is explicit
- wrapper responsibilities are smaller than product responsibilities
- next phases are ordered around semantic safety first, packaging second

### Diagnosis Result

- the canonical command surface already exists on the Python side:
  - `scan`
  - `review`
  - `pulse`
  - `sweep`
- there is no need for npm-specific command invention
- the wrapper should forward into `ai-slop-detector` / `slop-detector`, not
  duplicate logic
- current repository `package.json` files are unrelated product surfaces:
  - `remotion`
  - `vscode-extension`
- the correct next step is runtime-contract design, not package branding

Status: `OK`

---

## P1 - Wrapper Runtime Contract

### Target

Define how the wrapper discovers Python, invokes the CLI, and propagates output.

### Required Outputs

- runtime discovery policy
- argument forwarding policy
- stdout/stderr passthrough policy
- exit-code passthrough policy

### Risk

Medium. A thin wrapper is still dangerous if it hides environment failures or
mutates process semantics.

### Benefit

- keeps `npx` behavior boring and predictable
- prevents Node packaging from becoming a second execution model

### Diagnosis

- verify wrapper behavior on success, Python-missing, and CLI-failure paths
- verify JSON mode output is byte-for-byte compatible enough for downstream use

### OK Criteria

- wrapper is transparent
- exit codes stay faithful
- failure messages are actionable

### Current implementation

- `npm-wrapper/lib/runtime.js` now defines the thin-wrapper execution contract
- backend discovery order is explicit:
  - `AI_SLOP_DETECTOR_EXECUTABLE`
  - active virtualenv scripts
  - PATH commands
  - Python module fallback via `python -m slop_detector.cli`
- argument forwarding stays transparent:
  - wrapper does not parse or rename commands
  - forwarded args are appended unchanged
- stdout/stderr policy is transparent:
  - normal child process execution uses inherited stdio
  - backend-missing path prints a direct actionable message
- exit-code policy is transparent:
  - child exit code is propagated
  - signal or missing-backend failure returns non-zero
- Node tests now pin:
  - candidate ordering
  - successful backend discovery
  - invocation argument preservation
  - exit-code passthrough
  - backend-missing failure messaging

Status: `OK`

---

## P2 - NPM Package Surface

### Target

Create the actual package surface and command mapping.

### Required Outputs

- top-level `package.json`
- `bin` entry
- launcher script
- version/linkage policy aligned with Python release flow

### Rules

- expose only the canonical CLI surface
- do not expose legacy-only names as first-class npm branding
- keep install instructions simple

### Risk

High. Packaging mistakes become public UX regressions quickly.

### Benefit

- Node-first adoption path
- simpler distribution story for mixed-language teams

### Diagnosis

- verify package metadata is minimal but complete
- verify `npx` examples match docs
- verify local install and direct `node` invocation both work

### OK Criteria

- package surface is coherent
- canonical commands are discoverable
- legacy drift is not reintroduced through npm

### Current implementation

- top-level wrapper package now exists under `npm-wrapper/`
- package metadata is intentionally minimal:
  - package name: `ai-slop-detector`
  - version aligned to Python release line: `3.8.1`
  - single `bin` entry:
    - `ai-slop-detector`
- launcher script now exists:
  - `bin/ai-slop-detector.js`
  - delegates directly into the runtime contract layer
- package surface stays canonical:
  - no npm-only command invention
  - no legacy alias branding in package metadata
- validation so far:
  - `node --test tests/runtime.test.js`
  - `node ./bin/ai-slop-detector.js --version`
  - `npm pack --dry-run`

Status: `OK`

---

## P3 - Validation and CI

### Target

Lock wrapper behavior into tests and CI.

### Required Coverage

- launcher unit tests
- argument passthrough tests
- exit-code propagation tests
- docs examples sanity check

### Risk

Medium. Without tests, the wrapper will rot the first time Python packaging
changes.

### Benefit

- wrapper remains a maintained surface rather than a one-off experiment

### Diagnosis

- verify wrapper tests do not require network access
- verify CI can exercise wrapper logic deterministically

### OK Criteria

- tests cover success and failure cases
- CI includes the npm wrapper path
- docs examples are backed by real behavior

### Current implementation

- GitHub Actions now includes an `npm-wrapper` job in `.github/workflows/ci.yml`
- CI lock points:
  - `node --test tests/runtime.test.js`
  - `node ./bin/ai-slop-detector.js --version`
  - `npm pack --dry-run`
- CI job installs the Python package first, so wrapper verification exercises the
  real backend path rather than a mocked shell-only path
- validation remains network-free after checkout:
  - no npm publish
  - no registry install
  - no external package fetch beyond standard CI tool setup

Status: `OK`

---

## P4 - Docs and Release Surface

### Target

Explain the wrapper clearly without implying the product moved out of Python.

### Required Docs

- README install examples
- CLI usage examples
- release notes / changelog entry
- roadmap status update

### Rules

- say explicitly that npm is a thin wrapper over the Python core
- document Python prerequisite or bundled strategy precisely
- avoid “cross-platform magic” wording unless actually implemented

### Risk

Medium. Distribution confusion is easy to create and hard to undo.

### Benefit

- keeps adoption honest
- helps mixed Python/Node teams understand the integration model

### Diagnosis

- verify docs match actual runtime behavior
- verify release messaging does not oversell the wrapper

### OK Criteria

- docs are precise
- release notes are scoped
- wrapper identity stays thin

### Current implementation

- README now states that npm is a thin wrapper over the Python core
- CLI docs now show local wrapper usage and wrapper guarantees
- changelog now records:
  - wrapper package surface
  - launcher
  - CI coverage
- roadmap now tracks npm wrapper as mostly delivered with release-surface work
  remaining

Status: `OK`
