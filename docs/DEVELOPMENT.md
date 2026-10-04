# Development Guide

## Setup

```bash
git clone https://github.com/flamehaven01/AI-SLOP-Detector.git
cd AI-SLOP-Detector
python -m venv .venv
# Windows: .venv\Scripts\activate
# POSIX: source .venv/bin/activate
pip install -e ".[dev]"
slop-detector --version
```

Optional language and API extras are declared in `pyproject.toml`. Install only
the extras required by the test or integration being changed.

## Current Module Boundaries

```text
src/slop_detector/
  core.py                 compatibility facade and orchestration
  core_scoring.py         deterministic file-score helpers
  core_topology.py        DCF and structural coherence helpers
  core_project.py         discovery, coverage, aggregation
  cli*.py                 parsers, routing, analysis, output, history, init
  operations*.py          audit, health, cleanup, architecture helpers
  metrics/                LDR, inflation, dependency and related signals
  patterns/               registry and advanced pattern detectors
  analysis/               cross-file import graph, structure and connection evidence
  autofix/                line-oriented patchers (`--fix`)
  gate/                   legacy SlopGate (`--gate`)
  governance/             governance session and `verify-governance`
  ml/                     optional ML scoring and self-calibration
  auth/                   experimental, not wired into the core
  config/                 bundled data (known dependency names)
  languages/              JS/TS and Go adapters
  mcp/                    stdio tool surface
  api/                    optional local FastAPI surface
tests/                    regression and contract tests
npm-wrapper/              Node transport over the Python CLI
vscode-extension/         editor integration
```

Keep pure calculation in the focused `core_*` modules. Keep `core.py` facades
when an existing integration or test patches that seam. Do not duplicate score
or result-contract logic in the CLI, npm wrapper, or editor extension.

## Verification

Run focused tests while changing a module, then the declared local suite before
asking for review:

```bash
python -m pytest tests/test_core.py -q
python -m pytest -q --no-cov
python -m black --check src tests
python -m ruff check src tests
python -m mypy src
```

For a detector change, add a regression fixture and a negative control. For a
public contract change, test the CLI JSON, npm type surface, or MCP/API model
that consumes it. A passing local suite does not prove deployment behavior,
external validity, or release readiness.

## Documentation Rules

- Update the current behavior guides when CLI, config, JSON, or integration
  contracts change.
- Preserve `CHANGELOG.md` and `RELEASE_NOTES.md` as historical records.
- Keep `LEDA_CALIBRATION.md` and `LEDA_TURBO_PROTOCOL_DOGFOODING.md` marked as
  legacy material rather than using them for current behavior.
- State limits as clearly as capabilities. Do not convert dogfooding or local
  tests into accuracy, performance, security, or compliance claims.

## Commits And Releases

Stage only the intended paths:

```bash
git add <changed-paths>
git commit -m "type(scope): concise change summary"
```

Keep unreleased changes in `CHANGELOG.md` until a user-facing release is ready.
For a release, update the package version surfaces, validate the declared
release profile, create an annotated tag, and create the GitHub Release. The
release workflow owns publication; do not upload packages manually as a normal
development step.

## Review Checklist

- The diff preserves public and patch seams or deliberately version them.
- Targeted tests cover the changed behavior and an adverse case where relevant.
- Formatter, linter, and type checks pass for changed Python code.
- Documentation describes the observed implementation, not a roadmap.
- No secrets, local databases, build products, or generated reports are staged.

See [CLI_USAGE.md](CLI_USAGE.md), [CONFIGURATION.md](CONFIGURATION.md),
[VALIDATION.md](VALIDATION.md), and [GOVERNANCE.md](GOVERNANCE.md).
