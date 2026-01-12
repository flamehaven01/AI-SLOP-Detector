# AI-SLOP Detector - Architecture Documentation

**Version:** 2.6.1
**Last Updated:** 2026-01-12

---

## Overview

AI-SLOP Detector is a production-grade static analysis tool designed to identify quality issues in AI-generated code. The system uses a multi-metric analysis engine with pattern detection to provide comprehensive code quality assessment.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│              CLI / API Entry Point / CI Gate             │
└────────────────────┬────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────┐
│                   SlopDetector (Core)                    │
│  ┌───────────────────────────────────────────────────┐  │
│  │          Configuration Manager                     │  │
│  │  - YAML config loading                            │  │
│  │  - Threshold management                           │  │
│  │  - Pattern registry setup                         │  │
│  └───────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┬──────────────┐
        │            │            │              │
        ▼            ▼            ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐
│   LDR    │  │Inflation │  │   DDC    │  │Context Jargon│
│Calculator│  │Calculator│  │Calculator│  │   Detector   │
└────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘
     │             │             │                │
     │             │             └────────┬───────┘
     │             │                      │
     │             └──────────┬───────────┘
     │                        │
     └────────────┬───────────┘
                  │
     ┌────────────┼──────────────┬─────────────────┐
     │            │              │                 │
     ▼            ▼              ▼                 ▼
┌──────────┐  ┌───────┐  ┌──────────────┐  ┌─────────────┐
│Docstring │  │Pattern│  │Hallucination │  │  Question   │
│Inflation │  │Registry│  │ Dependencies │  │  Generator  │
│ Detector │  │14+ Det│  │   Detector   │  │  (v2.6)     │
└────┬─────┘  └───┬───┘  └──────┬───────┘  └──────┬──────┘
     │            │              │                 │
     └────────────┼──────────────┼─────────────────┘
                  │              │
                  ▼              ▼
          ┌─────────────────────────────┐
          │     FileAnalysis Result     │
          │  + Actionable Questions     │
          └────────────┬────────────────┘
                       │
                       ▼
                  ┌─────────┐
                  │ CI Gate │
                  │ (v2.6)  │
                  └─────────┘
```

---

## Core Components

### 1. Logic Density Ratio (LDR) Calculator

**Purpose:** Measures the ratio of actual logic to empty/placeholder code.

**Algorithm:**
```python
LDR = logic_lines / total_lines

Where:
- logic_lines = lines with actual implementation
- empty_lines = pass, ..., TODO, FIXME patterns
- total_lines = logic_lines + empty_lines
```

**Key Features:**
- AST-based analysis for accurate line counting
- Smart exception handling for:
  - ABC (Abstract Base Class) interfaces
  - Type stub files (.pyi)
  - Configuration files
- Pattern-based empty function detection

**Grading Scale:**
```
S++: >90%  - Excellent implementation
A:   75-90% - Good quality
B:   60-75% - Acceptable
C:   45-60% - Needs improvement
F:   <45%   - Critical slop detected
```

**Implementation:** `src/slop_detector/metrics/ldr.py`

---

### 2. Inflation Calculator

**Purpose:** Detects buzzword-to-code ratio in documentation and comments.

**Algorithm:**
```python
Inflation = jargon_count / (avg_complexity * 10)

Where:
- jargon_count = number of buzzwords detected
- avg_complexity = cyclomatic complexity (via Radon)
```

**Buzzword Categories:**
- AI/ML: neural, transformer, deep learning, reinforcement learning
- Architecture: Byzantine, cloud-native, microservices, serverless
- Quality: robust, resilient, performant, cutting-edge
- Academic: NeurIPS, ICLR, ICML, theorem, proof

**Context Awareness:**
```python
# Justified jargon (not counted):
import torch  # "neural" is justified
class NeuralNetwork:  # actual neural net implementation
    ...

# Unjustified jargon (counted):
def add(a, b):  # simple addition
    """Uses advanced neural optimization"""  # ← inflation!
    return a + b
```

**Thresholds:**
```
Pass:     <0.5   - Appropriate terminology
Warning:  0.5-1.0 - Moderate jargon
Fail:     1.0-2.0 - High buzzword density
Critical: >2.0    - Fake documentation
```

**Implementation:** `src/slop_detector/metrics/inflation.py`

---

### 3. Dependency Check (DDC)

**Purpose:** Identifies unused imports and fake dependencies.

**Algorithm:**
```python
DDC = actually_used / imported

