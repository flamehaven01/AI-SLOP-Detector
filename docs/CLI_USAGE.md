# CLI Usage Guide

Complete reference for `slop-detector` command-line interface.

## Canonical Commands

The preferred stable CLI surface is:

```bash
slop-detector scan <target>
slop-detector review <target>
slop-detector pulse <target>
slop-detector sweep <family> <target>
slop-detector watch <target> --follow
slop-detector explain <identifier>
slop-detector verify-governance <target>
slop-detector mcp
```

Legacy forms such as `--project`, `audit`, `health`, and direct cleanup-family
commands remain supported for backward compatibility.

## Basic Commands

### Single File Analysis

```bash
# Canonical
slop-detector scan mycode.py

# Compatible legacy form
slop-detector mycode.py

# With JSON output
slop-detector scan mycode.py --json

# Save to file
slop-detector scan mycode.py --output report.json
slop-detector scan mycode.py --output report.md
slop-detector scan mycode.py --output report.html
```

### Project Analysis

```bash
# Canonical
slop-detector scan ./src

# Compatible legacy form
slop-detector --project ./src

# Generate markdown report
slop-detector scan ./src --output report.md
```

## Output Formats

### Text (Default)

```bash
slop-detector mycode.py
# Outputs colored text report to console
```

### JSON

```bash
slop-detector mycode.py --json
# Outputs structured JSON for programmatic use
```

### Markdown

```bash
slop-detector mycode.py --output report.md
# Generates markdown report with tables
```

### HTML

```bash
slop-detector mycode.py --output report.html
# Generates interactive HTML report
```

## Pattern Management

### List Available Patterns

```bash
slop-detector --list-patterns
# Shows all 27+ detectable patterns with descriptions
```

### Disable Specific Patterns

```bash
# Disable single pattern
slop-detector mycode.py --disable todo_comment

# Disable multiple patterns
slop-detector mycode.py --disable empty_except --disable todo_comment

# Disable via config file
slop-detector mycode.py --config .slopconfig.yaml
```

### Pattern Categories

**Placeholder Patterns (27+):**

Python / universal:
- `empty_except` - Empty exception handlers
- `not_implemented` - NotImplementedError
- `pass_placeholder` - Pass statements
- `ellipsis_placeholder` - Ellipsis (...)
- `return_none_placeholder` - Return None
- `todo_comment` - TODO comments
- `fixme_comment` - FIXME comments
- `hack_comment` - HACK comments
- `bare_except` - Bare except blocks
- `mutable_default_arg` - Mutable defaults
- `star_import` - Star imports
- `interface_only_class` - Interface classes
- `function_clone_cluster` *(v3.1.0)* - Near-duplicate function bodies (CRITICAL)
- `placeholder_variable_naming` *(v3.1.0)* - Variables named `x`, `tmp`, `dummy` in production
- `return_constant_stub` *(v3.1.0)* - Functions that always return a constant (stub pattern)
- `phantom_import` - Imported but never used module (unused dependency)
- `god_function` - Function exceeding complexity/length thresholds
- `nested_complexity` *(v3.1.0)* - Deeply nested control flow (depth ≥ 4)
- `lint_escape` - Inline lint suppression comments

JavaScript / TypeScript:
- `console_log_debug` - Leftover console.log debugging
- `any_type_cast` - TypeScript `as any` / `: any` type erasure
- `disabled_test` - `.skip` / `.todo` / `.xtest` disabled test blocks
- `promise_ignore` - Unhandled promise (missing `await` / `.catch`)

Go:
- `error_discard` - `_ = fn()` silently discarding error return
- `empty_select` - `select {}` or `select` with only a `default: break`
- `todo_go` - `// TODO` / `// FIXME` in Go source
- `unused_goroutine` - `go func()` with no channel or sync primitive

See [PATTERNS.md](PATTERNS.md) for full descriptions, severity levels, and examples.

## Project Initialization

### Bootstrap a New Project

