# AI-SLOP-DETECTOR Upgrade Blueprint

This blueprint turns external architectural learnings into an internal
implementation sequence. The goal is not imitation. The goal is absorption:
keep our governance and mathematical strengths, then remove the operational
gaps that slow adoption.

---

## 1. Current Upgrade Thesis

`AI-SLOP-DETECTOR` is already strong at:

- mathematical governance
- reconstructable scoring outputs
- multi-axis deficit measurement
- self-calibration direction

It is weaker at:

- large-project runtime behavior
- developer-controlled exception handling
- repeated-run acceleration
- agent-native access paths

So the upgrade program should begin with mechanics, not marketing.

Execution note:
- model changes are now gated through
  `AI_SLOP_DETECTOR_MATHEMATICAL_CHECKLIST.md`
- output and operations changes are now gated through
  `AI_SLOP_DETECTOR_OPERATIONS_CHECKLIST.md`
- external capability absorption is now gated through
  `AI_SLOP_DETECTOR_ABSORPTION_CHECKLIST.md`
- the blueprint stays phase-oriented; the checklist handles add-one-by-one
  acceptance and rollback decisions

---

## 2. Active Implementation Ladder

### Phase 1: Structural Scaling

Priority:
- `P0`

Target:
- prevent structural coherence from always paying the full `O(N^2)` path

Delivered:
- `advanced.exact_topology_ceiling`
- `advanced.topology_mode_above_ceiling`
- exact MST below the ceiling
- deterministic approximation above the ceiling
- explicit approximation labeling in `ProjectAnalysis.coherence_level`
- CLI override surface and renderer observability

Status:
- closed

Acceptance:
- large project scans do not force exact topology beyond the configured ceiling
- approximation is deterministic across repeated runs
- exact versus approximate mode is visible in every renderer

### Phase 2: Inline Suppression

Priority:
- `P1`

Target:
- allow intentional local exceptions without forcing global ignore edits

Delivered:
- `# slop-disable-next-line <pattern_id|all>`
- `# slop-disable <pattern_id|all>`
- `# slop-enable <pattern_id|all>`
- suppression ledger in file, project, and CI/gate output
- compatibility with existing `@slop.ignore`
- warning heuristics for suppression overuse

Status:
- closed

Acceptance:
- local suppressions are auditable instead of silent
- suppressed issues are excluded from scoring but preserved in the ledger
- reviewers can see suppression counts in terminal and PR-facing output

### Phase 3: Repeated-Run Throughput and Signal Prioritization

Priority:
- `P2` then `P3`

Target:
- make repeated scans materially cheaper before adding more ranking signals

Track A: `P2` Metadata Cache
- SQLite-backed Python file analysis cache
- validation on path, size, mtime, hash, config fingerprint, and engine version
- partial project reuse when only a subset of files changed
- cache hits must preserve the same `FileAnalysis` contract as fresh analysis
- status: delivered

Track B: `P3` Churn and Coverage Overlay
- compute churn pressure from git history
- merge `.coverage` line hits into dead-code escalation
- surface “high churn + low coverage + high deficit” hotspots

Status:
- active now (`P2` closed, `P3` in progress)

Acceptance:
- unchanged Python files reuse cached analysis safely across repeated runs
- file edits and config drift invalidate cached entries deterministically
- churn and coverage change output prioritization without mutating core scoring semantics
- hotspot reporting stays useful when either churn or coverage data is unavailable

### Phase 4: Agent-Native Surface

Priority:
- `P4`

Target:
- expose focused query points for tools and assistants once engine internals are stable

Implementation:
- structured inspection endpoints
- report retrieval endpoints
- stable schema contracts for automation

Status:
- planned

---

## 3. Immediate Acceptance Criteria

The active phase is complete only when:

- git-backed churn pressure ranks actively changing sloppy files above stable ones
- `.coverage` data lowers the priority of well-exercised files and raises low-coverage deficit files
- hotspot output remains stable and informative when one signal source is missing
- tests lock hotspot ranking, coverage ingestion, and project/report wiring in place
