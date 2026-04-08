# Changelog

All notable changes to AI-SLOP Detector will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.1.1] - 2026-04-08

### Fixed

**Clone Detection visibility**
- `function_clone_cluster` results were only visible in the Issues section;
  Core Metrics table showed no duplication signal (reported via community issue).
- Fix: added "Clone Detection:" row to the Core Metrics table.
  CRITICAL/HIGH severity shown when `function_clone_cluster` fires; `PASS` otherwise.
  No model changes — reads from existing `pattern_issues` list.

**Table style unification (CLI UX)**
- Project-level output mixed three Rich table box styles
  (`SIMPLE`, `MINIMAL_DOUBLE_HEAD`, `ROUNDED`). All tables now use
  `box.ROUNDED` with `header_style="bold cyan"`.
- Jargon entries in File Analysis Notes column trimmed to first 3 terms
  + "+N more" — prevents column overflow on heavily-flagged files.
- File Analysis Status severity color extended to `critical_deficit` variant.

**VS Code extension (v3.1.1)**
- `extractJson()`: strips `[INFO]` log lines before `JSON.parse` — prevents
  parse failures when CLI emits log output alongside JSON.
- `recordHistory` setting now correctly passes `--no-history` to the CLI.
- Summary diagnostic message includes Clone Detection signal from `pattern_issues`.
- Status bar tooltip uses null-safe metric access and shows Clone PASS/CRITICAL.
- Workspace analysis: replaced single-line notification with a QuickPick list
  of deficit files sorted by score; clicking a file opens it in the editor.
- History Trends: formatted column table (Runs/Latest/Best/Worst/Trend)
  replaces raw JSON dump in Output panel.

**uv tooling**
- Added `.python-version` and `uv.lock` to `.gitignore`.

---

## [3.1.0] - 2026-04-08

### Added

#### Mathematical model corrections — three scoring formula fixes

**`ml/self_calibrator.py` — `_recompute_deficit`: arithmetic → geometric mean**
- The calibrator's objective function now mirrors GQG exactly.
  Previously used a weighted arithmetic mean; the scorer uses a weighted
  geometric mean. AM ≥ GM always, so the calibrator systematically
  underestimated deficit (~5-7pt gap), causing grid search to optimize
  weights against a biased objective.
- Fix: replaced `ldr*w + (1-inf)*w + ddc*w` with `exp(Σw_i*ln(v_i)/Σw_i)`.
  Purity excluded from calibrator (it depends on pattern count, not weights).

**`metrics/inflation.py` — complexity modifier baseline: cc=3 → cc=1**
- Previous formula: `max(1.0, 1.0 + (cc - 3.0) / 10.0)` created a "free zone"
  where cc=1,2,3 all produced modifier=1.0. Simple jargon-heavy functions with
  cc=2 paid zero complexity premium. Minimum meaningful cc is 1.
- Fix: `max(1.0, 1.0 + (cc - 1.0) / 10.0)`. cc=2 now gets modifier=1.10.

**`core.py` — purity weight configurable**
- `w_pur = 0.10` was hardcoded, invisible to the calibrator and non-configurable
  from `.slopconfig.yaml`.
- Fix: `w_pur = weights.get("purity", 0.10)`. Default unchanged.

#### New patterns — stub evasion and complexity fragmentation detection

**`return_constant_stub` (extended) — empty container stubs**
- `return {}`, `return []`, `return ()`, `return set()` now trigger
  `return_constant_stub` alongside existing `return True/False/"string"/0` detection.
- Same applies to `interface_only_class` placeholder check.

**`function_clone_cluster` (new) — DI2-based AST clone detection**
- Detects files where a large cluster of functions have near-identical AST
  node-type distributions (pairwise JSD < 0.05).
- Addresses the `complexity_hidden_in_helpers` adversarial evasion pattern:
  a god function split into N structurally identical one-liners evades all
  per-function gates (god_function, nested_complexity) but produces a measurable
  file-level signal.
- Thresholds: ≥ 6 clones → CRITICAL; ≥ 4 clones → HIGH.
- Algorithm: 30-dim AST histogram per function → pairwise JSD →
  BFS connected components. Ported and adapted from
  Protocol-ReGenesis-Engine `src/core/math_models.py` (itself a Python port
  of Flamehaven-TOE v4.5.0 `toe/math/di2.py`).
- New module: `metrics/stub_density.py` — `_jsd()`, `_node_histogram()`,
  `_find_largest_clone_group()`, `calculate_stub_density()`.

**`placeholder_variable_naming` (new, v1.0) — naming pattern detection**
- Two sub-checks:
  1. High single-letter parameter count: ≥ 5 single-letter params (excluding
     `self`, `cls`, `_`) → HIGH. E.g. `def process(a, b, c, d, e, f, g)`.
  2. Sequential numbered variable pattern: ≥ 8 in sequence → HIGH;
     ≥ 4 → MEDIUM. E.g. `r1, r2, r3 ... r12`.
- Addresses `vocab_clean_meaningless` adversarial evasion: meaningful-vocabulary
  code with zero semantic content evades all existing pattern gates, but
  placeholder naming is structurally detectable.
- v1.0 design note: detects naming **style**, not semantic quality. Known false
  positive zone: math/science libraries using single-letter variable conventions.
  Configure with `domain_overrides` or `--config ignore` to suppress.

#### fhval — SPAR-Code subcommand (`fhval spar`)

New `spar` subcommand in `fhval` (flamehaven-validator) providing a
3-layer adversarial regression loop for the scoring model:

- **Layer A** (ground truth anchors): 5 known code patterns with expected
  deficit ranges. Any deviation = scoring model regression.
  - `clean_trivial`: deficit ≤ 15 (regression guard)
  - `extreme_jargon`: deficit ≥ 40 (regression guard)
  - `stub_class_8_methods`: deficit ≥ 30 (was ANOMALY in v3.0.x)
  - `fragmented_god_function`: deficit ≥ 10 (was ANOMALY in v3.0.x)
  - `vocab_clean_meaningless`: deficit ≥ 8 (was ANOMALY in v3.0.x)
- **Layer B** (peer challenges): 4 documented architectural limitations
  with severity classification.
- **Layer C** (existence probes): 4 probes testing whether each metric
  measures what it claims (LDR genuineness, inflation blindspot, DDC
  annotation gap, calibrator consistency).

SPAR score progression: **55 FAIL → 85 PASS** after v3.1.0 fixes.

### Changed

- `patterns/__init__.py`: registered `FunctionClonePattern`,
  `PlaceholderVariableNamingPattern`.

### Notes

- All 188 tests pass. No public API changes.
- `vocab_clean_meaningless` SPAR check remains CONSISTENT via naming pattern
  detection (v1.0). The deeper semantic gap (arithmetic with no meaning) is
  documented in SPAR Layer C as a known scope limitation of static analysis.

---

## [3.0.3] - 2026-04-08

### Changed

#### Structural debt reduction — top-3 deficit files refactored (self-eating-own-dog-food)

Self-scan before: avg_deficit=23.57, 15 deficit files, status=suspicious
Self-scan after:  avg_deficit=20.33, 12 deficit files, status=**clean**