Where:
- imported = all import statements
- actually_used = names referenced in code
- unused = imported - actually_used
```

**Special Handling:**
- TYPE_CHECKING imports excluded
- __all__ exports considered
- Module-level usage detection

**Detection Categories:**
- Unused imports
- Fake imports (imports that don't exist)
- Ghost imports (imported but never used)

**Implementation:** `src/slop_detector/metrics/ddc.py`

---

### 4. Pattern Registry (v2.1+)

**Purpose:** Detect structural anti-patterns beyond metrics.

**Pattern Types:**

#### Structural Issues
```python
# Bare Except (Critical)
try:
    risky()
except:  # Catches SystemExit, KeyboardInterrupt!
    pass

# Mutable Default (Critical)
def func(items=[]):  # Shared state bug!
    items.append(1)
    return items

# Star Import (High)
from module import *  # Namespace pollution
```

#### Placeholder Indicators
```python
# Pass Placeholder (High)
def quantum_encode(data):
    pass  # Empty implementation

# Ellipsis Placeholder (High)
def transform(x):
    ...  # Not implemented

# TODO Comment (Medium)
def process():
    # TODO: implement this
    pass
```

#### Cross-Language Mistakes
```python
# JavaScript idioms in Python (High)
items.push(x)     # Should be: items.append(x)
items.length()    # Should be: len(items)

# Java idioms in Python (High)
obj.equals(other) # Should be: obj == other
obj.toString()    # Should be: str(obj)
```

**Pattern Detection Flow:**
```
1. Parse AST
2. Walk syntax tree
3. Match patterns
4. Collect issues with severity
5. Apply to deficit score
```

**Implementation:** `src/slop_detector/patterns/`

---

### 5. Docstring Inflation Detector (v2.6+)

**Purpose:** Detects documentation-heavy, implementation-light code patterns.

**Algorithm:**
```python
Inflation_Ratio = docstring_lines / implementation_lines

Where:
- docstring_lines = lines in docstring (excluding quotes)
- implementation_lines = actual code lines (excluding pass, ..., etc.)
```

**Severity Thresholds:**
```
CRITICAL: ratio >= 2.0  (2x+ more docs than code)
WARNING:  ratio >= 1.0  (more docs than code)
INFO:     ratio >= 0.5  (substantial docs)
PASS:     ratio <  0.5  (balanced or code-heavy)
```

**Detection Features:**
- Per-function/class/module analysis
- File-level aggregation
- Top 10 worst offenders reporting
- Preview of inflated docstrings

**Implementation:** `src/slop_detector/metrics/docstring_inflation.py`

---

### 6. Hallucination Dependencies Detector (v2.6+)

**Purpose:** Identifies purpose-specific imports that are never used, revealing AI's intended but unimplemented features.

**Algorithm:**
```python
Category_Usage = used_in_category / imported_in_category

Categories (12 total):
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
```

**Intent Inference:**
- "torch" unused → "machine learning model training or inference"
- "requests" unused → "HTTP requests or API integration"
- "sqlalchemy" unused → "database operations and ORM"

**Detection Features:**
- 60+ libraries tracked across 12 categories
- Per-category usage analysis
- Intent-based questioning
- Hallucination severity scoring

**Implementation:** `src/slop_detector/metrics/hallucination_deps.py`

---

### 7. Context-Based Jargon Detector (v2.6+)

**Purpose:** Cross-validates quality claims with actual codebase evidence instead of just flagging buzzwords.

**Algorithm:**
```python
Justification_Ratio = justified_claims / total_claims

Where:
- justified_claims = jargon terms with supporting evidence
- total_claims = all quality claims detected
- evidence_types = 14 categories (see below)
```

**Evidence Requirements (14 types):**

**Production-Ready:**
- error_handling (try/except with handlers)
- logging (actual logger usage)
- tests (test functions/files)
- input_validation (isinstance, type checks)
- config_management (settings, .env, yaml)

**Enterprise-Grade:**
- monitoring (prometheus, statsd, sentry)
- documentation (meaningful docstrings)
- security (auth, encryption, sanitization)

**Scalable:**
- caching (@cache, redis, memcache)
- async_support (async/await usage)
- connection_pooling
- rate_limiting

**Fault-Tolerant:**
- retry_logic (@retry, backoff)
- circuit_breaker
- fallback mechanisms

**Additional Evidence:**
- design_patterns (Factory, Singleton, Observer)
- advanced_algorithms (complexity >= 10)
- optimization (vectorization, memoization)

**Detection Features:**
- 14 jargon terms with evidence requirements
- Missing evidence reporting
- Worst offenders (0 evidence) identification
- Per-claim justification ratio

**Implementation:** `src/slop_detector/metrics/context_jargon.py`

---

### 8. Question Generator (v2.6+)

**Purpose:** Converts analysis findings into actionable review questions for code reviewers.

**Question Categories:**
- **Critical:** Low justification ratio, zero evidence, massive hallucination
- **Warning:** Unjustified jargon, category-specific unused imports, docstring inflation
- **Info:** Excessive empty lines, low logic density, pattern-specific questions

**Examples:**
```
CRITICAL:
"Only 14% of quality claims are backed by evidence.
 Are these marketing buzzwords without substance?"

