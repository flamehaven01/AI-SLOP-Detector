# Reports: what the detector shows, to whom, and how

Status: **contract approved for the 3.14 line; implemented (O2-O4).** The
report view, the terminal summary (`--quiet`, `--details`, progress), the
Markdown hollow section, the HTML report and its A4 PDF, the AI report
(`--format ai`, MCP `slop_ai_report`, npm `aiReport()`) and the bundle
(`--report-dir`). Showing hollow candidates in the VS Code extension is
still open (section 8).

## 1. Two audiences, one source of truth

| Audience | Surfaces | Goal |
|---|---|---|
| A person | terminal, Markdown, HTML, PDF | see in one screen what matters, open one page for the rest, act on the top items |
| An AI agent | AI report (`ai-slop-report/1`), JSON | verify each item, fix it or reject it with evidence, prove the fix, report back - with the fewest tokens |

Every surface reads **one report view** built once from the analysis result
(`ReportView`). A renderer formats; it never computes a number, a status or a
ranking of its own. Two surfaces therefore cannot disagree. JSON stays the
full-fidelity record; the view and the AI report are derived from it.

## 2. Rules every surface follows

1. **The score and the hollow channel are separate.** The deficit score and
   its status come from the pattern and metric channel only. Semantic (hollow)
   results are shown in their own section and never change the score.
2. **Two kinds of item.**
   - `FINDING`: a pattern finding (rule, file:line, severity, evidence).
   - `REVIEW_CANDIDATE`: a semantic result (`success_without_effect`,
     `input_never_used`, ...). Shown as "review candidate", not as a defect,
     until its precision is measured on independent data.
3. **Measurement state is always shown, per channel.** `MEASURED`, `SKIPPED`
   or `UNMEASURED`. An `UNMEASURED` channel is shown as "not measured", never
   as "0 findings". A project shows how many files each state covers.
4. **UNKNOWN is shown with its denominator.** For the semantic channel:
   functions analyzed, how many reached a definite effect state, how many are
   `EFFECT_UNKNOWN` and the main open-call reasons (`external`, `dynamic`,
   ...). "12 candidates" alone is not shown; "12 candidates in 340 functions,
   210 of them not decidable (calls into other modules)" is.