**`analysis/cross_file.py`** — deficit 70.3 → 28.7 (critical_deficit → clean)
- Extracted `_hash_function_body(func_node)` from `_extract_functions` — removes 4-deep nesting
- Rewrote `_extract_imports` using early-continue; removed single-value `for ext in (".py",)` loop
- Promoted nested `dfs()` closure to `_dfs(self, ...)` private method (was triggering nested_complexity as a closure inside `_detect_cycles`)
- Extracted `_build_exact_duplicate_pairs(hash_index)` from `_detect_duplicates` — separates hash indexing from pair enumeration

**`ci_gate.py`** — deficit 69.3 → 22.3 (inflated_signal → clean)
- Extracted `_classify_files(result)` — removes file-classification loop from `_evaluate_project`
- Added `_verdict_soft/hard/quarantine()` helpers — replaces 87-line if/elif/else mode dispatch with a dict-dispatch pattern; reduces `_evaluate_project` to ~20 lines
- Extracted `_evaluate_file_quarantine(result, verdict)` — removes nested QUARANTINE branch from `_evaluate_file`
- Extracted `_has_uncovered_production_claims(ctx_jargon)` — flattens the 4-deep loop in `_check_claims_evidence`
- Replaced `for file_result in result.file_results: if ...: break` with `next()` in `_update_quarantine`
- Moved production-claim strings to `_PRODUCTION_CLAIMS` class constant (was re-declared inline)

**`cli.py`** — deficit 68.4 → 20.9 (inflated_signal → clean)
- Extracted `_categorize_pattern(pattern) → str` — removes 4-branch if/elif from `list_patterns`
- Extracted `_print_pattern_category(category, patterns)` — removes triple-nested print loop
- Extracted `_file_has_production_claims(f_res)` — removes 4-deep evidence-detail loop from `_collect_test_evidence_stats`; moved shared production-claim set to `_PRODUCTION_CLAIMS_CLI` module constant
- Extracted `_write_json_output(args, result)` — removes `if args.output:` nesting inside `if args.json:`
- Extracted `_route_file_output(out, result, rich_ok)` — separates format routing from `_handle_output` dispatcher
- Extracted `_run_analysis_phase(args, detector)` — removes inner `if args.project:` branch from `main`'s try block
- Extracted `_text_file_lines(fr)` — removes 4-deep jargon-detail loop from `_text_project_section`; converts inner for-with-if to list comprehension

**`.slopconfig.yaml`** — Rule-0 false-positive prevention
- Added explicit `# RULE-0 NOTE` block documenting that `tests/corpus/` and `__init__.py` are intentional slop fixtures and packaging boilerplate respectively
- Documents correct invocation: `--config .slopconfig.yaml` is required when running SIDRCE or slop-detector from project root

All 188 tests pass. No public API changes.

---

## [3.0.2] - 2026-03-15

### Fixed

#### P0 — PhantomImportPattern: context-aware 3-tier import classification

**Project package auto-discovery** (`_find_project_root`, `_discover_project_packages`)
- Walks up to 12 directory levels to locate `pyproject.toml`, `setup.py`, `setup.cfg`, or `.git`.
- Scans the found root for internal project packages: `src/` layout, flat layout, and
  `[tool.setuptools.packages.find] where` directive.
- Parses `[project.dependencies]` and `[project.optional-dependencies]` to extract declared
  package names, stripping vendor prefixes (e.g. `flamehaven_nnsl` → `nnsl`).
- Results cached per-process (`_PROJECT_PACKAGES_CACHE`) — zero repeated I/O within a run.

**Import guard detection** (`_collect_import_guard_lines`, `_IMPORT_GUARD_EXC_NAMES`)
- AST walk of every `ast.Try` node in the file; collects line numbers of `import`/`from`
  statements inside `try` bodies whose `except` handlers catch any of:
  `ImportError`, `ModuleNotFoundError`, `Exception`, `BaseException`.
- Prevents false positives on broad-guard patterns (`except Exception:`) used in API adapter
  modules and framework bridges.

**3-tier classification** (`_make_issue`)

| Tier | Condition | Severity | Message |
|---|---|---|---|
| Internal | Module is part of current project | (skip) | — |
| Guarded | Import inside `try/except ImportError` block | MEDIUM | "Undeclared optional dependency" |
| Hard | Unresolvable, no guard | CRITICAL | "Phantom import" |

Result: eliminates the cascade where 252 project-internal phantom hits drove `DDC → 0`,
`GQG → ln(1e-4)`, and `deficit_score → 100` for every file in a src-layout project.

---

#### P1 — LDR: packaging `__init__.py` no longer collapses GQG

- `ldr.calculate()` now detects empty (content-free) `__init__.py` files before computing the
  ratio. Empty packaging init → `ldr_score=1.0`, `grade="N/A"`, `is_packaging_init=True`.
- Prevents `total_lines=0` → `ldr_score=0.0` → `GQG → ln(1e-4)` cascade on standard
  `src/<pkg>/__init__.py` files.
- `LDRResult` model: new `is_packaging_init: bool = False` field, serialized via `to_dict()`.

---

#### P2 — GodFunctionPattern: length-only paths demoted to LOW

Previously any function exceeding `lines_threshold` OR `complexity_threshold` was flagged HIGH.
This produced false positives on verbose-but-simple domain code: physics constant tables,
routing dispatch blocks, and rule interpreters with low cyclomatic complexity.

New severity routing:

| Condition | Severity |
|---|---|
| `cc > complexity_threshold` (regardless of length) | HIGH |
| `lines > lines_threshold` AND `cc > complexity_threshold` | HIGH |
| `lines > lines_threshold` AND `cc <= 5` | LOW |

---

#### P3 — Placeholder pattern precision

**`NotImplementedPattern`** — skip `@abstractmethod`
- `raise NotImplementedError` inside an `@abstractmethod`-decorated method is the correct
  Python ABC pattern, not a placeholder. Added the same decorator check already present in
  `PassPlaceholderPattern`.

**`EmptyExceptPattern`** — rewritten as 3-tier

| Handler | Severity | Message |
|---|---|---|
| Bare `except: pass` | CRITICAL | "Bare 'except: pass' swallows all exceptions including SystemExit" |
| `except (ImportError\|ModuleNotFoundError): pass` | LOW | "optional dependency guard; verify this is intentional" |
| `except SomeType: pass` | MEDIUM | "silently discards the exception" |

**`InterfaceOnlyClassPattern`** — `return self`/`return cls` counted as placeholder
- Method-chaining stubs (`return self`) provide no meaningful domain value in an otherwise
  unimplemented class. Now counted toward the placeholder threshold.

---

### Validation

- Applied to Flamehaven-TOE v4.5.0 (83 files, src-layout, 11 optional deps):
  - Before: 252 CRITICAL phantom imports, deficit_score=100 on all files, status=`critical_deficit`
  - After: 0 CRITICAL phantom imports, 11 MEDIUM (correctly classified optional deps),
    deficit_score avg ~18.1, status=`clean`
- 188 tests pass; ruff + mypy clean.

---

## [3.0.1] - 2026-03-10

### Added

**D4 — ReturnConstantStubPattern** (`return_constant_stub`, HIGH)
- New pattern detecting functions whose entire body (excluding docstring) is a single
  `return <constant>` statement (`return 42`, `return True`, `return "ok"`, etc.).
- Targets the `ldr_gaming` / `stub_with_real_structure` adversarial evasion:
  dense one-liner stubs score high on LDR but carry zero semantic value.
- Excluded: dunder methods (`__len__`, `__bool__`, `__hash__`, ...) which legitimately
  return constants; `@abstractmethod` decorated functions; `return None` (already covered
  by `ReturnNonePlaceholderPattern`).
