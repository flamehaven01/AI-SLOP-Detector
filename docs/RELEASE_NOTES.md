# Release Notes

Detailed change history for AI-SLOP Detector.
For a condensed summary see the [Changelog](../CHANGELOG.md).

---

## v3.7.3 — 2026-05-04

### Fixed

**Package import stability**
- `config.py`: pydantic imports and schema class definitions moved inside
  `try/except ImportError`. When pydantic is absent `_validate_yaml_config()`
  returns immediately — package imports cleanly in stripped environments (e.g.
  bare `pip install ai-slop-detector` before deps fully resolve). Validation
  activates automatically once pydantic is present.
- `tests/test_api_models.py`: guard changed from `importorskip("pydantic")` to
  `importorskip("fastapi")`. Pydantic moved to base deps in v3.7.2, so the old
  guard no longer skipped the file — causing a collection error when `fastapi`
  (the actual `[api]` optional dep) was absent.

**CI**
- `ci.yml` (Docker job): Docker Hub login uses `continue-on-error: true`; push
  step fires only when `steps.docker_login.outcome == 'success'` — missing
  `DOCKER_USERNAME`/`DOCKER_TOKEN` secrets no longer fail the build.
- `ci-gate-fixed.yml`: install pinned to `"ai-slop-detector>=3.7.3"` to prevent
  the self-referential quality gate from resolving to the broken v3.7.2 PyPI
  package.

---

## v3.7.2 — 2026-05-04

### Added

**Core — three-layer data boundary validation**

Layer 1 — Config boundary (`config.py`):
- `_validate_yaml_config()` validates critical sections of `.slopconfig.yaml`
  before merging into `DEFAULT_CONFIG` — pydantic v2 schemas `_WeightsSchema`
  (each weight `[0.0, 1.0]`), `_DomainOverrideSchema` (string pattern, int
  thresholds `≥ 1`), `_GodFunctionSchema`. Raises `ValueError` with exact field
  path at load time — bad config (e.g. `weights.ldr: "hello"`) is caught before
  it can reach the GQG formula.
- Pydantic v2 (`>=2.5.0`) promoted to base dependency.

Layer 2 — Computed metric results (`models.py`):
- `LDRResult.__post_init__`: clamps `ldr_score` to `[0, 1]` with `WARNING` log
  — protects `log(max(1e-4, ldr))` in GQG scorer from out-of-range inputs.
- `InflationResult.__post_init__`: clamps `inflation_score` to `[0, ∞)` —
  prevents negative score artefacts from radon edge cases.
- `DDCResult.__post_init__`: clamps `usage_ratio` to `[0, 1]` with `WARNING`
  log — prevents positive GQG distortion from ratio > 1 edge cases.

Layer 3 — History DB insertion (`history.py`):
- `HistoryEntry.__post_init__` clamps all six numeric fields before SQLite
  write: `deficit_score ≥ 0`, `ldr_score / ddc_usage_ratio ∈ [0, 1]`,
  `inflation_score ≥ 0`, `n_critical_patterns / pattern_count ≥ 0`.
- `fired_rules` validated as parseable JSON at write time — malformed strings
  raised `ValueError` immediately instead of silently returning `None` on the
  next LEDA calibration read (which would drop all FP candidate events for
  that file).

**VS Code Extension v3.7.2**
- `schema.ts` (new, 185 L): `ISlopReport`, `ILdrResult`, `IInflationResult`,
  `IDdcResult`, `ISlopPattern` TypeScript interfaces; `ParseResult<T>`
  discriminated union (`ok / error`, never throws); `parseSlopReport(data:
  unknown)` — handwritten type predicate guards, `status` enum membership,
  `ldr.ldr_score` numeric, `pattern_issues[i]` shape. Zero new npm deps.
- `analyzer.ts`: `runSlopDetector()` return type narrowed `any →
  Promise<ISlopReport>`; `parseSlopReport()` applied after `extractJson()`;
  schema mismatch throws with exact `field / expected / got` path and
  version-hint message.

**Docs**
- `docs/SCHEMA_VALIDATION.md` (new): four-layer validation reference —
  Layer 1 config, Layer 2 metric results, Layer 3 history DB, Layer 4 VS Code
  boundary — with tables, rationale, LEDA interaction pipeline, and extension guide.
- `docs/LEDA_CALIBRATION.md §5`: "Three Runtime Schema Guards" section added.
- `docs/ARCHITECTURE.md`: Data Boundary Validation section added.

---