```bash
# Auto-detect project type and generate .slopconfig.yaml
slop-detector --init

# Specify domain explicitly
slop-detector --init --domain general

# Overwrite an existing .slopconfig.yaml
slop-detector --init --force-init
```

`--init` creates a fully-documented `.slopconfig.yaml` tailored to your domain and
automatically adds `.slopconfig.yaml` to `.gitignore` (avoids leaking weakness maps).

---

## Advanced Options

### Verbose Output

```bash
slop-detector mycode.py --verbose
# Shows detailed analysis progress
```

### Custom Configuration

```bash
slop-detector mycode.py --config /path/to/config.yaml
# Uses custom configuration file
```

### Integration Test Evidence (v2.6.2)

```bash
# Enable claim-based enforcement
slop-detector --project . --ci-claims-strict

# Fails if production/enterprise claims lack integration tests
```

## Self-Calibration

```bash
# Run calibration check (does NOT write to config)
slop-detector . --self-calibrate

# Run calibration and apply optimal weights to .slopconfig.yaml
slop-detector . --self-calibrate --apply-calibration

# Require at least 8 events per class before calibrating
slop-detector . --self-calibrate --min-history 8
```

See [SELF_CALIBRATION.md](SELF_CALIBRATION.md) for full details.

---

## History & Trends

```bash
# Show recent history for files in current project
slop-detector . --show-history

# Show project-level trends over the last 30 days (default)
slop-detector . --history-trends

# Export full history to JSONL
slop-detector --export-history history.jsonl

# Disable history recording for this run
slop-detector mycode.py --no-history
```

---

## CI/CD Integration

See [CI/CD Integration Guide](CI_CD.md) for:
- Soft mode (informational)
- Hard mode (fail build)
- Quarantine mode (track offenders)
- Claim-based enforcement

## Governance Verification

The governance verification gate is separate from scoring and CI summary
reporting:

```bash
slop-detector verify-governance ./.cr-ep
```

It recomputes the canonical hash in `.cr-ep/governance_record.json` and
fails closed when:

- the record hash does not match
- `counts.halt_count > 0`
- `trust_tier == "UNTRUSTED"`

See [GOVERNANCE.md](GOVERNANCE.md) for the record contract.

## Operational Commands

These commands return the same meaning across `--json`, markdown, and plain text:

```bash
slop-detector review <path> --json
slop-detector pulse <path> --json
slop-detector sweep dead-code <path> --json
slop-detector sweep dupes <path> --json
slop-detector sweep unused-deps <path> --json
slop-detector sweep stale-suppressions <path> --json
slop-detector sweep boundary-violations <path> --json
slop-detector watch <path> --follow
slop-detector fix <path> --dry-run
slop-detector explain dead-code
```

Operational cleanup commands share one contract across text, markdown, and
JSON:

- every cleanup `issue` can carry `confidence`, `action_class`, and `evidence`
- `unused-deps` now includes project-manifest findings:
  - `manifest_unused_dependency`
  - `undeclared_import`
- `boundary-violations` remains import-cycle only unless architecture review is
  explicitly enabled in `.slopconfig.yaml`

Example opt-in architecture config:

```yaml
architecture:
  enabled: true
  preset: layered
  layers: []
```

The built-in `layered` preset keeps safe defaults:

- `api -> domain` is allowed
- `domain -> data` is blocked
- each `layer_boundary_violation` includes the matched importer/importee
  patterns plus the explicit allow/forbid rule

## MCP Server

The same structured agent surface is available over MCP stdio:

```bash
slop-detector mcp
# or
slop-mcp
```

Tools exposed by the wrapper:

- `slop_schema`
- `slop_analyze_file`
- `slop_analyze_project`

## Complete CLI Reference

