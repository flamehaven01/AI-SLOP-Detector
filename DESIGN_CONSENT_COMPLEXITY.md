# 📐 Design Proposal: Consent-Based Complexity (v3.1.0)
> **Target**: `ai-slop-detector` v3.1.0
> **Goal**: Distinguish "Intentional Complexity" (Genius) from "Accidental Complexity" (Slop).

## 1. Feature: `@slop.ignore` Decorator

### Concept
Allow developers to sign off on specific blocks of code, asserting that the complexity is intentional and necessary. This shifts responsibility from the *Tool* to the *Sovereign Developer*.

### Specification
*   **Decorator Name**: `@slop.ignore` (or `@slop.whitelist`)
*   **Arguments**:
    *   `reason` (Required): A string explaining *why* this complexity is needed.
    *   `rules` (Optional): List of specific rules to ignore (e.g., `["LDR", "INFLATION"]`). If empty, ignore all.

### Usage Example
```python
import slop

@slop.ignore(reason="Bitwise optimization for O(1) loop performance")
def fast_inverse_sqrt(number):
    # Highly complex, "ugly" code that is actually genius
    i = 0x5f3759df - (i >> 1)
    return y * (1.5 - (x2 * y * y))
```

### Implementation Logic
1.  **AST Analysis**: During AST traversal, check function decorators.
2.  **Marker**: If `slop.ignore` is found, flag the `FunctionDef` node as `ignored=True`.
3.  **Metric Exclusion**:
    *   **LDR**: Do not count lines within this function towards "Total Lines" or "Logic Lines" (Neutralize impact).
    *   **Inflation**: Skip AST node complexity scoring for this subtree.
4.  **Audit Trail**: The ignored function is logged in the report under a "Whitelisted Complexity" section, maximizing transparency.

---

## 2. Feature: Variable Entropy Analysis (Density Check)

### Concept
"Slop" often involves repetitive, low-information code (hallucination patterns, copy-paste). "Genius" code involves high-information density. We use **Shannon Entropy** or **Uniqueness Ratio** to distinguish them.

### Algorithm: The "Vocabulary Richness" Ratio (VRR)
*   **Formula**: `VRR = Unique_Variables / Total_Variable_Usages`
*   **Hypothesis**:
    *   **Low VRR (< 0.2)**: Same variables used over and over. (e.g., `x = x + 1; x = x * 2; print(x)`). Risk of "Filler".
    *   **High VRR (> 0.6)**: New concepts introduced frequently. (e.g., `a, b, c = unpack(); res = map(f, a)`). Indicates "Density".

### Integration
1.  **Collector**: Walk AST `Name` nodes. Collect `id` context (Load/Store).
2.  **Metric**: Calculate VRR per function.
3.  **Heuristic Adjustment**:
    *   **If** `LDR` is Low (Complex) **AND** `VRR` is High (Dense) --> **Downgrade Severity** (Likely Genius).
    *   **If** `LDR` is Low (Complex) **AND** `VRR` is Low (Repetitive) --> **Upgrade Severity** (Likely Slop/Spaghetti).

---

## 3. Implementation Roadmap

### Phase 1: The Decorator (Core)
- [ ] Create `src/slop_detector/decorators.py` (Dummy decorator for import).
- [ ] Update `SlopDetector._calculate_slop_status` to respect ignored nodes.
- [ ] Add unit test: `tests/test_ignore_pattern.py`.

### Phase 2: The Entropy Engine (Intelligence)
- [ ] Create `src/slop_detector/metrics/entropy.py`.
- [ ] Implement `VRRCalculator`.
- [ ] Tuning: Run on known "Good" vs "Bad" codebases to find VRR thresholds.

### Phase 3: Reporting
- [ ] Update CLI to show "Ignored Functions" count.
- [ ] Update JSON report to include `entropy_score`.
