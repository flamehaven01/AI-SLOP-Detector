# Sloppylint vs AI-SLOP-Detector 2.0 - Architecture Comparison

## [*] Executive Summary

**Recommendation:** **우리 AI-SLOP-Detector 2.0이 더 우수**하나, sloppylint에서 배울 점 다수 존재.

| Aspect | Sloppylint | AI-SLOP-Detector 2.0 | Winner |
|--------|-----------|---------------------|---------|
| **Architecture** | Pattern-based registry | Metric-based (LDR/BCR/DDC) | Sloppylint (+) |
| **Scoring System** | 4-axis slop index | Formula-based weighted | SLOP-Detector (+) |
| **Configuration** | pyproject.toml integration | YAML + env var | SLOP-Detector (+) |
| **Pattern Detection** | 100+ specific patterns | 3 core metrics | Sloppylint (+) |
| **CI/CD Integration** | Pre-commit hooks | GitHub Actions full pipeline | SLOP-Detector (+) |
| **Dependencies** | Stdlib only (lean) | pyyaml, radon, jinja2 | Sloppylint (+) |
| **Testing** | 68 tests with corpus | Unit tests per module | Sloppylint (+) |

**Verdict:** Merge best of both worlds → **AI-SLOP-Detector v2.1**

---

## [#] Detailed Comparison

### 1. Architecture Design

#### Sloppylint (Pattern Registry Approach)

```python
# patterns/base.py
class BasePattern(ABC):
    id: str = ""
    severity: Severity = Severity.MEDIUM
    axis: str = "noise"
    message: str = ""
    
    def check(self, node: ast.AST, file: Path, lines: list[str]) -> list[Issue]:
        pass

# Pattern registration
patterns = [
    MutableDefaultArg(),
    BareExcept(),
    PassPlaceholder(),
    HedgingComment(),
    # ... 100+ patterns
]
```

**Pros:**
- [+] Easy to add new patterns (just inherit BasePattern)
- [+] Each pattern is isolated and testable
- [+] Clear separation of concerns
- [+] Extensible by third parties

**Cons:**
- [-] Can become bloated (100+ patterns)
- [-] Hard to maintain consistency
- [-] Overlapping patterns possible

#### AI-SLOP-Detector 2.0 (Metric-Based Approach)

```python
# metrics/ldr.py, bcr.py, ddc.py
class LDRCalculator:
    def calculate(self, file_path, content, tree) -> LDRResult:
        # Single pass, comprehensive analysis
        
# core.py
ldr = self.ldr_calc.calculate(file_path, content, tree)
bcr = self.bcr_calc.calculate(file_path, content, tree)
ddc = self.ddc_calc.calculate(file_path, content, tree)
```

**Pros:**
- [+] Three metrics cover most slop types
- [+] Scientific/measurable (LDR = logic_lines / total_lines)
- [+] Single-pass AST analysis
- [+] Consistent scoring formula

