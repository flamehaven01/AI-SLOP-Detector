# AI SLOP Detector Configuration Examples

## Example 1: Basic Configuration in pyproject.toml

```toml
[tool.slop-detector]
# Ignore patterns
ignore = [
    "tests/**",
    "migrations/**",
    "**/__pycache__/**",
]

# Fail threshold for CI/CD
fail-threshold = 30

# Minimum severity to report
severity = "medium"

# Disabled patterns
disable = [
    "todo_comment",  # Allow TODO comments in this project
    "magic_number",  # Allow magic numbers
]
```

## Example 2: Strict Configuration

```toml
[tool.slop-detector]
ignore = ["tests/**"]
fail-threshold = 20
severity = "high"  # Only high and critical

# Enable all patterns
disable = []

# Pattern-specific settings
[tool.slop-detector.patterns]
enable-cross-language = true
```

## Example 3: Lenient Configuration

```toml
[tool.slop-detector]
ignore = [
    "tests/**",
    "examples/**",
    "docs/**",
]
fail-threshold = 50
severity = "critical"  # Only critical issues

# Disable placeholder checks (prototype project)
disable = [
    "pass_placeholder",
    "todo_comment",
    "fixme_comment",
    "hack_comment",
]
```

## Example 4: Enterprise Configuration

```toml
[tool.slop-detector]
ignore = ["tests/**", "migrations/**"]
fail-threshold = 25
severity = "medium"

# Strict structural checks
disable = []

[tool.slop-detector.thresholds]
# Custom thresholds
ldr = {excellent = 0.90, good = 0.80}
bcr = {pass = 0.40, warning = 0.80}
ddc = {excellent = 0.95, good = 0.80}

[tool.slop-detector.weights]
# Custom weights for scoring
ldr = 0.50  # Emphasize logic density
bcr = 0.30
ddc = 0.20
```

## Using with .slopconfig.yaml

You can also use `.slopconfig.yaml` for more complex configurations:

```yaml
version: "2.1"

thresholds:
  ldr: {excellent: 0.85, good: 0.75}
  bcr: {pass: 0.50, warning: 1.0}
  ddc: {excellent: 0.90, good: 0.70}

weights:
  ldr: 0.40
  bcr: 0.30
  ddc: 0.30

ignore:
  - "tests/**"
  - "**/__init__.py"

patterns:
  enabled: true
  disabled:
    - "todo_comment"
    - "magic_number"
  severity_threshold: "medium"

advanced:
  use_radon: true
  weighted_analysis: true
```

## Pre-commit Hook Configuration

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/flamehaven/ai-slop-detector
    rev: v2.1.0
    hooks:
      - id: slop-detector
        args: ['--fail-threshold', '30']
      
      # Or use strict mode
      - id: slop-detector-strict
        args: ['--fail-threshold', '20', '--severity', 'high']
```

Then install:

```bash
pre-commit install
```

## CI/CD Integration Examples

### GitHub Actions

```yaml
- name: Check code quality
  run: |
    pip install ai-slop-detector
    slop-detector --project . --fail-threshold 30
```

### GitLab CI

```yaml
slop-check:
  script:
    - pip install ai-slop-detector
    - slop-detector --project . --fail-threshold 30
  allow_failure: false
```

### Jenkins

```groovy
stage('SLOP Check') {
    steps {
        sh 'pip install ai-slop-detector'
        sh 'slop-detector --project . --fail-threshold 30'
    }
}
```
