# AI SLOP Detector — VS Code Extension v3.9.0

Real-time AI-generated code quality analysis inside VS Code. Surfaces
deficit scores, structural anti-patterns, ML signals, clone detection,
interactive webview reports, and actionable diagnostics without leaving your
editor.

---

## What's New in v3.9.0 — Webview Surfaces + Typed npm Data Layer

### Four interactive webview panels

The extension moves beyond text diagnostics with theme-aware webviews (styled
with VS Code CSS variables only — no external UI dependencies):

| Command | What it shows |
|---|---|
| **Show 4D Breakdown** | Penalty attribution — *why* a file's deficit is not 0.0, top driver first |
| **Show Cleanup Plan** | Confidence-ranked `sweep` family (`safe` / `needs` / `unsafe`) with evidence |
| **Show Pulse Dashboard** | Project health header + priority hotspots (deficit x churn x coverage) |
| **Show Changed-Code Review** | Diff-aware review — introduced-vs-inherited slop, recommended actions |

### Typed npm data layer

Analysis no longer shells out by hand. The extension consumes the
`ai-slop-detector` npm package's runtime API and TypeScript contracts, so
results are typed end-to-end and the modern `scan / review / pulse / sweep`
command surface is used throughout. The hand-written output schema was retired
in favour of the package's generated types.

### Onboarding + state-aware UI

- **Getting-started walkthrough** mapped to `scan -> diagnose -> patch -> gate -> calibrate`
- **State-aware empty states** with actionable links (`Get Started`, `Analyze`)
- **Context-key view menus** — Analyze before the first run, Refresh after
- **`slopDetector.domain` setting** (8 profiles) wired into config bootstrap

