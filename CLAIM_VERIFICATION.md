# AI-SLOP Detector — Claim Verification Against Source Code

**Date**: 2026-04-15  
**Version**: v3.5.0  
**Repo**: https://github.com/flamehaven01/AI-SLOP-Detector  
**Disputed post**: LinkedIn draft referencing self-calibration and download metrics

---

## Claim 1: "Every scan is recorded"

**Source**: `src/slop_detector/history.py`, lines 116–180

```python
def record(self, file_analysis, git_commit=None, git_branch=None, project_id=None) -> None:
```

- Auto-invoked on every CLI run (opt-out only via `--no-history`)
- Writes to SQLite: `~/.slop-detector/history.db`
- Stores: `deficit_score`, `ldr_score`, `inflation_score`, `ddc_usage_ratio`, `n_critical_patterns`, `fired_rules`, `git_commit`, `git_branch`, `project_id`
- Schema versioned through v5 (v2.9.0 → v3.5.0), auto-migrated on startup

**VERDICT: TRUE. Code is real, behavior is documented.**

---

## Claim 2: "Every re-scan becomes signal"

**Source**: `src/slop_detector/history.py`, lines 221–246

```python
def count_files_with_multiple_runs(self, project_id=None) -> int:
    # Only files scanned >= 2 times count as calibration events
    SELECT file_path FROM history GROUP BY file_path HAVING COUNT(*) >= 2
```

**Source**: `src/slop_detector/ml/self_calibrator.py`, lines 301–309

```python
def _extract_events(self, project_id=None):
    rows = self._load_history(project_id=project_id)
    by_file = self._group_runs_by_file(rows)
```

Single-scan files do NOT produce calibration events. Only repeat scans create improvement/fp_candidate labels.

**VERDICT: TRUE. The requirement for repeat scans is hardcoded — not assumed.**

---

## Claim 3: "Updates only when the signal is strong enough"

**Source**: `src/slop_detector/ml/self_calibrator.py`, lines 37–54 (constants) and 251–257 (enforcement)

```python
CONFIDENCE_GAP: float = 0.10   # min gap between #1 and #2 candidate
MIN_IMPROVEMENTS: int = 5       # improvement events required
MIN_FP_CANDIDATES: int = 5      # fp_candidate events required

# Enforcement (line 251):
if result.confidence_gap < CONFIDENCE_GAP:
    result.status = "insufficient_data"
    result.message = (
        f"Confidence gap {result.confidence_gap:.4f} < {CONFIDENCE_GAP}. "
        f"Candidates are too close — need more history data for reliable calibration."
    )
    return result  # NO UPDATE APPLIED
```

Additional guard (line 262):
```python
if current_score - winner_score < 0.02:
    result.status = "no_change"  # also does not apply
```

**VERDICT: TRUE. Two independent gates prevent ambiguous updates from applying.**

---

## Claim 4: "Leaves behind a visible policy every time it changes"

**Source**: `src/slop_detector/ml/self_calibrator.py`, docstring line 17–18

```
Return CalibrationResult; optionally write to .slopconfig.yaml via --apply-calibration
```

When `--apply-calibration` is passed and status == "ok", the optimal weights are written to `.slopconfig.yaml` — a plain-text YAML file that is human-readable and git-versionable.

**VERDICT: TRUE. The policy artifact is `.slopconfig.yaml`, explicit and versionable.**

---

## Claim 5: "Explicit limits" (mathematically governed)

**Source**: `src/slop_detector/ml/self_calibrator.py`, lines 37–54

```python
MIN_W: float = 0.10             # minimum allowed weight per dimension
MAX_W: float = 0.65             # maximum allowed weight per dimension
MAX_PURITY_WEIGHT: float = 0.25 # purity ceiling
DOMAIN_TOLERANCE: float = 0.15  # max per-dimension deviation from domain anchor
DOMAIN_DRIFT_LIMIT: float = 0.25 # warn when optimal weight drifts this far
GRID_STEP: int = 20             # 0.05 increment resolution
```

All constraints are hardcoded numeric constants in source. No ML model, no opaque learned bounds.

**VERDICT: TRUE. Every limit has an explicit numeric value with a code comment explaining its purpose.**

---

## Claim 6: "AI-generated code — empty implementations, phantom dependencies, disconnected pipelines"

**Source files (all real implementations)**:

| Defect class | Implementation file |
|---|---|
| Empty/stub functions | `src/slop_detector/metrics/ldr.py` — LDRCalculator detects `pass`, `...`, `raise NotImplementedError`, `TODO` |
| Phantom/unused imports | `src/slop_detector/metrics/hallucination_deps.py` — `HallucinatedDependency` dataclass, AST-based import vs usage analysis |
| Disconnected pipelines | `src/slop_detector/metrics/ddc.py` — DDC (Declared Dependency Completeness) usage ratio |
| Function clone clusters | `src/slop_detector/patterns/python_advanced.py` — Jensen-Shannon Divergence on 30-dim AST histograms, JSD < 0.05 = clone |

**VERDICT: TRUE. Each defect class has a named module with working implementation.**

---

## Claim 7: "~1.4K downloads in the past week"

**Source**: pypistats.org API (mirrors=false), queried 2026-04-15

```
last_week:  1,407  (mirrors excluded — actual pip install traffic)
last_month: 1,787
last_day:   83
```

The post says "~1.4K" which is within 0.5% of the actual 1,407.

**VERDICT: TRUE. Verified against pypistats API in real time. Not fabricated.**

---

## Summary

| Claim | Verdict | Evidence location |
|---|---|---|
| Every scan is recorded | TRUE | `history.py:116-180` |
| Repeat scans become calibration signal | TRUE | `history.py:221-246`, `self_calibrator.py:301-309` |
| Updates only when signal is strong enough | TRUE | `self_calibrator.py:46,251-257,262` |
| Visible policy artifact (.slopconfig.yaml) | TRUE | `self_calibrator.py:17-18`, CLI `--apply-calibration` |
| Explicit numeric limits | TRUE | `self_calibrator.py:37-54` |
| Detects empty/stub/phantom/disconnected code | TRUE | `ldr.py`, `hallucination_deps.py`, `ddc.py`, `python_advanced.py` |
| ~1.4K downloads last week | TRUE | pypistats API, last_week=1,407 |

**No claim in the disputed post is fabricated, exaggerated, or unimplemented.**

The codebase is production-grade, versioned, and publicly auditable at:  
https://github.com/flamehaven01/AI-SLOP-Detector

---

*Generated by static code analysis + API verification, 2026-04-15*