```
usage: slop-detector [-h] [--project] [--output OUTPUT] [--json] [--verbose]
                     [--topology-ceiling N]
                     [--topology-mode {exact,deterministic_approximate}]
                     [--config CONFIG] [--list-patterns]
                     [--disable PATTERN [PATTERN ...]]
                     [--init] [--domain DOMAIN] [--force-init]
                     [--self-calibrate] [--apply-calibration] [--min-history N]
                     [--show-history] [--history-trends] [--no-history]
                     [--export-history FILE]
                     [--ci-mode {soft,hard,quarantine}] [--ci-report]
                     [--ci-claims-strict]
                     [path]

AI-SLOP Detector v3.8.x — Evidence-based static analyzer (Python/JS/TS/Go)

positional arguments:
  path                  File or directory to analyze

optional arguments:
  -h, --help            Show this help message and exit
  --project             Analyze entire project (directory)
  --output OUTPUT       Output file path (.json, .md, .html)
  --json                Output as JSON (diagnostics go to stderr)
  --verbose             Show detailed progress
  --topology-ceiling N  Maximum Python-file count for exact structural topology
  --topology-mode {exact,deterministic_approximate}
                        Structural topology mode above the exact ceiling
  --config CONFIG       Custom config file path
  --list-patterns       List all detectable patterns

Pattern Options:
  --disable PATTERN     Disable specific pattern by ID (repeatable)

Init Options (v3.2.0):
  --init                Generate .slopconfig.yaml for current project
  --domain DOMAIN       Specify domain for --init (general/scientific/numerical/
                        web/api/library/sdk/cli/tool/bio/finance)
  --force-init          Overwrite existing .slopconfig.yaml

Self-Calibration Options (v3.2.0):
  --self-calibrate      Run calibration check against scan history
  --apply-calibration   Write optimal weights to .slopconfig.yaml (requires ok status)
  --min-history N       Minimum events per class for calibration (default: 5)

History Options (v3.2.0):
  --show-history        Show per-file history summary for current project
  --history-trends      Show project-level trends (last 30 days)
  --no-history          Skip recording this run to history.db
  --export-history FILE Export full history as JSONL

CI/CD Options:
  --ci-mode {soft,hard,quarantine}
                        CI gate mode (soft/hard/quarantine)
  --ci-report           Generate CI/CD gate report
  --ci-claims-strict    Fail if production claims lack integration tests
```

Structural topology notes:
- Exact structural coherence uses the full MST path up to the configured ceiling.
- Above that ceiling, `deterministic_approximate` keeps output stable while avoiding repeated quadratic cost.
- JSON output exposes this through `coherence_level`, and plain-text / markdown output prints the same mode directly.

Priority hotspot notes:
- Project output now ranks files by deficit score, recent git churn, and coverage gap when those signals are available.
- `.coverage` is read from the project root by default; missing git history or missing coverage data does not fail the scan.

## Examples

### Inline Suppression

```python
# slop-disable-next-line bare_except
except:
    pass

# slop-disable all
def compatibility_layer():
    ...
# slop-enable all
```

- `slop-disable-next-line <pattern_id|all>` suppresses only the next line
- `slop-disable <pattern_id|all>` opens a block suppression
- `slop-enable <pattern_id|all>` closes a block suppression

Suppressed findings stay visible in JSON / text / markdown / rich output through
the suppression ledger.

### Development Workflow

```bash
# Quick check during development
slop-detector mycode.py

# Detailed analysis with output
slop-detector mycode.py --verbose --output report.md

# Check before commit
slop-detector --project . --disable todo_comment
```

### Code Review

```bash
# Analyze PR changes
slop-detector --project ./src --json > review.json

# Generate review report
slop-detector --project ./src --output review.md
```

### Quality Audit

```bash
# Full project audit
slop-detector --project . --output audit.html

# Strict mode (no disabled patterns)
slop-detector --project . --config strict.yaml
```

## See Also

- [Configuration](CONFIGURATION.md) - Customize thresholds and patterns
- [CI/CD Integration](CI_CD.md) - Automated quality gates
- [Development](DEVELOPMENT.md) - Contributing guidelines
