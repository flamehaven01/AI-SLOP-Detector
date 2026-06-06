# AI-SLOP-DETECTOR Presentation Layer Checklist

This checklist opens the presentation chapter.

The engine absorption pass (see `AI_SLOP_DETECTOR_ABSORPTION_CHECKLIST.md`)
upgraded scoring, cleanup planning, dependency hygiene, and architecture review.
It explicitly deferred `editor/LSP expansion` and never touched output rendering.
Result: the product emits rich JSON that almost nothing renders well. The
terminal/markdown/html reports are thin, and the VS Code extension is frozen on
the pre-absorption CLI surface.

Core principle: **define once, render twice.** The asset is not a screen. It is
the presentation contract between the engine JSON and every surface that draws
it. VS Code is the proving ground; the same contract then flows back to the core
renderers. This prevents building the same thing twice and keeps the surfaces
from drifting apart.

Execution rule (same as absorption):

- finish one phase
- run the listed diagnosis
- mark the phase `OK`, `HOLD`, or `ROLLBACK`
- only then move to the next phase

---

## Intake Rules

Every presentation change must pass these gates before code work:

1. confirm the data already exists in the engine JSON; if not, it is an engine
   task, not a presentation task, and moves to the absorption track
2. render-only changes are preferred; no new scoring, no new policy, no forked
   output semantics
3. any visual element maps to a named field in the output contract
4. a design element that lands in VS Code must be expressible by at least one
   core renderer (text/rich/markdown/html) or be explicitly marked surface-only
5. preserve every existing unique surface (self-calibration, history, gate, 4D
   metric row, CodeLens, phantom_import QuickFix); improve, never remove

---

## Shared Presentation Contract (load-bearing artifact)

Status: `FROZEN 2026-06-05`. Four design decisions signed off (ASCII terminal
glyphs, Markdown emoji, penalty-attribution primary, bar-primary in VS Code) plus
three implementation rules (npm-wrapper consumption, CSS-variable webview
styling, pattern_id-based evidence). Changing this section after freeze requires
re-opening P2.

Definitions, not implementations. No CSS/JS/HTML in this section.

### Severity tokens (one source, three concrete renderings)

One token resolves to a different concrete glyph per surface. The terminal
renderers are Python source and are ASCII-only (cp949 safety, CLAUDE.md);
Markdown reports allow emoji; VS Code uses ThemeIcon/ThemeColor ids.

| Band (`SlopStatus`) | Score | Token | Terminal (ASCII) | Markdown | VS Code icon | VS Code color |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `clean` | < 30 | `clean` | `[ok]` green | ✅ CLEAN | `$(pass)` | `terminal.ansiGreen` |
| `suspicious` | 30-50 | `suspicious` | `[!]` yellow | ⚠️ SUSPICIOUS | `$(warning)` | `editorWarning.foreground` |
| `inflated_signal` | 50-70 | `inflated` | `[~]` orange | 🔶 INFLATED | `$(flame)` | `charts.orange` |
| `dependency_noise` | n/a | `dep-noise` | `[d]` magenta | 📦 DEP-NOISE | `$(package)` | `charts.purple` |
| `critical_deficit` | >= 70 | `critical` | `[x]` red | 🚨 CRITICAL | `$(error)` | `errorForeground` |

Bands are the existing scoring thresholds (README Scoring Model) and the five
`SlopStatus` enum values in `models.py` / `types.d.ts`. `dependency_noise` is
status-derived, not a score band. The contract adds only the token mapping, no
new math.

ASCII-First rule: the terminal ASCII column is the SINGLE no-color map. The
color renderer (`renderer_rich.py`) uses these same five glyphs and only adds
color on top; the no-color renderer (`renderer_text.py`) uses the glyphs alone.
The five glyphs (`[ok] [!] [~] [d] [x]`) are unambiguous without color, so one
map serves both. Do not introduce a second prefix scheme.

Note: `purity` is NOT a stored field. It is derived as `exp(-0.5 *
n_critical_patterns)` (the treeview already computes it this way). Any surface
must derive it identically, not look it up.

Bar/fill glyphs: terminal uses ASCII `#` (filled) and `.` (empty); VS Code uses
a native progress bar with the same 0-1 value and the same color token.