## v3.7.1 — 2026-05-03

### Fixed

**Pattern accuracy**
- `patterns/python_lint.py` — `LintEscapePattern.check()` now skips lines
  inside string/docstring literals. `# noqa:` text embedded in docstrings was
  incorrectly flagged as a live lint suppression; fix uses
  `_string_literal_lines()` to collect `ast.Constant[str]` line ranges.

**Code quality (self-scan audit — avg_deficit 13.85 → 9.80)**
- `cli_commands.py L215`: `except OSError: pass` in `detect_domain()` replaced
  with debug-level log.
- `cli_commands.py L380`: `except Exception: pass` in
  `_check_calibration_hint()` replaced with debug-level log.
- `scripts/global_injector.py`: Patch 1 (`DEFAULT_CONFIG["weights"]` rewrite)
  removed — dogfooding values belong only in `DOMAIN_PROFILES["general"]`.

**Documentation accuracy**
- `docs/LEDA_CALIBRATION.md §3.1`: GQG formula updated with `max(1e-4, ...)`
  clamp guards (matching `core.py` implementation).
- `docs/LEDA_CALIBRATION.md §4.3`: `ddc` "Before" corrected to `0.20²` with
  footnote (pre-3.7.0 historical value was `0.30`).
- `docs/CLAUDE_CODE_SKILL.md`: loop label corrected in 4 locations; Quality
  Loop updated to 7 numbered steps.

### Changed

**`.slopconfig.yaml`** — domain_overrides expanded for justified structural
complexity in `detect_domain`, `_collect_imports`, `_analyze_regex`,
`_run_self_calibration`, `_check_calibration_hint`.

**Claude Code Skill — v3.7.1 workflow**
- 3-Phase Pipeline: Triage → Deep-Dive (Confidence Routing) → Action Plan.
- `/slop-delta` new command: before/after delta table, regression detection.

**VS Code Extension v3.7.1**
- 855-line monolith split into 8 focused modules.
- `SlopCodeActionProvider`: QuickFix for `phantom_import`, `god_function`,
  `lint_escape`; "Add to .slopconfig.yaml ignore" action.
- TreeView sidebar: 3-level hierarchy (file → 4D metrics → issues), click-to-navigate.
- `SlopCodeLensProvider`: file-level summary at line 0 + per-function hints.

---

## v3.7.0 — 2026-05-02

### Added

**Real-world Dogfooding Model**
- `scripts/retrain_model.py`: new `ThresholdClassifier` (pure-Python, no
  `sklearn`) trained on 784 samples from 7 repos; `accuracy=0.7962`,
  `precision=0.9524`, `recall=0.6742`.
- Replaced `models/training_data.json` and `models/slop_classifier.pkl` with
  live representations.

**SKILL.md — CLI surface documented**
- `--emit-leda-yaml` / `--leda-output` / `--leda-profile`
- `--cross-file`, `--governance`, `--gate` vs `--ci-mode hard` distinction.

### Fixed

**SKILL.md — 10 OSOT violations (Sentinel-verified)**
- G1: `ddc` default weight corrected `0.30 → 0.20` (matches `core.py`).
- G2: `/slop-gate` split — `--gate` (SNP) vs `--ci-mode hard` (CIGate).
- G3: `DEPENDENCY_NOISE` status documented with exact trigger.
- D1: Project-level `CRITICAL_DEFICIT` threshold `weighted_deficit_score >= 50`.
- D2: CI hard gate 4 conditions documented.
- D4: `domain_overrides` YAML corrected — per-function exemption.
- D5: Self-calibration two-gate structure documented.

---

## v3.6.0 — 2026-04-27

### Added

**Claude Code Skill**
- `claude-skills/slop-detector/SKILL.md` — installable Claude Code skill with four
  slash commands: `/slop`, `/slop-file [path]`, `/slop-gate`, `/slop-spar`
- Implements `scan -> patch -> re-scan -> gate` quality loop with per-pattern fix
  guidance, delta reporting, and session-persistent review criteria
- `docs/CLAUDE_CODE_SKILL.md` — full skill documentation (install, commands,
  metric explanation, patch reference, calibration guide)
- README `Claude Code Skill` section with install instructions and loop diagram

### Fixed

**Documentation**
- `What It Detects`: "Three metric axes" corrected to "Four metric axes"; Purity
  row added (`exp(-0.5 x n_critical_patterns)`)
- Scoring Model: normalization note added — weights sum to 1.10; GQG divides by
  `total_w` (self-normalizing, matches `docs/MATH_MODELS.md`)