- `InterfaceOnlyClassPattern` updated to also count `return <constant>` methods as placeholders.

**D2 — Configurable god_function thresholds with domain_overrides**
- `GodFunctionPattern` now accepts `complexity_threshold`, `lines_threshold`, and
  `domain_overrides` constructor arguments.
- Thresholds configurable per-project via `.slopconfig.yaml`:
  ```yaml
  patterns:
    god_function:
      complexity_threshold: 10    # default
      lines_threshold: 50         # default
      domain_overrides:
        - function_pattern: "evaluate"    # fnmatch wildcard supported
          complexity_threshold: 80
          lines_threshold: 300
  ```
- `function_pattern` uses `fnmatch` — supports `evaluate`, `validate_*`, `check_?`, etc.
  First matching override wins. Falls back to global thresholds if no match.
- `Config.get_god_function_config()` added; `core.py` passes it to `get_all_patterns()`.
- Rationale: clinical governance engines, rule interpreters, and safety systems have
  inherent domain complexity that is not accidental. A single config entry suppresses
  false positives without disabling the pattern globally.

### Fixed

- `get_all_patterns()` now accepts optional `god_function_config` dict — no breaking change,
  default behavior (cc=10, lines=50, no overrides) is identical to v3.0.0.

---

## [3.0.0] - 2026-03-09

### Added

#### CQMS Level 2 — Code Quality Metric Space (Mathematical Foundation)

**DCF (Distributional Code Fingerprint)**
- `_compute_dcf(tree)` module-level function: `P(node_type | file) = count(node_type) / total_nodes`.
  Genuine probability distribution over AST node types; values in [0,1], sum to 1.
- `FileAnalysis.dcf: Dict[str, float]` — stores the DCF for each analyzed file.
- `analyze_file()` and `analyze_code_string()` now compute and attach DCF (reuses already-parsed AST).

**GQG (Geometric Quality Gate)**
- `_calculate_slop_status` now uses weighted geometric mean (GQG) instead of arithmetic mean.
- Formula: `Omega = exp(sum(w_i * ln(max(1e-4, v_i))) / sum(w_i))`
- AND-gate property: any dimension collapsing to 0 drives Omega to 0; no compensation.
- Dimensions: ldr (w=config), inflation_q (w=config), ddc (w=config), purity (w=0.10 fixed).
- Purity: `exp(-0.5 * n_critical_patterns)` — exponential penalty for CRITICAL-severity patterns.

**MST H0 VR Structural Coherence**
- `_js_divergence(p, q)` — Jensen-Shannon divergence in [0,1] (log-base-e, normalized).
- `_compute_coherence_vr(file_dcfs)` — MST H0 persistence coherence over file DCFs.
  `coherence = 1 - max_mst_edge` where max_mst_edge = longest edge in Prim's MST of
  pairwise sqrt-JSD distances. Epsilon-free; equivalent to max H0 persistence in
  the Vietoris-Rips filtration.
- `analyze_project()` now collects `file_dcfs` and computes structural coherence when >= 2 files.
- `ProjectAnalysis.structural_coherence: float` — 1.0 = all files structurally uniform.
- `ProjectAnalysis.coherence_level: str` — "vr_structural" when computed, "none" otherwise.

**Gate comment fix**
- `gate/slop_gate.py`: `_normalize_jsd()` now documents that the `jsd` key is not
  information-theoretic JSD. Key name preserved for SNP contract backward compatibility.
  True DCF-JSD is available via `FileAnalysis.dcf` (v3.0+).

### Changed
- `_calculate_slop_status`: arithmetic mean replaced with GQG (breaking: scoring values change).
- `DEPENDENCY_NOISE` override now guarded by `not critical_patterns and inflation <= 1.0`
  to prevent mislabeling multi-cause failures as dependency noise under GQG.

---

## [2.9.3] - 2026-03-09

### Added

#### Self-Calibration Engine — `--self-calibrate`
- New `src/slop_detector/ml/self_calibrator.py` — adaptive weight optimizer.
- Labels derived from **user behaviour**, not formula outputs (breaks tautology):
  - `improvement_event`: deficit > 25 in run[i], dropped > 10 in run[i+1] → user fixed it
  - `fp_candidate`: deficit > 25, same file_hash in next run, no change → user ignored it
- Grid search over weight simplex `{w_ldr + w_inflation + w_ddc = 1.0, wi ∈ [0.10, 0.65]}`
  at 0.05 resolution (no new dependencies — pure stdlib + yaml).
- Continuous tiebreaker (LEDA MetaLearning pattern): when candidates tie on binary FN+FP rate,
  secondary sort by `avg_fp_deficit − avg_tp_margin` breaks the tie.
- Copilot Guardian-style confidence gap: if gap between #1 and #2 < 0.10, reports
  `insufficient_data` rather than applying a weakly-supported calibration.
- `--apply-calibration [CONFIG]`: writes optimal weights to `.slopconfig.yaml` (default)
  only when `status == ok`.
- `--min-history N`: override minimum event threshold (default: 10).
- CLI output: 3-panel Rich layout (status, event counts, weight delta table with ± colors).

**First live run on Flamehaven history.db (180 unique files, 62 improvements, 176 FP candidates):**
| | Current | Optimal |
|---|---|---|
| ldr | 0.40 | 0.10 |
| inflation | 0.30 | 0.25 |
| ddc | 0.30 | 0.65 |
| combined error | 1.1069 | 0.9985 |
| confidence gap | — | **0.1088** |

Interpretation: high FN rate (91.9%) against metric-only recomputed deficits indicates
pattern penalties dominate this codebase's scoring. Weight calibration operates on the
metric component only; pattern-driven deficits are orthogonal and unaffected.

---

## [2.9.2] - 2026-03-09

### Fixed

#### Rich 3-Panel Single-File UI — Reconnected Missing Feature
- `_render_rich_single_file` was rendering a single `box.DOUBLE` panel containing
  raw key-value text — inconsistent with the documented 3-panel layout described
  in README and shown in interface screenshots.
- Reconnected the intended design:
  - **Panel 1** (`box.ROUNDED`): File path, status badge, deficit score — right-aligned.
  - **Panel 2** (`box.ROUNDED`): LDR / ICR / DDC / Justification Ratio / ML Prediction
    with per-row color coding (red/yellow/green).
  - **Panel 3** (`box.ROUNDED`): Review questions with inline severity badges
    (`[CRITICAL]` red, `[WARNING]` yellow, `[INFO]` blue).
- Header banner unified to `box.ROUNDED` to match panel chrome.
- Helpers added: `_build_header_table`, `_build_metrics_table`, `_build_questions_panel`.
- Single-file text-report path (`_build_single_file_content`) preserved unchanged.

---

## [2.9.1] - 2026-03-08

### Changed

#### Self-Inspection Patch — cli.py God Function Decomposition
- `print_rich_report()` split into six focused helpers:
  `_build_rich_summary_tables`, `_build_rich_files_table`,
  `_render_rich_project`, `_build_single_file_content`,
  `_append_pattern_issues_rich`, `_render_rich_single_file`.
  Each is now ≤ 40 logic lines.
- `main()` extracted to `_build_arg_parser()`, `_evaluate_ci_gate()`,
  `_run_optional_features()`. Complexity reduced from 25 → 14.
- `_handle_output()` refactored with `_write_file()` helper; nesting depth
  reduced from 5 → 3.
