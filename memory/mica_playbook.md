# AI-SLOP Detector Playbook

How work is done in this repository. The archive (`memory/mica_archive.json`)
says what has been decided; this file says how to act on it. Both are loaded
through `mica.yaml`; MICA itself is explained at
https://github.com/flamehaven01/Flamehaven-MICA.

## Session start

1. Load the declared surfaces: `python <MICA_ROOT>/tools/mica_runtime.py . --format context`
   (or the `mica-context` skill). Say which surfaces were loaded; if the
   contract is incomplete, say so and stop relying on memory.
2. Read the archive's design invariants before editing. A change that would
   undo one needs a maintainer's decision first; the invariant names the
   tests or the procedure that hold it. An invariant marked "unreleased"
   applies to the development line only.
3. For the layout, read `docs/ARCHITECTURE.md`; for behavior a user sees,
   `docs/GUIDE.md`.

## Where things are

| Area | Path |
|---|---|
| Scan engine (one engine behind CLI, MCP, REST) | `src/slop_detector/service/`, `core.py`, `core_project.py` |
| Languages other than Python | `src/slop_detector/language_registry.py`, `languages/` |
| Python rules | `src/slop_detector/patterns/` |
| Scoring | `core_scoring.py`, `diagnostic_bands.py` |
| History and self-calibration | `history.py`, `ml/self_calibrator.py`, `ml/calibration_evidence.py` |
| CLI | `cli.py`, options `cli_parsers.py`; terminal screen `renderer_terminal.py` |
| Reports | `renderer_html.py`, `renderer_markdown.py`; AI work order `ai_report_md.py`, JSON Lines `ai_report.py` |
| VS Code extension, npm wrapper | `vscode-extension/`, `npm-wrapper/` |

## Making a change

- Behavior change: write the test that fails first, then make it pass. Name
  tests after the behavior they hold.
- New Python code is ASCII-only (Windows consoles with code page 949 fail on
  other characters). Not every existing file is ASCII yet; do not add more.
- A user-visible claim in docs or the README needs a test or a measurement
  behind it. Counts in commits and docs come from the run's output, not from
  memory.
- Any change to the scan JSON, adding a key included, is a contract change
  (DI-001): it needs a maintainer's explicit approval, an entry under
  "Changes you see when upgrading" in `CHANGELOG.md`, and the regression
  tests plus the raw byte comparison (verification step 4) showing that
  nothing else moved. Renaming or removing a key also breaks existing
  consumers.

## Verification, in this order

1. The tests of the area you touched: `pytest -q tests/<files>`.
2. The CI lint gates, all three (DI-013):
   ```bash
   python -m black --check src/ tests/      # black 24.8.0
   ruff check src/ tests/
   mypy src/
   ```
3. The full suite on the newest Python you have and on Python 3.8, the
   oldest supported: `pytest -q`.
4. If output could have changed: run the same targets with the previous
   release and this tree, e.g.
   `slop-detector --project examples/demo_project --json --no-history`, and
   compare the raw bytes. Treat both sides the same: a normalization applied
   to one side only (line endings, a version string) produces a false
   difference. Give each side its own empty `HOME`: the analysis cache and
   git's global settings live there, and either can change a result. Run
   each side twice and compare the second run too (DI-016): a cache hit must
   give the same bytes and the same file count as the first run.
5. For a behavior change, break the code on purpose (a mutation) and confirm
   a test fails. Confirm the mutation was actually applied to the code under
   test: a mutation that no longer matches the source tests nothing.

Report what was run and its result; "tests pass" without the command and the
counts is not a report.

## Release

Verification passing grants no permission. Each outward step below, the
push to `main`, the tag, the GitHub Release (which publishes PyPI and npm)
and the VS Code Marketplace upload, needs a maintainer's explicit approval
at that step; an approval for one step does not cover the next. An agent
prepares and verifies, then stops and asks.

1. One version everywhere (DI-011): `pyproject.toml`,
   `src/slop_detector/__init__.py`, `Dockerfile`, `npm-wrapper/package.json`,
   and the wrapper entry in `vscode-extension/package-lock.json`.
2. `CHANGELOG.md`: a dated section with "Changes you see when upgrading";
   `docs/RELEASE_NOTES.md`: the release section and its highlights row.
   State what changes results apart from what does not (DI-001).
3. Push to `main` as a fast-forward (no force push) and wait for every CI job.
4. Annotated tag `vX.Y.Z` with the message `release X.Y.Z`, on the commit CI
   passed.
5. A GitHub Release publishes PyPI and npm (the workflow checks the versions).
   Then download the published files and compare their contents with the
   tagged commit; the rebuilt files have their own hashes.
6. The VS Code extension: in `vscode-extension/`, `npm ci`, `npm run check`,
   `npm test`, `npx vsce package`, from the same commit. A maintainer
   uploads it to the Marketplace.

## When memory and reality disagree

The archive records what was decided, not what is true now. If code, tests
or a measurement disagree with an entry, report the conflict with the
evidence. Update the archive in the same change that alters a decision, and
keep `tests/test_mica_package.py` passing.
