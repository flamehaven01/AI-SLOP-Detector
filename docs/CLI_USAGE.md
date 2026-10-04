# CLI Usage

**Current contract:** `main` after v3.9.1. Run `slop-detector --help` in the installed environment for the authoritative option list.

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

## Structured Output

```bash
slop-detector scan . --format json --output scan.json
slop-detector review . --base origin/main --json --output review.json
slop-detector pulse . --format=json
```

`--json` and `--format json` are equivalent, and they are the only way to get JSON: for normal scans the output file's extension selects the human renderer (`.md` for Markdown, `.html` for HTML), and any other name, `.json` included, receives the plain-text report. Operational commands support plain text and JSON; use JSON for agents and CI.

Read project results with their scope:

- `finding_summary`: aggregate finding and severity totals.
- `scan_coverage`: analyzed, excluded, and unsupported source files.
- `ml_scoring`: optional ML capability state.
- `coherence_level`: exact or deterministic-approximate topology mode.

`clean` means the measured configured signals are below the applicable status threshold. It is not a claim that the project is complete, safe, or fully covered.

## Configuration And Init

```bash
# Create the baseline config.
slop-detector --init

# Preview adaptive suggestions without writing.
slop-detector --init-preview

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

# Inspect a repository-local recommendation.
slop-detector . --self-calibrate

# Explicit review-and-apply path.
slop-detector . --self-calibrate --apply-calibration
```

History is local. The guarded milestone path may also update an existing local config after it has enough repeat-run evidence. Calibration is a local review-sensitivity aid, not external score validation. See [SELF_CALIBRATION.md](SELF_CALIBRATION.md).

## CI And Governance

```bash
slop-detector scan . --ci-mode soft --ci-report --output slop-report.md
slop-detector scan . --ci-mode hard
slop-detector verify-governance ./.cr-ep
```

`--ci-mode` keeps the normal scan report (text, `--json`, or `--output`) and adds the gate's exit code. `--ci-report` replaces the scan report with the gate report, written to `--output` when given and otherwise printed to stdout; it does not publish a pull-request comment. Governance verification checks a generated artifact record; it is not a general compliance certification. See [CI_CD.md](CI_CD.md) and [GOVERNANCE.md](GOVERNANCE.md).

## Node, MCP, And Local Observability

```bash
npm install --save-dev ai-slop-detector
pip install ai-slop-detector
npx ai-slop-detector review . --format json

slop-detector mcp
slop-detector impact enable
slop-detector telemetry inspect --example
```

The npm package delegates to the installed Python CLI. It does not implement a second analyzer. Impact tracking is opt-in and local; telemetry is off by default. Inspect telemetry payloads before enabling it.

For agent-specific guidance, see [AGENT_WORKFLOW.md](AGENT_WORKFLOW.md) and [CLAUDE_CODE_SKILL.md](CLAUDE_CODE_SKILL.md).