- `generate_markdown_report()` split into `_md_summary_section()`,
  `_md_test_evidence_section()`, `_md_findings_section()`.
- `generate_text_report()` split into `_text_project_section()` and
  `_text_single_file_section()`.

#### DDC False-Positive Fix — registry.py and question_generator.py
- Both files had `DDC = 0.00` because `BasePattern` / `FileAnalysis` were
  imported only for type annotations, which `UsageCollector` correctly skips.
- Fix: annotation-only project imports moved under `if TYPE_CHECKING:` guard.
  DDC now correctly classifies them as type-checking imports (excluded from
  usage ratio), resolving the false positive without changing runtime behavior.
- `registry.py`: added `from __future__ import annotations`, replaced eager
  `global _global_registry` lazy-init pattern with module-level eager
  initialization (eliminates `global` statement, DDC HIGH flag).
- `question_generator.py`: restored `from __future__ import annotations`,
  converted Python 3.10+ union syntax (`int | None`, `str | None`,
  `list[Q]`, `dict[...]`) to `Optional[int]`, `Optional[str]`,
  `List[Q]`, `Dict[...]` for Python 3.8 compatibility.

### Fixed
- Self-inspection result (dogfooding on own `src/`):
  - `deficit_files`: 3 → **0** (cli.py 53.5→29.1, registry.py 39.5→clean,
    question_generator.py 30.0→clean)
  - `avg_deficit_score`: 11.65 → **9.57**
  - `weighted_deficit_score`: 15.88 → **12.42**
  - `overall_status`: clean (unchanged)
- 188 tests pass; ruff + mypy clean.

---

## [2.9.0] - 2026-03-08

### Added

#### PhantomImportPattern — Hallucinated Package Detection (CRITICAL)
- New pattern `phantom_import` detects imports referencing packages that do not exist
  in the current environment: not in stdlib, built-in C extensions, or installed distributions.
- Resolution index built once per process from three sources:
  1. `sys.builtin_module_names` — C extension modules
  2. `sys.stdlib_module_names` — standard library (Python 3.10+)
  3. `importlib.metadata.packages_distributions()` — pip-installed packages
- `importlib.util.find_spec` fallback covers namespace packages and editable installs.
- Relative imports (`from . import X`) excluded — local project structure is environment-dependent.
- Severity: **CRITICAL**, Axis: **QUALITY**, ID: `phantom_import`
- Errs toward False Negative on resolution errors to avoid false positives.

#### History Auto-Tracking (v2.9.0)
- Every CLI run automatically records results to `~/.slop-detector/history.db` (SQLite).
- Schema: `deficit_score`, `ldr_score`, `inflation_score`, `ddc_usage_ratio`,
  `pattern_count`, `grade`, `git_commit`, `git_branch`, `file_hash` (SHA256 prefix).
- Auto-migration on first run — safe `ALTER TABLE` for schema evolution.
- New CLI flags:
  - `--show-history` — per-file trend table (timestamp, deficit, LDR, patterns, grade)
  - `--history-trends` — project-wide daily aggregates for last 7 days
  - `--export-history <path>` — full JSONL export for ML training pipeline
  - `--no-history` — opt-out from recording this run
- Trend analysis: direction indicator (improved / degraded / stable) + delta across N runs.
- `export_jsonl()` produces training-ready JSONL for `DatasetLoader.load_jsonl()`.

#### Real Training Data Pipeline (`[ml-data]` extra)
- `MLPipeline.run_on_real_data()`: loads CodeSearchNet / the-stack / custom JSONL,
  applies self-supervised labelling (`deficit_score >= 30 → slop`), trains classifier.
- `DatasetLoader`: `load_codesearchnet()`, `load_stack()`, `load_jsonl()`.
- New extra: `pip install "ai-slop-detector[ml-data]"` (scikit-learn + numpy + datasets>=2.9.0).
- `datasets` added to `full` extra and mypy ignore list.

#### Core Identity Reframe
- README primary statement updated to reflect the project's ontology:
  *"Catches the slop that AI produces — before it reaches production."*
  Authorship (human / Claude / Cursor / custom agent) is irrelevant; the code speaks for itself.

### Changed
- `history.py` fully rewritten: `bcr_score` → `inflation_score` (v2.8.0 alignment),
  `pattern_count` added, global DB path `~/.slop-detector/history.db`,
  `export_jsonl()` replaces `export_history()`.
- `RandomForestClassifier` now trained with `class_weight="balanced"` to handle
  real-data class imbalance (~4% slop rate in public datasets).
- `load_codesearchnet()`: removed deprecated `trust_remote_code=True` (datasets>=4.x).
- `pyproject.toml` version: `2.8.0` → `2.9.0`.

### Fixed
- `--show-history` resolves relative paths to absolute before DB lookup.

---

## [2.8.0] - 2026-03-07

### Added

#### Python Advanced Pattern Detectors (AST-based)
- **`god_function`** (HIGH): flags functions where `logic_lines > 50` OR
  `cyclomatic_complexity > 10`. Complexity computed as
  `1 + count(If, For, While, ExceptHandler, With, BoolOp)`.
- **`dead_code`** (MEDIUM): detects statements after terminal nodes
  (`return`, `raise`, `break`, `continue`) in any block, including `orelse`,
  `finalbody`, and exception handler bodies.
- **`deep_nesting`** (HIGH): detects control-flow nesting depth > 4.
  Depth is computed recursively over `If/For/While/With/Try` bodies.
- New file: `src/slop_detector/patterns/python_advanced.py`
- `patterns/__init__.py` registers all three via `get_all_patterns()`

#### JS/TS Tree-Sitter Analysis (`[js]` extra)
- Full AST-based analysis: cyclomatic complexity, god function, dead code,
  callback hell detection — replaces regex-based heuristics when tree-sitter
  is available
- `FunctionMetrics` dataclass: per-function complexity, max depth, is_god_function
- `JSFileAnalysis` extended with: `function_metrics`, `max_complexity`,
  `god_function_count`, `dead_code_count`, `ast_mode`
- Graceful fallback to regex when `tree-sitter` is not installed

#### ML Secondary Signal (`[ml]` extra)
- `MLScore` dataclass: `slop_probability`, `confidence`, `model_type`,
  `agreement`, `features_used`
- `MLScorer.from_model(path)` — returns `None` silently on missing model
  or missing scikit-learn; zero import overhead without the extra installed
- `FileAnalysis.ml_score` field (v2.8.0, `Any = None`)
- `SlopDetector.__init__` accepts optional `model_path: Path` parameter
- `MLScore.label` property: `"slop"` (>= 0.70), `"uncertain"` (>= 0.40),
  `"clean"` (< 0.40)
- Agreement: `(deficit_score >= 30) == (slop_probability >= 0.40)`
- New file: `src/slop_detector/ml/scorer.py`
- `MLScore`, `MLScorer` exported from `slop_detector.__init__`

#### CLI Improvements
- `print_rich_report()` single-file panel: Pattern Issues section (severity-
  sorted, top 10 + overflow count), Advanced summary (`N god-fn, N dead-code,
  N deep-nest`), ML Score section (probability, confidence, model_type,
  agreement) — shown only when model is present
- `list_patterns()` now includes "Python Advanced" category

#### VS Code Extension
- Summary diagnostic message includes ML score when `result.ml_score` present
- Status bar tooltip includes ML confidence and label
- New pattern IDs (`god_function`, `dead_code`, `deep_nesting`) automatically
  appear as diagnostics via existing generic `pattern_id` code handler

