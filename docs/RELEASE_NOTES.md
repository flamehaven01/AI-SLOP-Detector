# Release Notes

Detailed change history for AI-SLOP Detector.
For a condensed summary see the [Changelog](../CHANGELOG.md).

---

## v3.1.2 — 2026-04-11

### Fixed

**`ml/data_collector.py` — structural refactor + debug output**
- Extracted two inner counting loops in `from_analysis()` as static helpers:
  `_count_severities(issues)` and `_count_cross_lang(issues)`.
  Reduces `from_analysis` from 75 lines / depth=7 to ~30 lines / depth=3.
- `print(f"[!] Failed ...")` error handlers replaced with `logger.warning(...)`.
  Module-level `logger = logging.getLogger(__name__)` added.
  `save_dataset()` progress prints marked `# noqa: T201` (intentional CLI output).

**`.slopconfig.yaml` — domain overrides gap fill**
- Added `nested_complexity` + `god_function` overrides for functions not previously covered:
  `_analyze_function`, `_detect_unused_imports`, `_count_implementation_lines`,
  `_count_module_implementation_lines`, `analyze`, and ML pipeline methods.
- Self-scan result: **43/43 files CLEAN** (was 4 suspicious before this patch).

---

## v3.1.1 — 2026-04-08

### Fixed

**Clone Detection visibility**
- `function_clone_cluster` results were only visible in the Issues section;
  Core Metrics table showed no duplication signal.
- Fix: added **Clone Detection** row to the Core Metrics table.
  Shows CRITICAL/HIGH severity when `function_clone_cluster` fires; `PASS` otherwise.

**Table style unification (CLI UX)**
- Project-level output mixed three Rich table box styles
  (`SIMPLE`, `MINIMAL_DOUBLE_HEAD`, `ROUNDED`). All tables now use
  `box.ROUNDED` with `header_style="bold cyan"`.
- Jargon entries in File Analysis Notes column trimmed to first 3 terms + "+N more".
- File Analysis Status severity color extended to `critical_deficit` variant.

**VS Code extension (v3.1.1)**
- `extractJson()`: strips `[INFO]` log lines before `JSON.parse`.
- `recordHistory` setting now correctly passes `--no-history` to the CLI.
- Summary diagnostic message includes Clone Detection signal.
- Status bar tooltip uses null-safe metric access and shows Clone PASS/CRITICAL.
- **Workspace analysis**: scrollable QuickPick list of deficit files sorted by score.
- **History Trends**: formatted column table (Runs/Latest/Best/Worst/Trend)
  replaces raw JSON dump in Output panel.

**uv tooling**
- Added `uv.lock` and `[tool.uv]` section to `pyproject.toml`.
  `uvx ai-slop-detector` now works without a local install.

---

## v3.1.0 — 2026-04-05

### Changed — Mathematical model refinements

**Calibrator geometric mean** (`ml/self_calibrator.py`): Self-calibration engine now
uses the same weighted geometric mean (GQG) as the scorer. The previous arithmetic mean
produced a ~5-7pt gap on files with uneven dimension profiles.

**Complexity modifier baseline** (`metrics/inflation.py`): Jargon density penalty
activates from cc=1 instead of cc=3. Functions with cc=2 now receive a 1.10×
complexity premium for jargon.

**Purity weight configurable** (`core.py`): `w_pur` readable from `.slopconfig.yaml`
via `weights.purity` (default: 0.10 unchanged).

### Added — Three new adversarial patterns

| Pattern | Targets | Severity |
|---|---|---|
| `return_constant_stub` (extended) | `return {}`, `return []`, `return ()` | HIGH |
| `function_clone_cluster` | N structurally identical helpers (fragmented god function) | CRITICAL/HIGH |
| `placeholder_variable_naming` | ≥5 single-letter params; r1,r2...rN sequences | HIGH/MEDIUM |

**SPAR-Code score: 55 (FAIL) → 85 (PASS)** — all three previously-evading
adversarial cases are now detected.

#### `function_clone_cluster` — DI2/AST clone detection

A god function split into N one-liner helpers evades `god_function` and
`nested_complexity` entirely. v3.1.0 detects this at the file level:

```
For each function: compute 30-dim AST node-type histogram
Pairwise JSD between all function pairs
BFS connected components on (JSD < 0.05) graph
Largest component >= 6 -> CRITICAL
```

#### `placeholder_variable_naming`

```python
# Before v3.1.0: deficit = 0.0
def process(a, b, c, d, e, f, g):
    r1 = a + b; r2 = c - d; ...r12 = r11 + r6; return r12

# After v3.1.0: 2x HIGH (deficit = 10.0)
# "7 single-letter parameters" + "12 sequential numbered variables (r1..r12)"
```

