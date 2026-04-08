<p align="center">
  <img src="https://raw.githubusercontent.com/flamehaven01/AI-SLOP-Detector/main/docs/assets/AI%20SLop%20DETECTOR.png" alt="AI-SLOP Detector Logo" width="400"/>
</p>

<h1 align="center">AI-SLOP Detector</h1>

<p align="center">
  <a href="https://pypi.org/project/ai-slop-detector/"><img src="https://img.shields.io/pypi/v/ai-slop-detector.svg" alt="PyPI version"/></a>
  <a href="https://pypi.org/project/ai-slop-detector/"><img src="https://img.shields.io/pypi/dm/ai-slop-detector.svg" alt="PyPI downloads"/></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python 3.8+"/></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT License"/></a>
  <br/>
  <a href="https://github.com/flamehaven01/AI-SLOP-Detector/actions"><img src="https://github.com/flamehaven01/AI-SLOP-Detector/actions/workflows/ci.yml/badge.svg" alt="CI"/></a>
  <a href="https://github.com/flamehaven01/AI-SLOP-Detector/actions"><img src="https://img.shields.io/badge/tests-188%20passed-brightgreen.svg?v=3.1.1" alt="Tests"/></a>
  <a href="htmlcov/"><img src="https://img.shields.io/badge/coverage-82%25-brightgreen.svg" alt="Coverage"/></a>
  <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Black"/></a>
  <a href="https://github.com/flamehaven01/AI-SLOP-Detector/issues"><img src="https://img.shields.io/github/issues/flamehaven01/AI-SLOP-Detector.svg" alt="Issues"/></a>
</p>

<p align="center"><b>Catches the slop that AI produces — before it reaches production.</b></p>

<p align="center">
The problem isn't that AI writes code.<br/>
The problem is the specific class of defects AI reliably introduces:<br/>
unimplemented stubs, disconnected pipelines, phantom imports, and buzzword-heavy noise.<br/>
<br/>
<b>The code speaks for itself.</b>
</p>

---

