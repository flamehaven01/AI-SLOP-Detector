# P0-P4 Remediation Plan - CuraFrame Revalidation

**Baseline:** AI-SLOP-Detector `v3.8.8` / CuraFrame `b891ad9`
**Evidence:** [CURAFRAME_REVALIDATION.md](CURAFRAME_REVALIDATION.md)
**Release target:** `3.8.9` only after the P4 gates pass.

This plan preserves the external audit plan as evidence. It corrects its
release gates where a display-only change could not make the supplied repro
script pass, and separates reporting truthfulness from classifier tuning.

## Non-negotiable constraints

1. Do not publish a single "accuracy" or "success rate" from the CuraFrame
   audit subset. Report coverage, finding visibility, capability availability,
   root-cause precision, and actionability separately.
2. Do not change clone thresholds, similarity channels, or suppressions before
   positive and intentional-pattern controls exist in a labeled corpus.
3. Keep test files excluded by default. The defect is silent scope, not the
   default itself.
4. Preserve the weighted deficit score contract. Add explicit reporting states
   rather than redefining `clean` as "no signals of any kind."
5. A missing ML capability must never silently contribute to a full-capability
   result or gate decision.

## P0 - Make scan scope and unavailable capability explicit

### P0.1 ML capability contract

**Problem:** the shipped ML artifact cannot be loaded by `SlopClassifier.load()`;
the failure becomes a warning and the report looks complete.

**Implement**

- Add `ml_scoring` to JSON output with `available`, `unavailable`, or
  `disabled` status and a safe, actionable reason.
- Render the same state in text and Markdown reports.
- Mark gate output as partial when ML scoring is unavailable; do not silently
  report a full PASS.
- Validate artifact schema before indexing required keys. Include the expected
  schema version/keys in the diagnostic, not a raw `KeyError`.

**Acceptance**

- A deliberately incompatible model reports `ml_scoring.status=unavailable`.
- The normal score remains deterministic and separately labeled as core-only.
- A saved model can be loaded by the same version's loader.

### P0.2 Coverage envelope

**Problem:** default ignored tests and unsupported candidate files are invisible.

**Implement**

- Track candidate files as `analyzed`, `excluded`, `unsupported`, and
  `opt_in_supported` where applicable.
- Expose counts in text, Markdown, and JSON. JSON/verbose output must include
  each excluded path with its matched ignore pattern.
- Add `--include-tests` that removes only default test exclusions, not artifact,
  dependency, or user-configured ignores.

**Acceptance**

- Default project output says how many files were excluded and why.
- `--include-tests` analyzes the CuraFrame test files while build artifacts
  remain excluded.
- A direct file target still bypasses project discovery as it does today.

### P0.3 Finding visibility and status semantics

**Problem:** project text hides findings in clean-score files; CuraFrame hid 29
rows, including one critical finding.

**Implement**

- Add project-level pattern totals, severity distribution, and affected-file
  count to every output surface.
- Keep file detail gated by deficit status if desired, but include a compact
  finding index for clean-score files.
- Add an explicit result field such as `finding_summary.has_critical`; do not
  overload `overall_status`, which remains the weighted deficit classification.

**Acceptance**

- Text, Markdown, and JSON have identical aggregate pattern and severity totals.
- A critical finding is visible even if its file and weighted project status are
  clean.
- The result documents that `overall_status=clean` does not mean a zero-finding
  scan.

## P1 - Correct deterministic boundary and evidence classification

### P1.1 Docstring threshold semantics

**Problem:** a `4/4` docstring ratio is a warning while the prose says
"more documentation than implementation."

**Implement**

- Use strict `>` comparisons for per-node warning/critical thresholds, or
  change all user-facing wording to inclusive semantics. Prefer strict `>` for
  the current stated meaning.
- Test exact `0.5`, `1.0`, and `2.0` boundaries.

**Acceptance**

- `4/4` is not a warning.
- `5/4` is a warning.
- Every message agrees with the implemented comparison.

### P1.2 Dependency evidence states

**Problem:** one `phantom_import` category conflates a missing active runtime,
an import declared only in `requirements.txt`, and an undeclared import.

**Implement**

- Classify separately as `runtime_unavailable`, `declared_outside_primary_metadata`,
  and `undeclared_dependency`.
- Read recognized Python dependency sources before issuing an undeclared finding.
- Lower the default severity for metadata/environment evidence; retain high
  severity only for evidence of an actually unavailable required import in the
  declared execution context.

**Acceptance**