- Quick Start: `pip install "ai-slop-detector[go]"` extra added (was missing)
- Positioning line added: "Not a style linter. A structural-risk scanner for AI-assisted code."

### Removed

- `tests/manual_test/audit_report.md`, `audit_report_full.md`, `report.md` —
  stale artifacts from previous manual runs

### Tests

311 passed (was 308 in v3.5.0)

---

## v3.5.0 — 2026-04-13

### Added

**Domain-aware `--init` (8 profiles)**
- `DOMAIN_PROFILES` in `config.py`: `general`, `scientific/ml`, `scientific/numerical`,
  `web/api`, `library/sdk`, `cli/tool`, `bio`, `finance` — each with a tuned
  `capability_vector` (ldr/inflation/ddc/purity weights) and `pattern_config` thresholds.
- `--init` auto-detects domain from imports; `--domain` flag for explicit override.
- Generated `.slopconfig.yaml` is pre-seeded with the domain's weight profile.

**JS/TS analysis — JSAnalyzer v2.8.0 + `[js]` optional dep**
- Activates for `.js/.jsx/.ts/.tsx`; tree-sitter AST with regex fallback.
- Results in `ProjectAnalysis.js_file_results`.

**Go analysis — GoAnalyzer v1.0.0 + `[go]` optional dep**
- Regex-based detection for `.go`: empty stubs, panic-as-error, fmt debug prints,
  ignored errors, TODO/FIXME, god functions. Results in `go_file_results`.

**Self-calibration patches (P1–P5)**
- **P5** — removed dead `float("inf")` guard in `_recompute_deficit`; upstream caps at 10.0.
- **P1 — Schema v5** (`project_id TEXT`): every history record now tagged with
  `sha256[:12]` of the scan's cwd. Prevents cross-project signal pollution in the
  global `~/.slop-detector/history.db`. Auto-migrated.
- **P2 — milestone trigger** replaced `count_total_records() % 10` with
  `count_files_with_multiple_runs(project_id) % 10`. A first-time N-file scan records
  N rows but zero repeat-file pairs — the old trigger was a false milestone.
- **P3 — domain-anchored grid search**: `_grid_search(domain_anchor=...)` constrains
  each dimension's range to `[anchor ± DOMAIN_TOLERANCE(0.15)]`. Auto-calibration
  passes current config weights as anchor.
- **P4 — `CalibrationResult.warnings`**: after a confident "ok" result, any weight
  deviating > `DOMAIN_DRIFT_LIMIT(0.25)` from the reference emits a warning string.
  Printed in `--self-calibrate` output (rich yellow / plain `[!]`).

**16 new unit tests** (`tests/test_calibration_patches.py`):
P2 count logic (6), P1 project_id isolation (3), P3 grid bounds (3), P4 warnings (4).

### Fixed

- **CI jq parse error** — `_check_calibration_hint()` prints redirected to `stderr`
  to prevent calibration text from contaminating `--json` stdout.
- **`float("inf")` in JSON** — `inflation.py` returns `10.0` (not `inf`) when
  `logic_lines == 0`; `json.dumps(..., allow_nan=False)` added as a fail-fast guard.
- **`avg_inflation` filter regression** — `math.isfinite()` check replaces brittle
  `status != "error"` guard.
- **`_sanitize_for_json` tuple support** — added `tuple` alongside `list`.
- **E2E calibration assertions** — check both `stdout` and `stderr` for milestone signals.

---

## v3.2.1 — 2026-04-11

### Added

**P1 — Auto-calibration at milestone (zero-config)**
- Every 10 scans (`CALIBRATION_MILESTONE`), calibration now runs automatically and
  writes updated weights to `.slopconfig.yaml` if it exists and calibration is confident.
- Prints a per-weight diff (`ldr: 0.40 -> 0.45`) for full auditability.
- Safety gates: only applies when `status == "ok"` — `CONFIDENCE_GAP < 0.10` and
  `no_change` both suppress the write correctly.
- Closes the full LEDA loop end-to-end: **"the more you use it, the smarter it gets"** —
  no manual `--self-calibrate` / `--apply-calibration` required.

**P2 — Git commit context as noise filter**
- `_get_git_context()` in `cli.py`: captures `git rev-parse --short HEAD` and
  `git branch --show-current` per run (3 s timeout, graceful `None` fallback).
