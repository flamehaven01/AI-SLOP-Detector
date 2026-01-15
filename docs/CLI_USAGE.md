# CLI Usage Guide

Complete reference for `slop-detector` command-line interface.

## Basic Commands

### Single File Analysis

```bash
# Analyze a single Python file
slop-detector mycode.py

# With JSON output
slop-detector mycode.py --json

# Save to file
slop-detector mycode.py --output report.json
slop-detector mycode.py --output report.md
slop-detector mycode.py --output report.html
```

### Project Analysis

```bash
# Scan entire project
slop-detector --project ./src

# Scan with specific path
slop-detector --project /path/to/project

# Generate markdown report
slop-detector --project ./src --output report.md
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
# Shows all 14 detectable patterns with descriptions
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

**Placeholder Patterns (14):**
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

## CI/CD Integration

See [CI/CD Integration Guide](CI_CD.md) for:
- Soft mode (informational)
- Hard mode (fail build)
- Quarantine mode (track offenders)
- Claim-based enforcement

## Complete CLI Reference

```
usage: slop-detector [-h] [--project] [--output OUTPUT] [--json] [--verbose]
                     [--config CONFIG] [--list-patterns]
                     [--disable PATTERN [PATTERN ...]]
                     [--ci-mode {soft,hard,quarantine}] [--ci-report]
                     [--ci-claims-strict]
                     [path]

AI-SLOP Detector - Evidence-based static analyzer

positional arguments:
  path                  File or directory to analyze

optional arguments:
  -h, --help            Show this help message and exit
  --project             Analyze entire project (directory)
  --output OUTPUT       Output file path (.json, .md, .html)
  --json                Output as JSON
  --verbose             Show detailed progress
  --config CONFIG       Custom config file path
  --list-patterns       List all detectable patterns
  --disable PATTERN     Disable specific patterns

CI/CD Options:
  --ci-mode {soft,hard,quarantine}
                        CI gate mode (soft/hard/quarantine)
  --ci-report           Generate CI/CD gate report
  --ci-claims-strict    Fail if production claims lack integration tests (v2.6.2)
```

## Examples

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