### 4D + breakdown panel (B1) — penalty-attribution primary

Decision (signed off): the main axis is penalty attribution, not raw 4D scores.
Raw dimensions mix "higher is better" (ldr/ddc/purity) with "higher is worse"
(inflation); penalties are uniformly "higher is worse" and sum to `total`, so
they answer "why not 0.0" directly. Raw scores are shown only as a secondary
parenthetical. The same penalty-bar is the main UI in the terminal, markdown,
and the VS Code webview. A radar of raw dims is allowed only as a small optional
summary element in the webview, and may be dropped if costly.

Inputs already in JSON (`FileAnalysis.to_dict`): the v3.7.6 `deficit_breakdown`
(`ldr_penalty`, `inflation_penalty`, `ddc_penalty`, `purity_penalty`,
`pattern_hits`, `total`) plus raw `ldr`/`inflation`/`ddc` blocks.

```
 file.py   deficit 45.2   [!] SUSPICIOUS
 Why not 0.0 -- penalty attribution (sum = total):
   inflation    ########............  12.4  <- top driver  (score 0.30)
   ldr          #####...............   8.1                  (score 0.62)
   ddc          ###.................   4.0                  (score 0.81)
   purity       ....................   0.0                  (derived 1.00)
   pattern hits ####################  20.7
   ------------------------------------------------------
   total                              45.2
```

- bar length = penalty / total (uniform direction); top driver = max penalty
- `purity` derived as `exp(-0.5 * n_critical)`, not stored
- invariant: the five penalty fields sum to `total` within 0.01 when
  `deficit_score < 100`; render-time check, emit a warning row on violation
- fallback: if `deficit_breakdown` is empty (older CLI output, or a clean file
  with no attribution), show raw 4D scores only plus one line
  `(breakdown unavailable)`; never crash the panel

### Cleanup plan layout (B2)

Inputs already in JSON: `sweep` family `confidence`, `action_class`, `evidence`.

| action_class | Threshold | Tag | Token | Default surface affordance |
| :--- | :--- | :--- | :--- | :--- |
| `safe_review` | conf >= 0.75 | `[safe]` | green | one-click jump + show evidence |
| `needs_review` | conf >= 0.45 | `[needs]` | amber | jump + evidence, no bulk action |
| `unsafe_auto_remove` | else | `[unsafe]` | red | evidence only, manual confirm required |

Thresholds are fixed in `operations.py:_classify_action` (do not re-derive in any
surface). Ordering: by `confidence` descending, stable on equivalent input.

```
 Cleanup Plan -- 12 candidates (sweep dead-code)
 [safe]   conf 0.82  utils/old_helper.py:14   unused function `legacy_parse`
            evidence: 0 refs project-wide; low churn; covered
 [needs]  conf 0.58  api/handlers.py:210      duplicate of services/io.py:88
            evidence: 92% token similarity; both edited last 30d
 [unsafe] conf 0.41  core/boot.py:3           unused import `tomli`
            evidence: high churn; runtime fallback path
```

### Evidence formatting rule

Every finding renders `message`, then `evidence` as a bullet list, then
`suggestion` prefixed with `-> `. Identical wording across terminal, markdown,
and VS Code tooltip/webview. Branch behavior on `pattern_id`, never on message
substring matching (`renderer_markdown.py` currently does the latter; the
contract retires it).

### Project summary header + hotspots

Inputs (`ProjectAnalysis.to_dict`): `overall_status`, `avg_deficit_score`,
`weighted_deficit_score` (SR9 = 0.6*min + 0.4*mean), `total_files`,
`clean_files`, `coherence_level`, `suppressed_issue_count`, `priority_hotspots`,
and the `js_file_results` / `go_file_results` counts.

```
 SLOP Report -- myproject
 [!] SUSPICIOUS   avg 31.2   weighted 28.9   files 142 (clean 118 / flagged 24)
 coherence 0.84 (vr_structural)   suppressed 7   py 120  js 18  go 4

 Priority Hotspots (deficit x churn x coverage):
   prio  file                deficit churn cov   reasons
   88.0  core/boot.py          72.1    41  31%   sloppy+churns+undertested
   61.5  api/handlers.py       45.2    22  60%   churns
```