WARNING:
"'production-ready' claim at line 42 lacks: error_handling, logging, tests.
 Only 20% of required evidence present."

INFO:
"Function 'process' has 15 lines of docstring but only 2 lines of implementation.
 Is this AI-generated documentation without substance?"
```

**Implementation:** `src/slop_detector/question_generator.py`

---

### 9. CI Gate System (v2.6+)

**Purpose:** Progressive enforcement for CI/CD pipelines with 3-tier quality gates.

**Modes:**

**Soft Mode (Informational):**
- PR comments only
- Never fails build
- Use for: visibility, onboarding

**Hard Mode (Strict):**
- Fails build on thresholds
- deficit_score >= 70 → FAIL
- critical_patterns >= 3 → FAIL
- Use for: production branches

**Quarantine Mode (Gradual):**
- Tracks repeat offenders
- Escalates to FAIL after 3 violations
- Persistent tracking (.slop_quarantine.json)
- Use for: gradual rollout

**Thresholds (Configurable):**
```python
deficit_fail: 70.0
deficit_warn: 30.0
critical_patterns_fail: 3
high_patterns_warn: 5
inflation_fail: 1.5
ddc_fail: 0.5
```

**Implementation:** `src/slop_detector/ci_gate.py`

---

## Scoring System

### Deficit Score Calculation

```python
# Base quality from metrics (0-1, higher is better)
base_quality = (
    ldr_score * weight_ldr +
    (1 - inflation_normalized) * weight_inflation +
    ddc_ratio * weight_ddc
)

# Base deficit (0-100, higher is worse)
base_deficit = 100 * (1 - base_quality)

# Pattern penalties
pattern_penalty = sum(severity_weights[issue.severity] for issue in issues)
pattern_penalty = min(pattern_penalty, 50)  # Cap at 50 points

# Final deficit score
deficit_score = min(base_deficit + pattern_penalty, 100)
```

**Default Weights:**
- LDR: 40%
- Inflation: 30%
- DDC: 30%

**Severity Weights:**
- Critical: 10 points
- High: 5 points
- Medium: 2 points
- Low: 1 point

### Status Classification

```python
if deficit_score >= 70:
    status = CRITICAL_DEFICIT
elif len(critical_patterns) >= 3:
    status = CRITICAL_DEFICIT
elif inflation > 1.0:
    status = INFLATED_SIGNAL
elif ddc_ratio < 0.5:
    status = DEPENDENCY_NOISE
elif deficit_score >= 30:
    status = SUSPICIOUS
else:
    status = CLEAN
```

---

## Data Flow

### File Analysis Flow

```
1. Input: file_path
   ↓
2. Read file content
   ↓
3. Parse AST
   ↓
4. Calculate metrics (parallel):
   - LDR ───┐
   - Inflation ─┤→ Combine
   - DDC ───┘
   ↓
5. Run pattern detection
   ↓
6. Calculate deficit score
   ↓
7. Determine status
   ↓
8. Return FileAnalysis object
```

### Project Analysis Flow

```
1. Input: project_path, pattern
   ↓
2. Find Python files (glob)
   ↓
3. Filter by ignore patterns
   ↓
4. For each file:
   - analyze_file()
   - Collect results
   ↓
5. Aggregate metrics:
   - Average deficit
   - Weighted deficit (by LOC)
   - Overall status
   ↓
6. Return ProjectAnalysis object
```

---

## Configuration System

### Configuration Hierarchy

```
1. Default config (hardcoded)
   ↓
2. User config file (.slopconfig.yaml)
   ↓
3. CLI arguments (highest priority)
```

### Config Structure

```yaml
version: "2.0"

