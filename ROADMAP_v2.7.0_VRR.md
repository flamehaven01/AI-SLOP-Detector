# ROADMAP: v2.7.0 - Variable Entropy Analysis (VRR)

> **"Distinguish Dense Genius from Verbose Garbage"**
>
> Document Version: 1.0.0
> Target Release: 2026-01-17
> Drift Target: 0%

---

## 1. Executive Summary

### 1.1 Problem Statement

Current `ai-slop-detector` treats all high-complexity code equally:
- **False Positive**: Brilliant 10-line algorithm flagged as "complex"
- **False Negative**: Repetitive 10-line spaghetti passes as "acceptable"

The missing dimension: **Variable Entropy** (VRR - Vocabulary Richness Ratio)

### 1.2 Solution

Implement Variable Entropy Analysis to distinguish:
- **Dense Genius**: High information density, new concepts introduced efficiently
- **Verbose Garbage**: Low information density, repetitive patterns, hallucination loops

### 1.3 Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| False Positive Reduction | >= 30% | Compare against curated "genius" codebase |
| False Negative Detection | >= 25% | Detect slop in synthetic "bad" code |
| Performance Impact | < 5ms/file | Benchmark on 1000-file project |
| Test Coverage | >= 90% | New module coverage |

---

## 2. Technical Specification

### 2.1 Core Algorithm: VRR (Vocabulary Richness Ratio)

**Formula:**
```
VRR = Unique_Variables / Total_Variable_Usages
```

**Interpretation:**
| VRR Range | Classification | Meaning |
|-----------|----------------|---------|
| < 0.20 | Low | Same variables repeated (filler, loops) |
| 0.20 - 0.40 | Normal | Typical code pattern |
| 0.40 - 0.60 | Rich | Good information density |
| > 0.60 | Dense | New concepts introduced frequently |

### 2.2 Heuristic Integration with LDR

**Current State (v2.6.3):**
- LDR Low (< 0.60) = Warning/Critical

**New State (v2.7.0):**
```
IF LDR is Low AND VRR is High:
    -> Downgrade Severity (Likely Genius)
    -> Add note: "Complex but information-dense"

IF LDR is Low AND VRR is Low:
    -> Upgrade Severity (Likely Slop)
    -> Add note: "Complex and repetitive - likely AI-generated slop"
```

### 2.3 AST Collection Strategy

**Target Nodes:**
```python
ast.Name       # Variable references (id, ctx)
ast.Attribute  # Attribute access (value, attr)
ast.arg        # Function arguments
```

**Context Tracking:**
```python
class VariableContext(Enum):
    STORE = "store"     # Assignment target (x = ...)
    LOAD = "load"       # Variable read (... = x)
    PARAM = "param"     # Function parameter
    ATTRIBUTE = "attr"  # obj.attr access
```

### 2.4 Per-Function Analysis

VRR calculated at function level (not file level):
- Each function gets its own VRR score
- Aggregated to file-level weighted average
- Weight by function LOC

---

## 3. Implementation Plan

### 3.1 Phase 1: Core VRR Calculator (Day 1)

**File:** `src/slop_detector/metrics/entropy.py`

**Classes:**
```python
@dataclass
class EntropyResult:
    """Variable Entropy Analysis result."""
    vrr_score: float               # 0.0 - 1.0
    unique_variables: int          # Count of unique variable names
    total_usages: int              # Total variable usage count
    classification: str            # "low", "normal", "rich", "dense"
    per_function_vrr: Dict[str, float]  # Function-level breakdown

    def to_dict(self) -> Dict[str, Any]: ...


class VRRCalculator:
    """Calculate Variable Richness Ratio for code files."""

    def __init__(self, config: Config): ...

    def calculate(
        self,
        file_path: str,
        content: str,
        tree: ast.AST
    ) -> EntropyResult: ...

    def _collect_variables(
        self,
        node: ast.AST
    ) -> Tuple[Set[str], int]: ...

    def _calculate_function_vrr(
        self,
        func_node: ast.FunctionDef
    ) -> float: ...

    def _classify_vrr(self, vrr: float) -> str: ...
```

**Unit Tests:** `tests/test_entropy.py`
- `test_vrr_low_repetitive_code`
- `test_vrr_high_dense_code`
- `test_vrr_per_function_calculation`
- `test_vrr_classification_thresholds`
- `test_vrr_empty_function`
- `test_vrr_async_function`

### 3.2 Phase 2: Core Integration (Day 1)

**Modified Files:**

1. **`src/slop_detector/core.py`**
   - Import `VRRCalculator`
   - Add `self.vrr_calc = VRRCalculator(self.config)` in `__init__`
   - Call `vrr = self.vrr_calc.calculate(...)` in `analyze_file`
   - Pass `vrr` to `FileAnalysis`

2. **`src/slop_detector/models.py`**
   - Add `entropy: Optional[EntropyResult] = None` to `FileAnalysis`
   - Update `to_dict()` to include entropy

