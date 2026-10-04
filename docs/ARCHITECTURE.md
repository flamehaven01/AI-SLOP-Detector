# Architecture

**Current contract:** v3.9.1. This page describes the current implementation, not a product roadmap or a performance benchmark.

## Purpose And Boundary

AI-SLOP Detector is a deterministic static-analysis tool for structural-risk signals in source code. It reports metrics, pattern findings, scan coverage, and optional operational guidance.

It does not prove semantic correctness, security, authorship, or that a score is an externally validated governance control. See [VALIDATION.md](VALIDATION.md) for the evidence boundary.

## Runtime Shape

```text
CLI / npm wrapper / MCP / optional local API
                    |
                    v
             SlopDetector facade
                    |
     +--------------+---------------+
     |              |               |
     v              v               v
core_scoring   core_topology   core_project
     |              |               |
     +--------------+---------------+
                    |
                    v
 metrics + patterns + language analyzers
                    |
                    v
 FileAnalysis / ProjectAnalysis contracts
                    |
     +--------------+---------------+
     |              |               |
     v              v               v
 renderers      operations      governance verifier
```

`core.py` is a compatibility facade. It coordinates analysis and retains the existing private seams used by integrations and tests. Focused modules own the pure scoring, structural-topology, and project-aggregation logic.

- `core_scoring.py`: four-dimensional score and penalty attribution. The status is the band of the score, from `diagnostic_bands.py`.
- `core_topology.py`: DCF, Jensen-Shannon distance, and exact or deterministic approximate coherence calculations.
- `core_project.py`: discovery policy, coverage envelope, and project result aggregation.

## Source Scope

The project scanner recognizes Python, JavaScript, TypeScript, and Go. It distinguishes analyzed files from intentionally excluded supported files and known unsupported source files. Build products and dependency trees such as `build`, `dist`, `.tox`, `node_modules`, and `.next` are excluded by default.

Language support is not a claim of equivalent analysis depth. Python supplies the core metric and pattern path; JS/TS and Go use language analyzers and are included in the project contract. Inspect `scan_coverage` and language-specific result arrays before treating a project result as complete scope.

## Deterministic Scoring

For a Python file, the base quality gate is a weighted geometric mean of four dimensions:

```text
GQG = exp(sum(weight_i * log(max(1e-4, dimension_i))) / sum(weight_i))
base_deficit = 100 * (1 - GQG)
deficit = min(base_deficit + pattern_penalty, 100)
```

Default weights are LDR `0.40`, inflation `0.30`, dependency usage (DDC) `0.20`, and critical-pattern purity `0.10`. A geometric mean is deliberate: one near-zero dimension cannot be hidden by high values in the others. Pattern penalties are added after the base score; the penalty is capped at `50` points and the total at `100`.

The detailed formula and ranges live in [MATH_MODELS.md](MATH_MODELS.md). A status is the band of the deficit score (CLEAN <30, SUSPICIOUS <50, INFLATED_SIGNAL <70, CRITICAL_DEFICIT >=70), the same for files, projects, JS, and Go; no rule overrides it. The score is deterministic for the same input and configuration; that is reproducibility, not external validation.

## Project Results

`ProjectAnalysis` keeps language result arrays separate while calculating a project-level deficit. The weighted deficit uses analyzed line counts when weighted analysis is enabled. Project LDR is conservative: `0.6 * minimum + 0.4 * mean` so a low-density file is not diluted by many clean files.

Python structural coherence is derived from distributional code fingerprints (DCF) and an MST over pairwise square-root Jensen-Shannon distances. Exact calculation is used through the configured ceiling; above it, the default is a deterministic sample. The report exposes whether the result is exact or approximate through `coherence_level`.

## Operations And Enforcement

The normal score, cleanup planning, and governance enforcement are separate layers:

- `scan` gives a baseline result.
- `review` (an alias for `audit`) attributes changed-code findings against a git base.
- `pulse` (an alias for `health`) prioritizes hotspots.
- `sweep` gathers a bounded cleanup family such as `dead-code`, `dupes`, or `unused-deps` and attaches confidence and evidence.
- `verify-governance` verifies a generated governance record and fails closed on a bad or untrusted record.

Cleanup confidence is prioritization evidence, not permission for blind deletion. Governance verification checks the artifact contract; it does not make the mathematical score a compliance certification.

## History, Calibration, And Telemetry

Normal scans record repository-local history unless `--no-history` is used. The calibration path derives local improvement and false-positive-candidate signals from repeat-file history. At a guarded milestone it can update an existing local `.slopconfig.yaml`; manual `--self-calibrate --apply-calibration` remains the explicit review-and-apply path.

This adaptation is repository-scoped and is not an external validation loop. It does not export history as a validation channel. Local impact tracking is opt-in, and telemetry is off by default; inspect its payload before enabling it. See [SELF_CALIBRATION.md](SELF_CALIBRATION.md) and [HISTORY_TRACKING.md](HISTORY_TRACKING.md).

## Integration Boundaries

The npm package is a transport layer over the Python CLI, not a second analyzer. The MCP server provides structured tools over the same core.

The optional FastAPI service is a local integration surface. It has no built-in authentication or request authorization and permits all origins by default. Do not expose it directly to an untrusted network. Its webhook and project-status stubs are not supported deployment features; see [API.md](API.md).

## Related Documents

- [USAGE.md](USAGE.md): short safe starting path.
- [CLI_USAGE.md](CLI_USAGE.md): complete command reference.
- [CONFIGURATION.md](CONFIGURATION.md): config and adaptive init.
- [PATTERNS.md](PATTERNS.md): pattern catalog and fix boundaries.
- [GOVERNANCE.md](GOVERNANCE.md): artifact verification contract.
- [VALIDATION.md](VALIDATION.md): claims this implementation does not make.
