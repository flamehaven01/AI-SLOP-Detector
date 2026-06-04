# AI-SLOP Detector Mathematical Model Checklist

This checklist is the working surface for adding or changing mathematical
models in the detector.

Rule of use:
- do not merge a new model into the roadmap until it passes its own checklist
- low-risk items may be bundled into a single phase only when they share the
  same signal family and failure mode
- high-risk items must be handled alone

---

## Phase Group A: Snapshot Score Core

These items are low risk because they operate on one repository snapshot and
already have direct code paths, renderers, and regression tests.

### 1. Weighted Geometric Deficit

- Add target: `ldr + inflation + ddc + purity` geometric aggregation
- Risk: low
- Benefit: stable baseline deficit score with explicit component attribution
- Code anchor: `src/slop_detector/core.py`
- Test verification: `tests/test_core.py`, `tests/test_fp_reduction.py`
- Expected result: `deficit_score`, `deficit_breakdown`, and status thresholds
  remain deterministic
- Decision: `OK`
- Status: validated in tests

### 2. Deterministic Coherence

- Add target: `sqrt-JSD` structural coherence over file DCFs with exact /
  deterministic-approximate fallback
- Risk: low
- Benefit: captures repository structural separation without exposing
  nondeterministic topology
- Code anchor: `src/slop_detector/core.py`, `src/slop_detector/renderer_*`
- Test verification: `tests/test_core.py`, renderer contract tests
- Expected result: `coherence_level` is visible and repeated runs are stable
- Decision: `OK`
- Status: validated in tests

### 3. Priority Hotspot Overlay

- Add target: `deficit + churn + coverage gap`
- Risk: low to medium
- Benefit: tells reviewers what to fix first without mutating the core score
- Code anchor: `src/slop_detector/prioritization.py`, `src/slop_detector/core.py`
- Test verification: `tests/test_prioritization.py`, `tests/test_core.py`
- Expected result: hotspots remain optional, deterministic, and suppressed when
  data is missing
- Decision: `OK`
- Status: validated in tests

Bundle rule:
- these three may stay in one phase because they are all snapshot-level signals
- keep them separate in tests so regressions can be isolated quickly

---

## Phase Group B: Medium-Risk Operational Expansion

These items add operational behavior around the snapshot score.

### 4. Repeated-Run Metadata Cache

- Add target: SQLite-backed file analysis reuse
- Risk: medium
- Benefit: lower repeated-run cost, same `FileAnalysis` contract
- Code anchor: `src/slop_detector/analysis_cache.py`
- Test verification: cache hit, invalidation, serialization round-trip tests
- Expected result: cache reuse does not change score semantics
- Decision: `OK`
- Status: validated in tests

### 5. Inline Suppression Ledger

- Add target: local suppression comments and audit ledger
- Risk: medium
- Benefit: allows intentional exceptions without global ignore drift
- Code anchor: `src/slop_detector/suppression_handler.py`
- Test verification: `tests/test_suppression.py`
- Expected result: suppressed findings are excluded from scoring but retained
  in output
- Decision: `OK`
- Status: validated in tests

Bundle rule:
- these may be grouped only if test coverage for each signal stays independent
- never add a new suppression rule and cache logic in the same patch unless both
  have separate tests

---

## Phase Group C: High-Risk Governance Extensions

These items change policy or comparability and must be isolated.

### 6. Temporal Drift

- Add target: compare comparable records across time
- Risk: high
- Benefit: trend detection and release regression visibility
- Code anchor: `src/slop_detector/history.py`
- Test verification: `tests/test_history_drift.py`
- Expected result: read-only drift summary is available; no enforcement policy
  changes
- Decision: `OK` for read-only summary surface
- Status: validated in tests

### 7. Governance Record Enforcement

- Add target: record hash, comparability policy, fail-closed verdict surface
- Risk: high
- Benefit: reproducible external governance
- Code anchor: `src/slop_detector/governance/session.py`
- Test verification: `tests/test_governance_session.py`
- Expected result: reconstructable record artifact with stable hash
- Decision: `OK` for read-only record surface
- Status: validated in tests

### 8. Automatic Calibration Mutation

- Add target: auto-apply changed weights to runtime config
- Risk: high
- Benefit: less manual tuning
- Code anchor: calibration pipeline
- Test verification: offline calibration report only, no silent runtime mutation
- Expected result: requires explicit approval before activation
- Decision: `DEFER`

---

## Current Working Order

1. Keep snapshot score stable.
2. Phase Group A is now validated; keep its contracts pinned by regression tests.
3. Phase Group B is now validated; keep cache and suppression contracts pinned.
4. Add or adjust only one low-risk snapshot model at a time if the change is
   not already covered by existing tests.
5. Treat medium-risk operational changes as separate patches with dedicated
   tests.
6. Do not touch high-risk governance items until the snapshot and operational
   layers are frozen, except for read-only drift summaries and read-only record
   artifacts.