**Navigation:**
[Quick Start](#quick-start) •
[What's New v3.1.1](#whats-new-in-v311) •
[What's New v3.1.0](#whats-new-in-v310) •
[What's New v3.0.2](#whats-new-in-v302) •
[What's New v3.0.0](#whats-new-in-v300) •
[What It Detects](#what-it-detects) •
[Scoring Model](#scoring-model) •
[Structural Coherence](#structural-coherence) •
[Self-Calibration](#self-calibration) •
[History Tracking](#history-tracking) •
[CI/CD](#cicd-integration) •
[Docs](docs/) •
[Changelog](CHANGELOG.md)

---

## Quick Start

```bash
pip install ai-slop-detector

slop-detector mycode.py               # single file
slop-detector --project ./src         # entire project
slop-detector mycode.py --json        # machine-readable output
slop-detector --project . --ci-mode hard --ci-report  # CI gate

# Optional extras
pip install "ai-slop-detector[js]"     # JS/TS tree-sitter analysis
pip install "ai-slop-detector[ml]"     # ML secondary signal
pip install "ai-slop-detector[ml-data]"  # real training data pipeline

# uvx (no install required)
uvx ai-slop-detector mycode.py
```

<p align="center">
  <img src="docs/assets/cli-output.png" alt="CLI Output Example" width="800"/>
</p>

---

## What's New in v3.1.1

Patch release with visibility improvements and UX refinements reported after v3.1.0.

**Clone Detection now visible in Core Metrics**

`function_clone_cluster` (added in v3.1.0) only fired in the Issues section.
The Core Metrics table now includes a dedicated **Clone Detection** row:

```
┌─────────────────────────────── Core Metrics ────────────────────────────────┐
│   LDR (Logic Density):                                      100.00% (S++)   │
│   ICR (Inflation Check):                                      0.00 (PASS)   │
│   DDC (Dependency Check):                             100.00% (EXCELLENT)   │
│   Clone Detection:                                                   PASS   │  ← new
└─────────────────────────────────────────────────────────────────────────────┘

# When structural clones are detected:
│   Clone Detection:              CRITICAL — structural duplicates detected   │
```

**Consistent table style across all project output**

Project-level output previously mixed three Rich table box styles
(`SIMPLE`, `MINIMAL_DOUBLE_HEAD`, `ROUNDED`). All tables now use
`box.ROUNDED` with `header_style="bold cyan"`. Jargon entries in File
Analysis are trimmed to the first 3 terms + "+N more" to prevent overflow.

**VS Code extension (v3.1.1)**

- `extractJson()`: strips `[INFO]` log lines before `JSON.parse` — prevents
  parse failures when the CLI emits log output to stdout alongside JSON.
- `recordHistory` setting now correctly passes `--no-history` to the CLI.
- Summary diagnostic message includes Clone Detection signal.
- Status bar tooltip uses null-safe metric access (`?.`) and shows Clone status.
- **Workspace analysis**: replaced single-line notification with a scrollable
  QuickPick list of deficit files sorted by score. Clicking a file opens it.
- **History Trends**: replaced raw JSON dump with a formatted column table
  (Runs / Latest / Best / Worst / Trend per file).

---

## What's New in v3.1.0

### Mathematical model refinements

Three formula refinements that align the calibrator and scorer to the same
objective and close known detection gaps:

**Calibrator geometric mean** (`ml/self_calibrator.py`): The self-calibration
engine now uses the same weighted geometric mean (GQG) as the scorer. The
first-generation calibrator used an arithmetic mean — a simpler approximation
that produced a ~5-7pt gap on files with uneven dimension profiles, where
weights were being optimized against a different formula than the scorer used.

**Complexity modifier baseline** (`metrics/inflation.py`): The jargon density
penalty multiplier now activates from cc=1 (simplest function) instead of cc=3.
Functions with cc=2 now correctly receive a 1.10× complexity premium for jargon.

**Purity weight configurable** (`core.py`): `w_pur` is now readable from
`.slopconfig.yaml` via `weights.purity` (default: 0.10 unchanged).

### Three new adversarial patterns

These patterns close specific evasion cases validated by fhval SPAR-Code:

| Pattern | Targets | Severity |
|---|---|---|
| `return_constant_stub` (extended) | `return {}`, `return []`, `return ()` | HIGH |
| `function_clone_cluster` | N structurally identical helpers (fragmented god function) | CRITICAL/HIGH |
| `placeholder_variable_naming` | ≥5 single-letter params; r1,r2...rN sequences | HIGH/MEDIUM |

**SPAR-Code score: 55 (FAIL) → 85 (PASS)** — all three previously-evading
adversarial cases are now detected.

#### `function_clone_cluster` — DI2/AST clone detection

A god function split into N one-liner helpers evades `god_function` and
`nested_complexity` entirely (no single function exceeds thresholds).
v3.1.0 detects this at the file level:

```
For each function: compute 30-dim AST node-type histogram
Pairwise JSD between all function pairs
BFS connected components on (JSD < 0.05) graph
Largest component >= 6 -> CRITICAL
```

```
# Before v3.1.0: deficit = 0.0 (completely evaded)
def _h1(x): return x + 1
def _h2(x): return x + 2
...
def _h12(x): return x + 12
def process(x): return _h12(_h11(_h10(..._h1(x)...)))

# After v3.1.0: CRITICAL function_clone_cluster (deficit = 14.4)
# "12 structurally near-identical functions detected (AST JSD < 0.05)"
```

#### `placeholder_variable_naming` — naming pattern detection (v1.0)

```
# Before v3.1.0: deficit = 0.0 (inflation=0, no buzzwords)
def process(a, b, c, d, e, f, g):
    r1 = a + b
    r2 = c - d
    ...r12 = r11 + r6
    return r12

# After v3.1.0: 2x HIGH (deficit = 10.0)
# "7 single-letter parameters" + "12 sequential numbered variables (r1..r12)"
```

**Scope note:** v1.0 detects naming *style*, not semantic quality. Math/science
libraries using single-letter conventions should configure `domain_overrides`
or add to `.slopconfig.yaml` ignore list.

### fhval SPAR-Code feedback loop

`fhval spar` — new subcommand providing 3-layer adversarial validation:

```bash
cd your-project
fhval spar                    # full report
fhval spar --layer a          # ground truth anchors only
fhval spar --layer c          # existence probes only
fhval spar --json             # machine-readable output
```

Layer A checks that known code patterns produce expected deficit ranges.
Regression: if a future change makes `clean_trivial` score > 15, SPAR fails.
Layer C probes whether each metric is measuring what it claims.

---

## What's New in v3.0.2

### Phantom import false-positive elimination

`PhantomImportPattern` now understands your project's own packages and its optional
dependencies before flagging anything. The previous version had no awareness of the
project it was scanning — every `src/`-layout internal import and every guarded optional
dep triggered a CRITICAL hit, which cascaded through GQG to drive `deficit_score → 100`
on every file.

Three-tier classification (replacing flat CRITICAL-for-all):

| Tier | Condition | Severity |
|---|---|---|
| Internal | Module resolves to the current project | (skip) |
| Guarded | Inside `try/except ImportError` / `Exception` block | MEDIUM |
| Hard phantom | Unresolvable, unguarded | CRITICAL |

Project packages are discovered automatically from `pyproject.toml` `[project.dependencies]`,
`[project.optional-dependencies]`, and the `src/` directory layout — no config required.

---

### LDR no longer collapses on empty `__init__.py`

An empty packaging init file (`src/mypkg/__init__.py`, zero content lines) previously
produced `total_lines=0 → ldr_score=0.0 → GQG ln(1e-4) → deficit_score=100`.

v3.0.2 detects this case and returns `ldr_score=1.0, grade="N/A", is_packaging_init=True`.
The `is_packaging_init` flag is exposed in JSON output for downstream tooling.

---

### GodFunctionPattern: long-but-simple paths demoted to LOW

Functions that exceed the line threshold but have low cyclomatic complexity (`cc ≤ 5`) are
now flagged LOW instead of HIGH. This eliminates false positives on physics constant tables,
routing dispatch blocks, and domain rule lists — code that is deliberately verbose but not
structurally complex.

Only functions that exceed the complexity threshold are flagged HIGH, regardless of length.

---

### Placeholder pattern precision

- `NotImplementedPattern` — skips `@abstractmethod` decorated methods (correct ABC pattern).
- `EmptyExceptPattern` — 3-tier: bare `except: pass` → CRITICAL; `except ImportError: pass` →
  LOW with "optional dependency guard" hint; typed `except X: pass` → MEDIUM.
- `InterfaceOnlyClassPattern` — `return self` / `return cls` method-chaining stubs now count
  toward the placeholder threshold.

---

## What's New in v3.0.0

### Geometric mean replaces arithmetic mean in scoring

The previous scoring model used a weighted arithmetic mean across three dimensions
(LDR, inflation, DDC). Arithmetic means allow a high score in one dimension to
partially offset a low score in another.

v3.0.0 switches to a weighted geometric mean:

```
quality = exp( sum(w_i * ln(max(1e-4, v_i))) / sum(w_i) )
```

A near-zero value in any single dimension pulls the result significantly lower,
regardless of the other dimensions. This better reflects how quality actually
degrades — a file with 5% import usage is bad even if its logic density is high.

A fourth dimension is added: `purity = exp(-0.5 * n_critical_patterns)`.
This makes CRITICAL-severity pattern hits (phantom imports, etc.) compound rather
than add flat points on top of the metric score.

| Dimension | Source | Weight |
|---|---|---|
| `ldr` | Logic Density Ratio | config (default 0.40) |
| `inflation_q` | `1 - normalized_inflation` | config (default 0.30) |
| `ddc` | Import usage ratio | config (default 0.20) |
| `purity` | `exp(-0.5 * n_critical_patterns)` | configurable (default 0.10) |

---

### AST node type distribution per file

Every analyzed file now carries a `dcf` field: the normalized frequency of each
AST node type across the file.

```python
result = detector.analyze_file("mycode.py")
print(result.dcf)
# {'FunctionDef': 0.12, 'Return': 0.09, 'Call': 0.14, 'Pass': 0.002, ...}
```

This is the foundation for the project-level structural distance metric below.
It is also accessible via `--json` output for external tooling.

---

### Project-level structural distance metric

`analyze_project()` now computes how similar files are to each other in terms
of AST node type composition.

```python
project = detector.analyze_project("./src")
print(project.structural_coherence)  # 0.0 - 1.0
print(project.coherence_level)       # "vr_structural" | "none"
```

The value is `1 - d`, where `d` is the longest edge in the minimum spanning tree
of pairwise sqrt-JSD distances between file distributions. A value near 1.0 means
files are structurally similar; lower values indicate more variation across files.

This is an experimental metric. Interpret with caution — a heterogeneous project
(utilities + models + tests) will naturally score lower than a uniform one, which
is not a defect.

**In JSON output:**
```json
{
  "structural_coherence": 0.91,
  "coherence_level": "vr_structural"
}
```

---

## What's New in v2.9.3

### Self-Calibration — The Tool Learns Your Codebase

The default weights (`ldr: 0.40, inflation: 0.30, ddc: 0.30`) were tuned against
one codebase. They may not fit yours. A Django project has more structural boilerplate
than a data pipeline. A heavily documented library has a different logic density
profile than a microservice.

Starting in v2.9.3, the tool calibrates its own weights from your usage history.

```bash
slop-detector . --self-calibrate              # see what your history suggests
slop-detector . --self-calibrate --apply-calibration  # write to .slopconfig.yaml
```

**How it works in one sentence:**
Files you edited after a bad score are confirmed real slop. Files you ignored
despite a bad score are likely false positives. The engine searches for weights
that maximize the first and minimize the second — using only your own history,
no external data required.

**First live run result (Flamehaven codebase, 180 files, 62 confirmed fixes):**

| Dimension | Default | Calibrated |
|---|---:|---:|
| ldr | 0.40 | 0.10 |
| inflation | 0.30 | 0.25 |
| ddc | 0.30 | **0.65** |
| Combined error | 1.1069 | **0.9985** |
| Confidence gap | — | 0.1088 |

Interpretation: this codebase's style leans documentation-heavy with meaningful
dependency usage — DDC is the stronger quality signal here than logic density.
The tool adapted to that. Yours will adapt to your style.

More data = better calibration. The tool gets more accurate the more you use it.

[Full documentation: Self-Calibration →](docs/SELF_CALIBRATION.md)

---

## What's New in v2.9.1

### Self-Inspection Patch — Zero Deficit Files

v2.9.1 applies the tool to itself and patches what it finds.
Running `slop-detector --project src/` on its own codebase produced three
deficit files. All three are resolved.

**Before → After:**

| Metric | v2.9.0 | v2.9.1 |
| :--- | ---: | ---: |
| Deficit files | 3 | **0** |
| Avg deficit score | 11.65 | **9.57** |
| Weighted deficit score | 15.88 | **12.42** |

**What was fixed:**

**`cli.py` (53.5 → 29.1)** — god function decomposition.
`print_rich_report`, `main`, `generate_markdown_report`, `generate_text_report`,
and `_handle_output` each exceeded the 50-line / complexity-10 threshold.
Extracted 9 focused helpers; every function now fits within limits.

**`registry.py` (39.5 → clean)** — DDC false positive + `global` statement.
`BasePattern` was imported only for type annotations.
`UsageCollector` (by design) skips annotations, so DDC scored it as 0% used.
Fix: move annotation-only imports under `if TYPE_CHECKING:`.
Also replaced lazy `global _global_registry` singleton with eager module-level
initialization, removing the `global` statement the pattern detector flagged.

**`question_generator.py` (30.0 → clean)** — same DDC false positive.
`FileAnalysis` was annotation-only. Same `TYPE_CHECKING` guard fix.
Converted Python 3.10+ union syntax (`int | None`, `str | None`) to
`Optional[int]`, `Optional[str]` for Python 3.8 compatibility.

---

## What's New in v2.9.0

### `phantom_import` — Hallucinated Package Detection (CRITICAL)

AI models sometimes generate plausible-sounding but non-existent package names.
This catches them before they become a runtime `ModuleNotFoundError`.

```python
import tensorflow_magic         # CRITICAL — does not exist
from requests_async_v2 import get  # CRITICAL — does not exist

import numpy                    # OK — installed
from os.path import join         # OK — stdlib
from . import utils              # OK — relative, excluded by design
```

Resolution order: `sys.builtin_module_names` → `sys.stdlib_module_names` →
`importlib.metadata.packages_distributions()` → `importlib.util.find_spec`

Full spec: [docs/PHANTOM_IMPORT.md](docs/PHANTOM_IMPORT.md)

---

### History Auto-Tracking

Every run is recorded to `~/.slop-detector/history.db` automatically.

```bash
slop-detector mycode.py --show-history     # per-file trend
slop-detector --history-trends             # 7-day project aggregate
slop-detector --export-history data.jsonl  # ML training export
slop-detector mycode.py --no-history       # opt-out
```

```
History: src/mymodule.py
----------------------------------------------------------------------
  Timestamp                Deficit    LDR Patterns  Grade
----------------------------------------------------------------------
  2026-03-06T09:12:43         42.0  0.631        7  suspicious
  2026-03-07T11:03:21         18.0  0.812        3  clean
  2026-03-08T14:55:09          0.0  1.000        0  clean
----------------------------------------------------------------------
  Trend (3 runs): improved  delta=-42.0
```

Full spec: [docs/HISTORY_TRACKING.md](docs/HISTORY_TRACKING.md)

---

## What It Detects

**27 patterns across 5 categories.** Full catalog: [docs/PATTERNS.md](docs/PATTERNS.md)

| Category | Patterns | Signal |
|---|---|---|
| **Placeholder** | `empty_except`, `not_implemented`, `pass_placeholder`, `ellipsis_placeholder`, `return_none_placeholder`, `return_constant_stub`, `todo_comment`, `fixme_comment`, `hack_comment`, `xxx_comment`, `interface_only_class` | Unfinished / scaffolded code |
| **Structural** | `bare_except`, `mutable_default_arg`, `star_import`, `global_statement` | Anti-patterns |
| **Cross-Language** | `js_push`, `java_equals`, `ruby_each`, `go_print`, `csharp_length`, `php_strlen` | Wrong-language syntax |
| **Python Advanced** | `god_function`, `dead_code`, `deep_nesting`, `lint_escape`, `function_clone_cluster`, `placeholder_variable_naming` | Structural complexity + evasion patterns |
| **Phantom** | `phantom_import` | Hallucinated packages |

Beyond patterns, three metric axes are computed per file:

| Metric | What it measures |
|---|---|
| **LDR** (Logic Density Ratio) | `logic_lines / total_lines` — code vs. whitespace/comments |
| **ICR** (Inflation) | `jargon_density × complexity_modifier` — buzzword weight |
| **DDC** (Dependency Check) | `used_imports / total_imports` — import utilization |

---

## Scoring Model

**v3.0.0: weighted geometric mean**

```
purity        = exp(-0.5 * n_critical_patterns)
quality       = exp( (w_ldr*ln(ldr) + w_inf*ln(1-inf) + w_ddc*ln(ddc) + w_pur*ln(purity))
                     / (w_ldr + w_inf + w_ddc + w_pur) )
deficit_score = 100 * (1 - quality) + pattern_penalty
```

| Score | Status |
|---|---|
| >= 70 | `CRITICAL_DEFICIT` |
| >= 50 | `INFLATED_SIGNAL` |
| >= 30 | `SUSPICIOUS` |
| < 30 | `CLEAN` |

Project aggregation uses SR9 conservative weighting for LDR:
`project_ldr = 0.6 × min(file_ldrs) + 0.4 × mean(file_ldrs)`

Full mathematical specification: [docs/MATH_MODELS.md](docs/MATH_MODELS.md)

---

## Structural Coherence

```python
project = detector.analyze_project("./src")
print(project.structural_coherence)  # 0.0 - 1.0
```

Reports how similar files are to each other in AST node type composition.
`1.0` = all files have nearly identical structural profiles; lower = more
variation across files.

This is an experimental signal. A heterogeneous project (e.g., CLI code +
data models + tests) will score lower than a uniform one by design. Use
it for longitudinal comparison within the same project, not as an absolute
quality gate.

---

## Self-Calibration

The default weights work. Calibrated weights work better — for you.

```bash
# Check what your history recommends
slop-detector . --self-calibrate

# Apply automatically to .slopconfig.yaml
slop-detector . --self-calibrate --apply-calibration

# Require more data before trusting the result
slop-detector . --self-calibrate --min-history 50
```

The engine extracts two signals from your history database:

| Event | Definition | Label |
|---|---|---|
| **Improvement** | Deficit was high → you edited the file → score dropped | True positive |
| **FP candidate** | Deficit was high → same file, no change, next run still bad | Likely false positive |

It then grid-searches 200+ weight combinations and finds the set that minimizes
missed real slops and unnecessary alerts — for your specific codebase.

Requires at least 10 labeled events (accumulated automatically as you use the tool).
Result is only written when the confidence gap between the top two candidates
exceeds 0.10 — the same pattern used in Copilot Guardian's multi-hypothesis selection.

| Status | Meaning |
|---|---|
| `ok` | Confident winner found — `--apply-calibration` writes to config |
| `no_change` | Current weights already near-optimal |
| `insufficient_data` | Need more history, or candidates too close to call |

[Full documentation: Self-Calibration →](docs/SELF_CALIBRATION.md)

---

## History Tracking

The history database is the foundation for longitudinal quality analysis.
Files that improve from `deficit=42` to `deficit=0` over multiple runs
provide an independent training signal for the ML pipeline.

```python
from slop_detector.history import HistoryTracker

tracker = HistoryTracker()
regression = tracker.detect_regression("src/api.py", current_score=55.0)
trends = tracker.get_project_trends(days=7)
count = tracker.export_jsonl("training.jsonl")  # → DatasetLoader.load_jsonl()
```

[Full documentation →](docs/HISTORY_TRACKING.md)

---

## CI/CD Integration

```bash
# Soft — informational, never fails build
slop-detector --project . --ci-mode soft --ci-report

# Hard — fails build at deficit_score >= 70 or critical_patterns >= 3
slop-detector --project . --ci-mode hard --ci-report

# Quarantine — escalates repeat offenders after 3 violations
slop-detector --project . --ci-mode quarantine --ci-report
```

**GitHub Actions:**
```yaml
- name: Slop Gate
  run: |
    pip install ai-slop-detector
    slop-detector --project . --ci-mode hard --ci-report
```

[CI/CD Integration Guide →](docs/CI_CD.md)

---

## Configuration

```yaml
# .slopconfig.yaml
weights:
  ldr: 0.40
  inflation: 0.35
  ddc: 0.25

thresholds:
  ldr:
    critical: 0.30
    warning: 0.60

disabled_patterns:
  - lint_escape  # opt-out specific patterns
```

[Full Configuration Guide →](docs/CONFIGURATION.md)

---

## VS Code Extension

Real-time inline diagnostics, debounced lint-on-type, ML score and Clone Detection in status bar.

**Commands:** Analyze File · Analyze Workspace · Auto-Fix · Show Gate Decision · Cross-File Analysis · History Trends · Export History

**Workspace Analysis** opens a scrollable QuickPick list of deficit files sorted by score. Click any file to open it directly. **History Trends** renders a formatted table (Runs / Latest / Best / Worst / Trend) in the Output panel instead of a raw JSON dump.

Install from the [VS Code Marketplace](https://marketplace.visualstudio.com/items?itemName=Flamehaven.vscode-slop-detector)
or build locally:

```bash
cd vscode-extension
npm install
npx vsce package
# → vscode-slop-detector-3.1.1.vsix
```

---

## Development

```bash
git clone https://github.com/flamehaven01/AI-SLOP-Detector.git
cd AI-SLOP-Detector
pip install -e ".[dev]"
pytest tests/ -v --cov
black src/ tests/
ruff check src/ tests/
```

[Development Guide →](docs/DEVELOPMENT.md)

---

## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  <b>Flamehaven Labs</b> •
  <a href="https://github.com/flamehaven01/AI-SLOP-Detector/issues">Issues</a> •
  <a href="https://github.com/flamehaven01/AI-SLOP-Detector/discussions">Discussions</a> •
  <a href="docs/">Docs</a>
</p>