- CuraFrame's `streamlit` is not labeled a phantom import merely because the
  current analyzer environment lacks it.
- `psycopg` and `psycopg_pool` identify metadata location rather than claiming
  absence.
- A fixture with no recognized declaration remains detectable.

## P2 - Build the labeled strictness corpus

**Purpose:** establish controls before detector tuning.

**Corpus contents**

- True copied functions, renamed-variable copies, and non-clones with similar
  AST shape.
- CuraFrame symmetric comparators and declarative constraint factories.
- Strategy/interface implementations such as qualified `check_node` methods.
- Protocol ellipses, compatibility fallbacks, and valid context-manager
  `__exit__ -> False` methods.
- One expectation per case: `detected`, `not_detected`, or `informational`.

**Acceptance**

- Tests assert qualified owner names, source locations, and rule ids.
- Corpus output reports true-positive, false-positive, and abstained counts by
  family. It must not collapse them into one percentage.

## P3 - Tune strictness under the corpus contract

**Clone detector**

- Keep exact duplicate detection separate from near-clone clustering.
- Add discriminating channels proven by corpus results, such as normalized size
  ratio and stable call/attribute/constant signatures.
- Emit qualified function names (`Class.method`) to make evidence reviewable.
- Avoid new filename/framework exceptions unless the corpus proves a general
  semantic rule is impossible.

**Placeholder and complexity families**

- Treat protocol markers, documented compatibility shims, and required context
  manager semantics as explicit non-stub controls.
- Deduplicate correlated complexity signals into one root-cause group while
  retaining the individual evidence in JSON.
- Present lint escapes and empty-except signals as review prompts unless their
  surrounding context proves a defect.

**Acceptance**

- All P2 intentional controls remain non-defects.
- Existing true-positive controls remain detected.
- CuraFrame reports root locations separately from emitted evidence rows.

## P4 - Verification and release decision

1. Run the complete test suite and all P0/P1/P2 contract tests.
2. Re-run the scanner against the AI-SLOP-Detector repository and CuraFrame at
   pinned commits. Record coverage envelope, capability state, root-location
   counts, severity totals, and corpus confusion counts.
3. Run CuraFrame's test suite in an environment that installs its declared
   requirements; record environment failure separately from analyzer output.
4. Replace the old T2/T5/T6 repro exit conditions with output-contract checks;
   their current scripts only prove that files/findings exist and cannot pass
   after display-only remediation.
5. Update CHANGELOG and release notes only if measured acceptance criteria pass.

### P4 implementation observations

- P0-P3 are implemented and covered by the repository test suite. The current
  coverage envelope reports analyzed, excluded, and known-but-unsupported
  source files. Excluded-file details are capped at 200 entries with exact
  totals and per-reason counts so dependency trees cannot inflate JSON output.
- Rust discovery now emits root-relative paths. CuraFrame parity confirmed the
  same 27 Python files as the root-relative Python discovery, with no fallback
  warning. The Python parity guard remains a correctness control.
- The bundled ML artifact is currently reported as `unavailable` with its
  schema mismatch. It is not repaired or retrained by this work and must not
  be advertised as an active scoring capability.
- Release evidence must report finding totals and severities beside weighted
  deficit status. A `clean` weighted score does not mean no independent
  findings were emitted.
- CuraFrame runtime requirements install in an isolated environment, but its
  declared dependency surface omits `pytest`. Adding pytest only to the test
  harness produced `186 passed in 17.02s` on Python 3.14. The run emitted 214
  target-side deprecation warnings; it is recorded as target-environment
  evidence, not an analyzer result.
- The original `red_t2`, `red_t5`, and `red_t6` scripts remain unchanged as
  historical RED evidence. Their P4 replacements are
  `contract_t2_test_exclusion.py`, `contract_t5_coverage.py`, and
  `contract_t6_hidden_findings.py`; each passed against the remediated output
  contract.

### P4 completion status

The P0-P4 acceptance checks are satisfied for the deterministic core and
reporting surfaces. The ML artifact remains explicitly unavailable rather than
silently treated as a capability. Release notes must preserve that boundary and
must not turn the CuraFrame audit subset into an aggregate accuracy claim.

## Execution order

`P0.1 -> P0.2 -> P0.3 -> P1.1 -> P1.2 -> P2 -> P3 -> P4`

P0-P4 implementation and verification are complete. The next release step is
reviewing the accumulated diff, updating release documentation, and creating a
release commit only after those statements remain evidence-backed.