#### Documentation
- `docs/MATH_MODELS.md` — comprehensive mathematical specification of all
  scoring formulas, thresholds, SR9 aggregation, AST models, ML feature
  vector, and formula change history

#### Packaging
- New extras: `js`, `ml-full`, `full`
- `ml` extra no longer includes xgboost (moved to `ml-full`)
- `requires-python` raised from `>=3.8` to `>=3.9`

### Changed

#### Inflation Score Formula (ICR) — Breaking
- Complexity now **amplifies** jargon penalty (`max(1.0, 1+(cc-3)/10)`)
  instead of dividing it
- Formula: `min((jargon/logic_lines) * complexity_modifier * 10, 10.0)`
- A function with complexity=13 receives 2x penalty vs. complexity=3

#### Status Determination — Breaking
- Single monotonic axis on `deficit_score` replaces multi-branch logic
- `INFLATED_SIGNAL` threshold: `deficit_score >= 50`
- `SUSPICIOUS` threshold: `deficit_score >= 30`
- `CRITICAL_DEFICIT` threshold: `deficit_score >= 70`
- Two supplementary overrides: critical-pattern count and DDC ratio

#### Project LDR — SR9 Conservative Aggregation
- `project_ldr = 0.6 * min(file_ldrs) + 0.4 * mean(file_ldrs)`
- Worst file weighted 60% to prevent masking by majority of clean files

#### Jargon Justification — Function-Scoped
- Justification scope changed from file-level to per-function scope
- Scope includes decorator lines (`scope_start = min(decorator.lineno)`)
- One import no longer justifies jargon across the entire file

#### ML Feature Vector
- `bcr_score` renamed to `inflation_score`
- 3 new features added: `god_function_count`, `dead_code_count`,
  `deep_nesting_count`
- Total: 16 features (was 13)

#### `MLScore.to_dict()` — Python 3.14 Compatibility
- Explicit `bool()`, `float()`, `int()` casts for JSON serialization

---

## [2.7.0] - 2026-02-12

### Added - VS Code Extension v2.7.0
- **Docstring inflation diagnostics**: Line-level detection from `docstring_inflation.details[]` with severity mapping (critical -> Error, warning -> Warning)
- **Context jargon evidence diagnostics**: Flags unjustified claims from `context_jargon.evidence_details[]` where `is_justified === false`
- **Hallucinated dependency diagnostics**: Surfaces `hallucination_deps.hallucinated_deps[]` as Info-level diagnostics
- **Pattern fix suggestions**: Appends `suggestion` field to pattern issue messages when present
- **Lint-on-type debounce**: 1500ms debounce timer prevents excessive analysis during typing
- **LDR grade in status bar**: Tooltip now displays `LDR Grade: {grade}`

### Changed
- VS Code extension surfaces ~95% of CLI JSON output (up from ~40%)
- Version alignment: `pyproject.toml`, `__init__.py`, `package.json` all at 2.7.0

---

## [2.6.4] - 2026-02-08

### Fixed
- **run_scan ignore handling**: `run_scan.py` now applies configured ignore patterns before file analysis.
- **Fixture exclusion consistency**: Paths matched by config ignore rules (for example `tests/**`) are excluded from scanner input.
- **Scan/report alignment**: `run_scan.py` behavior now aligns with `SlopDetector.analyze_project()` path filtering.

### Changed
- **Pattern matching implementation**: Added normalized path matching with `fnmatch`, including compatibility handling for `**/` prefixes.

---

## [2.6.3] - 2026-01-16

### Added - Consent-Based Complexity (Phase 1)

**Core Feature**: Allow developers to explicitly whitelist intentional complexity, shifting responsibility from the tool to the sovereign developer.

#### @slop.ignore Decorator
- **New decorator**: `@slop.ignore(reason="...", rules=[...])` to mark functions as intentionally complex
- **Reason required**: All ignored functions must provide explanation
- **Selective rules**: Optionally ignore specific rules only (LDR, INFLATION, DDC, PLACEHOLDER)
- **AST detection**: Decorator detected at analysis time, not runtime
- **Filtered issues**: Pattern issues inside ignored functions are excluded from reports

#### Innovation Zone Exemptions
- **Playground directories**: `playground/`, `labs/`, `experiments/`, `prototypes/`, `sandbox/` now exempt from strict analysis
- **Configuration**: New `consent_complexity` section in `.slopconfig.yaml`
- **Report tracking**: Ignored functions logged in "Whitelisted Complexity" section

#### Usage Examples
```python
import slop

@slop.ignore(reason="Bitwise optimization for O(1) performance")
def fast_inverse_sqrt(number):
    # Complex but intentional implementation
    i = 0x5f3759df - (number >> 1)
    return i

@slop.ignore(reason="Domain algorithm", rules=["LDR"])
def complex_calculation():
    # Only LDR check ignored, other rules still apply
    ...
```

### Changed
- **Version alignment**: Unified version to 2.6.3 (was incorrectly showing 3.0.0)
- **FileAnalysis model**: Added `ignored_functions` field
- **Pattern detection**: Now filters issues from ignored function ranges

### Technical Details
- **New files**:
  - `src/slop_detector/decorators.py` (decorator implementation)
  - `tests/test_ignore_pattern.py` (10 test cases)
- **Modified files**:
  - `src/slop_detector/core.py` (+100 lines: AST detection, filtering)
  - `src/slop_detector/models.py` (+15 lines: IgnoredFunction dataclass)
  - `src/slop_detector/__init__.py` (exports)
  - `.slopconfig.example.yaml` (new sections)

### Philosophy
> "Rules should be the soil for the dream to grow, not the cage that kills it."

This release implements the "Dream-Saver Protocol" from SIDRCE_SLOP_EVOLUTION_PLAN.md, ensuring that innovation is not killed by overly strict enforcement.

---

## [2.6.2] - 2026-01-15

### Added - Integration Test Evidence Detection

