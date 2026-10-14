# Configuration Guide

AI-SLOP Detector can be customized using `.slopconfig.yaml` in your project root.

## Basic Configuration

Create `.slopconfig.yaml`:

```yaml
# Metric weights
weights:
  ldr: 0.40        # Logic Density Ratio (40%)
  inflation: 0.30  # Jargon/Buzzword Inflation (30%)
  ddc: 0.20        # Dependency Check (20%)
  purity: 0.10     # Critical pattern purity (10%)

# Thresholds
thresholds:
  ldr:
    critical: 0.30    # Below this = critical
    warning: 0.60     # Below this = warning
  # Only the ldr thresholds are configurable.

# Pattern control
patterns:
  disabled:
    - todo_comment      # Ignore TODO comments
    - pass_placeholder  # Allow pass statements

# File exclusions
ignore:
  - "tests/"
  - "**/*_test.py"
  - "venv/"
  - ".venv/"

advanced:
  # Cross-file structure ("coherence") is measured exactly up to this many files.
  exact_topology_ceiling: 300
  # Past that ceiling, fall back to deterministic sampling. Set "exact" to force full analysis.
  topology_mode_above_ceiling: deterministic_approximate
  # Reuse analysis results for unchanged files between runs, so re-scans are faster.
  analysis_cache_enabled: true
  # How many recent commits to read when judging how often a file changes (churn).
  churn_commit_window: 200
  # Optional coverage file; when present, low-coverage files rank higher as hotspots.
  coverage_data_file: ".coverage"
  # Max number of priority "hotspot" files listed in the report.
  hotspot_limit: 10

architecture:
  enabled: false
  preset: none
  layers: []
```

`architecture` is opt-in. If you do nothing, `boundary-violations` reports
import cycles only.

## Config Validation

The config is validated before any analysis, and a config that cannot be
applied as written stops the run with `ConfigError` (a `ValueError`):

- every key the detector reads must have its type and range; values are not
  coerced (`complexity_threshold: "10"` and `hotspot_limit: true` are refused);
- `advanced.topology_mode_above_ceiling` must be `deterministic_approximate`
  or `exact`;
- a `--config` or `SLOP_CONFIG` file that does not exist, invalid YAML, or a
  top level that is not a mapping is an error, not a silent run on defaults.

```yaml
# Refused at startup:
weights:
  ldr: 2.5                      # must be within [0, 1]
patterns:
  god_function:
    complexity_threshold: "10"  # must be an integer, not a string
```

```
.slopconfig.yaml: invalid configuration
  - weights.ldr: Input should be less than or equal to 1
  - patterns.god_function.complexity_threshold: Input should be a valid integer
```

The message names the file, the key path and the expected type, and every
problem is listed at once. Keys that never had an effect only warn; unknown
keys are accepted; an empty file means defaults and a null value leaves its key
at the default. The check uses the standard library only (no pydantic needed). The raw values are merged as
written, so a partial config changes only the keys it sets.

Full specification: [docs/SCHEMA_VALIDATION.md](SCHEMA_VALIDATION.md)

---

## Integration Test Configuration (v2.6.2)

Configure integration test detection:

```yaml
evidence:
  tests:
    # Integration test detection
    integration:
      enabled: true
      # Directory path patterns
      dir_patterns:
        - "tests/integration/**"
        - "integration_tests/**"
        - "tests/e2e/**"
        - "e2e/**"
      # File name patterns
      file_patterns:
        - "test_integration_*.py"
        - "*_integration_test.py"
        - "it_*.py"
      # Pytest markers to detect
      pytest_markers:
        - "integration"
        - "e2e"
        - "slow"
      # Runtime signals detection
      runtime_signals:
        enabled: true
        keywords:
          - "testcontainers"
          - "docker-compose"
          - "TestClient"

# Quality claims validation (v2.6.2)
claims:
  production_ready:
    require_integration_tests: true
    require_unit_tests: true
    require_error_handling: true
    require_logging: true

  enterprise_grade:
    require_integration_tests: true
    require_monitoring: true
    require_security: true
```

## Domain-Aware Initialization (v3.2.0)

Instead of writing `.slopconfig.yaml` by hand, run:

```bash
slop-detector --init
slop-detector --init --domain general
slop-detector --init --adaptive-init --init-preview
slop-detector --init --adaptive-init --apply-init-suggestions
```

