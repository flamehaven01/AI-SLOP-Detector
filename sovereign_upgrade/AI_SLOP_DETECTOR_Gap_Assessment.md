# AI-SLOP-DETECTOR Gap Assessment

This is the hard internal reading of where the product stands after the latest
release.

---

## 1. Scorecard

| Dimension | Current Position | Main Risk |
| :--- | :---: | :--- |
| execution speed and scaling | 3 / 10 | structural coherence cost expands too fast on large repos |
| mathematical rigor | 9 / 10 | strong moat, but only if operational reliability holds |
| false-positive control | 4 / 10 | intentional exceptions still create too much friction |
| agent and ecosystem readiness | 5 / 10 | CLI-first surface is useful but narrow |
| self-calibration direction | 9 / 10 | strong concept, needs more operational reinforcement |

---

## 2. Core Risks

### Structural Scaling Risk

The structural coherence path is exact and clean, but expensive. Once file count
grows, the pairwise distance matrix becomes an immediate scaling ceiling.

### Exception-Handling Risk

Developers still need local, auditable suppression semantics. Without that,
noise handling becomes a config-management problem instead of a code-review
workflow.

### Repeated-Run Cost Risk

The engine still recomputes too much on unchanged files. That cost accumulates
in CI, local loops, and workspace scans.

### Prioritization Risk

Static severity alone is not enough. Files that change constantly should not be
treated the same as stable archive code.

---

## 3. Immediate Countermoves

1. ship deterministic topology approximation above a safe exact ceiling
2. add inline suppression with audit-visible reporting
3. layer churn and coverage into prioritization
4. add metadata-anchored cache paths

---

## 4. Current Move

Move 1 has started in code now. That is the correct opening because it reduces
runtime risk without weakening the mathematical model.