5. **The headline never contradicts the findings.** The status band is kept
   as it is (`CLEAN` means the deficit score is below 30; findings can exist
   under it), and the screen shows the findings next to it. The next-step
   text never says "no action needed" while findings are open; with a
   critical or high finding it asks for a review before the scan is accepted.
   (Observed in 3.13: a project with 11 findings, 1 high, printed "All
   metrics are healthy - no action needed".)
6. **Nothing is claimed beyond the detector's evidence.** No "safe",
   "verified", "AI-written" or "production-ready" wording. A candidate is
   evidence for a review, not a verdict.
7. **Internal names stay out of human surfaces, never out of machine ones.**
   Human text uses plain words with value, healthy direction and meaning; JSON
   and the AI report keep exact identifiers.

## 3. Terminal (default `scan`)

Today: one `[INFO] Analyzing: <path>` line per file, then summary and metric
tables, then next steps. The hollow channel is not shown.

The important part fits one terminal screen. Output of the implemented
summary on a two-function demo module (abridged):

```
AI SLOP Detector 3.14.0 - demo (1 file, 1.5 s)    measurement: COMPLETE
Score     12.5/100  CLEAN (score band)
Findings  2  (critical 0 / high 0 / medium 2 / low 0)
Hollow    3 review candidate(s), not scored  -  4 functions, 2 not decidable

Findings  top 2 of 2
MEDIUM  pkg/store.py:4   return_none_placeholder  Function only returns None - likely placeholder
MEDIUM  pkg/store.py:21  empty_except             Empty handler for 'Exception' silently discards ...

Hollow review candidates (not scored)  top 3 of 3
  pkg/store.py:8   success_without_effect       save_record: reports success, and every call it
                                                makes resolves to module functions with no effect
  ...

Next
  1. 2 lower-severity finding(s) are open for review.

Full tables: --details   Report file: -o report.md
```

- Progress: one updating line on a TTY (`[37/120] ml/pipeline.py`), nothing
  when output is not a TTY. Per-file lines only with `--verbose`.
- Lists are capped at 5 pattern findings and 3 hollow candidates
  (`report_view.TERMINAL_LIMITS`), with the remaining count shown.
- The full tables of 3.13 are kept behind `--details`.
- `--quiet`: one summary line (for CI logs). Exit codes do not change.
- `--json` / `--format json` unchanged.

## 4. Report files

| Command | Writes |
|---|---|
| `-o report.md` / `-o report.html` | as today, rebuilt on the report view |
| `-o report.pdf` | new: the HTML report printed to A4 |
| `--report-dir DIR` | new, only when given: the bundle `report.md`, `report.html`, `report.pdf`, `ai-report.jsonl`, `scan.json` |
| `--format ai` | new: the AI report (JSON Lines) on stdout |

- A plain `scan` writes no file, as today. `--read-only` keeps refusing file
  output.
- `-o report.pdf` without a PDF engine fails with a clear `ENV_BLOCKED` error
  and the HTML print alternative; it never writes a broken PDF or skips
  silently.
- `--report-dir`: files of the same name in `DIR` are replaced; the command
  lists every file it wrote and every file it could not write (for example
  the PDF without an engine) and exits non-zero when one is missing. A
  partial bundle is never reported as complete.

## 5. Human Markdown

Sections, in this order: Summary (score, status, counts, measurement state) /
Findings by severity (file:line, rule, evidence, suggestion) / Hollow review
candidates (with the denominator of rule 4) / Coverage (what was and was not
measured) / Next steps. Tables stay narrow (at most 4-5 columns); long text
goes into the row below, not into a wide column.

## 6. Human HTML and PDF (one design)

The PDF is the HTML printed. Same sections, same order, one stylesheet with a
print part, so the two cannot drift.

**HTML**: one self-contained file (inline CSS and SVG, no network, no
external script), a sticky section bar, severity filter chips, collapsible
evidence. Sections: Summary / Findings / Hollow review candidates / Coverage /
Next steps / Appendix (full file list, full paths).

**PDF on A4**, the layout problems to design out:

| Problem | Rule |
|---|---|
| A wide table pushed to the next page leaves the previous page half empty | No wide tables. Findings print as compact rows (2 lines per item: location + rule / evidence), not as a 7-column table. Long paths are shortened in the middle in the body; the full path is in the appendix |
| A row or card split across pages | `break-inside: avoid` on each row and card; a section heading never ends a page (`break-after: avoid`) |
| A long table loses its header on page 2 | the table header repeats on every page |
| Page 1 overflows or is half empty | Page 1 is a one-page brief with a fixed content budget: headline, counts, measurement state, the top 5 items by priority (at most 3 of them hollow candidates, marked as such), the count of the rest, next steps. The rest starts on page 2 |
| Every section on a new page wastes paper | only the page-1 brief forces a page break; every other section flows (a forced break before the appendix left a page holding one short table in the large sample) |

Acceptance: three sample sizes (a few files, a medium project, a large one)
rendered to PDF and checked page by page before the format is called done:
no split row, no orphan heading, page 1 complete on its own.

**PDF engine** (decided: optional headless Chromium):

| Option | For | Against |
|---|---|---|
| Headless Chromium (via an optional extra) | the PDF looks exactly like the HTML print preview | a large optional download |
| WeasyPrint | Python package, print CSS support | needs system libraries on Windows |
| ReportLab | no browser | a second layout to maintain: HTML and PDF can drift |

Decision: print CSS in the HTML from the start (a browser's "Print to PDF"
gives the same A4 layout), and `-o report.pdf` through an optional extra that
drives an installed Chromium. The scan never downloads or installs a browser.
The same HTML is not promised to be pixel-identical across Chromium versions;
A4 layout is accepted by the page-by-page check above.

Safety: the analyzed repository is untrusted input. Every string from it is
HTML-escaped, the report loads no remote resource, and PDF rendering runs
with no network access and no script from the repository.

## 7. AI report: `ai-slop-report/1`

For an agent only: JSON Lines, one record per line, stable order, every item
bound to the source it was computed from. The first record is the header:
schema, tool and engine version, target, measurement state per channel,
counts, and the rules shared by every item (`hold_if`, `forbid`, `verify`,
`prove`), stated once so items stay short. Each following record is one
finding (by severity) or hollow candidate. Output of a two-function demo,
abridged (`...` marks cut fields):

```
{"schema": "ai-slop-report/1", "record": "header", "tool": "ai-slop-detector", "version": "3.14.0", "engine": "analysis-cache-v48", "target": "demo", "files": 1, "score": 12.5, "status": "CLEAN", "measurement": {"pattern": "COMPLETE", "hollow": "MEASURED"}, "findings": 2, "candidates": 3, ..., "emitted": 5, "truncated": 0, "loop": ["VERIFY", "ACK_OR_REJECT", "FIX", "PROVE", "REPORT"], "hold_if": [...], "forbid": [...], "verify": {...}, "prove": {...}}
{"record": "item", "id": "F25121da30296", "kind": "FINDING", "rule": "return_none_placeholder", "severity": "medium", "file": "pkg/store.py", "line": 4, "source_sha256": "ae59...", "channel_state": "COMPLETE", "evidence": "Function only returns None - likely placeholder", "fix": "Implement the function or clarify intent"}
{"record": "item", "id": "Cda889280e711", "kind": "REVIEW_CANDIDATE", "rule": "failure_reported_as_success", "severity": null, "file": "pkg/store.py", "line": 21, "source_sha256": "ae59...", "channel_state": "MEASURED", "evidence": "send: a catch-all handler swallows the failure and the function goes on to report success", "fix": "NOT-APPLICABLE: decide in VERIFY first"}
```

- Per item: a stable id (from kind, rule, path and line), kind, rule,
  severity (null for a candidate), path relative to the target, line, the
  file's SHA-256, the channel's state, one-line evidence and the fix
  direction. The models in `ai_report.py` are the schema (`schema()` gives
  it as JSON Schema).
- `prove` is a verification suggestion, not a command for an agent to run
  unattended; nothing taken from the analyzed repository is executed. Running
  it needs an approved test profile and environment boundary.
- The agent loop it is written for: VERIFY (source sha and locator still
  match) -> ACK or REJECT with evidence (a rejection is the false-alarm
  channel) -> FIX -> PROVE (re-run: item gone, no new item, tests pass) ->
  REPORT (one completion line). A stale sha or an unmeasured channel -> HOLD.
- Empty values are explicit: `NOT-MEASURED`, `NOT-APPLICABLE: <why>`,
  `MISSING`. A null result is a result.
- The report is checked against its JSON schema before it is written; if the
  check fails, nothing is written and the command fails (fail closed).
- Size is bounded (`--ai-limit N`, the truncated count is stated).

## 8. Same report on every entry point

| Entry point | What it gets |
|---|---|
| CLI | sections 3-7 |
| npm wrapper | `npx ai-slop-detector ...` passes every flag through; `aiReport(target, { limit })` returns the parsed records (typed in `types.d.ts`) |
| MCP | tool `slop_ai_report` (`target`, `limit`): the JSON Lines as text and the records as `structuredContent`; the JSON snapshots stay on `slop_analyze_file` / `slop_analyze_project` |
| VS Code extension | findings as diagnostics as today; hollow candidates as a separate, lower-level "review" list, never as errors (open) |

## 9. Build order

| Step | Work | Check |
|---|---|---|
| O1 | this contract, reviewed | approved |
| O2 | `ReportView` + Markdown + terminal (sections 3, 5) | done: renderer tests and controls (UNMEASURED never "0", the advice matches the findings), 3.13 / 3.14 comparison on one interpreter |
| O3 | HTML + print CSS + PDF (section 6) | done: three sample sizes, page-by-page PDF check |
| O4 | AI report + schema, `--format ai`, `--report-dir`, MCP, npm (sections 4, 7, 8) | done: schema and fail-closed tests, bundle failure contract, MCP and npm tests |
| next | VS Code review list | before the 3.14 release |

## 10. Decisions

1. PDF engine: optional headless Chromium (section 6).
2. AI report: JSON Lines, schema `ai-slop-report/1` (section 7).
3. Caps: terminal 5 findings + 3 candidates; PDF page 1 top 5 (at most 3
   candidates), the rest counted.
4. Bundle: only with an explicit `--report-dir`.
