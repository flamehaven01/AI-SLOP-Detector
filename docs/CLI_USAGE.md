# CLI Usage

**Current contract:** v3.10.1. Run `slop-detector --help` in the installed environment for the authoritative option list.

## Canonical Commands

```bash
# Baseline analysis. `scan` is the preferred spelling.
slop-detector scan <target>

# Changed-code attribution. `review` maps to the audit operation.
slop-detector review <target> --base HEAD

# Repository hotspots. `pulse` maps to the health operation.
slop-detector pulse <target>

# Bounded cleanup families.
slop-detector sweep dead-code <target>
slop-detector sweep dupes <target>
slop-detector sweep unused-deps <target>
slop-detector sweep stale-suppressions <target>
slop-detector sweep boundary-violations <target>

# Artifact integrity.
slop-detector verify-governance <project-or-record>
```

Compatible forms remain available: `slop-detector <path>`, `slop-detector --project <directory>`, `audit`, `health`, and direct cleanup family commands. New automation should prefer the canonical forms above.

A directory is scanned as a project. A single `.py` file is scanned as Python; a
single `.js`, `.jsx`, `.ts`, `.tsx` or `.go` file is scanned in its own language
(as a project of that one file).

`--read-only` (also accepted as `--inspector-read-only`) changes nothing in the
project or in the detector's state (history, impact, telemetry, analysis cache)
and refuses write-capable options such as `--output`, `--fix`, `--init`,
`--ci-mode` and `--ci-report`.

## Structured Output

```bash
slop-detector scan . --format json --output scan.json
slop-detector review . --base origin/main --json --output review.json
slop-detector pulse . --format=json
```

`--json` and `--format json` are equivalent, and they are the only way to get JSON: for normal scans the output file's extension selects the human renderer (`.md` for Markdown, `.html` for HTML), and any other name, `.json` included, receives the plain-text report. Operational commands support plain text and JSON; use JSON for agents and CI.

Read project results with their scope:

- `finding_summary`: aggregate finding and severity totals.
- `scan_coverage`: analyzed, excluded, unsupported, and failed source files; `complete` is false when any file could not be analyzed (a hard gate then fails with "analysis incomplete"); `analysis_modes.javascript` says whether JS/TS was analyzed with tree-sitter or the regex fallback.
- `scan_coverage.measurement_state`: `COMPLETE`, `PARTIAL` (some files or checks could not be measured; the score covers the rest) or `NO_MEASUREMENT` (no file was analyzed; `score_valid` is false and `reason` is `all_analysis_failed`, `all_excluded` or `no_eligible_files`). Human reports then show `NOT EVALUATED` and `N/A`.
- `ml_scoring`: optional ML capability state.
- `coherence_level`: exact or deterministic-approximate topology mode.

`--fail-threshold N` exits 1 when the headline score (weighted for a project) is above `N`, and when every file failed to analyze; a scan with nothing to measure is not evaluated and exits 0. A hard CI gate (`--ci-mode hard`) fails an incomplete scan and warns without failing when there was nothing to measure.

`clean` means the measured configured signals are below the applicable status threshold. It is not a claim that the project is complete, safe, or fully covered.

## Configuration And Init

```bash
# Create the baseline config in the current directory, or in a given one.
slop-detector --init
slop-detector path/to/repo --init

# Preview adaptive suggestions without writing.
slop-detector --init --adaptive-init --init-preview

# Explicitly merge adaptive suggestions.
slop-detector --init --adaptive-init --apply-init-suggestions

# Use a chosen config.
slop-detector scan . --config .slopconfig.yaml
```

`--include-tests` removes only the built-in test-file exclusions. It does not override user-configured ignores or artifact exclusions.

See [CONFIGURATION.md](CONFIGURATION.md) and [CONFIG_EXAMPLES.md](CONFIG_EXAMPLES.md).

## Fixes And Suppressions

```bash
# Inspect registered line-oriented patches first.
slop-detector scan module.py --fix --dry-run

# Apply only after reviewing the dry run.
slop-detector scan module.py --fix

# Disable one pattern for this invocation.
slop-detector scan module.py --disable todo_comment
```

Only selected line-oriented patterns have patchers. Cleanup confidence and a dry-run result are review evidence, not autonomous authorization to modify code. Use inline suppressions or `.slopconfig.yaml` only with an explanation that can be reviewed later.

## History And Calibration

```bash
# Avoid writing local history for this run.
slop-detector scan . --no-history

# Advisory weight report from local history (never writes weights).
slop-detector . --self-calibrate
```

History is local, and scans never run calibration. The report (Calibration v2) uses only rows of the scanned project root that were measured the same way (detector, engine and configuration); rows written before v3.10 are not evidence. `--apply-calibration` is disabled: it writes nothing and exits 2. See [SELF_CALIBRATION.md](SELF_CALIBRATION.md).

## CI And Governance

```bash
slop-detector scan . --ci-mode soft --ci-report --output slop-report.md
slop-detector scan . --ci-mode hard
slop-detector verify-governance ./.cr-ep
```

`--ci-mode` keeps the normal scan report (text, `--json`, or `--output`) and adds the gate's exit code. `--ci-report` replaces the scan report with the gate report, written to `--output` when given and otherwise printed to stdout; it does not publish a pull-request comment. Governance verification checks a generated artifact record; it is not a general compliance certification. See [CI_CD.md](CI_CD.md) and [GOVERNANCE.md](GOVERNANCE.md).

## Node, MCP, And Local Observability

```bash
pip install ai-slop-detector
npm install --save-dev /path/to/AI-SLOP-Detector/npm-wrapper   # not on the npm registry
npx ai-slop-detector review . --format json

slop-detector mcp
slop-detector impact enable
slop-detector telemetry inspect --example
```

The npm wrapper is not published to npm (its package.json is private); install it from a checkout of this repository. It delegates to the installed Python CLI. It does not implement a second analyzer. Impact tracking is opt-in and local; telemetry is off by default. Inspect telemetry payloads before enabling it.

For agent-specific guidance, see [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) and [CLAUDE_CODE_SKILL.md](CLAUDE_CODE_SKILL.md).
