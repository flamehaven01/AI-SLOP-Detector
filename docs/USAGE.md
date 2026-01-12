# Complete Usage Guide - AI-SLOP Detector

**Version:** 2.6.1
**Last Updated:** 2026-01-12

---

## Table of Contents

1. [Installation](#installation)
2. [Command Line Usage](#command-line-usage)
3. [Python API](#python-api)
4. [Configuration](#configuration)
5. [Output Formats](#output-formats)
6. [CI/CD Integration](#cicd-integration)
7. [Troubleshooting](#troubleshooting)

---

## Installation

### Basic Installation

```bash
# From PyPI (recommended)
pip install ai-slop-detector

# Verify installation
slop-detector --version
```

### Development Installation

```bash
# Clone repository
git clone https://github.com/flamehaven01/AI-SLOP-Detector.git
cd AI-SLOP-Detector

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run tests to verify
pytest
```

### Optional Dependencies

```bash
# Install ML features (scikit-learn, xgboost)
pip install ai-slop-detector[ml]

# Install all features including dev tools
pip install ai-slop-detector[dev,ml]
```

---

## Command Line Usage

### Basic Commands

#### Analyze Single File

```bash
# Simple analysis
slop-detector analyze myfile.py

# With custom config
slop-detector analyze myfile.py --config .slopconfig.yaml

# Verbose output
slop-detector analyze myfile.py --verbose

# Quiet mode (errors only)
slop-detector analyze myfile.py --quiet
```

#### Scan Project

```bash
# Scan entire directory
slop-detector scan ./src

# Scan with pattern
slop-detector scan ./src --pattern "**/*.py"

# Exclude paths
slop-detector scan ./src --ignore "tests/**" --ignore ".venv/**"
```

### Advanced Options

#### Custom Thresholds

```bash
# Set LDR threshold
slop-detector scan ./src --ldr-threshold 0.6

# Set inflation threshold
slop-detector scan ./src --inflation-threshold 1.0

# Set DDC threshold
slop-detector scan ./src --ddc-threshold 0.7
```

#### Pattern Control

```bash
# Disable specific patterns
slop-detector scan ./src --disable-pattern todo_comment

# Enable only critical patterns
slop-detector scan ./src --severity critical
```

### Output Control

#### Output Formats

```bash
# JSON output
slop-detector scan ./src --format json --output report.json

# Markdown output
slop-detector scan ./src --format markdown --output REPORT.md

# HTML output
slop-detector scan ./src --format html --output report.html

# Terminal output (default)
slop-detector scan ./src --format terminal
```

#### Verbosity Levels

```bash
# Quiet (errors only)
slop-detector scan ./src -q

# Normal (default)
slop-detector scan ./src

# Verbose (detailed info)
slop-detector scan ./src -v

# Debug (all logs)
slop-detector scan ./src -vv
```

---

## Python API

### Basic Usage

```python
from slop_detector import SlopDetector

# Initialize detector
detector = SlopDetector()

# Analyze file
result = detector.analyze_file("mycode.py")

# Print summary
print(f"Status: {result.status.value}")
print(f"Deficit: {result.deficit_score:.1f}/100")
print(f"LDR: {result.ldr.ldr_score:.2%}")
print(f"Inflation: {result.inflation.inflation_score:.2f}x")
```

### Advanced Usage

```python
from slop_detector import SlopDetector
from slop_detector.models import SlopStatus

# Initialize with custom config
detector = SlopDetector(config_path=".slopconfig.yaml")

# Analyze file
result = detector.analyze_file("mycode.py")

# Check status
if result.status == SlopStatus.CRITICAL_DEFICIT:
    print("CRITICAL ISSUES FOUND!")
    
    # Show warnings
    for warning in result.warnings:
        print(f"  - {warning}")
    
    # Show pattern issues
    for issue in result.pattern_issues:
        print(f"  Line {issue.line}: {issue.message}")

# Access detailed metrics
print(f"\nLDR Breakdown:")
print(f"  Logic lines: {result.ldr.logic_lines}")
print(f"  Empty lines: {result.ldr.empty_lines}")
print(f"  Total lines: {result.ldr.total_lines}")

print(f"\nInflation Details:")
print(f"  Jargon count: {result.inflation.jargon_count}")
print(f"  Buzzwords: {', '.join(result.inflation.jargon_found[:5])}")

print(f"\nDDC Analysis:")
print(f"  Imported: {len(result.ddc.imported)}")
print(f"  Used: {len(result.ddc.actually_used)}")
print(f"  Unused: {len(result.ddc.unused)}")
```

### Project Analysis

```python
from pathlib import Path
from slop_detector import SlopDetector

detector = SlopDetector()

# Analyze entire project
project_result = detector.analyze_project(
    project_path="./src",
    pattern="**/*.py"
)

# Summary stats
print(f"Total files: {project_result.total_files}")
print(f"Clean files: {project_result.clean_files}")
print(f"Slop files: {project_result.deficit_files}")
print(f"Average deficit: {project_result.avg_deficit_score:.1f}")
print(f"Weighted deficit: {project_result.weighted_deficit_score:.1f}")

# Per-file results
for file_result in project_result.file_results:
    if file_result.status != SlopStatus.CLEAN:
        print(f"\n{file_result.file_path}:")
        print(f"  Status: {file_result.status.value}")
        print(f"  Score: {file_result.deficit_score:.1f}")
```

### Custom Configuration in Code

```python
from slop_detector import SlopDetector, Config

# Create custom config
config = Config()
config.set("thresholds.ldr.critical", 0.4)
config.set("thresholds.inflation.fail", 1.5)

# Use custom config
detector = SlopDetector()
detector.config = config

# Analyze with custom thresholds
result = detector.analyze_file("mycode.py")
```

---

## Configuration

### Configuration File Format

Create `.slopconfig.yaml`:

```yaml
version: "2.0"

# Metric thresholds
thresholds:
  ldr:
    excellent: 0.85
    good: 0.75
    acceptable: 0.60
    warning: 0.45
    critical: 0.30
  
  inflation:
    pass: 0.50
    warning: 1.0
    fail: 2.0
  
  ddc:
    excellent: 0.90
    good: 0.70
    acceptable: 0.50
    suspicious: 0.30

# Metric weights (must sum to 1.0)
weights:
  ldr: 0.40
  inflation: 0.30
  ddc: 0.30

# Files to ignore
ignore:
  - "**/__init__.py"
  - "tests/**"
  - "**/*_test.py"
  - "**/test_*.py"
  - "**/*.pyi"
  - ".venv/**"
  - "venv/**"

# Exception handling
exceptions:
  abc_interface:
    enabled: true
    penalty_reduction: 0.5
  
  config_files:
    enabled: true
    patterns:
      - "**/settings.py"
      - "**/config.py"
      - "**/constants.py"
  
  type_stubs:
    enabled: true
    patterns:
      - "**/*.pyi"

# Pattern detection
patterns:
  disabled:
    - "todo_comment"    # Allow TODO comments
    - "fixme_comment"   # Allow FIXME comments
  
  severity_filter: "medium"  # Only report medium+ severity

# Advanced options
advanced:
  use_radon: true
  weighted_analysis: true
  min_file_size: 10
  max_file_size: 10000
```

### Environment Variables

```bash
# Config file location
export SLOP_CONFIG=".slopconfig.yaml"

# Output format
export SLOP_OUTPUT_FORMAT="json"

# Verbosity
export SLOP_VERBOSE="1"
```

---

## Output Formats

### JSON Format

```json
{
  "file_path": "mycode.py",
  "status": "critical_deficit",
  "deficit_score": 85.3,
  "ldr": {
    "ldr_score": 0.42,
    "logic_lines": 25,
    "empty_lines": 35,
    "total_lines": 60,
    "grade": "F"
  },
  "inflation": {
    "inflation_score": 2.8,
    "jargon_count": 45,
    "avg_complexity": 12.5,
    "status": "FAIL",
    "jargon_found": ["neural", "transformer", "quantum"]
  },
  "ddc": {
    "usage_ratio": 0.3,
    "imported": ["os", "sys", "json", "typing"],
    "unused": ["json", "typing"],
    "grade": "D"
  },
  "warnings": [
    "CRITICAL: Logic density only 42.00%",
    "CRITICAL: Inflation ratio 2.80"
  ],
  "pattern_issues": [
    {
      "pattern_id": "bare_except",
      "severity": "critical",
      "message": "Bare except catches everything",
      "line": 45,
      "suggestion": "Catch specific exceptions"
    }
  ]
}
```

### Markdown Format

See [DETECTION_REPORT.md](../tests/corpus/DETECTION_REPORT.md) for full example.

### Terminal Format

```
================================================================
  AI-SLOP Analysis Report
================================================================

File: mycode.py
Status: CRITICAL_DEFICIT
Deficit Score: 85.3/100

Metrics:
  [F] LDR: 42.00% (25 logic / 60 total lines)
  [F] Inflation: 2.80x (45 buzzwords detected)
  [D] DDC: 30.00% (2/4 imports unused)

Buzzwords Found:
  neural, transformer, quantum, cutting-edge, state-of-the-art

Pattern Issues (2):
  [CRITICAL] Line 45: Bare except catches everything
  [HIGH]     Line 12: Empty function with only pass

Warnings:
  - CRITICAL: Logic density only 42.00%
  - CRITICAL: Inflation ratio 2.80
  - PATTERNS: 1 critical issues found

================================================================
```

---

## CI/CD Integration

### GitHub Actions

```yaml
name: Code Quality Check

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  slop-check:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install AI-SLOP Detector
        run: pip install ai-slop-detector
      
      - name: Run slop detection
        run: |
          slop-detector scan ./src \
            --format json \
            --output slop-report.json \
            --ldr-threshold 0.6 \
            --inflation-threshold 1.5
      
      - name: Upload report
        uses: actions/upload-artifact@v3
        with:
          name: slop-report
          path: slop-report.json
      
      - name: Fail on critical issues
        run: |
          python -c "
          import json
          with open('slop-report.json') as f:
              report = json.load(f)
              if report['status'] == 'critical_deficit':
                  exit(1)
          "
```

### GitLab CI

```yaml
stages:
  - test
  - quality

slop-detection:
  stage: quality
  image: python:3.10
  
  before_script:
    - pip install ai-slop-detector
  
  script:
    - slop-detector scan ./src --format json --output slop-report.json
  
  artifacts:
    reports:
      codequality: slop-report.json
    paths:
      - slop-report.json
    expire_in: 1 week
  
  allow_failure: true
```

### Pre-commit Hook

Install as git hook:

```bash
# .git/hooks/pre-commit
#!/bin/bash

echo "Running AI-SLOP Detector..."

# Get staged Python files
FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$')

if [ -z "$FILES" ]; then
    exit 0
fi

# Run detector
slop-detector analyze $FILES --quiet

if [ $? -ne 0 ]; then
    echo "❌ AI-SLOP detected! Fix issues before committing."
    exit 1
fi

echo "✅ Code quality check passed."
exit 0
```

---

## Troubleshooting

### Common Issues

#### Import Error: No module named 'slop_detector'

```bash
# Solution: Install package
pip install ai-slop-detector

# Or install from source
pip install -e .
```

#### Syntax Error in Analyzed File

The detector handles syntax errors gracefully:
- Syntax errors are reported as CRITICAL_DEFICIT
- Deficit score = 100.0
- LDR = 0.0

#### High False Positive Rate

Adjust thresholds in config:

```yaml
thresholds:
  ldr:
    critical: 0.30  # Lower = stricter
  inflation:
    fail: 2.5       # Higher = more lenient
```

#### Slow Analysis on Large Projects

```bash
# Use pattern to limit files
slop-detector scan ./src --pattern "src/**/*.py" --ignore "tests/**"

# Disable ML classifier if enabled
slop-detector scan ./src --no-ml
```

### Debug Mode

```bash
# Enable debug logging
slop-detector scan ./src --debug

# Check specific file with verbose output
slop-detector analyze problem_file.py -vv
```

### Getting Help

```bash
# Show help
slop-detector --help

# Show command help
slop-detector scan --help

# Show version
slop-detector --version
```

---

## Examples

See [docs/examples/](examples/) for complete examples:
- `basic_usage.py` - Simple API usage
- `custom_config.py` - Configuration examples
- `batch_analysis.py` - Analyzing multiple files
- `ci_integration.py` - CI/CD integration script

---

**[← Back to Main README](../README.md)**