**Cons:**
- [-] Less granular (can't catch specific anti-patterns)
- [-] Harder to add edge cases
- [-] May miss language-specific idioms

---

### 2. Scoring System

#### Sloppylint: 4-Axis Slop Index

```python
# scoring.py
@dataclass
class SlopScore:
    noise: int = 0      # Information Utility
    quality: int = 0    # Information Quality (Lies)
    style: int = 0      # Style/Taste (Soul)
    structure: int = 0  # Structural Issues
    
    @property
    def verdict(self) -> str:
        if self.total < 25:   return "ACCEPTABLE"
        elif self.total < 100: return "SLOPPY"
        else:                  return "DISASTER"
```

**Weights:**
```python
SEVERITY_WEIGHTS = {
    "critical": 30,
    "high": 15,
    "medium": 8,
    "low": 3,
}
```

**Example Output:**
```
SLOPPY INDEX
Information Utility (Noise)    : 24 pts
Information Quality (Lies)     : 105 pts
Style / Taste (Soul)           : 31 pts
Structural Issues              : 45 pts
TOTAL SLOP SCORE               : 205 pts
Verdict: SLOPPY
```

#### AI-SLOP-Detector 2.0: Weighted Formula

```python
# core.py
weights = config.get_weights()  # {ldr: 0.4, bcr: 0.3, ddc: 0.3}

quality_factor = (
    ldr.ldr_score * weights["ldr"] +
    (1 - bcr_normalized) * weights["bcr"] +
    ddc.usage_ratio * weights["ddc"]
)

slop_score = 100 * (1 - quality_factor)
```

**Example Output:**
```
Slop Score: 18.5/100
  LDR: 88.20% (S++)
  BCR: 0.42 (PASS)
  DDC: 85.50% (EXCELLENT)
Status: CLEAN
```

**Winner:** AI-SLOP-Detector 2.0
- More scientific (formula-based)
- Configurable weights
- Clear meaning (0-100 scale)

---

### 3. Pattern Detection

#### Sloppylint: 100+ Specific Patterns

**Examples:**

```python
# patterns/hallucinations.py
class MutableDefaultArg:
    """Detect def func(items=[]):"""
    severity = Severity.CRITICAL
    axis = "quality"

class BareExcept:
    """Detect except: without Exception type"""
    severity = Severity.CRITICAL
    axis = "structure"

class HedgingComment:
    """Detect 'should work hopefully' comments"""
    severity = Severity.HIGH
    axis = "quality"

# Cross-language patterns
class JavaScriptPush:
    """Detect .push() instead of .append()"""
    severity = Severity.HIGH
    axis = "quality"
```

**Coverage:**
- JavaScript: `.push()`, `.length`, `.forEach()`
- Java: `.equals()`, `.toString()`, `.isEmpty()`
- Ruby: `.each`, `.nil?`, `.first`, `.last`
- Go: `fmt.Println()`, `nil`
- C#: `.Length`, `.Count`, `.ToLower()`
- PHP: `strlen()`, `array_push()`, `explode()`

#### AI-SLOP-Detector 2.0: 3 Core Metrics

**LDR (Logic Density Ratio):**
- Empty patterns: `pass`, `...`, `return None`, `raise NotImplementedError`
- Exception handling: ABC interfaces, type stubs

**BCR (Buzzword-to-Code Ratio):**
- 60+ buzzwords categorized (AI/ML, architecture, quality, academic)
- Context-aware justification (e.g., "neural" OK if torch is used)

**DDC (Deep Dependency Check):**
- Import usage tracking
- TYPE_CHECKING block awareness
- Heavyweight library detection (torch, tensorflow, numpy, etc.)

**Winner:** Sloppylint
- More comprehensive pattern coverage
- Catches language-specific mistakes
- Better for multi-language codebase review

**However:** Can integrate both approaches!

---

### 4. Configuration System

#### Sloppylint: pyproject.toml Integration

```toml
[tool.sloppy]
exclude = ["tests/*", "migrations/*"]
disable = ["magic_number", "debug_print"]
severity = "medium"
max-score = 100
ci = false
format = "detailed"
```

**Pros:**
- [+] Standard Python convention
- [+] One config file for entire project
- [+] Works with Poetry, Hatch, setuptools

#### AI-SLOP-Detector 2.0: Dedicated YAML

```yaml
# .slopconfig.yaml
version: "2.0"

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
```

**Pros:**
- [+] Environment variable support (`SLOP_CONFIG`)
- [+] Deep nesting for complex config
- [+] Cross-language (can use same format for JS version)

**Winner:** Tie
- Both valid approaches
- **Recommendation:** Support both (YAML primary, pyproject.toml fallback)

---

### 5. CLI & User Experience

#### Sloppylint CLI

```bash
sloppylint .                    # Scan
sloppylint --severity high      # Filter
sloppylint --lenient            # Preset
sloppylint --ci                 # CI mode
sloppylint --output report.json # Export
sloppylint --ignore "tests/*"   # Exclude
sloppylint --disable magic_number # Skip pattern
```

**Features:**
- Pre-commit hook support (`.pre-commit-hooks.yaml`)
- Rich terminal output (optional)
- Compact vs detailed format
- JSON export

#### AI-SLOP-Detector 2.0 CLI

```bash
slop-detector file.py
slop-detector --project src/
slop-detector --project . --json
slop-detector --project . -o report.html
slop-detector --fail-threshold 30
slop-detector --config .slopconfig.yaml
```

**Features:**
- HTML report generation
- Docker integration
- GitHub Actions CI/CD
- Weighted analysis

**Winner:** AI-SLOP-Detector 2.0
- More deployment options (Docker, CI/CD)
- HTML reports are valuable
- Fail threshold for CI/CD

---

### 6. Testing Strategy

#### Sloppylint: 68 Tests + Corpus

```
tests/
├── conftest.py
├── test_patterns/
│   ├── test_hallucinations.py
│   ├── test_noise.py
│   ├── test_style.py
│   └── test_structure.py
├── test_analyzers/
│   ├── test_ast_analyzer.py
│   └── test_import_validator.py
├── corpus/
│   ├── bad_code_samples.py
│   ├── good_code_samples.py
│   └── edge_cases.py
└── fixtures/
```

**Corpus approach:**
```python
# tests/corpus/hallucinations.py
def mutable_default():
    def bad(items=[]):  # Should trigger
        pass
    
    def good(items=None):  # Should NOT trigger
        pass
```

**Pros:**
- [+] Real-world code samples
- [+] Easy to add new test cases
- [+] Visual inspection of patterns

#### AI-SLOP-Detector 2.0: Module-Based

```
tests/
├── test_ldr.py
├── test_bcr.py
├── test_ddc.py
└── test_integration.py
```

**Pros:**
- [+] Focused on metrics
- [+] Fast execution

**Winner:** Sloppylint
- Corpus approach is better for pattern-based detection
- **Recommendation:** Add corpus to AI-SLOP-Detector

---

### 7. Dependencies

#### Sloppylint: Stdlib Only

```python
# Core dependencies (all stdlib)
import ast
import re
import pathlib
import difflib
import importlib.util
import json
import argparse

# Optional
rich>=13.0  # Pretty output
```

**Pros:**
- [+] Zero dependencies for core
- [+] Fast installation
- [+] No version conflicts

#### AI-SLOP-Detector 2.0: External Dependencies

```toml
dependencies = [
    "pyyaml>=6.0",      # Config parsing
    "radon>=6.0.1",     # Complexity calculation
    "jinja2>=3.1.0",    # HTML templates
]
```

**Winner:** Sloppylint
- Lighter footprint
- **Recommendation:** Make radon optional, use stdlib fallback

---

## [T] Integration Plan: Best of Both Worlds

### Phase 1: Immediate Improvements (v2.1)

#### 1.1 Add Pattern Registry System

```python
# src/slop_detector/patterns/registry.py
from slop_detector.patterns.base import BasePattern

class PatternRegistry:
    def __init__(self):
        self.patterns: list[BasePattern] = []
    
    def register(self, pattern: BasePattern):
        self.patterns.append(pattern)
    
    def get_all(self) -> list[BasePattern]:
        return self.patterns

# Usage
registry = PatternRegistry()
registry.register(MutableDefaultArg())
registry.register(BareExcept())
```

**Files to create:**
- `src/slop_detector/patterns/__init__.py`
- `src/slop_detector/patterns/base.py`
- `src/slop_detector/patterns/structural.py` (bare except, mutable defaults)
- `src/slop_detector/patterns/cross_language.py` (JS/Java/Ruby patterns)

#### 1.2 Add Test Corpus

```
tests/corpus/
├── structural_issues.py
├── cross_language_mistakes.py
├── empty_code.py
└── good_examples.py
```

#### 1.3 Support pyproject.toml

```python
# config.py
def load_config(config_path: Optional[str] = None):
    # Try .slopconfig.yaml first
    # Fall back to pyproject.toml [tool.slop-detector]
    # Fall back to defaults
```

#### 1.4 Add Pre-commit Hook

```yaml
# .pre-commit-hooks.yaml
- id: slop-detector
  name: AI SLOP Detector
  entry: slop-detector
  language: system
  types: [python]
  args: ['--fail-threshold', '30']
```

---

### Phase 2: Enhanced Patterns (v2.2)

#### 2.1 Cross-Language Pattern Detection

```python
# patterns/cross_language.py
class JavaScriptPatterns(BasePattern):
    """Detect JS patterns in Python."""
    
    patterns = [
        (r'\.push\(', '.append('),
        (r'\.length\b', 'len()'),
        (r'\.forEach\(', 'for loop'),
    ]
    
    def check(self, content: str) -> list[Issue]:
        issues = []
        for js_pattern, py_fix in self.patterns:
            for match in re.finditer(js_pattern, content):
                issues.append(self.create_issue(
                    line=self._get_line_number(content, match.start()),
                    message=f"JavaScript pattern: use {py_fix} instead"
                ))
        return issues
```

#### 2.2 Hallucinated Import Detection

```python
# patterns/hallucinations.py
class HallucinatedImport(BasePattern):
    """Detect imports that don't exist."""
    
    KNOWN_HALLUCINATIONS = [
        'transformers.AutoModelForCausalLM',  # Real
        'transformers.BertTransformer',       # Fake
        'torch.nn.TransformerEncoder',        # Real
        'torch.nn.BERTEncoder',               # Fake
    ]
    
    def check(self, tree: ast.AST) -> list[Issue]:
        # Check if imported module/attribute actually exists
```

---

### Phase 3: Advanced Features (v2.3)

#### 3.1 ML-Based Detection

```python
# ml/classifier.py
from sklearn.ensemble import RandomForestClassifier

class SlopClassifier:
    def __init__(self):
        self.model = self._load_model()
    
    def predict(self, features: dict) -> float:
        # features = {ldr, bcr, ddc, pattern_counts, ...}
        return self.model.predict_proba([features])[0][1]
```

**Training data sources:**
- Known good repos (NumPy, Flask, Django)
- Known slop repos (AI-generated garbage)
- Labeled corpus from code review

#### 3.2 Historical Tracking

```python
# tracking/history.py
class SlopHistory:
    def track(self, commit: str, score: float):
        # Store in SQLite
        
    def get_trend(self) -> list[tuple[str, float]]:
        # Return commit history
        
    def detect_regression(self) -> bool:
        # Alert if score increases >20% from baseline
```

---

## [W] Recommendations

### Immediate Actions (This Week)

1. **Add Pattern Registry** - 2 days
   - Base pattern class
   - 10 critical patterns (bare except, mutable defaults, etc.)
   - Test corpus

2. **Support pyproject.toml** - 1 day
   - Config loader enhancement
   - Migration guide

3. **Pre-commit Hook** - 1 day
   - `.pre-commit-hooks.yaml`
   - Documentation

### Short Term (Next Month)

4. **Cross-Language Patterns** - 1 week
   - JS, Java, Ruby, Go patterns
   - 50+ pattern database

5. **Hallucination Detection** - 1 week
   - Import validator
   - Known fake APIs database

6. **Rich Output (Optional)** - 2 days
   - Install `rich` as optional dependency
   - Colored terminal output

### Long Term (Q1 2026)

7. **ML Classifier** - 2 weeks
   - Collect training data
   - Train random forest
   - Integrate as optional feature

8. **VS Code Extension** - 2 weeks
   - Real-time linting
   - Inline suggestions

---

## [L] Code Snippets to Adopt

### 1. Pattern Base Class (from sloppylint)

```python
# src/slop_detector/patterns/base.py
from abc import ABC
from dataclasses import dataclass
from enum import Enum

class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class Issue:
    pattern_id: str
    severity: Severity
    file: Path
    line: int
    column: int
    message: str
    code: str | None = None

class BasePattern(ABC):
    id: str = ""
    severity: Severity = Severity.MEDIUM
    message: str = ""
    
    def check(self, node: ast.AST, file: Path, lines: list[str]) -> list[Issue]:
        """Override in subclasses."""
        pass
```

### 2. File Scanning Logic (from sloppylint)

```python
# Elegant glob pattern matching
def _should_scan(self, path: Path) -> bool:
    rel_path = self._get_relative_posix_path(path)
    
    # Check ignore patterns
    for pattern in self.ignore_patterns:
        if self._match_pattern(rel_path, pattern):
            return False
    
    # Check include patterns
    if self.include_patterns:
        matched = any(
            self._match_pattern(rel_path, pattern) 
            for pattern in self.include_patterns
        )
        if not matched:
            return False
    
    return True
```

### 3. Severity Ordering (from sloppylint)

```python
SEVERITY_ORDER = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

# Sort issues
issues.sort(
    key=lambda i: (
        -SEVERITY_ORDER.get(i.severity.value, 0),  # Critical first
        i.file,
        i.line,
    )
)
```

---

## [%] Final Verdict

### What to Keep from AI-SLOP-Detector 2.0

- [+] Metric-based approach (LDR, BCR, DDC)
- [+] Formula-based scoring
- [+] Docker + CI/CD infrastructure
- [+] YAML configuration
- [+] HTML reports
- [+] Weighted analysis

### What to Adopt from Sloppylint

- [+] Pattern registry system
- [+] 100+ specific anti-pattern detection
- [+] Test corpus approach
- [+] Stdlib-only core (make radon optional)
- [+] Pre-commit hook support
- [+] pyproject.toml integration
- [+] Cross-language pattern detection

### Hybrid Architecture (v2.1)

```
ai-slop-detector/
├── src/slop_detector/
│   ├── metrics/           # Keep: LDR, BCR, DDC
│   ├── patterns/          # NEW: Pattern registry
│   │   ├── base.py
│   │   ├── structural.py
│   │   ├── cross_language.py
│   │   └── hallucinations.py
│   ├── core.py           # Enhanced: Run both metrics + patterns
│   └── config.py         # Enhanced: Support pyproject.toml
├── tests/
│   ├── test_metrics/     # Keep
│   ├── test_patterns/    # NEW
│   └── corpus/           # NEW: Test corpus
└── .pre-commit-hooks.yaml # NEW
```

**Best of Both Worlds** = Superior Detection Engine 🚀

---

**Generated:** 2026-01-08  
**Status:** Ready for Implementation  
**Priority:** Phase 1 (Immediate) → v2.1 release
