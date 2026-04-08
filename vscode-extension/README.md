# AI SLOP Detector — VS Code Extension v3.1.1

Real-time AI-generated code quality analysis inside VS Code. Surfaces
deficit scores, structural anti-patterns, ML signals, clone detection,
and actionable diagnostics without leaving your editor.

---

## What's New in v3.1.1

- **Clone Detection in Core Metrics**: `function_clone_cluster` results are
  now visible in the Core Metrics summary row — CRITICAL/PASS at a glance.
  Previously only surfaced in the Issues section.
- **Workspace QuickPick**: "Analyze Workspace" now shows a sorted QuickPick
  list of deficit files. Click any file to open it directly in the editor.
- **JSON parse fix**: `extractJson()` strips `[INFO]` log lines before parsing
  — prevents silent failures when CLI emits log output alongside JSON.
- **`recordHistory` fix**: setting `slopDetector.recordHistory: false` now
  correctly passes `--no-history` to the CLI.
- **History Trends formatting**: formatted column table (Runs / Latest / Best /
  Worst / Trend) replaces raw JSON dump in the Output panel.
- **Status bar tooltip**: null-safe metric access; includes Clone PASS/CRITICAL.

## What's New in v3.1.0

- **Function Clone Detection** (`function_clone_cluster`): AST Jensen-Shannon
  divergence detects structurally identical function bodies — the primary
  evasion pattern for copy-paste slop at scale.
- **Return Constant Stub** (`return_constant_stub`): catches functions whose
  entire body is `return <literal>` — a real-structure-but-zero-value pattern.
- **Placeholder Variable Naming** (`placeholder_variable_naming`): detects
  numbered variable sequences (`data1`, `data2`, `data3`) indicating
  copy-paste expansion instead of proper abstraction.
- **SPAR adversarial regression**: 55 adversarial cases validated against the
  full detection pipeline; false-positive rate confirmed < 5%.
- **GQG (Geometric Quality Gate)**: weighted geometric mean replaces
  arithmetic mean for deficit scoring — outlier metrics now dominate correctly.

---

## Features

### Inline Diagnostics (Problems Panel)

Every analysis run produces structured diagnostics in the Problems panel:

| Source label | Diagnostic type | Severity |
|---|---|---|
| SLOP Detector | Summary: score, status, LDR/ICR/DDC, ML score, Clone | Error / Warning / Info |
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
- LDR / ICR / DDC metric values
- ML slop probability (when model is present)
- Clone Detection: PASS or CRITICAL

### Workspace Analysis (QuickPick)

"Analyze Workspace" scans all Python files and opens an interactive QuickPick:

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
| SLOP Detector: Auto-Fix Issues | Apply or preview (dry-run) auto-fixable patterns |
| SLOP Detector: Show Gate Decision (SNP) | Display SNP gate result |
| SLOP Detector: Run Cross-File Analysis | Detect cycles, duplicates, hotspots |
| SLOP Detector: Show File History | View historical score for current file |
| SLOP Detector: Show History Trends | Formatted table: Runs / Latest / Best / Worst / Trend |
| SLOP Detector: Export History to JSONL | Export full history DB to `.jsonl` |
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
code --install-extension vscode-slop-detector-3.1.1.vsix
```

---

## Requirements

- **Python 3.9+**
- `ai-slop-detector` installed in the Python environment VS Code uses:

```bash
pip install ai-slop-detector          # core only
pip install "ai-slop-detector[ml]"    # + ML secondary signal
pip install "ai-slop-detector[js]"    # + JS/TS tree-sitter patterns
pip install "ai-slop-detector[full]"  # everything
```

The extension invokes `python -m slop_detector.cli <file> --json` internally.
Set `slopDetector.pythonPath` if your Python interpreter is not on `PATH`.

---

## Configuration

Open Settings (`Ctrl+,`) and search **"SLOP Detector"**, or edit `settings.json`:

```jsonc
{
  "slopDetector.enable": true,
  "slopDetector.lintOnSave": true,
  "slopDetector.lintOnType": false,
  "slopDetector.showInlineWarnings": true,
  "slopDetector.failThreshold": 50.0,   // deficit_score >= 50 -> Error
  "slopDetector.warnThreshold": 30.0,   // deficit_score >= 30 -> Warning
  "slopDetector.pythonPath": "python",
  "slopDetector.configPath": "",        // path to .slopconfig.yaml (optional)
  "slopDetector.recordHistory": true    // write results to ~/.slop-detector/history.db
}
```

### Deficit Score Thresholds

| Status | deficit_score |
|---|---|
| CLEAN | < 30 |
| SUSPICIOUS | 30 – 49 |
| INFLATED_SIGNAL | 50 – 69 |
| CRITICAL_DEFICIT | >= 70 |

Recommended: `warnThreshold: 30`, `failThreshold: 50` (defaults).

---

## Pattern Reference (v3.1.1 — 27 patterns)

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