- `history.py record()` stores `git_commit` and `git_branch` alongside each record.
- `self_calibrator.py _classify_run_pair()` uses git context:
  - Same commit + score drop → skip (measurement noise within one commit).
  - Different commit + stable file hash → skip (ambiguous signal).
  - `git_commit = NULL` → original hash heuristic unchanged (backward compatible).
- Fewer but higher-fidelity labeled events for more reliable calibration.

**P3 — Per-class minimum thresholds**
- `MIN_EVENTS = 20` replaced by `MIN_IMPROVEMENTS = 5` / `MIN_FP_CANDIDATES = 5`.
- `CALIBRATION_MILESTONE = MIN_IMPROVEMENTS + MIN_FP_CANDIDATES` (= 10).
- Each class checked independently: both must meet their floor before grid search runs.
  Prevents class-imbalanced calibration.
- 4D model's continuous tiebreak signal makes 5+5 statistically sufficient.

### Fixed

- `self_calibrator.py calibrate()`: default `min_events` was `CALIBRATION_MILESTONE` (10),
  causing `max(10, MIN_IMPROVEMENTS=5) = 10` per-class floor. Fixed to `MIN_IMPROVEMENTS` (5)
  so both classes require 5 — matching the 5+5 design intent.
- `cli.py _run_self_calibration()`: `getattr(args, "min_history", 20)` default corrected to 5.
- `--min-history` CLI default: 20 → 5 (per-class floor, not total event count).

---

## v3.2.0 — 2026-04-11

### Added

**4D calibration — purity dimension**
- `self_calibrator.py`: added purity as a 4th calibration dimension.
- `purity_score = exp(-0.5 * n_critical_patterns)` — tracks how many CRITICAL-severity
  pattern issues were detected; score = 1.0 (clean) and decays toward 0 with more criticals.
- Grid search extended to 4D simplex: `w_ldr + w_inflation + w_ddc + w_purity = 1.0`.
- `apply_to_config()` now writes all 4 weight keys to `.slopconfig.yaml`.
- Old history rows default `n_critical_patterns = 0` → backward compatible (purity_score = 1.0).

**`n_critical_patterns` history column (schema v2)**
- `history.db` gains `n_critical_patterns INTEGER NOT NULL DEFAULT 0`.
- Auto-migrated from schema v1. Records CRITICAL-severity pattern issues per run.
- Used by self-calibration purity dimension.

**`--init` bootstrap command**
- `slop-detector --init [path]` generates a fully documented `.slopconfig.yaml` in
  the target project (or `.` by default).
- Auto-detects project type (python / javascript / go).
- Automatically adds `.slopconfig.yaml` to `.gitignore` — creates `.gitignore` if missing,
  appends if present, skips if entry already exists.
- `--force-init` flag to overwrite an existing config.

**Auto-trigger calibration hints**
- After each scan, if total history records cross a 20-record milestone, prints:
  `[*] Calibration milestone: N history records. Run --self-calibrate to optimize weights.`
- Closes the full LEDA loop: `--init` → scan (auto-log) → hint → `--self-calibrate` → `--apply-calibration`.

**`_extract_events` refactored (no behaviour change)**
- Split into `_group_runs_by_file`, `_classify_consecutive_runs`, `_classify_run_pair`.
- Reduces max nesting depth from 4 to 3, CC from 11 to 3 per function.

**`.slopconfig.yaml` self-scan config**
- `weights:` block now includes `purity: 0.10`.
- Domain overrides added for `_grid_search`, `calibrate`, `apply_to_config`.
- Self-scan: **44/44 CLEAN**.

---

## v3.1.3 — 2026-04-11

### Fixed

**`ml/self_calibrator.py` — P1: `apply_to_config` comment preservation**
- Replaced `yaml.safe_load` + `yaml.dump` full-file rewrite with targeted regex in-place
  replacement. Comments, `domain_overrides`, and all other keys are preserved.

**`ml/self_calibrator.py` — P2: FP candidate deduplication**
- `seen_fp_files` set introduced; each file contributes at most one `fp_candidate` event.
  Prevents consecutive-run bias (50 unchanged runs → 49 fp_candidates → skewed weights).

**`ml/self_calibrator.py` — P4: MIN_EVENTS raised from 10 → 20**
- Minimum labeled events required for calibration raised to 20 for statistical reliability.

**`README.md` — P3: weight drift correction**
- `ddc` weight corrected from `0.20` to `0.30` in Scoring Model section.

### Security

**`.gitignore` — P5: slop-detector runtime artifacts**
- Added `.slop-detector/` to `.gitignore`.

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