> Note: the extension now depends on the `ai-slop-detector` npm package; see
> [Requirements](#requirements).

---

## What's New in v3.7.5

### `phantom_import` False Positive Fix — Flat-Module Projects

`phantom_import` now correctly handles projects where Python files are
not organized as packages (no `__init__.py`, no `pyproject.toml`).
Sibling `.py` files in the same directory are automatically recognised
as local modules and never flagged as phantom imports.

The `phantom_import_allowlist` key in `.slopconfig.yaml` is now fully
wired to the detection engine — previously it was parsed but silently
ignored. A new **QuickFix** action in the editor lets you add a flagged
module directly from the Problems panel:

> **Right-click → SLOP: Allowlist 'module_name' — add to phantom_import_allowlist in .slopconfig.yaml**

The action either appends the entry to an existing `phantom_import_allowlist:` section
or creates one at the end of the file.

### New Setting: `slopDetector.phantomImportAllowlist`

```jsonc
"slopDetector.phantomImportAllowlist": ["my_local_module", "another_sibling"]
```

Documents which local modules you want allowlisted. When a phantom_import
QuickFix fires, VS Code surfaces this setting alongside the `.slopconfig.yaml`
entry suggestion so you have a clear, in-editor record.

---

## What's New in v3.7.4

### False Positive Patch — ABC / Optional / FastAPI / Extras

Six sources of false positives eliminated:

- `ellipsis_placeholder` / `interface_only_class`: `@abstractmethod` bodies no
  longer trigger stub warnings
- `return_none_placeholder`: `return None` in `-> Optional[T]` methods is the
  Null Object pattern, not a placeholder
- `phantom_import`: PEP-508 extras specifiers (`psycopg[binary]`) are stripped
  before resolution, fixing guarded optional-dep imports
- `function_clone_cluster`: FastAPI / Flask route files with an `app` or `router`
  assignment are exempt from clone-cluster flagging
- Jargon matching: `\b` word boundaries prevent `neural` matching inside
  `neural_network_training` identifiers

---

## What's New in v3.6.0

### CI Gate Bug Fix — `--ci-mode hard` Now Exits Non-Zero

The core CLI had a silent bug: `--ci-mode hard` only propagated its exit code
when `--ci-report` was also passed. Without `--ci-report`, it returned 0 even on
`CRITICAL_DEFICIT` files. This is now fixed — `hard` mode always gates correctly.

Pre-commit hooks were also rewritten to use `python -m slop_detector.cli` (the
`.exe` wrapper on Windows did not reliably propagate exit codes):

```yaml
repos:
  - repo: https://github.com/flamehaven01/AI-SLOP-Detector
    rev: v3.6.0
    hooks:
      - id: slop-detector          # hard gate — fails on CRITICAL_DEFICIT >= 70
      # - id: slop-detector-warn   # soft mode — reports only, never blocks
      # - id: slop-detector-patterns  # fast per-file pattern scan
```

### Claude Code Skill (`/slop`, `/slop-file`, `/slop-gate`, `/slop-spar`)

Install the skill and get four agentic commands inside Claude Code:

```bash
cp -r claude-skills/slop-detector ~/.claude/skills/slop-detector
```

| Command | What it does |
|---|---|
| `/slop` | Full project scan + interpretation + patch suggestions |
| `/slop-file [path]` | Per-file deep-dive with fix guidance |
| `/slop-gate` | CI PASS/FAIL decision with metric breakdown |
| `/slop-spar` | Adversarial validation — challenges "clean" findings |

See [`docs/CLAUDE_CODE_SKILL.md`](../docs/CLAUDE_CODE_SKILL.md) for full reference.

---

## What's New in v3.5.0

### Go Language Support (Phase 3c)

The extension now activates on **Go files** (`.go`). Install the Go extra and
get 6 Go-specific patterns detected in real-time:

```bash
pip install "ai-slop-detector[go]"
```

| Pattern | Meaning |
|---|---|
| `go_empty_func` | Empty `{}` function body |
| `go_panic` | `panic()` crash-on-error anti-pattern |
| `go_fmt_print` | `fmt.Print*` debug output left in code |
| `go_ignored_error` | `_ = fn()` silently discarded error |
| `go_todo_comment` | `// TODO` inline marker |
| `go_god_function` | Function exceeding 50 lines |

### JS/TS Full Analysis (Phase 3b)

JavaScript and TypeScript files now receive full structural analysis via the
dedicated **JS/TS Analyzer** — not just cross-language pattern matching.

### Domain-Aware `--init` (Phase 3a)

`slop-detector.initConfig` auto-detects your project domain (library, web app,
CLI tool, data pipeline) and generates a `.slopconfig.yaml` with domain-specific
thresholds pre-tuned for that type of project.

### CI Stability Fix

Fixed a `jq exit 5` parse error in CI pipelines: calibration milestone hints
were being written to stdout alongside the JSON payload. Hints are now correctly
sent to stderr.

---

## What's New in v3.2.1

### LEDA Self-Evolving Configuration Loop

The biggest addition: the extension now exposes the **LEDA calibration loop** — the engine that learns your codebase's unique coding style and automatically tunes its own detection weights.

- **Bootstrap Config** (`slop-detector.initConfig`): Generates a `.slopconfig.yaml`
  in your workspace root with domain-specific overrides and secure `.gitignore` injection.
  Run this once on a new project.
- **Self-Calibrate** (`slop-detector.selfCalibrate`): Runs the 4D grid-search
  calibration (LDR × Inflation × DDC × Purity) against your analysis history, shows
  the result in the Output panel, and offers a one-click **Apply** button to write
  the optimal weights back to `.slopconfig.yaml`.

> **The more you use it, the smarter it gets.** After 10+ analyses the LEDA engine
> reverse-engineers your team's past behavior and Git history to derive mathematically
> optimal weights. Run self-calibrate periodically — it evolves with your codebase.

### Purity Dimension (4D Scoring)

The **Purity score** (`exp(−0.5 × n_critical)`) is now visible everywhere:

- **Diagnostics summary** — appended after LDR / Inflation / DDC
- **Status bar tooltip** — shows `Purity: 0.xxx (N critical)`

This completes the 4D metric display: LDR + Inflation + DDC + Purity.

### Other v3.2.1 Fixes

- `calibrate()` min_events guard: correctly handles fewer events than the minimum
  without raising, returns `insufficient_data` status
- Git noise filter (P2): per-file deduplication prevents FP overcounting across runs
- Black + ruff CI green across all source files

## What's New in v3.1.1

- **Clone Detection in Core Metrics**: `function_clone_cluster` results are
  now visible in the Core Metrics summary row — CRITICAL/PASS at a glance.
- **Workspace QuickPick**: "Analyze Workspace" now shows a sorted QuickPick
  list of deficit files. Click any file to open it directly in the editor.
- **JSON parse fix**: `extractJson()` strips `[INFO]` log lines before parsing.
- **History Trends formatting**: formatted column table (Runs / Latest / Best /
  Worst / Trend) replaces raw JSON dump.

---

## Features

### Inline Diagnostics (Problems Panel)

Every analysis run produces structured diagnostics in the Problems panel:

| Source label | Diagnostic type | Severity |
|---|---|---|
| SLOP Detector | Summary: score, status, LDR/ICR/DDC/Purity, ML score, Clone | Error / Warning / Info |
| SLOP Detector - Inflation | Unjustified jargon term at exact line | Warning |
| SLOP Detector - Docstring | Over-documented function (doc/impl ratio) | Error / Warning |
| SLOP Detector - Evidence | Unjustified quality claim lacking evidence | Warning |
| SLOP Detector - DDC | Unused imports summary | Info |
| SLOP Detector - Patterns | Structural anti-patterns (god_function, dead_code, phantom_import, function_clone_cluster, etc.) | Error / Warning / Info |

Pattern diagnostics use `pattern_id` as the diagnostic code — VS Code's
Problems panel filter works natively (e.g., filter for `god_function` only).

### Status Bar

Right side of the status bar shows live quality at a glance:

```
$(check) Good (12.4)      <- score below warn threshold
$(warning) Warning (34.1) <- score >= warnThreshold
$(error) Error (67.8)     <- score >= failThreshold
$(sync~spin) Analyzing... <- analysis in progress
```

**Tooltip includes:**
- Deficit Score and Status
- LDR / Inflation / DDC / **Purity** metric values
- ML slop probability (when model is present)
- Clone Detection: PASS or CRITICAL

### Workspace Analysis (QuickPick)

"Analyze Workspace" scans all supported files (Python, JS/TS, Go) and opens an interactive QuickPick:

```
$(error) src/slop_detector/cli.py          [67.8] INFLATED_SIGNAL
$(warning) src/slop_detector/core.py       [34.1] SUSPICIOUS
$(check) src/slop_detector/models.py       [11.2] CLEAN
```

Click any entry to open the file directly in the editor.

### Lint on Save / Lint on Type

- **Lint on save** (default: on) — triggers on every `Ctrl+S`
- **Lint on type** (default: off) — triggers with 1500ms debounce

### Commands (Ctrl+Shift+P → "SLOP")

| Command | Description |
|---|---|
| SLOP Detector: Analyze Current File | Run analysis on active file |
| SLOP Detector: Analyze Workspace | Scan workspace, open QuickPick of deficit files |
| SLOP Detector: Show 4D Breakdown | **[v3.9.0]** Webview: penalty attribution (why not 0.0) |
| SLOP Detector: Show Cleanup Plan | **[v3.9.0]** Webview: confidence-ranked sweep family |
| SLOP Detector: Show Pulse Dashboard | **[v3.9.0]** Webview: health + priority hotspots |
| SLOP Detector: Show Changed-Code Review | **[v3.9.0]** Webview: diff-aware review |
| SLOP Detector: Auto-Fix Issues | Apply or preview (dry-run) auto-fixable patterns |
| SLOP Detector: Show Gate Decision (SNP) | Display SNP gate result |
| SLOP Detector: Run Cross-File Analysis | Detect cycles, duplicates, hotspots |
| SLOP Detector: Show File History | View historical score for current file |
| SLOP Detector: Show History Trends | Formatted table: Runs / Latest / Best / Worst / Trend |
| SLOP Detector: Export History to JSONL | Export full history DB to `.jsonl` |
| SLOP Detector: Bootstrap .slopconfig.yaml | **[v3.2.1]** Generate config + inject .gitignore entry |
| SLOP Detector: Run Self-Calibration | **[v3.2.1]** 4D LEDA calibration → optional Apply to config |
| SLOP Detector: Install Git Pre-Commit Hook | Set up pre-commit quality gate |

---

## Installation

### From Marketplace

Search **"AI SLOP Detector"** in the VS Code Extensions panel, or:

```
ext install Flamehaven.vscode-slop-detector
```

### From VSIX (Local)

```bash
code --install-extension vscode-slop-detector-3.9.0.vsix
```

---

## Requirements

- **Python 3.9+**
- `ai-slop-detector` installed in the Python environment VS Code uses:

```bash
pip install ai-slop-detector          # core only
pip install "ai-slop-detector[ml]"    # + ML secondary signal
pip install "ai-slop-detector[js]"    # + JS/TS tree-sitter patterns
pip install "ai-slop-detector[go]"    # + Go analysis (v3.5.0)
pip install "ai-slop-detector[full]"  # everything
```

Since v3.9.0 the extension consumes the **`ai-slop-detector` npm package** as its
data layer; it is bundled with the extension and delegates to the Python backend
above (it does not reimplement analysis). Set `slopDetector.pythonPath` if your
Python interpreter is not on `PATH`.

---

## Configuration

Open Settings (`Ctrl+,`) and search **"SLOP Detector"**, or edit `settings.json`:

```jsonc
{
  "slopDetector.enable": true,
  "slopDetector.lintOnSave": true,
  "slopDetector.lintOnType": false,
  "slopDetector.showInlineWarnings": true,
  "slopDetector.failThreshold": 50.0,            // deficit_score >= 50 -> Error
  "slopDetector.warnThreshold": 30.0,            // deficit_score >= 30 -> Warning
  "slopDetector.pythonPath": "python",
  "slopDetector.configPath": "",                 // path to .slopconfig.yaml (optional)
  "slopDetector.recordHistory": true,            // write results to ~/.slop-detector/history.db
  "slopDetector.showCalibrationHints": true,     // notify when LEDA calibration milestone is reached
  "slopDetector.phantomImportAllowlist": []      // [v3.7.5] module names to skip in phantom_import
}
```

### `phantom_import_allowlist` — flat-module projects

For projects where sibling `.py` files import each other directly (no `pyproject.toml`
or `__init__.py`), the detector automatically discovers sibling modules. If a false
positive still occurs, add the module name to `.slopconfig.yaml`:

```yaml
phantom_import_allowlist:
  - my_local_module
  - another_sibling
```

Or use the QuickFix action in the Problems panel — it writes the entry directly into `.slopconfig.yaml`.

### Deficit Score Thresholds

| Status | deficit_score |
|---|---|
| CLEAN | < 30 |
| SUSPICIOUS | 30 – 49 |
| INFLATED_SIGNAL | 50 – 69 |
| CRITICAL_DEFICIT | >= 70 |

Recommended: `warnThreshold: 30`, `failThreshold: 50` (defaults).

---

## Pattern Reference (v3.5.0 — 33 patterns)

Use the `pattern_id` as a Problems panel filter code.

**Placeholder / Stub**
- `pass_placeholder` — function body is only `pass`
- `ellipsis_placeholder` — function body is only `...`
- `not_implemented` — `raise NotImplementedError` (non-abstract)
- `return_none_placeholder` — function body is only `return None`
- `return_constant_stub` — function body is `return <literal>`
- `todo_comment` — inline `# TODO`
- `fixme_comment` — inline `# FIXME`
- `hack_comment` — inline `# HACK`
- `xxx_comment` — inline `# XXX`

**Structural**
- `god_function` — >50 logic lines or cyclomatic complexity >10
- `dead_code` — statements after `return`/`raise`/`break`/`continue`
- `deep_nesting` — control-flow depth >4
- `empty_except` — bare or typed `except: pass`
- `interface_only_class` — class with ≥50% placeholder methods
- `nested_complexity` — deep nesting AND high cyclomatic complexity combined
- `placeholder_variable_naming` — numbered variable sequences (data1, data2…)

**Quality**
- `phantom_import` — import that cannot be resolved (hallucinated dependency)
- `function_clone_cluster` — structurally identical function bodies (AST JSD)

**Cross-Language**
- `js_var_usage` — JavaScript `var` in Python file
- `js_console_log` — `console.log` in Python file
- `ruby_array_each` — Ruby-style `.each` block
- `go_print_format` — Go `fmt.Printf` style

**Go** (`pip install "ai-slop-detector[go]"`)
- `go_empty_func` — empty function body `{}`
- `go_panic` — `panic()` crash-on-error anti-pattern
- `go_fmt_print` — `fmt.Print*` debug output left in code
- `go_ignored_error` — `_ = fn()` silently discarded error
- `go_todo_comment` — `// TODO` inline marker
- `go_god_function` — function exceeding 50 lines

**Lint Escape**
- `noqa_overuse` — excessive `# noqa` suppression
- `type_ignore_overuse` — excessive `# type: ignore`

---

## Development

```bash
cd vscode-extension
npm install
npm run compile    # one-time build
npm run watch      # auto-recompile on changes
```

Press **F5** to open Extension Development Host. The Output panel channel
**"SLOP Detector"** logs all CLI invocations and their stdout/stderr.

---

## Changelog

See the [full CHANGELOG](https://github.com/flamehaven01/AI-SLOP-Detector/blob/main/CHANGELOG.md).

**v3.9.0:** Four interactive webview panels (4D breakdown, cleanup plan, pulse dashboard, diff-aware review); typed `ai-slop-detector` npm data layer replacing hand-rolled subprocess calls; getting-started walkthrough, state-aware empty states, context-key menus, and `slopDetector.domain` setting.

**v3.7.5:** `phantom_import` FP fix for flat-module projects (sibling discovery + allowlist wired); new `addModuleToAllowlist` QuickFix action; `slopDetector.phantomImportAllowlist` setting.

**v3.7.4:** False positive patch: ABC `@abstractmethod`, `Optional[T]` return, FastAPI router clone exemption, PEP-508 extras parsing, jargon `\b` boundary fix.

**v3.6.0:** CI gate bug fix (`--ci-mode hard` always exits non-zero), Claude Code skill (`/slop`, `/slop-file`, `/slop-gate`, `/slop-spar`).

**v3.5.0:** Go analysis (GoAnalyzer v1.0.0 — 6 patterns), JS/TS full structural
analysis, domain-aware `--init`, CI jq fix (calibration hints → stderr).

**v3.2.1:** LEDA self-calibration UI (`initConfig`, `selfCalibrate`), Purity
dimension in diagnostics + tooltip, min_events bugfix, black/ruff CI green.

**v3.1.1:** Clone Detection in Core Metrics, table style unification, Workspace
QuickPick, JSON parse fix, History Trends formatting, pattern refactoring.

**v3.1.0:** Function clone detection (AST JSD), return_constant_stub,
placeholder_variable_naming, SPAR adversarial regression, GQG scoring.

**v3.0.x:** Self-calibration, CI gate (`--ci-mode`), cross-file analysis,
configurable god_function thresholds with domain overrides.

**v2.9.x:** Phantom import detection, history database, History Trends command.

---

## License

MIT License — see [LICENSE](LICENSE)