3. **`src/slop_detector/__init__.py`**
   - Export `EntropyResult`

### 3.3 Phase 3: Heuristic Adjustment (Day 1)

**Modified File:** `src/slop_detector/core.py`

**Location:** `_calculate_slop_status` method

**Logic:**
```python
def _calculate_slop_status(self, ldr, inflation, ddc, vrr, pattern_issues):
    # ... existing logic ...

    # v2.7.0: VRR-based severity adjustment
    if ldr.ldr_score < 0.60:  # Low LDR (complex code)
        if vrr and vrr.vrr_score > 0.50:  # But high entropy
            # Downgrade severity
            base_deficit_score *= 0.7  # 30% reduction
            warnings.append(
                f"NOTE: Complex but information-dense (VRR: {vrr.vrr_score:.2f})"
            )
        elif vrr and vrr.vrr_score < 0.20:  # Low entropy
            # Upgrade severity
            base_deficit_score *= 1.3  # 30% increase
            warnings.append(
                f"WARNING: Repetitive pattern detected (VRR: {vrr.vrr_score:.2f})"
            )
```

### 3.4 Phase 4: Configuration (Day 1)

**Modified File:** `.slopconfig.example.yaml`

**New Section:**
```yaml
# Variable Entropy Analysis (v2.7.0)
entropy:
  enabled: true
  thresholds:
    low: 0.20      # Below = "filler" warning
    normal: 0.40   # Normal code
    rich: 0.60     # Rich vocabulary
    dense: 0.80    # Very dense (rare)

  # Severity adjustment multipliers
  adjustments:
    high_entropy_reduction: 0.70   # Reduce severity by 30%
    low_entropy_increase: 1.30     # Increase severity by 30%

  # Exclude from VRR calculation
  exclude_builtins: true           # Skip print, len, str, etc.
  exclude_common: ["i", "j", "k", "x", "y", "z"]  # Loop vars
```

### 3.5 Phase 5: Reporting (Day 1)

**Modified Files:**

1. **`src/slop_detector/cli.py`**
   - Add VRR to text report output
   - Add VRR to markdown report

2. **Report Format:**
```
File: example.py
  LDR: 0.45 (C) | Inflation: 0.8 | DDC: 0.85 | VRR: 0.72 (Dense)
  -> Complex but information-dense - likely intentional
```

---

## 4. Test Plan

### 4.1 Unit Tests

**File:** `tests/test_entropy.py`

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_low_vrr_repetitive` | `x=x+1; x=x*2; print(x)` | VRR < 0.20 |
| `test_high_vrr_dense` | `a,b,c = unpack(); res = map(f,a)` | VRR > 0.60 |
| `test_function_vrr` | Multi-function file | Per-function dict |
| `test_empty_function` | `def f(): pass` | VRR = 0 (no warning) |
| `test_builtins_excluded` | `print(len(str(x)))` | Builtins not counted |
| `test_common_vars_excluded` | `for i in range(10)` | `i` not counted |

### 4.2 Integration Tests

**File:** `tests/test_entropy_integration.py`

| Test Case | Scenario | Expected |
|-----------|----------|----------|
| `test_genius_code_not_flagged` | Fast inverse sqrt algorithm | Low LDR + High VRR = Reduced severity |
| `test_slop_code_flagged` | AI-generated boilerplate | Low LDR + Low VRR = Increased severity |
| `test_report_includes_vrr` | Analyze project | VRR in output |

### 4.3 Benchmark Tests

**File:** `tests/benchmarks/test_entropy_performance.py`

| Test | Target | Method |
|------|--------|--------|
| `test_vrr_single_file` | < 5ms | 100 iterations, avg |
| `test_vrr_large_project` | < 10s | 1000 files |
| `test_memory_usage` | < 50MB | Peak heap measurement |

---

## 5. Tuning Data

### 5.1 "Genius" Code Corpus

Sources for high-quality, intentionally-dense code:
- Python stdlib `functools`, `itertools`
- NumPy core algorithms
- FastAPI routing internals
- Cryptographic implementations

### 5.2 "Slop" Code Corpus

Sources for AI-generated low-quality code:
- Synthetic generator (existing `ml/synthetic_generator.py`)
- Known bad examples from issues
- Automated hallucination patterns

### 5.3 Threshold Tuning Process

1. Run VRR on both corpora
2. Plot distribution histograms
3. Find optimal separation thresholds
4. Validate with held-out set
5. Document final thresholds

---

## 6. Rollback Plan

If VRR causes regressions:

1. **Quick Disable:**
   ```yaml
   # .slopconfig.yaml
   entropy:
     enabled: false
   ```

2. **Version Rollback:**
   ```bash
   pip install ai-slop-detector==2.6.3
   ```

3. **Monitoring:**
   - Track false positive reports via GitHub issues
   - Compare severity distributions before/after

---

## 7. Documentation Updates

### 7.1 README.md

Add section:
```markdown
### Variable Entropy Analysis (v2.7.0)

