# AI SLOP Detector — VS Code Extension v2.9.1

Real-time AI-generated code quality analysis inside VS Code. Surfaces
deficit scores, structural anti-patterns, ML signals, and actionable
diagnostics without leaving your editor.

---

## What's New in v2.9.1

- **Self-inspection patch**: the Python backend (v2.9.1) now scores zero
  deficit files against its own codebase — avg deficit 11.65 → 9.57,
  weighted 15.88 → 12.42
- **God function decomposition**: `cli.py` refactored from 5 oversized
  functions into 14 focused helpers; complexity and nesting depth reduced
- **DDC false-positive fix**: `registry.py` and `question_generator.py`
  annotation-only imports now correctly classified via `TYPE_CHECKING` guard;
  `global` statement eliminated from registry singleton

## What's New in v2.9.0

- **Phantom Import Detection**: `phantom_import` (CRITICAL) fires inline when
  an import references a package that cannot be resolved in the current
  environment — catches hallucinated dependencies from AI-generated code
- **History Trends command**: `SLOP Detector: Show History Trends` displays
  per-file regression and improvement data from the SQLite history database
- **Export History command**: `SLOP Detector: Export History to JSONL` saves
  the full history database to a `.jsonl` file for ML training or auditing
- **History auto-record**: every analysis run is silently written to
  `~/.slop-detector/history.db`; disable per-file with `slopDetector.recordHistory: false`

---

## Features

### Inline Diagnostics (Problems Panel)

Every analysis run produces structured diagnostics in the Problems panel:

| Source label               | Diagnostic type                                        | Severity |
|----------------------------|--------------------------------------------------------|----------|
| SLOP Detector              | Overall summary: score, status, LDR/ICR/DDC, ML score | Error / Warning / Info |
| SLOP Detector - Inflation  | Unjustified jargon term at exact line                  | Warning |
| SLOP Detector - Docstring  | Over-documented function (doc/impl ratio)              | Error / Warning |
| SLOP Detector - Evidence   | Unjustified quality claim lacking evidence             | Warning |
| SLOP Detector - DDC        | Unused imports summary                                 | Info |
| SLOP Detector - Hallucination | Import serving no verified purpose                  | Info |
| SLOP Detector - Patterns   | Structural anti-patterns (bare_except, god_function, dead_code, deep_nesting, etc.) | Error / Warning / Info |

Pattern diagnostics use `pattern_id` as the diagnostic code — VS Code's
filter-by-code works natively (e.g., filter for `god_function` only).

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
- LDR Grade (A/B/C/D)
- LDR / Inflation / DDC metric values
- ML slop probability and confidence (when model is present)

### Lint on Save / Lint on Type

- **Lint on save** (default: on) — triggers on every `Ctrl+S`
- **Lint on type** (default: off) — triggers with 1500ms debounce to avoid
  excessive analysis during active editing

### Commands (Ctrl+Shift+P → "SLOP")

| Command                              | Description                                    |
|--------------------------------------|------------------------------------------------|
| SLOP Detector: Analyze Current File  | Run analysis on active file                    |
| SLOP Detector: Analyze Workspace     | Scan entire workspace, show summary popup      |
| SLOP Detector: Auto-Fix Issues       | Apply or preview (dry-run) auto-fixable patterns |
| SLOP Detector: Show Gate Decision    | Display SNP gate result (sr9/di2/jsd/ove)      |
| SLOP Detector: Run Cross-File Analysis | Detect cycles, duplicates, hotspots          |
| SLOP Detector: Show File History     | View historical score trends                   |
| SLOP Detector: Install Git Pre-Commit Hook | Set up pre-commit quality gate          |

---

## Installation

### From VSIX (Local)

```bash
# Build
cd vscode-extension
npm install
npm run compile
npx vsce package --out vscode-slop-detector-2.8.0.vsix

# Install in VS Code
code --install-extension vscode-slop-detector-2.8.0.vsix
```

### From Marketplace

Search **"AI SLOP Detector"** in the VS Code Extensions panel or:

```
ext install Flamehaven.vscode-slop-detector
```

---

## Requirements

- **Python 3.9+**
- `ai-slop-detector` installed in the Python environment VS Code uses:

