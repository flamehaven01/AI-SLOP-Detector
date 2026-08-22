# Usage Guide

**Version:** 3.8.9
**Last reviewed:** 2026-08-22

This page is the short entry point. The canonical command reference is
[CLI_USAGE.md](CLI_USAGE.md); it supersedes older examples that mentioned
removed options such as `--pattern`, `--ignore`, `--no-ml`, or `--debug`.

## Start Here

```bash
# Current file or directory baseline
slop-detector scan . --format json

# Changed-code review
slop-detector review . --format json

# Prioritize repository hotspots
slop-detector pulse . --format json

# Plan a bounded cleanup family
slop-detector sweep dead-code . --format json
```

The compatible `slop-detector path/to/file.py` and
`slop-detector --project .` forms remain available, but new automation should
use `scan`, `review`, `pulse`, and `sweep`.

## Read Results Safely

A weighted `clean` status is not a claim that the project has no findings or
that every file was analyzed. For a project JSON report, inspect:

- `finding_summary` for aggregate findings and severities
- `scan_coverage` for analyzed, excluded, and unsupported files
- `ml_scoring` for the optional ML capability state

Use `--include-tests` only when test-file findings are relevant. It includes
the built-in test-file exclusions only; configured ignores and build-artifact
exclusions continue to apply.

## Choose the Right Guide

- [CLI usage](CLI_USAGE.md): commands, output formats, init, history, and CI
- [Configuration](CONFIGURATION.md): `.slopconfig.yaml` and profiles
- [Agent workflow](AGENT_WORKFLOW.md): JSON-first review and cleanup loop
- [Claude Code skill](CLAUDE_CODE_SKILL.md): installation and agent boundaries
- [API](API.md): optional local FastAPI surface
- [Validation](VALIDATION.md): what the score does and does not establish

## Installation

```bash
pip install ai-slop-detector
slop-detector --version
```

For JavaScript or Go analysis, install the appropriate optional extra described
in [CLI_USAGE.md](CLI_USAGE.md). For a Node-first transport wrapper, see the
same guide's npm section.

## Help

```bash
slop-detector --help
slop-detector scan --help
slop-detector review --help
```

Return to the [main README](../README.md) for the product overview.