Distinguishes "Dense Genius" from "Verbose Garbage":

| VRR Score | Classification | Action |
|-----------|----------------|--------|
| < 0.20 | Low (repetitive) | Increase severity |
| > 0.60 | Dense (rich) | Reduce severity |
```

### 7.2 CHANGELOG.md

```markdown
## [2.7.0] - 2026-01-17

### Added - Variable Entropy Analysis (Phase 2)

#### VRR (Vocabulary Richness Ratio)
- New metric: Unique variables / Total usages
- Per-function VRR calculation
- Heuristic integration with LDR
- Configurable thresholds

#### Intelligence Upgrade
- "Dense Genius": High VRR reduces severity for complex code
- "Verbose Garbage": Low VRR increases severity for repetitive code
- Report output includes VRR score and classification
```

---

## 8. File Checklist

### 8.1 New Files

- [ ] `src/slop_detector/metrics/entropy.py`
- [ ] `tests/test_entropy.py`
- [ ] `tests/test_entropy_integration.py`
- [ ] `tests/benchmarks/test_entropy_performance.py`

### 8.2 Modified Files

- [ ] `src/slop_detector/core.py` (import, init, call, heuristic)
- [ ] `src/slop_detector/models.py` (EntropyResult field)
- [ ] `src/slop_detector/__init__.py` (export)
- [ ] `src/slop_detector/config.py` (entropy config)
- [ ] `src/slop_detector/cli.py` (report output)
- [ ] `.slopconfig.example.yaml` (entropy section)
- [ ] `pyproject.toml` (version bump to 2.7.0)
- [ ] `CHANGELOG.md` (release notes)
- [ ] `README.md` (feature docs)

---

## 9. Success Criteria

### 9.1 Must Have (P0)

- [x] VRRCalculator implemented and tested
- [x] Integration with core.py
- [x] Heuristic adjustment logic
- [x] Configuration support
- [x] All tests pass (existing + new)
- [x] Coverage >= 85%

### 9.2 Should Have (P1)

- [ ] Benchmark tests
- [ ] Tuning data documented
- [ ] Report output updated

### 9.3 Nice to Have (P2)

- [ ] CLI flag `--vrr-only` for VRR-focused analysis
- [ ] Visual VRR distribution chart in HTML report

---

## 10. Timeline

| Phase | Task | Duration |
|-------|------|----------|
| 1 | VRRCalculator implementation | 30 min |
| 2 | Core integration | 20 min |
| 3 | Heuristic adjustment | 15 min |
| 4 | Configuration | 10 min |
| 5 | Reporting | 15 min |
| 6 | Testing | 30 min |
| 7 | Documentation | 15 min |
| **Total** | | ~2.5 hours |

---

## 11. Dependencies

### 11.1 Internal

- `v2.6.3` must be stable (COMPLETED)
- `@slop.ignore` must work (COMPLETED)

### 11.2 External

- None (pure Python AST analysis)

---

## 12. Drift Prevention

### 12.1 Consistency Rules

1. **Naming Convention**: All entropy-related classes prefixed with `Entropy` or `VRR`
2. **Config Key**: Always under `entropy:` namespace
3. **Test Naming**: `test_vrr_*` or `test_entropy_*`
4. **CHANGELOG Format**: Follow existing pattern exactly

### 12.2 Verification Checklist

Before merge:
- [ ] All tests pass
- [ ] Coverage >= 85%
- [ ] CHANGELOG updated
- [ ] Version bumped
- [ ] No breaking changes to existing API
- [ ] Documentation updated

---

## Appendix A: VRR Calculation Example

**Input Code:**
```python
def calculate_tax(income, rate, deduction):
    taxable = income - deduction
    tax = taxable * rate
    return tax
```

**Analysis:**
- Unique variables: `income`, `rate`, `deduction`, `taxable`, `tax` = 5
- Total usages: `income`(1) + `rate`(1) + `deduction`(1) + `taxable`(2) + `tax`(2) = 7
- VRR = 5 / 7 = 0.71 (Dense)

**Comparison (Slop Code):**
```python
def calculate_tax(x, x2, x3):
    x = x - x3
    x = x * x2
    return x
```

**Analysis:**
- Unique variables: `x`, `x2`, `x3` = 3
- Total usages: `x`(5) + `x2`(1) + `x3`(1) = 7
- VRR = 3 / 7 = 0.43 (Normal, but borderline)

The first example has better variable naming (higher entropy), the second uses generic names (lower entropy signal of possible AI generation).

---

**Document Control:**
- Author: Flamehaven Labs
- Created: 2026-01-16
- Last Updated: 2026-01-16
- Status: APPROVED FOR IMPLEMENTATION
