# Configuration Guide

AI-SLOP Detector can be customized using `.slopconfig.yaml` in your project root.

## Basic Configuration

Create `.slopconfig.yaml`:

```yaml
# Metric weights
weights:
  ldr: 0.40        # Logic Density Ratio (40%)
  inflation: 0.35  # Jargon/Buzzword Inflation (35%)
  ddc: 0.25        # Dependency Check (25%)

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
```

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

## Advanced Options

```yaml
# Buzzword categories (context-aware)
buzzwords:
  # AI/ML terms - justified if torch/tf is used
  ai_ml:
    terms: ["neural", "transformer", "deep learning"]
    justify_with: ["torch", "tensorflow", "keras"]

  # Architecture terms
  architecture:
    terms: ["byzantine", "fault-tolerant", "distributed"]
    justify_with: ["multiprocessing", "concurrent.futures"]

# Reporting options
reporting:
  formats:
    - text
    - html
    - json

  html:
    theme: "dark"
    show_charts: true

  ci:
    fail_threshold: 30
    fail_on_critical: true
```

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

## See Also

- [CLI Usage](CLI_USAGE.md) - Command-line options
- [CI/CD Integration](CI_CD.md) - Automated quality gates
- [Development](DEVELOPMENT.md) - Contributing guidelines