```bash
# Core only
pip install ai-slop-detector

# With JS/TS tree-sitter support
pip install "ai-slop-detector[js]"

# With ML secondary signal
pip install "ai-slop-detector[ml]"

# Everything
pip install "ai-slop-detector[full]"
```

The extension invokes `python -m slop_detector.cli <file> --json` internally.
Set `slopDetector.pythonPath` if your Python is not on `PATH`.

---

## Configuration

Open Settings (`Ctrl+,`) and search **"SLOP Detector"**, or edit directly:

```jsonc
{
  // Enable / disable the extension
  "slopDetector.enable": true,

  // Trigger analysis on file save
  "slopDetector.lintOnSave": true,

  // Trigger analysis while typing (1500ms debounce)
  "slopDetector.lintOnType": false,

  // Show inline diagnostics
  "slopDetector.showInlineWarnings": true,

  // deficit_score >= failThreshold -> Error severity in Problems
  "slopDetector.failThreshold": 50.0,

  // deficit_score >= warnThreshold -> Warning severity in Problems
  "slopDetector.warnThreshold": 30.0,

  // Python interpreter to use
  "slopDetector.pythonPath": "python",

  // Optional path to .slopconfig.yaml
  "slopDetector.configPath": "",

  // Record results in local history database
  "slopDetector.recordHistory": true
}
```

### Threshold Alignment with v2.8.0 Status Axis

The status axis in v2.8.0 uses:

| Status            | deficit_score |
|-------------------|---------------|
| CLEAN             | < 30          |
| SUSPICIOUS        | 30 – 49       |
| INFLATED_SIGNAL   | 50 – 69       |
| CRITICAL_DEFICIT  | >= 70         |

Recommended threshold settings to match:
```json
"slopDetector.warnThreshold": 30.0,
"slopDetector.failThreshold": 50.0
```

---

## Diagnostic Reference

### Pattern IDs (v2.8.0)

The following `pattern_id` values appear as diagnostic codes. Use VS Code's
Problems panel filter to focus on specific patterns:

**Structural:**
- `empty_function` — function with only `pass` or `...`
- `bare_except` — `except:` with no exception type
- `god_function` — function >50 logic lines or cyclomatic complexity >10
- `dead_code` — statements after `return`/`raise`/`break`/`continue`
- `deep_nesting` — control-flow depth >4

**Placeholder:**
- `not_implemented` — `raise NotImplementedError`
- `mutable_default` — mutable default argument (`def f(x=[])`)
- `todo_comment` — inline TODO/FIXME
- `ellipsis_placeholder` — `...` as only function body

**Cross-Language:**
- `js_var_usage` — JavaScript `var` in Python file
- `js_console_log` — `console.log` in Python file
- `ruby_array_each` — Ruby-style `.each` block
- `go_print_format` — Go `fmt.Printf` style

### ML Score Fields (when model present)

```jsonc
// Appears in summary diagnostic message and status bar tooltip
"ml_score": {
  "slop_probability": 0.82,   // [0,1] — probability of being slop
  "confidence": 0.91,          // [0,1] — model certainty
  "label": "slop",             // "slop" | "uncertain" | "clean"
  "model_type": "random_forest",
  "agreement": false           // true if ML and rule-based agree
}
```

When `agreement` is `false`, the rule-based `deficit_score` takes precedence.

---

## Development

```bash
npm install
npm run compile     # One-time build
npm run watch       # Auto-recompile on changes
```

Press **F5** in VS Code to open Extension Development Host with the extension
loaded. The Output panel channel **"SLOP Detector"** logs all commands run and
their stdout/stderr.

---

## Changelog

See the [main CHANGELOG](https://github.com/flamehaven01/AI-SLOP-Detector/blob/main/CHANGELOG.md)
for full history.

**v2.8.0:** Python Advanced patterns (god_function, dead_code, deep_nesting),
ML score in diagnostics and tooltip, rebuilt ICR/status formulas.

**v2.7.0:** Docstring inflation diagnostics, evidence claim validation,
hallucinated dependency detection, lint-on-type debounce.

---

## License

MIT License — see [LICENSE](LICENSE)