- show both `weighted` and `avg` deficit; never collapse to one
- multi-language counts (py/js/go) appear in the header when non-zero
- churn/coverage degrade to `n/a` when `churn_analysis_available` /
  `coverage_analysis_available` is false

### Implementation rules (frozen)

- **Data source**: the VS Code extension consumes the `ai-slop-detector` npm
  package -- the runtime API (`scanProject`, `reviewChanges`, `computeHealth`,
  `runCleanupFamily`, `explain` from `lib/api.js`) and the types
  (`ai-slop-detector/types`). It must NOT spawn the Python CLI by hand or parse
  JSON manually. This retires the hand-written `schema.ts` and makes the
  extension the npm wrapper's first major consumer. Wiring: depend on the
  workspace package during dev, version-pin (`>=3.8.2`) for publish.
- **Webview styling**: use VS Code CSS theme variables (`--vscode-*`) for theme
  and accessibility. `@vscode/webview-ui-toolkit` is rejected -- Microsoft
  archived/deprecated it (Jan 2025). If a component library is later needed, the
  community successor `@vscode-elements/elements` is the only allowed option.
- **Token source**: severity tokens / thresholds come from one shared module per
  surface; never inline a color or threshold per file. P4 adds a parity test.

---

## P0 - Presentation Inventory and Boundary Check

### Target

Produce a code-backed inventory of what the engine emits versus what each
surface renders, and set the shared-vs-surface boundary.

### Diagnosis

- confirm each render candidate has a backing JSON field
- classify each surface gap as `render-only`, `re-design`, or `engine-task`

### Diagnosis Result (2026-06-05, verified against source)

- **Two separate render pipelines exist and the contract must cover both:**
  1. analysis-result path: `cli_output.py:_route_file_output` -> `renderer_{text,
     rich,markdown,html}.py`, consuming the result OBJECT
     (`FileAnalysis`/`ProjectAnalysis` from `models.py`)
  2. command-payload path: `cli_output.py:_emit_command_payload` ->
     `operations.py:render_payload_{markdown,text}`, consuming a dict payload.
     The cleanup family (`sweep`) renders here, and has NO rich/html renderer
- single JSON contract is `models.py`: `FileAnalysis.to_dict()` (ldr/inflation/
  ddc blocks + `pattern_issues[]` + optional `deficit_breakdown`, `dcf`,
  `ml_score`, `suppression_ledger`, `masked_issues`, `context_jargon`) and
  `ProjectAnalysis.to_dict()` (aggregates + `priority_hotspots[]` +
  `coherence_level` + `file_results[]` + `js_file_results[]`/`go_file_results[]`)
- `action_class` thresholds are fixed in `operations.py:_classify_action`:
  `>= 0.75` safe_review, `>= 0.45` needs_review, else unsafe_auto_remove
- HTML renderer already exists -> directly reusable by a VS Code webview
- SARIF emitter does NOT exist (grep clean) -> Problems-panel integration is an
  engine-task, deferred
- VS Code extension calls only the legacy CLI (`--project`, `--show-history`,
  `--history-trends`, `--self-calibrate`, `--init`); none of `scan/review/pulse/
  sweep/impact/verify-governance/mcp` is reachable from the editor
- `deficit_breakdown` (v3.7.6) exists in `FileAnalysis.to_dict()` but is rendered
  by NO surface (markdown/rich/text/html/extension); strongest output-improvement
  target
- `renderer_markdown.py:_md_findings_section` branches mitigation by fragile
  message substring matching (`"bare except" in desc`) instead of `pattern_id`;
  the contract's evidence rule removes this

### Boundary decisions

- 4D + breakdown visualization: render-only (High)
- cleanup plan UI: render-only (High)
- pulse/hotspot dashboard: render-only (High)
- diff-aware review: render-only, VS Code uses `review` CLI (High)
- per-pattern mute UX: re-design, client-side filter (Med)
- `.slopconfig.yaml` schema editing: re-design (Med)
- SARIF Problems integration: engine-task (deferred)
- LSP real-time push: engine-task, structural (deferred)

### OK Criteria

- inventory is code-backed
- each item has a boundary decision
- next phase is prioritized by gap, not novelty

