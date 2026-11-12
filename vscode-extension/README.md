# AI SLOP Detector for VS Code

Finds code that looks finished but is not: stubs, swallowed failures,
inputs a function never uses, success reported without an effect. The
results show up where you write code: on the line, in a hover, in Problems
and in a sidebar, and you can export them as an HTML, PDF, Markdown or AI
report without leaving the editor.

Everything runs locally through the `ai-slop-detector` Python backend.
Nothing is sent anywhere.

---

## What you see in the editor

| Where | What |
|---|---|
| **Flagged lines** | A tint and a coloured bar by severity (critical red, high orange, medium yellow, low grey; review candidates purple, dashed) and a mark in the scroll bar |
| **End of the line** | `■ MEDIUM empty_except: Empty handler for 'Exception' ...`, with `(+N)` when the line has more |
| **The line under the cursor** | A stronger tint, a frame and the full text in bold; the status bar names the item (`SLOP MEDIUM empty_except`) |
| **Hover** | For every item on the line: a severity badge, the rule, what was found, the docstring promise it breaks (if any), the **Fix**, and two links: **Copy work order for an AI agent** and **Open report**; at the bottom, the file score and what each channel measured (`pattern COMPLETE · hollow MEASURED · promises MEASURED`) |
| **Problems** (`Ctrl+Shift+M`) | One short line per item, the rule as the code (filter by `god_function`, `empty_except`, ...) |
| **Issues view** (SLOP icon in the Activity Bar) | Files by score, each with its findings and review candidates; click to jump |
| **Status bar** | The file's score and review candidates: `Good (12.5) · 2 review`, `Warning (34.1)`, `Error (67.8)`; the tooltip lists what each channel measured |
| **CodeLens** | The file's score at the top, a hint above flagged functions |

A file is analyzed when you open it or bring it to the front (once, until
you save it again), on every save, and optionally while you type.

**After you edit a file** (backend 3.14+): the analysis is bound to the
SHA-256 of the bytes it read. Once the file differs from them (unsaved
edits, or a change on disk), its highlights turn faint and dotted, the end
of the line says `(file changed - analyze again)`, the hover offers
**Analyze again**, and the status bar and the Issues view say `changed`,
so a line that may have moved is never shown as exact.

### Review candidates

With the backend 3.14 or newer, the detector also reports two kinds of
review candidate:

- **Hollow code**: it follows calls inside a module and reports functions
  whose result does not depend on what they do, for example a
  `save_record()` that returns `True` while every call it makes has no
  effect, or a catch-all handler that turns a failure into success.
- **Docstring promises** (`claim_without_mechanism`): the first sentence of a
  docstring says the function does something (`"Sum the values in
  parallel."`) and the body cannot do it (no concurrent call, no await). The
  hover shows the promise, what the body would need and what was found. A
  promise broken by code that already has a finding (a constant answer under
  `"Compute the discount"`) is shown on that finding instead.

They are **review candidates, not findings**: they never change the score,
they appear at the Information level and in purple, and the hover says so.
Decide whether the effect or the mechanism is expected there; if it is,
implement it or change the docstring. When a call goes to another module or
a value chosen at run time, the detector cannot decide and says nothing.
Turn them off with `slopDetector.showHollowCandidates`.

---

## Reports from the extension

**SLOP Detector: Export Report** (also the export icon in the Issues view)
writes a report of the workspace, or of the open file when no folder is open:

| Format | For |
|---|---|
| HTML | One self-contained page: summary cards, the top items, every finding, review candidates, score details, coverage and the file list. Severity filters on screen; prints to A4 |
| PDF (A4) | The same page printed. Needs Chrome, Edge or Chromium installed; without one the export says so and offers HTML instead |
| Markdown | A PR, an issue or a wiki page |
| AI work order (Markdown) | A document for an AI agent: the rules it must follow, a VERIFY question per rule, one block per item bound to its file's SHA-256, and a response form. **Auditor** (code excerpts, read-only; optional token budget) or **Agent** (no code copied; holds until operator approval, matching hashes and a test profile are confirmed) |
| AI report (JSON Lines) | `ai-slop-report/1`: a header with the rules every item shares, then one line per item |
| All reports | `report.md`, `report.html`, `report.pdf`, `ai-report.jsonl`, `ai-report.md` and `scan.json` in one folder |

