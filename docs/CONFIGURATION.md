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

  inflation:
    critical: 1.0     # Above this = critical
    warning: 0.5      # Above this = warning

  ddc:
    critical: 0.50    # Below this = critical (50% unused)
    warning: 0.70     # Below this = warning (30% unused)

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
  exact_topology_ceiling: 300
  topology_mode_above_ceiling: deterministic_approximate
  analysis_cache_enabled: true
  churn_commit_window: 200
  coverage_data_file: ".coverage"
  hotspot_limit: 10

architecture:
  enabled: false
  preset: none
  layers: []
```

`architecture` is opt-in. If you do nothing, `boundary-violations` reports
import cycles only.

## Config Validation (v3.7.2)

`.slopconfig.yaml` is validated by Pydantic v2 schemas before merging into the
default config. Invalid values raise `ValueError` with the exact field path —
before they can reach the GQG formula or the LEDA calibration grid search.

### Validated Sections

**`weights:` block** — each key must be `float` in `[0.0, 1.0]`:

```yaml
# Raises ValueError at load time:
weights:
  ldr: 2.5        # Error: ldr must be <= 1.0
  inflation: -0.1 # Error: inflation must be >= 0.0
```

**`patterns.god_function:` block**:

```yaml
patterns:
  god_function:
    complexity_threshold: 10  # must be int >= 1
    lines_threshold: 50       # must be int >= 1
    domain_overrides:
      - function_pattern: "train_*"   # must be string
        complexity_threshold: 30      # must be int >= 1
        lines_threshold: 200          # must be int >= 1
```

### Error Format

All sections are validated before raising — you see every problem at once:

```
ValueError: .slopconfig.yaml validation failed:
  - weights: 1 validation error for _WeightsSchema
    ldr
      Input should be less than or equal to 1 [type=less_than_equal, input_value=2.5]
  - patterns.god_function: 1 validation error for _GodFunctionSchema
    domain_overrides.0.function_pattern
      Input should be a valid string [type=string_type, input_value=123]
```

Unknown top-level keys are silently ignored for forward compatibility.

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
| Web / API | `web/api` | FastAPI, Flask, API services |
| Library / SDK | `library/sdk` | Shared packages and client libraries |
| CLI Tool | `cli/tool` | Command-line applications |
| Bio | `bio` | Bioinformatics and lab pipelines |
| Finance | `finance` | Quant and financial analysis tooling |

Each profile comes with pre-configured `capability_vector` (weight anchors) and
`domain_overrides` (pattern severity adjustments). The `capability_vector` is used
by the self-calibration engine as the initial anchor for grid search.

Example generated config for a `general` project:

```yaml
# Generated by slop-detector --init --domain general
# Auto-added to .gitignore to protect your weakness map

domain: general

weights:
  ldr: 0.40
  inflation: 0.30
  ddc: 0.20
  purity: 0.10

capability_vector:
  ldr: 0.40
  inflation: 0.30
  ddc: 0.20
  purity: 0.10

thresholds:
  ldr:
    critical: 0.30
    warning: 0.45
  inflation:
    critical: 2.0
    warning: 1.0
  ddc:
    critical: 0.30
    warning: 0.50

patterns:
  disabled:
    - todo_comment
```

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

1. Command-line arguments (highest)
2. `.slopconfig.yaml` in current directory
3. `--config` specified file
4. Default values (lowest)

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
  inflation:
    critical: 0.8
    warning: 0.4
  ddc:
    critical: 0.60
    warning: 0.80

patterns:
  disabled: []  # Enable all patterns
```

### Lenient Mode (Development)

```yaml
thresholds:
  ldr:
    critical: 0.20
    warning: 0.50
  inflation:
    critical: 1.5
    warning: 0.8

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