**Scope note:** v1.0 detects naming *style*, not semantic quality. Math/science
libraries using single-letter conventions should configure `domain_overrides`.

### Added — fhval SPAR-Code

```bash
fhval spar              # full 3-layer adversarial validation
fhval spar --layer a    # ground truth anchors only
fhval spar --layer c    # existence probes only
fhval spar --json
```

---

## v3.0.2 — 2026-03-28

### Fixed

**Phantom import false-positive elimination**

Three-tier classification replacing flat CRITICAL-for-all:

| Tier | Condition | Severity |
|---|---|---|
| Internal | Module resolves to the current project | (skip) |
| Guarded | Inside `try/except ImportError` block | MEDIUM |
| Hard phantom | Unresolvable, unguarded | CRITICAL |

Project packages auto-discovered from `pyproject.toml` and `src/` layout.

**LDR no longer collapses on empty `__init__.py`**
- Empty init (`total_lines=0`) previously drove `deficit_score=100`.
- Fix: returns `ldr_score=1.0, grade="N/A", is_packaging_init=True`.

**GodFunctionPattern: long-but-simple paths demoted to LOW**
- Functions exceeding line threshold but with `cc ≤ 5` → LOW instead of HIGH.
- Eliminates false positives on constant tables, routing blocks, domain rule lists.

**Placeholder pattern precision**
- `NotImplementedPattern` skips `@abstractmethod` decorated methods.
- `EmptyExceptPattern` 3-tier: bare `except: pass` → CRITICAL; `except ImportError: pass` → LOW; typed `except X: pass` → MEDIUM.
- `InterfaceOnlyClassPattern` counts `return self`/`return cls` stubs toward threshold.

---

## v3.0.0 — 2026-03-20

### Changed — Scoring: geometric mean replaces arithmetic mean

```
purity        = exp(-0.5 * n_critical_patterns)
quality       = exp( (w_ldr*ln(ldr) + w_inf*ln(1-inf) + w_ddc*ln(ddc) + w_pur*ln(purity))
                     / (w_ldr + w_inf + w_ddc + w_pur) )
deficit_score = 100 * (1 - quality) + pattern_penalty
```

A near-zero in any single dimension pulls the result significantly lower.
Fourth dimension `purity` makes CRITICAL hits compound rather than add flat points.

### Added — AST node type distribution (DCF)

Every analyzed file carries a `dcf` field: normalized frequency of each AST node type.
Accessible via `--json` for external tooling and powers the structural coherence metric.

### Added — Project-level structural coherence

```python
project = detector.analyze_project("./src")
print(project.structural_coherence)  # 0.0 – 1.0
```

`1 - d` where `d` is the longest edge in the minimum spanning tree of pairwise
sqrt-JSD distances between file DCF distributions. Experimental — use for
longitudinal comparison within a project, not as an absolute gate.

---

## v2.9.3 — 2026-03-10

### Added — Self-Calibration

```bash
slop-detector . --self-calibrate
slop-detector . --self-calibrate --apply-calibration
slop-detector . --self-calibrate --min-history 50
```

Grid-searches 200+ weight combinations using your history database (true positives vs.
likely false positives). Writes to `.slopconfig.yaml` only when confidence gap > 0.10.

Full spec: [SELF_CALIBRATION.md](SELF_CALIBRATION.md)

---

## v2.9.1 — 2026-03-05

### Fixed — Self-inspection patch (3 deficit files → 0)

| Metric | v2.9.0 | v2.9.1 |
|:---|---:|---:|
| Deficit files | 3 | **0** |
| Avg deficit score | 11.65 | **9.57** |
| Weighted deficit score | 15.88 | **12.42** |

- `cli.py` (53.5 → 29.1): extracted 9 focused helpers from 5 oversized functions.
- `registry.py`: annotation-only imports moved under `TYPE_CHECKING`; `global` statement removed.
- `question_generator.py`: same `TYPE_CHECKING` guard; union syntax backported to Python 3.8.

---

## v2.9.0 — 2026-02-28

### Added — `phantom_import` detection (CRITICAL)

Resolution order: `sys.builtin_module_names` → `sys.stdlib_module_names` →
`importlib.metadata.packages_distributions()` → `importlib.util.find_spec`

Full spec: [PHANTOM_IMPORT.md](PHANTOM_IMPORT.md)

### Added — History auto-tracking

Every run recorded to `~/.slop-detector/history.db`.

```bash
slop-detector mycode.py --show-history
slop-detector --history-trends
slop-detector --export-history data.jsonl
slop-detector mycode.py --no-history
```

Full spec: [HISTORY_TRACKING.md](HISTORY_TRACKING.md)