Status: `OK`

---

## P1 - VS Code UX Foundation

### Target

Bring the manifest-level UX to current-product parity with low risk, and start
extracting the shared contract as each piece lands.

### Scope

- state-aware empty states (`viewsWelcome`) with actionable command links
- getting-started walkthrough mapped to scan -> diagnose -> patch -> gate ->
  calibrate
- context-key (`slop.hasAnalyzed`) view/title menus (analyze first, refresh after)
- settings UX: `enumDescriptions` for ci-mode and domain, `markdownDescription`,
  per-pattern-category toggles
- wire the canonical `scan / review / pulse / sweep` commands so the editor
  reflects v3.8.x, not v3.6
- migrate the data layer from hand-rolled `child_process.exec` + `schema.ts` to
  the `ai-slop-detector` npm API + `ai-slop-detector/types` (see frozen
  implementation rules); this naturally forces the modern command surface

### Risk

Low. Manifest plus thin command wiring. No scoring path touched.

### Diagnosis

- every new command resolves to an existing CLI subcommand
- empty/active states switch correctly on `hasAnalyzed`
- severity tokens used here match the contract table exactly

### OK Criteria

- no dead command in the palette
- walkthrough completes against a real repo
- token usage is sourced from the contract, not inlined per file

Status: `OK` (data layer + UX foundation complete 2026-06-06; tsc/compile clean,
no direct child_process)

Increment log:
- 2026-06-05 manifest UX foundation (DONE, tsc clean): 4-step walkthrough
  (`media/step-{scan,diagnose,fix,gate}.md` mapped to scan->diagnose->patch->gate
  ->calibrate), state-aware `viewsWelcome`, `slop.hasAnalyzed`/`slop.isClean`
  context keys set centrally in `state.ts:updateFileResult`, state-aware
  `view/title` menus, `treeview.ts` returns [] when empty so welcome renders
- 2026-06-05 npm-API data-layer migration (DONE, tsc + compile clean, scan path
  empirically verified against the real backend):
  - wrapper `npm-wrapper/lib/api.js`: added `options.cwd` passthrough so config
    discovery and history project_id stay correct (+2 tests, 7/7 pass)
  - wrapper `npm-wrapper/types.d.ts`: added `RunOptions` + 7 function
    declarations so the API is actually typed for consumers
  - extension depends on `ai-slop-detector` (`file:../npm-wrapper`, installed)
  - new `src/client.ts`: typed data layer (`scanFile`/`scanProject`/`runRaw`),
    injects pythonPath (module candidate), configPath, recordHistory, cwd
  - `analyzer.ts` `runSlopDetector` and `commands.ts` `analyzeWorkspace` now go
    through the client; no hand-rolled `child_process.exec` on the scan path
  - `schema.ts`: `ISlopReport = FileAnalysisOutput` from the npm contract;
    retired the duplicated `ILdrResult`/`IInflationResult`/`IDdcResult`
    interfaces; kept the runtime `parseSlopReport` guard
- 2026-06-06 P1 close-out (DONE, tsc + compile clean, wrapper 9/9, text path
  verified against real backend):
  - wrapper `api.js`: added `runTextCommand` (raw stdout/stderr capture, cwd,
    rejects on non-zero) + `types.d.ts` `TextResult`/`runTextCommand` decls +2
    tests
  - `client.ts`: added `runText` (text path) alongside `runRaw` (JSON path);
    ALL backend execution now flows through the wrapper
  - migrated every legacy command off `child_process.exec`:
    `calibration.ts` (autoFix/gate/init/selfCalibrate) and `commands.ts`
    (showFileHistory/installGitHook/crossFile/historyTrends/exportHistory);
    JSON-clean -> `runRaw`, JSON-with-logs and text -> `runText` (+extractJson)
  - `grep child_process src/` = 0 (clean state achieved)
  - settings UX: added `slopDetector.domain` enum with `enumDescriptions` +
    `markdownDescription`, wired into `initConfig` as `--domain`
- Version pinning strategy (item 3): dev uses `ai-slop-detector:
  file:../npm-wrapper` (installed as a symlink, live edits). Release must swap to
  a published pin (`^3.8.2`); `vsce` bundles `dependencies`, so verify at package
  time that `ai-slop-detector` is included in the VSIX (vsce does not always
  follow `file:` symlinks -- if missing, switch to the published version or
  bundle via esbuild in P4).