When it is written, an **Open** button opens it: HTML in a VS Code tab or
your browser, Markdown with its preview, PDF in your PDF viewer.

**SLOP Detector: Open Report in VS Code** (the preview icon in the Issues
view, or the hover link) builds the HTML report and shows it beside the
editor.

**Copy work order for an AI agent** (in the hover) copies that one item as
the backend writes it in the work order: the contract (hard stops, the
fixes that are not allowed, invariants), the VERIFY question of its rule,
its block (location, SHA-256 of the file, evidence, the code) and the
response form. Paste it into an agent chat. The mode follows
`slopDetector.workOrderMode` (`auditor` by default). Save the file first:
the work order is bound to the bytes on disk. More on the format:
[docs/AI_WORK_ORDER.md](../docs/AI_WORK_ORDER.md).

The reports need the backend 3.14 or newer; an older backend gets a message
saying so.

---

## Commands (`Ctrl+Shift+P`, then "SLOP")

| Command | What it does |
|---|---|
| Analyze Current File | Analyze the active file |
| Analyze Workspace | Analyze every supported file; pick a file to open |
| Export Report (HTML / PDF / Markdown / AI work order / AI JSON Lines) | Write a report (see above) |
| Open Report in VS Code | Show the HTML report in a tab |
| Show 4D Breakdown (why not 0.0) | Penalty attribution: why the score is not 0 |
| Show Cleanup Plan | Confidence-ranked cleanup families (dead code, duplicates, unused dependencies, ...) |
| Show Pulse Dashboard (health + hotspots) | Project health and priority hotspots |
| Show Changed-Code Review (diff-aware) | Findings in changed code only |
| Auto-Fix Detected Issues | Apply or preview the auto-fixable patterns |
| Show Gate Decision (SNP) | The quality gate result |
| Run Cross-File Analysis | Import cycles, duplicates, hotspots |
| Show File History / Show History Trends / Export History to JSONL | Scores over time |
| Bootstrap .slopconfig.yaml | Write a config for the project |
| Run Self-Calibration | Suggest weights from your history |
| Install Git Pre-Commit Hook | Run the gate before each commit |
| Show SLOP Output Panel | The log of every backend call |
| Refresh Issues | Analyze the workspace again |

---

## Installation

Search **AI SLOP Detector** in the Extensions view, or:

```
ext install Flamehaven.vscode-slop-detector
```

From a `.vsix` file:

```bash
code --install-extension vscode-slop-detector-<version>.vsix
```

## Requirements

- **Python 3.8+** with `ai-slop-detector` installed in the interpreter VS Code uses:

```bash
pip install ai-slop-detector          # core
pip install "ai-slop-detector[js]"    # + JS/TS tree-sitter patterns
pip install "ai-slop-detector[go]"    # + Go analysis
pip install "ai-slop-detector[full]"  # everything
```

- Set `slopDetector.pythonPath` when that interpreter is not `python` on `PATH`.
- Review candidates, the reports, the work order and the changed-file
  marking need the backend 3.14 or newer; with an older backend the
  extension shows the pattern findings only.
- PDF reports need Chrome, Edge or Chromium installed.

The extension talks to the backend through the bundled `ai-slop-detector`
npm package; it does not reimplement the analysis.

---

## Settings

Open Settings (`Ctrl+,`) and search **SLOP Detector**, or edit `settings.json`:

```jsonc
{
  "slopDetector.enable": true,
  "slopDetector.analyzeOnOpen": true,          // analyze a file when it is opened
  "slopDetector.lintOnSave": true,
  "slopDetector.lintOnType": false,            // 1.5 s after you stop typing
  "slopDetector.highlightLines": true,         // tint flagged lines, frame the cursor line
  "slopDetector.showInlineWarnings": true,     // the finding at the end of its line
  "slopDetector.showHollowCandidates": true,   // review candidates: hollow code, docstring promises (backend 3.14+)
  "slopDetector.workOrderMode": "auditor",     // the copied work order: "auditor" or "agent"
  "slopDetector.enableCodeLens": true,
  "slopDetector.failThreshold": 50.0,          // score >= 50: the file summary is an Error
  "slopDetector.warnThreshold": 30.0,          // score >= 30: a Warning
  "slopDetector.pythonPath": "python",
  "slopDetector.configPath": "",               // a .slopconfig.yaml (optional)
  "slopDetector.recordHistory": true,          // keep scores in ~/.slop-detector/history.db
  "slopDetector.domain": "",                   // domain profile for --init
  "slopDetector.phantomImportAllowlist": []    // module names phantom_import skips
}
```

### Score bands

| Status | Score |
|---|---|
| CLEAN | < 30 |
| SUSPICIOUS | 30 - 49 |
| INFLATED_SIGNAL | 50 - 69 |
| CRITICAL_DEFICIT | >= 70 |

A band measures the score. A file can be CLEAN and still have findings; the
editor shows them either way.

### `phantom_import` in flat-module projects

Sibling `.py` files that import each other without a `pyproject.toml` or an
`__init__.py` are discovered automatically. If one is still reported, use
the Quick Fix in Problems, or add it to `.slopconfig.yaml`:

```yaml
phantom_import_allowlist:
  - my_local_module
```

---

## Pattern reference

The maintained catalog is [docs/PATTERNS.md](../docs/PATTERNS.md); this list
is an overview. Use the `pattern_id` as the Problems filter.

**Placeholder / stub**: `pass_placeholder`, `ellipsis_placeholder`,
`not_implemented`, `return_none_placeholder`, `return_constant_stub`,
`todo_comment`, `fixme_comment`, `hack_comment`, `xxx_comment`

**Structural**: `god_function` (over 50 logic lines or cyclomatic complexity
over 10), `dead_code`, `deep_nesting`, `empty_except`, `interface_only_class`,
`nested_complexity`, `placeholder_variable_naming`

**Quality**: `phantom_import` (an import that cannot be resolved),
`function_clone_cluster` (structurally identical function bodies)

**Cross-language**: `js_var_usage`, `js_console_log`, `ruby_array_each`,
`go_print_format`

**Go** (`ai-slop-detector[go]`): `go_empty_func`, `go_panic`, `go_fmt_print`,
`go_ignored_error`, `go_todo_comment`, `go_god_function`

**Lint escape**: `noqa_overuse`, `type_ignore_overuse`

**Hollow review candidates** (backend 3.14+, not scored):
`success_without_effect`, `input_never_used`, `effect_never_runs`,
`failure_reported_as_success`, `success_ignores_outcome`,
`finally_return_hides_failure`, and `claim_without_mechanism` (a docstring
promise the body cannot keep)

---

## Development

```bash
cd vscode-extension
npm ci
npm run check      # type check
npm run bundle     # out/extension.js
```

Package the vsix with the links of this README resolved against this folder
(vsce's default base is the repository root):

```bash
BASE="$(node -p "require('./package.json').repository.url")/blob/main/$(basename "$PWD")"
npx vsce package --baseContentUrl "$BASE" --baseImagesUrl "$BASE"
```

Press **F5** for an Extension Development Host. A development build says so
in the status bar (`SLOP: Ready (dev build)`) and in the **SLOP Detector**
output channel, which logs every backend call.

---

## Changes

See the [CHANGELOG](../CHANGELOG.md).

## License

MIT, see [LICENSE](LICENSE)