This generates a fully-documented config tuned to your domain profile.

The adaptive layer is conservative by design:

- preview mode prints suggestions only
- apply mode is explicit opt-in
- existing handwritten sections are preserved during merge
- architecture stays disabled unless repository evidence is strong

### Built-in Domain Profiles

| Domain | `--domain` key | Typical use case |
|---|---|---|
| General | `general` | General-purpose Python libraries and scripts |
| Scientific / Numerical | `scientific/numerical` | NumPy, SciPy, scientific computing |
| Scientific / ML | `scientific/ml` | Machine learning, deep learning, data science |
| Web / API | `web/api` | FastAPI, Flask, API services |
| Library / SDK | `library/sdk` | Shared packages and client libraries |
| CLI Tool | `cli/tool` | Command-line applications |
| Bio | `bio` | Bioinformatics and lab pipelines |
| Finance | `finance` | Quant and financial analysis tooling |

Every profile uses the default weights; a profile changes pattern thresholds
(`god_function`, `nested_complexity`) and may add ignore patterns, and `--init`
prints each threshold change
(for example `nested_complexity: depth 4 -> 4, cc 5 -> 8` for `web/api`).
Function exemptions (`domain_overrides`) are never written: an exemption by
function name would hide today's worst functions project-wide, so
`--init-preview` lists them as complexity hotspots to review, capped at three
function names with every file of each name. Domain detection reads project
code only (test files and environments are left out), and a tied lead is
`general`.

Example generated config for a `general` project (abridged):

```yaml
# Generated by: slop-detector --init
# Domain:       general  (General-purpose project (default))
version: "2.0"

# Default weights for every domain (the profile changes pattern thresholds
# only). --self-calibrate prints an advisory report; it never writes these.
weights:
  ldr:       0.40
  inflation: 0.30
  ddc:       0.20
  purity:    0.10

ignore:
  - "**/__init__.py"
  - "tests/**"
  - "**/.venv/**"
  # ...

patterns:
  god_function:
    complexity_threshold: 10
    lines_threshold: 50
    domain_overrides: []
  nested_complexity:
    depth_threshold: 4
    cc_threshold: 5
    domain_overrides: []

advanced:
  use_radon: true
```

`--init` also adds `.slopconfig.yaml` to `.gitignore` (remove that line to
share the config with your team).

---

```yaml
architecture:
  enabled: true
  preset: layered
  layers: []
```

The built-in `layered` preset is intentionally narrow and evidence-heavy:

- `api -> domain` is allowed
- `domain -> data` is blocked
- `domain -> api` is blocked
- `domain -> service` is blocked

Findings are emitted as `layer_boundary_violation` issues inside the existing
cleanup contract.

## Configuration Priority

Which file is loaded:

1. `SLOP_CONFIG` environment variable (wins over `--config`)
2. `--config <file>`
3. `.slopconfig.yaml` in the scanned project's root (or next to a single scanned file)
4. none: built-in defaults

A file named by 1 or 2 must exist. Command-line options (`--include-tests`,
`--disable`, `--topology-ceiling`, ...) then apply on top of the loaded config.

## Example Configurations

### Strict Mode (Production)

```yaml
weights:
  ldr: 0.50
  inflation: 0.30
  ddc: 0.20

thresholds:
  ldr:
    critical: 0.40
    warning: 0.70

patterns:
  disabled: []  # Enable all patterns
```

### Lenient Mode (Development)

```yaml
thresholds:
  ldr:
    critical: 0.20
    warning: 0.50

patterns:
  disabled:
    - todo_comment
    - fixme_comment
    - pass_placeholder
```

### Dependency Hygiene + Architecture Review

```yaml
ignore:
  - "tests/**"
  - "node_modules/**"

advanced:
  coverage_data_file: ".coverage"
  churn_commit_window: 200

architecture:
  enabled: true
  preset: layered
  layers: []
```

This enables:

- manifest-level `unused-deps` review for `pyproject.toml` and `package.json`
- undeclared import detection
- opt-in layered boundary review on top of default cycle detection

## See Also

- [CLI Usage](CLI_USAGE.md) - Command-line options
- [CI/CD Integration](CI_CD.md) - Automated quality gates
- [Development](DEVELOPMENT.md) - Contributing guidelines
