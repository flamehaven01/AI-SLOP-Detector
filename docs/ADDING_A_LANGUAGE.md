# Adding a language

Python has its own analysis (patterns, the hollow channel, docstring promises,
structural locators). Every other language is an **adapter**: an analyzer
registered in `src/slop_detector/language_registry.py`. A registered adapter
reaches every surface by itself: discovery, scan coverage, the project score,
the finding summary, the report view and every human report (terminal,
`--details`, Markdown, HTML, PDF), the AI report and work order, the CI gate
and quarantine, history and telemetry, the JSON, the REST snapshot, the
public `languages.get_analyzer_for_file` lookup and the `--init` language
count.

Releases 3.15.1 and 3.15.2 each fixed a language that one surface did not
know. The registry, and the tests below, exist so that this cannot ship again.

## What the tests enforce

`tests/test_language_slot.py` registers a language that exists only in the
test ("toy") and checks that its findings appear on every surface listed
above, including a scan of a single `.toy` file and the real `--details`
command. The PDF is the HTML report printed by a local browser, so the test
checks its content through the HTML. It also fails when:

- a registered language has no field in `ProjectAnalysis`
  (`models.py`), in the REST model `AgentProjectResponse`
  (`api/models.py`) or in the npm types (`npm-wrapper/types.d.ts`);
- a registered extension is still listed as unsupported
  (`core_project._UNSUPPORTED_SOURCE_EXTENSIONS`);
- any code outside `language_registry.py`, `models.py` and `api/models.py`
  reads a language result by its key (`js_file_results`, ...);
- a file whose analysis raises is not recorded as a failed file of its
  language (the scan goes on), or the Markdown coverage table has no column
  for the language;
- the VS Code extension names a language result key instead of reading every
  `*_file_results` list;
- the VS Code extension's one language list (`src/languages.ts` in the
  extension) misses a registered extension, its manifest does not activate on
  one of the listed language ids, or another extension file keeps a language
  list of its own.

These checks were themselves tested: 16 deliberately broken copies (a
consumer that knows only JS/TS and Go: reports, gate, summary, history,
telemetry, JSON, REST, analysis, counts, modes, file lookup, `--init`; a
language registered without its fields; a direct key read) were all caught.

## Steps

1. **Analyzer.** `src/slop_detector/languages/<name>_analyzer.py`. Per file
   it returns an object with `file_path`, `total_lines`, `issues`,
   `slop_score` (0-100), `status` (`clean`, `suspicious`,
   `critical_deficit`), `ast_mode`, `source_sha256`, `content_origin` and
   `to_dict()`. Each issue has `pattern_id`, `severity` (a string:
   `critical`, `high`, `medium`, `low`), `line`, `message`, `suggestion`,
   `fingerprint`, `locator`. Finish with `finding_identity.bind_lines` (it
   binds the result to the bytes read and addresses the issues by line).
2. **Registry entry** in `language_registry.LANGUAGES`: name, label, result
   key (`<name>_file_results`), extensions, the analyzer factory, and how the
   analysis mode is reported. When the language's build tool writes sources
   into the project (Cargo's `target/`), list them in `extra_ignore`: they
   are skipped for that language only and listed as excluded in scan
   coverage.
3. **Schema fields** the slot test asks for: `ProjectAnalysis`,
   `AgentProjectResponse`, `types.d.ts` (the REST snapshot also keeps a
   language without a declared field, as an extra field); remove the
   extensions from the unsupported list. `LANGUAGE_ANALYZERS` and the
   `--init` table follow the registry by themselves. The VS Code extension
   needs the extensions and the VS Code language id in its `languages.ts`
   and an `onLanguage:` activation event in its manifest.
4. **Rules, each with:**
   - a **fix text** (`suggestion`), on every parser path: a rule found by a
     fallback parser has the same fix as on the AST path (3.15.1 found a
     fallback whose findings had none);
   - a positive and a negative control (the code shape it reports, and the
     shapes it must leave alone);
   - a severity a reviewer can defend: three critical findings fail the CI
     gate.
5. **Precision before release.** Run the analyzer on public repositories
   chosen and pinned (commit) before the run, and read the findings: label
   each true positive, false positive or unsure, and publish the counts
   with the release. A rule with false positives on legitimate code is
   narrowed or dropped before release, not after.
6. **Mutation.** Break each new rule in a copy and require a test to fail
   (see the mutation runners described in DEVELOPMENT.md).

## What an adapter does not get

- The hollow channel and docstring promises are Python-only. An adapter
  reports pattern findings and a score.
- Locators are lines (with the column, or the order on the line, when one
  rule fires twice on a line): a line shift changes an adapter item's id.
- Inflation and DDC are Python metrics; the CI gate never judges an adapter
  on a metric it does not measure.
