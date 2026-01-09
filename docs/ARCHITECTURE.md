# AI-SLOP Detector - Architecture Documentation

**Version:** 2.5.0  
**Last Updated:** 2026-01-09

---

## Overview

AI-SLOP Detector is a production-grade static analysis tool designed to identify quality issues in AI-generated code. The system uses a multi-metric analysis engine with pattern detection to provide comprehensive code quality assessment.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CLI / API Entry Point                 │
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
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│   LDR    │  │Inflation │  │   DDC    │
│Calculator│  │Calculator│  │Calculator│
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │
     └─────────────┼─────────────┘
                   │
                   ▼
          ┌─────────────────┐
          │ Pattern Registry │
          │  12+ Detectors   │
          └────────┬─────────┘
                   │
                   ▼
          ┌─────────────────┐
          │  FileAnalysis   │
          │  Result Object  │
          └─────────────────┘
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
- Context-aware jargon detection
- Learning from user feedback
- Cross-project pattern mining

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

**Last Updated:** 2026-01-09  
**Version:** 2.5.0
