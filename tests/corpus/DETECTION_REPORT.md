# AI-SLOP Detector - Test Results Report

**Generated:** 2026-01-09

---

## Test Case 1: AI Slop

**File:** `test_case_1_ai_slop.py`

### Summary

- **Status:** `CRITICAL_DEFICIT`
- **Deficit Score:** 100.0/100
- **Logic Density (LDR):** 46.03% (B)
- **Inflation Ratio:** 2.54x
- **Import Usage (DDC):** 0.00%

### Metrics Breakdown

| Metric | Value | Status |
|--------|-------|--------|
| Logic Lines | 29/63 | B |
| Empty Lines | 34 | - |
| Jargon Count | 37 | FAIL |
| Unused Imports | 2 | - |

### Buzzwords Detected

`neural`, `transformer`, `neural`, `transformer`, `cutting-edge`, `deep learning`, `attention mechanism`, `state-of-the-art`, `enterprise-grade`, `production-ready`

### Pattern Issues

Found **11** anti-patterns:

- 🔴 **Line 81:** Bare except catches everything including SystemExit and KeyboardInterrupt (`bare_except` - critical)
- 🔴 **Line 81:** Empty exception handler for all exceptions - errors silently ignored (`empty_except` - critical)
- 🟠 **Line 60:** Empty function with only pass - placeholder not implemented (`pass_placeholder` - high)
- 🟠 **Line 25:** Empty function with only pass - placeholder not implemented (`pass_placeholder` - high)
- 🟠 **Line 29:** Empty function with only pass - placeholder not implemented (`pass_placeholder` - high)
- 🟠 **Line 43:** Empty function with only pass - placeholder not implemented (`pass_placeholder` - high)
- 🟠 **Line 68:** Empty function with only ... - placeholder not implemented (`ellipsis_placeholder` - high)
- 🟠 **Line 36:** Empty function with only ... - placeholder not implemented (`ellipsis_placeholder` - high)
- 🟡 **Line 48:** TODO comment - incomplete implementation (`todo_comment` - medium)
- 🟡 **Line 56:** FIXME comment - known issue not addressed (`fixme_comment` - medium)

### Warnings

- ⚠️ WARNING: Low logic density 46.03%
- ⚠️ CRITICAL: Inflation ratio 2.54
- ⚠️ CRITICAL: Only 0.00% of imports used
- ⚠️ PATTERNS: 2 critical issues found
- ⚠️ PATTERNS: 6 high-severity issues found


---

## Test Case 2: Fake Docs

**File:** `test_case_2_fake_docs.py`

### Summary

- **Status:** `INFLATED_SIGNAL`
- **Deficit Score:** 69.6/100
- **Logic Density (LDR):** 90.79% (S++)
- **Inflation Ratio:** 3.27x
- **Import Usage (DDC):** 0.00%

### Metrics Breakdown

| Metric | Value | Status |
|--------|-------|--------|
| Logic Lines | 69/76 | S++ |
| Empty Lines | 7 | - |
| Jargon Count | 64 | FAIL |
| Unused Imports | 2 | - |

### Buzzwords Detected

`cloud-native`, `microservices`, `serverless`, `sophisticated`, `byzantine`, `distributed`, `neural`, `optimization`, `neurips`, `iclr`

### Pattern Issues

Found **2** anti-patterns:

- 🔴 **Line 30:** Mutable default argument - shared state bug (`mutable_default_arg` - critical)
- 🟠 **Line 56:** Empty function with only pass - placeholder not implemented (`pass_placeholder` - high)

### Warnings

- ⚠️ CRITICAL: Inflation ratio 3.27
- ⚠️ CRITICAL: Only 0.00% of imports used
- ⚠️ PATTERNS: 1 critical issues found
- ⚠️ PATTERNS: 1 high-severity issues found


---

## Test Case 3: Hyped Comments

**File:** `test_case_3_hyped_comments.py`

### Summary

- **Status:** `INFLATED_SIGNAL`
- **Deficit Score:** 60.8/100
- **Logic Density (LDR):** 98.31% (S++)
- **Inflation Ratio:** 2.28x
- **Import Usage (DDC):** 100.00%

### Metrics Breakdown

| Metric | Value | Status |
|--------|-------|--------|
| Logic Lines | 58/59 | S++ |
| Empty Lines | 1 | - |
| Jargon Count | 44 | FAIL |
| Unused Imports | 0 | - |

### Buzzwords Detected

`optimization`, `cutting-edge`, `sophisticated`, `optimization`, `state-of-the-art`, `neural`, `cutting-edge`, `sophisticated`, `deep learning`, `transformer`

### Pattern Issues

Found **6** anti-patterns:

- 🔴 **Line 76:** Bare except catches everything including SystemExit and KeyboardInterrupt (`bare_except` - critical)
- 🔴 **Line 76:** Empty exception handler for all exceptions - errors silently ignored (`empty_except` - critical)
- 🟠 **Line 96:** HACK comment - technical debt indicator (`hack_comment` - high)
- 🟡 **Line 66:** TODO comment - incomplete implementation (`todo_comment` - medium)
- 🟡 **Line 65:** FIXME comment - known issue not addressed (`fixme_comment` - medium)
- 🔵 **Line 67:** XXX comment - potential code smell (`xxx_comment` - low)

### Warnings

- ⚠️ CRITICAL: Inflation ratio 2.28
- ⚠️ PATTERNS: 2 critical issues found
- ⚠️ PATTERNS: 1 high-severity issues found


---

## Overall Comparison

| Test Case | Status | Deficit | LDR | Inflation | Patterns |
|-----------|--------|---------|-----|-----------|----------|
| Test Case 1: AI Slop | critical_deficit | 100.0 | 46.03% | 2.54x | 11 |
| Test Case 2: Fake Docs | inflated_signal | 69.6 | 90.79% | 3.27x | 2 |
| Test Case 3: Hyped Comments | inflated_signal | 60.8 | 98.31% | 2.28x | 6 |