**Thanks to [@OnlineProxy](https://onlineproxy.io/) for the critical feedback:** *"CI is green, but 0 integration tests"* — This release addresses exactly that gap.

#### Phase 1 + 2: Core Detection (v2.6.2-alpha)
- **Split test evidence**: `tests` → `tests_unit` + `tests_integration`
- **4-layer detection**:
  1. Path-based: `tests/integration/`, `e2e/`, `it/`
  2. File name: `test_integration_*.py`, `*_integration_test.py`
  3. Pytest markers: `@pytest.mark.integration`, `@pytest.mark.e2e`
  4. Runtime signals: `TestClient`, `testcontainers`, `docker-compose`
- **Enhanced EVIDENCE_REQUIREMENTS**:
  - `production-ready`: Now requires both `tests_unit` AND `tests_integration`
  - `enterprise-grade`: Now requires both test types
  - `scalable`: Now requires `tests_integration`
  - `fault-tolerant`: Now requires `tests_integration`
- **False positive prevention**: `_is_real_test_file()` excludes helper files

#### Phase 3: Report Output (v2.6.2-beta)
- **Markdown reports**: New "Test Evidence Summary" section
  - Table showing unit vs integration test breakdown
  - Warning when integration tests missing but production claims exist
- **Text reports**: Test statistics in project summary
- **Enhanced questions**: Human-readable evidence names
  - `tests_integration` → "integration tests"
  - Special note: "Integration tests are critical for production claims"

#### Phase 4: Configuration & CI Gate (v2.6.2-rc)
- **Configuration Extension**: `.slopconfig.yaml` support for integration test detection
  - Customizable dir/file patterns, pytest markers, runtime signals
  - Quality claims validation requirements (production_ready, enterprise_grade, scalable, fault_tolerant)
- **CI Gate Claim-Based Mode**: `--ci-claims-strict` flag
  - Fails build if production/enterprise/scalable/fault-tolerant claims lack integration tests
  - Integrates with existing soft/hard/quarantine modes

### Changed
- **Evidence tracking**: 14 types → 15 types (split tests into unit/integration)
- **Context-jargon coverage**: 74% → 95% (+21%)
- **Question readability**: Raw evidence names replaced with formatted versions

### Technical Details
- **Tests**: 170/170 passed (165 existing + 5 new)
- **Coverage**: 85% overall
- **New files**:
  - `tests/test_integration_evidence.py` (5 tests)
- **Modified files**:
  - `src/slop_detector/metrics/context_jargon.py` (+47 lines)
  - `src/slop_detector/cli.py` (+43 lines)
  - `src/slop_detector/question_generator.py` (+14 lines)
  - `README.md` (updated evidence list)

### Contributing
Special thanks to community feedback that drives these improvements. This release demonstrates responsive development based on real-world usage patterns.

---

## [2.6.1] - 2026-01-12

### Added
- **Configuration Sovereignty**: Externalized CATEGORY_MAP and INTENT_PATTERNS to `src/slop_detector/config/known_deps.yaml`
- **Question Generator Tests**: Comprehensive test suite with 8 test cases
- **VS Code Extension**: Synchronized to v2.6.1

### Changed
- **Hallucination Dependencies**: Refactored to load configuration dynamically from YAML
- **Test Coverage**: Increased from 43% to 85% (overall), question_generator.py: 11% → 88%

### Fixed
- **Import Issues**: Resolved test import conflicts
- **Documentation**: Updated all version references to 2.6.1
- **Date Consistency**: Unified all dates to 2026-01-12

### Technical Details
- **Tests**: 165/165 passed (100% pass rate)
- **Coverage**: 85% overall (target: 80%, achieved: +5%)
- **New Module Coverage**: 88-92% (all above 90% target)
  - context_jargon.py: 91%
  - docstring_inflation.py: 89%
  - question_generator.py: 88%
  - hallucination_deps.py: 92%

---

## [2.6.0] - 2026-01-12

### Added - 6 Killer Upgrades (Phase 2 Complete)

#### 1. Context-Based Jargon Detection
- **Evidence-based validation** for quality claims (production-ready, enterprise-grade, etc.)
- **14 evidence types**: error_handling, logging, tests, input_validation, config_management, monitoring, documentation, security, caching, async_support, retry_logic, design_patterns, advanced_algorithms, optimization
- **Justification ratio**: `justified_claims / total_claims`
- **Missing evidence reporting**: Specific feedback on what's lacking per claim
- Cross-validation of buzzwords against actual codebase artifacts

#### 2. Docstring Inflation Analysis
- **Ratio-based detection**: `docstring_lines / implementation_lines`
- **Severity levels**: CRITICAL (>=2.0x), WARNING (>=1.0x), INFO (>=0.5x)
- **Per-entity tracking**: Functions, classes, and modules analyzed separately
- **File-level aggregation**: Overall ratio and top 10 offenders
- Detects AI-generated documentation without substance

#### 3. Placeholder Pattern Catalog
- **5 new patterns added**:
  - `NotImplementedPattern` (HIGH) - Functions raising NotImplementedError
  - `EmptyExceptPattern` (CRITICAL) - Empty exception handlers
  - `ReturnNonePlaceholderPattern` (MEDIUM) - Functions only returning None
  - `InterfaceOnlyClassPattern` (MEDIUM) - Classes with 75%+ placeholder methods
  - `EllipsisPlaceholderPattern` (HIGH) - Ellipsis-only functions
- **Total: 14 placeholder patterns** across 4 severity tiers
- Integration with existing pattern detection system

#### 4. Hallucination Dependencies
- **12 purpose categories**: ML, Vision, HTTP, Database, Async, Data, Serialization, Testing, Logging, CLI, Cloud, Security
- **60+ libraries tracked** across categories
- **Category-level usage analysis**: Detects unused ML stack, HTTP libs, etc.
- **Intent inference**: "Why was this dependency added?"
- Per-library and per-category reporting

#### 5. Question Generation UX
- **Actionable review questions** instead of raw scores
- **3 severity levels**: Critical, Warning, Info
- **Context-aware phrasing**: Line numbers, specific evidence, intent
- Examples:
  - "Why import 'torch' for ML but never use it?"
  - "'production-ready' claim lacks: error_handling, logging, tests"
  - "Function has 15 lines of docstring, 2 lines of code"
- Integrated into CLI output with Rich formatting

#### 6. CI Gate 3-Tier Enforcement
- **Soft Mode**: PR comments only, never fails (informational)
- **Hard Mode**: Fail build on thresholds (strict enforcement)
- **Quarantine Mode**: Track repeat offenders, escalate after 3 violations
- **Configurable thresholds**: deficit_score, pattern counts, inflation, DDC
- **Persistent tracking**: `.slop_quarantine.json` database
- **GitHub Action examples** provided
- CLI flags: `--ci-mode`, `--ci-report`

### Changed
- **Improved exception handling**: Specific exceptions instead of broad catch
- **Added encoding specifications**: UTF-8 for all file I/O operations
- **Removed unused imports**: Cleaned up ci_gate.py, question_generator.py

### Fixed
- Broad exception catching in quarantine DB load/save
- Missing encoding in file operations
- Unused variable in pattern question generation

### Technical Details
- **Files added**: 7 (ci_gate.py, docstring_inflation.py, hallucination_deps.py, context_jargon.py + 3 test files)
- **Lines of code**: ~2,500 new lines
- **Test coverage**: 68% overall, 90%+ for new modules
- **Pylint score**: 9.30/10
- **All tests**: 58/58 passed

---

## [Unreleased]

### Planned for v3.1 (Q3 2026)
- Advanced ML models with transfer learning
- Predictive quality scoring
- Real-time code analysis IDE integration

---

## [2.5.1] - 2026-01-10

### Fixed
- **Type Hint Detection**: Implemented proper `_is_in_annotation()` using NodeVisitor pattern for accurate import usage detection
- **API Compatibility**: Migrated `run_scan.py` to v2.x API (was using deprecated v1.x API)
- **Type Safety**: Enabled mypy type checking (removed `ignore_errors = true`)
- **Code Quality**: Removed dead code and unnecessary return statements

### Added
- **Comprehensive CLI Tests**: 58 test cases covering all CLI functionality (JSON, HTML, Markdown outputs)
- **Test Coverage**: Achieved 80% coverage on core modules (up from 26%)

### Changed
- **Coverage Measurement**: Focused on core modules (excluded enterprise features in beta)
- **Documentation**: Updated badges and status to reflect actual metrics
- **ASCII Safety**: Replaced emoji markers with ASCII equivalents in `run_scan.py`

### Includes all features from 2.5.0
- Polyglot architecture with LanguageAnalyzer interface
- Pattern refinement for anti-pattern detection
- Professional terminology (Deficit, Inflation, Jargon)
- Python-focused quality analysis

---

## [2.5.0] - 2026-01-09

### Added
- Re-architected `src/slop_detector/languages` with `LanguageAnalyzer` interface
- Robust `PythonAnalyzer` implementation
- Pattern-based detection system

### Changed
- Renamed metrics for clarity: Slop→Deficit, Hype→Inflation/Jargon
- Removed conflicting `slop_detector.py` from root

### Fixed
- Obfuscated regex patterns to prevent self-detection of TODO/FIXME tags

---

## [3.0.0] - PLANNED (Not Yet Implemented)

> **Note:** The following is a roadmap of planned features for v3.0.0.
> None of these features are implemented or benchmarked yet.
> Prototype code exists in `src/slop_detector/auth/` and `src/slop_detector/ml/`
> but is marked EXPERIMENTAL and not integrated with the core.

### Planned Features
- Multi-language support (JavaScript, TypeScript, Java, Go, Rust, C++, C#)
- Enterprise authentication (SSO via SAML 2.0, OAuth2/OIDC)
- Role-based access control (RBAC) with hierarchical permissions
- Tamper-proof audit logging (SQLite/PostgreSQL backend)
- Cloud-native deployment (Kubernetes Helm charts, Docker Compose)
- Compliance features (GDPR, SOC 2, HIPAA)

---

## [2.4.0] - 2026-05-15

### Added - REST API + Team Dashboard

#### REST API
- **FastAPI Server**: Production-ready REST API with OpenAPI docs
- **Endpoints**:
  - `POST /analyze/file`: Analyze single file with history tracking
  - `POST /analyze/project`: Full project analysis (async background tasks)
  - `GET /history/file/{path}`: Get file analysis history
  - `GET /trends/project`: Quality trends over time
  - `POST /webhook/github`: GitHub push event handler
  - `GET /status/project/{id}`: Real-time project status
- **Auto-documentation**: Swagger UI at `/docs`, ReDoc at `/redoc`
- **CORS Support**: Cross-origin requests for dashboard integration

#### Team Dashboard
- **Real-time Monitoring**: Auto-refresh every 30 seconds
- **Visualizations**: 
  - Overall quality score across all projects
  - Total files monitored
  - Critical issues count
  - 30-day quality trend chart (Chart.js)
- **Project List**: Quick overview with scores and grades
- **Alert System**: Recent warnings and critical issues
- **Dark Theme**: Developer-friendly UI with Tailwind-inspired design
- **ASCII-safe Icons**: Cross-platform compatible symbols

#### GitHub Integration
- **Webhook Handler**: Automatic analysis on push events
- **Changed Files Detection**: Only analyze modified/added files
- **Status Updates**: Post analysis results back to GitHub
- **Branch Filtering**: Configure which branches to monitor

#### CLI Enhancements
- **New Command**: `slop-api` to start REST API server
- **Server Config**: `--host`, `--port`, `--config` options
- **Background Mode**: Detached server execution

### Changed
- **Dependencies**: Added FastAPI, Uvicorn, Pydantic
- **Architecture**: Separated API layer from core logic
- **Data Models**: Pydantic models for request/response validation

### Technical Details
- **Performance**: Async/await for non-blocking operations
- **Scalability**: Background tasks for heavy operations
- **Security**: HMAC signature validation for webhooks (production)
- **Monitoring**: Health endpoint for uptime checks

---

## [2.3.0] - 2026-01-08

### Added - IDE Plugins + Historical Tracking

#### History Tracking System
- **HistoryTracker**: SQLite-based analysis history storage
- **Regression Detection**: Automatic detection when scores worsen
- **Trend Analysis**: Project-wide quality trends over time
- **File-level History**: Track individual file evolution
- **Export Capability**: Export history to JSON for external analysis

#### Git Integration
- **GitIntegration**: Extract commit/branch info automatically
- **Pre-commit Hook**: Automatic quality detection before commits
- **Staged Files Detection**: Only analyze files being committed
- **Fail on Regression**: Block commits with quality degradation

#### VS Code Extension (v2.3.0)
- **Real-time Linting**: Analyze on save or while typing
- **Inline Diagnostics**: Show warnings/errors directly in editor
- **Status Bar Integration**: Quick quality overview
- **Commands**:
  - Analyze Current File
  - Analyze Workspace
  - Show File History
  - Install Git Pre-Commit Hook
- **Configuration**: Customizable thresholds, auto-lint settings
- **Multi-language**: Python, JavaScript, TypeScript support

#### CLI Enhancements
- `--record-history`: Store analysis results in history DB
- `--show-history`: Display file analysis history
- `--fail-on regression`: Exit with error on quality degradation
- `--install-git-hook`: Setup pre-commit hook automatically

### Changed
- History database stored in `.slop_history.db` by default
- CLI now supports history-aware operations
- Improved error messages for missing dependencies

### Fixed
- Git repository detection on Windows
- File hash calculation for large files
- Thread-safety for concurrent history writes

---

## [2.2.0] - 2026-01-08

### Added - ML Detection + JavaScript/TypeScript Support

#### Machine Learning Classification (Experimental)
- **SlopClassifier**: ML-based quality detection with ensemble models
- **Training Data Collection**: Automatic data collection from high-quality repos
- **Model Support**:
  - RandomForest: Baseline ensemble model
  - XGBoost: Gradient boosting for improved accuracy
  - Ensemble: Combines RF + XGBoost via voting
- **Performance Targets Achieved**:
  - Accuracy: >90% on test set
  - Precision: >85% (minimizes false positives)
  - Recall: >95% (catches most deficits)
  - F1-Score: >90%

#### Feature Engineering
- **15 ML Features**:
  - Metric-based: LDR, ICR, DDC scores
  - Pattern-based: Critical/High/Medium/Low pattern counts
  - Code-quality: Avg function length, comment ratio, complexity
  - Cross-language patterns, hallucination count
  - Volume metrics: Total lines, logic lines, empty lines

#### Training Infrastructure
- **TrainingDataCollector**: Clones and analyzes GitHub repos
- **Good Data Sources**: NumPy, Flask, Django, Requests, CPython
- **Bad Data Sources**: Known low-quality repositories
- **Dataset Format**: JSON with features and labels
- **Model Persistence**: Pickle-based save/load

#### CLI Enhancements
- `--ml` flag to enable ML-based detection
- `--ml-model <path>` to specify custom trained model
- `--confidence-threshold` for ML prediction filtering
- ML confidence score in output

#### Optional Dependencies
- `pip install ai-slop-detector[ml]` for ML support
- scikit-learn, xgboost, numpy as extras

### Technical
- Training data module: `slop_detector/ml/training_data.py`
- Classifier module: `slop_detector/ml/classifier.py`
- Feature extraction from file analysis results
- Cross-validation support
- Feature importance analysis

### Documentation
- ML training guide in README
- Feature engineering documentation
- Model performance benchmarks

---

## [2.1.0] - 2026-01-08

### Added - Pattern Detection System
- **Pattern Registry**: Extensible system for managing detection patterns
- **23 Detection Patterns**:
  - 6 Structural patterns (bare_except, mutable_default_arg, star_import, global_statement, exec_eval, assert)
  - 5 Placeholder patterns (pass, TODO, FIXME, HACK, ellipsis)
  - 12 Cross-language patterns (JavaScript, Java, Ruby, Go, C#, PHP)
- **Hybrid Scoring**: Combines metric-based (LDR/ICR/DDC) with pattern-based detection
- **Pattern Penalties**: Critical=10pts, High=5pts, Medium=2pts, Low=1pt (capped at 50pts)
- **Pre-commit Hooks**: Full integration with `.pre-commit-hooks.yaml`
- **CLI Enhancements**:
  - `--list-patterns` to show all available patterns
  - `--disable <pattern_id>` to disable specific patterns
  - `--patterns-only` to skip metrics and only run patterns
- **Configuration Examples**: `CONFIG_EXAMPLES.md` with pyproject.toml examples

### Changed
- `SlopDetector` now includes pattern detection alongside metrics
- `FileAnalysis` model includes `pattern_issues` field
- Deficit score calculation includes pattern penalties
- Config system supports `patterns.disabled` list
- README updated with v2.1.0 features and examples

### Technical
- Pattern base classes: `BasePattern`, `ASTPattern`, `RegexPattern`
- Pattern registry with enable/disable functionality
- 8 unit tests for pattern detection
- Test corpus with 30+ code examples (good and bad)
- Documentation: CONFIG_EXAMPLES.md for setup guides

---

## [2.1.0-alpha] - 2026-01-08

### Added - Pattern Detection System
- **Pattern Registry**: Extensible system for managing detection patterns
- **23 Detection Patterns**:
  - 6 Structural patterns (bare_except, mutable_default_arg, star_import, global_statement, exec_eval, assert)
  - 5 Placeholder patterns (pass, TODO, FIXME, HACK, ellipsis)
  - 12 Cross-language patterns (JS, Java, Ruby, Go, C#, PHP)
- **Hybrid Scoring**: Combines metric-based (LDR/ICR/DDC) with pattern-based detection
- **Pattern Penalties**: Critical=10pts, High=5pts, Medium=2pts, Low=1pt (capped at 50pts)
- **Test Corpus**: 3 corpus files with good/bad code examples
- **Configuration**: Pattern enable/disable via config file

### Changed
- `SlopDetector` now includes pattern detection alongside metrics
- `FileAnalysis` model includes `pattern_issues` field
- Deficit score calculation includes pattern penalties
- Config system supports `patterns.disabled` list

### Technical
- Pattern base classes: `BasePattern`, `ASTPattern`, `RegexPattern`
- Pattern registry with enable/disable functionality
- 8 unit tests for pattern detection
- Test corpus with 30+ code examples

---

## [2.0.0] - 2026-01-08

### Added - Initial Release
- **Metric-based architecture**: LDR, ICR, DDC calculators
- **YAML configuration system**: `.slopconfig.yaml` with deep customization
- **Context-aware jargon detection**: Justification checking (e.g., "neural" OK if torch used)
- **Docker support**: Production Dockerfile + docker-compose.yml
- **GitHub Actions CI/CD**: Full pipeline (test, lint, docker, publish)
- **HTML report generation**: Rich visual reports with charts
- **Weighted project analysis**: Files weighted by LOC
- **TYPE_CHECKING awareness**: Type hint imports excluded from DDC
- **Formula-based scoring**: Configurable weights (LDR: 40%, ICR: 30%, DDC: 30%)
- **Environment variable support**: `SLOP_CONFIG` for config path

### Core Metrics
- **LDR (Logic Density Ratio)**: Measures actual logic vs empty shells
  - Empty patterns: `pass`, `...`, `return None`, `raise NotImplementedError`, `# TODO`
  - ABC interface exception (50% penalty reduction)
  - Type stub file support (`.pyi`)
  - Thresholds: S++ (0.85+), A (0.60+), C (0.30+), F (0.15-)

- **ICR (Inflation-to-Code Ratio)**: Technical jargon vs implementation complexity
  - 60+ jargon terms tracked (AI/ML, architecture, quality, academic)
  - Radon integration for accurate complexity
  - Config file exception (ICR = 0.0 for settings files)
  - Context-aware justification (jargon OK if backed by code)
  - Thresholds: PASS (<0.5), WARNING (0.5-1.0), FAIL (>1.0)

- **DDC (Deep Dependency Check)**: Imported vs actually used libraries
  - TYPE_CHECKING block detection
  - Heavyweight library identification (torch, tensorflow, numpy, etc.)
  - Usage ratio: `actually_used / imported`
  - Thresholds: EXCELLENT (0.90+), ACCEPTABLE (0.50+), SUSPICIOUS (0.30-)

### CLI Features
- Single file analysis mode
- Project analysis mode (`--project` flag)
- JSON output support (`--json` flag)
- HTML report generation (`--output report.html`)
- Custom config file (`--config`)
- Fail threshold for CI/CD (`--fail-threshold`)
- Verbose debug output (`--verbose`)
- Version flag (`--version`)

### Technical
- **Dependencies**: pyyaml, radon, jinja2
- **Python support**: 3.8, 3.9, 3.10, 3.11, 3.12
- **Build system**: Modern pyproject.toml
- **Testing**: Unit tests for LDR, ICR, DDC modules
- **Single-pass AST analysis**: Read file once, parse once
- **Documentation**: Comprehensive README, CONTRIBUTING, CHANGELOG

---

## Version History Summary

| Version | Date | Focus | Status |
|---------|------|-------|--------|
| **3.0.2** | 2026-03-15 | Phantom import 3-tier classification, LDR packaging init fix, god_function LOW path, placeholder precision | [+] Current |
| **3.0.1** | 2026-03-10 | ReturnConstantStubPattern, configurable god_function thresholds + domain_overrides | [+] Released |
| **3.0.0** | 2026-03-09 | GQG scoring, DCF fingerprint, MST H0 VR coherence | [+] Released |
| **2.9.3** | 2026-03-09 | Self-calibration engine | [+] Released |
| **2.9.2** | 2026-03-09 | Rich 3-panel single-file UI reconnected | [+] Released |
| **2.9.1** | 2026-03-08 | Self-inspection patch, DDC false positive fix | [+] Released |
| **2.9.0** | 2026-03-08 | PhantomImportPattern, history auto-tracking | [+] Released |
| **2.8.0** | 2026-03-07 | Python advanced patterns, JS tree-sitter, ML secondary signal | [+] Released |
| **2.7.0** | 2026-02-12 | VS Code extension full diagnostic surface | [+] Released |
| **2.6.x** | 2026-01-12 | Consent-based complexity, integration test evidence, config sovereignty | [+] Released |
| **2.0.0** | 2026-01-08 | Initial production release | [+] Released |

---

## Deprecation Notices

### Future v3.0
- **Stdlib fallback for radon**: Will become optional dependency
- **Text-only output**: HTML will be default

---

## Contributors

- **Flamehaven Labs** - Core development
- **Community** - Bug reports and feature requests

---

## Links

- **PyPI**: https://pypi.org/project/ai-slop-detector
- **GitHub**: https://github.com/flamehaven/ai-slop-detector
- **Docker Hub**: https://hub.docker.com/r/flamehaven/ai-slop-detector
- **Documentation**: (Coming soon)

---

## Notes

### Versioning Strategy

- **Major (X.0.0)**: Breaking changes, architectural rewrites
- **Minor (X.Y.0)**: New features, non-breaking changes
- **Patch (X.Y.Z)**: Bug fixes, documentation updates

### Release Cadence

- **Major releases**: Quarterly (Q1, Q2, Q3, Q4)
- **Minor releases**: Monthly
- **Patch releases**: As needed

---

**Last Updated**: 2026-03-15
**Current Version**: 3.0.2
**Status**: Production Ready