- P1 status: data layer + UX foundation COMPLETE. `review`/`pulse`/`sweep`
  surfacing intentionally lands in P2 as webviews (cleanup plan, pulse
  dashboard), not as raw commands here.

---

## P2 - VS Code Innovation Surfaces

### Target

Render the engine assets that no surface shows today, via webviews, and freeze
the shared contract here (this is where the design system crystallizes).

### Scope

- B1 4D radar + `deficit_breakdown` attribution panel
- B2 cleanup plan panel (confidence / action_class / evidence)
- B6 pulse health dashboard (hotspot = deficit x churn x coverage)
- B3 diff-aware review on git changes (new slop only)
- noise control: `LanguageStatusItem` + QuickPick manage + mute CodeAction across
  the 27 patterns / 5 categories

### Risk

Medium. Webview lifecycle and message passing add surface; no engine change.

### Diagnosis

- each panel renders purely from existing JSON, no new fields invented
- 4D penalty rows satisfy the sum-to-total invariant
- cleanup ordering is stable and matches CLI ordering
- mute filter guards on `source === 'slop-detector'` so other linters pass through

### OK Criteria

- the three webviews open from both palette and sidebar
- the contract tokens/components are now documented and reused, not ad hoc
- nothing in P2 forks output semantics from the CLI

Status: `PENDING`

---

## P3 - Core Output Convergence

### Target

Apply the contract proven in VS Code back to the core renderers so the terminal
and report output reach the same clarity. This is the payoff of "define once."

### Scope

- `renderer_text.py` / `renderer_rich.py`: 4D + breakdown row, severity tokens
- `renderer_markdown.py`: cleanup plan section, evidence formatting, breakdown
  table; becomes the canonical archival report
- `renderer_html.py`: align with the webview layout (shared structure)
- consistent severity tokens and evidence wording across all four renderers

### Risk

Medium. Output is consumed by CI and humans; changes must not break parsers.
JSON output is the contract and stays stable; only human-facing renderers change.

### Diagnosis

- markdown/html/text/rich render the same finding with identical wording
- no JSON field renamed or removed
- CI report consumers (`--ci-report`) still parse

### OK Criteria

- a finding looks the same conceptually in terminal, markdown, html, and VS Code
- the markdown packet is presentation-complete for archival
- no regression in machine-readable output

Status: `PENDING`

---

## P4 - Drift Guard and Hardening

### Target

Keep the two surfaces from diverging and lock the gains.

### Scope

- a single source for severity tokens / band thresholds consumed by both the
  extension and the core renderers; a test asserts parity
- VS Code unit coverage for the webview data adapters (render-from-JSON)
- docs: presentation contract section in `docs/`, extension README refresh
- packaging: VSIX builds clean against the new manifest

### Risk

Low to medium. Mostly tests and docs.

### Diagnosis

- editing a band threshold in one place updates both surfaces
- parity test fails on intentional drift
- VSIX installs on the pinned engine floor

### OK Criteria

- token/threshold drift is test-caught, not review-caught
- both surfaces ship from one documented contract

Status: `PENDING`

---

## Deferred (engine-track, not this checklist)

- SARIF emitter + VS Code Problems integration
- LSP server migration for real-time push diagnostics
- schema-driven TypeScript codegen + drift test

These are structural engine work. Revisit after P0-P4 land.

---

## Phase Order

1. `P0` presentation inventory and boundary check  (`OK`)
2. `P1` VS Code UX foundation
3. `P2` VS Code innovation surfaces  (contract frozen here)
4. `P3` core output convergence
5. `P4` drift guard and hardening

Move only after the previous phase is diagnosed and accepted.

---

## Guardrails

- The JSON output contract is stable; only human-facing rendering changes.
- Define presentation tokens once; never inline severity colors per file.
- Render-only first; if a screen needs data the engine does not emit, it is an
  engine task, not a presentation hack.
- Preserve every unique surface; this pass improves UX and output, removes none.
- VS Code is the proving ground, the core renderers are the destination; both
  consume the same contract.