thresholds:
  ldr:
    excellent: 0.85
    critical: 0.30
  inflation:
    fail: 2.0
  ddc:
    suspicious: 0.30

weights:
  ldr: 0.40
  inflation: 0.30
  ddc: 0.30

ignore:
  - "**/__init__.py"
  - "tests/**"

exceptions:
  abc_interface:
    enabled: true
    penalty_reduction: 0.5

patterns:
  disabled:
    - "todo_comment"
```

**Implementation:** `src/slop_detector/config.py`

---

## Extension Points

### Adding New Metrics

```python
class CustomMetric:
    def __init__(self, config):
        self.config = config
    
    def calculate(self, file_path, content, tree):
        # Analyze AST or content
        score = ...
        return CustomResult(score=score)
```

### Adding New Patterns

```python
from slop_detector.patterns.base import ASTPattern

class CustomPattern(ASTPattern):
    id = "custom_pattern"
    severity = Severity.HIGH
    message = "Custom issue detected"
    
    def detect(self, tree, file, content):
        issues = []
        for node in ast.walk(tree):
            if self._matches(node):
                issues.append(self.create_issue(node, file))
        return issues
```

### Custom Configuration

```python
detector = SlopDetector(config_path=".slopconfig.yaml")
detector.config.set("thresholds.ldr.critical", 0.4)
detector.pattern_registry.disable("todo_comment")
```

---

## Performance Considerations

### Optimization Strategies

1. **Single-pass AST parsing**
   - Parse once, share tree across analyzers
   - Reduces CPU overhead

2. **Efficient pattern matching**
   - Compiled regex patterns
   - Early exit conditions

3. **Smart caching**
   - Config cached after first load
   - Pattern registry built once

4. **Parallel processing** (future)
   - File-level parallelization
   - Independent metric calculations

### Performance Targets

- Single file: <100ms (typical)
- Medium project (100 files): <10s
- Large project (1000 files): <2min

**Bottlenecks:**
- AST parsing (unavoidable)
- Radon complexity calculation (optional)
- File I/O (mitigated by streaming)

---

## Testing Strategy

### Unit Tests
- Individual metric calculators
- Pattern detectors
- Configuration loading

### Integration Tests
- End-to-end file analysis
- Project scanning
- Config precedence

### Real-World Tests
- Synthetic AI-generated code
- Known slop patterns
- Edge cases (ABC, type stubs)

**Test Coverage Target:** >75% (current: 79%)

---

## API Integration

### Python API

```python
from slop_detector import SlopDetector

detector = SlopDetector()
result = detector.analyze_file("mycode.py")

print(f"Status: {result.status.value}")
print(f"Deficit: {result.deficit_score:.1f}/100")
print(f"LDR: {result.ldr.ldr_score:.2%}")
```

### REST API (Enterprise)

```bash
# Start server
slop-api --host 0.0.0.0 --port 8080

# Analyze file
curl -X POST http://localhost:8080/analyze \
  -H "Content-Type: application/json" \
  -d '{"file_path": "code.py"}'
```

### CLI

```bash
slop-detector analyze file.py
slop-detector scan ./src --format json
```

---

## Security Considerations

### Input Validation
- Path traversal prevention
- File size limits (default: 10KB-10MB)
- Syntax error handling

### Safe AST Parsing
- No code execution
- Pure static analysis
- Sandboxed parsing

### Dependency Safety
- Minimal dependencies
- No network calls during analysis
- Optional ML features isolated

---

## Future Enhancements

### Planned Features
- [ ] Multi-language support (JavaScript, Java, Go)
- [ ] ML-based classification (optional)
- [ ] IDE integrations (VS Code, PyCharm)
- [ ] Git hook templates
- [ ] Performance profiling mode

### Research Areas
- Semantic analysis (beyond syntax)
- Learning from user feedback
- Cross-project pattern mining
- AI-based pattern evolution

---

## References

### Internal Documentation
- [Usage Guide](USAGE.md)
- [Pattern Catalog](PATTERNS.md)
- [API Reference](API.md)

### External Resources
- [AST Module Documentation](https://docs.python.org/3/library/ast.html)
- [Radon - Code Metrics](https://radon.readthedocs.io/)
- [PEP 8 - Style Guide](https://pep8.org/)

---

## Contributors

**Maintainer:** Flamehaven Labs  
**Contact:** info@flamehaven.space  
**Repository:** https://github.com/flamehaven01/AI-SLOP-Detector

---

**Last Updated:** 2026-01-12
**Version:** 2.6.1
