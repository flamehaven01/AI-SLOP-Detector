<p align="center">
  <img src="docs/assets/AI SLop DETECTOR.png" alt="AI-SLOP Detector Logo" width="400"/>
</p>

# AI-SLOP Detector v2.6

[![PyPI version](https://img.shields.io/pypi/v/ai-slop-detector.svg)](https://pypi.org/project/ai-slop-detector/)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-58%20passed-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-68%25-green.svg)](htmlcov/)

**Production-grade static analyzer for detecting AI-generated code quality issues with evidence-based validation.**

Detects six critical categories of AI-generated code problems with actionable, context-aware questions.

---

## Quick Start

```bash
# Install from PyPI
pip install ai-slop-detector

# Analyze a single file
slop-detector mycode.py

# Scan entire project
slop-detector --project ./src

# CI/CD Integration (Soft mode - PR comments only)
slop-detector --project ./src --ci-mode soft --ci-report

# CI/CD Integration (Hard mode - fail build on issues)
slop-detector --project ./src --ci-mode hard --ci-report

# Generate JSON report
slop-detector mycode.py --json --output report.json
```

---

## What's New in v2.6

### 6 Killer Upgrades

1. **Context-Based Jargon Detection** - Cross-validates quality claims with actual evidence
2. **Docstring Inflation Analysis** - Detects documentation-heavy, implementation-light code
3. **Placeholder Pattern Catalog** - 14 patterns detecting unfinished/scaffolded code
4. **Hallucination Dependencies** - Identifies purpose-specific imports that are never used
5. **Question Generation UX** - Converts findings into actionable review questions
6. **CI Gate 3-Tier System** - Soft/Hard/Quarantine enforcement modes

---

## What is AI Slop?

**AI Slop** refers to code patterns commonly produced by AI code generators that lack substance:

### Pattern 1: Placeholder Code
```python
def quantum_encode(self, data):
    """Apply quantum encoding with advanced algorithms."""
    pass  # [CRITICAL] Empty implementation

def process_data(self):
    """Process data comprehensively."""
    raise NotImplementedError  # [HIGH] Unimplemented
```

**Detection:** 14 placeholder patterns (empty except, NotImplementedError, pass, ellipsis, return None, etc.)

### Pattern 2: Buzzword Inflation
```python
class EnterpriseProcessor:
    """
    Production-ready, enterprise-grade, highly scalable processor
    with fault-tolerant architecture and comprehensive error handling.
    """
    def process(self, data):
        return data + 1  # [CRITICAL] Claims without evidence
```

**Detection:** Cross-validates claims like "production-ready" against actual evidence (error handling, logging, tests, etc.)

### Pattern 3: Docstring Inflation
```python
def add(a, b):
    """
    Sophisticated addition algorithm with advanced optimization.

    This function implements a state-of-the-art arithmetic operation
    using enterprise-grade validation and comprehensive error handling
    with production-ready reliability guarantees.

    Args:
        a: First operand with advanced type validation
        b: Second operand with enterprise-grade checking

    Returns:
        Optimized sum with comprehensive quality assurance
    """
    return a + b  # [WARNING] 12 lines of docs, 1 line of code
```

**Detection:** Ratio analysis (docstring lines / implementation lines)

### Pattern 4: Hallucinated Dependencies
```python
# [CRITICAL] 10 unused purpose-specific imports detected
import torch  # ML: never used
import tensorflow as tf  # ML: never used
import requests  # HTTP: never used
import sqlalchemy  # Database: never used

def process():
    return "hello"  # None of the imports are actually used
```

**Detection:** Categorizes imports by purpose (ML, HTTP, database) and validates usage

---

## Architecture Overview

AI-SLOP Detector v2.2 uses a **multi-dimensional analysis engine**:

```
Python Code
    ↓
┌─────────────────────────────────────┐
│  Core Metrics (v2.0)                │
│  • LDR (Logic Density Ratio)        │
│  • Inflation (Jargon Detection)     │
│  • DDC (Dependency Check)           │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Pattern Detection (v2.1)           │
│  • 14 Placeholder Patterns          │
│  • 4 Structural Anti-patterns       │
│  • 6 Cross-language Patterns        │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Evidence Validation (v2.2)         │
│  • Context-Based Jargon             │
│  • Docstring Inflation              │
│  • Hallucination Dependencies       │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│  Question Generation (v2.2)         │
│  • Critical/Warning/Info Questions  │
│  • Actionable Review Guidance       │
└─────────────────────────────────────┘
    ↓
Deficit Score (0-100) + Status + Questions
```

---

## Core Features

### 1. Context-Based Jargon Detection

Validates quality claims against actual codebase evidence:

```python
# Claims "production-ready" but missing:
# - error_handling
# - logging
# - tests
# - input_validation
# - config_management

# [CRITICAL] "production-ready" claim lacks 5/5 required evidence
```

**Evidence tracked (14 types):**
- Error handling (try/except with non-empty handlers)
- Logging (actual logger usage, not just imports)
- Tests (test functions, test files, test directories)
- Input validation (isinstance, type checks, assertions)
- Config management (settings, .env, yaml references)
- Monitoring (prometheus, statsd, sentry)
- Documentation (meaningful docstrings)
- Security (auth, encryption, sanitization)
- Caching (@cache, redis, memcache)
- Async support (async/await usage)
- Retry logic (@retry, backoff, circuit breaker)
- Design patterns (Factory, Singleton, Observer)
- Advanced algorithms (complexity >= 10)
- Optimization (vectorization, memoization)

### 2. Docstring Inflation Analysis

Detects documentation-heavy, implementation-light functions:

```python
Ratio = docstring_lines / implementation_lines

CRITICAL: ratio >= 2.0  (2x more docs than code)
WARNING:  ratio >= 1.0  (more docs than code)
INFO:     ratio >= 0.5  (substantial docs)
PASS:     ratio <  0.5  (balanced or code-heavy)
```

### 3. Placeholder Pattern Catalog

14 patterns detecting unfinished/scaffolded code:

**Critical Severity:**
- Empty exception handlers (`except: pass`)
- Bare except blocks

**High Severity:**
- `raise NotImplementedError`
- Ellipsis placeholders (`...`)
- HACK comments

**Medium Severity:**
- `return None` placeholders
- Interface-only classes (75%+ placeholder methods)

**Low Severity:**
- `pass` statements
- TODO/FIXME comments

### 4. Hallucination Dependencies

Categorizes imports by purpose and validates usage:

**12 Categories tracked:**
- ML: torch, tensorflow, keras, transformers
- Vision: cv2, PIL, imageio
- HTTP: requests, httpx, aiohttp, flask
- Database: sqlalchemy, pymongo, redis
- Async: asyncio, trio, anyio
- Data: pandas, polars, dask
- Serialization: json, yaml, toml
- Testing: pytest, unittest, mock
- Logging: logging, loguru, structlog
- CLI: argparse, click, typer, rich
- Cloud: boto3, google-cloud, azure
- Security: cryptography, jwt, passlib

### 5. Question Generation UX

Converts findings into actionable review questions:

```
CRITICAL QUESTIONS:
1. Only 14% of quality claims are backed by evidence.
   Are these marketing buzzwords without substance?

2. Claims like "fault-tolerant", "scalable" have ZERO supporting evidence.
   Where are the tests, error handling, and other indicators?

WARNING QUESTIONS:
3. (Line 4) "production-ready" claim lacks: error_handling, logging, tests.
   Only 20% of required evidence present.

4. Function "process" has 15 lines of docstring but only 2 lines of implementation.
   Is this AI-generated documentation without substance?

5. Why import "torch" for machine learning but never use it?
   Was this AI-generated boilerplate?
```

### 6. CI Gate 3-Tier System

Progressive enforcement for CI/CD pipelines:

**Soft Mode (Informational):**
```bash
slop-detector --project . --ci-mode soft --ci-report
# Posts PR comment, never fails build
# Use for: visibility, onboarding
```

**Hard Mode (Strict):**
```bash
slop-detector --project . --ci-mode hard --ci-report
# Fails build if deficit_score >= 70 or critical_patterns >= 3
# Exit code 1 on failure
# Use for: production branches
```

**Quarantine Mode (Gradual):**
```bash
slop-detector --project . --ci-mode quarantine --ci-report
# Tracks repeat offenders in .slop_quarantine.json
# Escalates to FAIL after 3 violations
# Use for: gradual rollout
```

**GitHub Action Example:**
```yaml
- name: Quality Gate
  run: |
    pip install ai-slop-detector
    slop-detector --project . --ci-mode quarantine --ci-report
```

---

## CLI Usage

### Basic Analysis

```bash
# Single file
slop-detector mycode.py

# Project scan
slop-detector --project ./src

# With output file
slop-detector --project ./src --output report.json

# Markdown report
slop-detector --project ./src --output report.md
```

### CI/CD Integration

```bash
# Soft mode (informational only)
slop-detector --project . --ci-mode soft --ci-report

# Hard mode (fail on threshold)
slop-detector --project . --ci-mode hard --ci-report

# Quarantine mode (track repeat offenders)
slop-detector --project . --ci-mode quarantine --ci-report
```

### Pattern Management

```bash
# List all patterns
slop-detector --list-patterns

# Disable specific patterns
slop-detector mycode.py --disable empty_except --disable todo_comment

# Use custom config
slop-detector mycode.py --config .slopconfig.yaml
```

---

## Configuration

Create `.slopconfig.yaml` in your project root:

```yaml
# Metric weights
weights:
  ldr: 0.40        # Logic Density Ratio
  inflation: 0.35  # Jargon/Buzzword Inflation
  ddc: 0.25        # Dependency Check

# Thresholds
thresholds:
  ldr:
    critical: 0.30    # Below this = critical
    warning: 0.60     # Below this = warning

  inflation:
    critical: 1.0     # Above this = critical
    warning: 0.5      # Above this = warning

  ddc:
    critical: 0.50    # Below this = critical
    warning: 0.70     # Below this = warning

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

---

## Output Examples

### Console Output (Rich)

```
┌────────────────────────────┐
│ AI CODE QUALITY REPORT     │
└────────────────────────────┘

File: mycode.py
Status: CRITICAL
Score: 71.1/100

LDR: 47.22% (B)
ICR: 1.50 (FAIL)
DDC: 10.00% (SUSPICIOUS)

CRITICAL QUESTIONS:
1. Only 14% of quality claims are backed by evidence.
2. "production-ready" claim lacks: error_handling, logging, tests.

WARNING QUESTIONS:
3. Function "process" has 15 lines of docstring, 2 lines of code.
4. Why import "torch" for ML but never use it?
```

### JSON Output

```json
{
  "file_path": "mycode.py",
  "deficit_score": 71.1,
  "status": "critical_deficit",
  "ldr": {"ldr_score": 0.47, "grade": "B"},
  "inflation": {"inflation_score": 1.5, "status": "FAIL"},
  "ddc": {"usage_ratio": 0.10, "grade": "SUSPICIOUS"},
  "context_jargon": {
    "justification_ratio": 0.14,
    "worst_offenders": ["production-ready", "scalable"]
  },
  "docstring_inflation": {
    "overall_ratio": 7.5,
    "inflated_count": 3
  },
  "hallucination_deps": {
    "total_hallucinated": 10,
    "categories": ["ml", "http", "database"]
  }
}
```

---

## VS Code Extension

**Coming Soon:** Real-time analysis in VS Code with inline diagnostics.

Current status: Local testing complete, marketplace publishing pending.

---

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/yourusername/ai-slop-detector.git
cd ai-slop-detector

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v --cov

# Run linting
pylint src/slop_detector
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=src/slop_detector --cov-report=html

# Specific test file
pytest tests/test_core.py -v
```

---

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

**Contribution Guidelines:**
- Add tests for new features
- Maintain 70%+ code coverage
- Follow existing code style
- Update documentation

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

## Citation

If you use AI-SLOP Detector in research, please cite:

```bibtex
@software{ai_slop_detector,
  title = {AI-SLOP Detector: Evidence-Based Static Analysis for AI-Generated Code},
  author = {Flamehaven},
  year = {2024},
  version = {2.2.0},
  url = {https://github.com/yourusername/ai-slop-detector}
}
```

---

## Acknowledgments

- Built with Python 3.8+
- AST analysis powered by Python's `ast` module
- Pattern detection inspired by traditional linters
- Evidence validation methodology developed in-house
- Thanks to the open-source community

---

## Roadmap

**v2.3 (Planned):**
- [ ] VS Code Extension marketplace release
- [ ] Enhanced evidence types (15+ types)
- [ ] Custom pattern DSL
- [ ] Multi-language support (JavaScript, TypeScript)

**v3.0 (Future):**
- [ ] ML-based pattern recognition
- [ ] Auto-fix suggestions
- [ ] Team analytics dashboard
- [ ] IDE plugins (PyCharm, IntelliJ)

---

## Support

- **Documentation:** [docs/](docs/)
- **Issues:** [GitHub Issues](https://github.com/yourusername/ai-slop-detector/issues)
- **Discussions:** [GitHub Discussions](https://github.com/yourusername/ai-slop-detector/discussions)

---

**Made with ❤️ by Flamehaven | Detecting AI slop since 2024**
