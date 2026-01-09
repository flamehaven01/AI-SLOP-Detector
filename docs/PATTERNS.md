# AI-SLOP Detector - Pattern Catalog

**Version:** 2.5.0  
**Last Updated:** 2026-01-09

Complete reference of all anti-patterns detected by AI-SLOP Detector.

---

## Pattern Categories

1. [Structural Issues](#structural-issues)
2. [Placeholder Indicators](#placeholder-indicators)
3. [Cross-Language Mistakes](#cross-language-mistakes)

---

## Structural Issues

### 1. Bare Except

**ID:** `bare_except`  
**Severity:** CRITICAL  
**Category:** Error Handling

**Description:**  
Catches all exceptions including SystemExit and KeyboardInterrupt, which should never be caught.

**Bad Example:**
```python
try:
    risky_operation()
except:  # ← Catches everything!
    pass
```

**Good Example:**
```python
try:
    risky_operation()
except ValueError as e:  # ← Specific exception
    logger.error(f"Invalid value: {e}")
except IOError as e:
    logger.error(f"I/O error: {e}")
```

**Why It's Bad:**
- Masks critical system signals (Ctrl+C)
- Hides programming errors
- Makes debugging impossible
- Violates Python best practices

**Fix:**
```python
# Catch specific exceptions
except (ValueError, IOError) as e:
    handle_error(e)

# If you must catch all, at least log it
except Exception as e:  # Better than bare except
    logger.exception("Unexpected error")
    raise
```

---

### 2. Mutable Default Arguments

**ID:** `mutable_default_arg`  
**Severity:** CRITICAL  
**Category:** Function Definition

**Description:**  
Using mutable objects (list, dict) as default arguments creates shared state bugs.

**Bad Example:**
```python
def add_item(item, items=[]):  # ← Bug!
    items.append(item)
    return items

add_item(1)  # [1]
add_item(2)  # [1, 2] ← Unexpected!
```

**Good Example:**
```python
def add_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items
```

**Why It's Bad:**
- Default argument created once at function definition
- Shared across all calls
- Leads to subtle, hard-to-debug bugs
- Common AI code generation mistake

**Fix:**
```python
def func(arg=None):
    if arg is None:
        arg = []  # Fresh list each call
```

---

### 3. Star Imports

**ID:** `star_import`  
**Severity:** HIGH  
**Category:** Import Statement

**Description:**  
Imports all names from a module, polluting namespace and hiding dependencies.

**Bad Example:**
```python
from os import *
from sys import *

path = "test"  # Which path? os.path or local?
```

**Good Example:**
```python
import os
import sys

path = os.path.join("test", "file.txt")
```

**Why It's Bad:**
- Namespace pollution
- Name conflicts
- Unclear dependencies
- Makes refactoring difficult

**Fix:**
```python
# Specific imports
from os import path, environ

# Or import module
import os
```

---

## Placeholder Indicators

### 4. Pass Placeholder

**ID:** `pass_placeholder`  
**Severity:** HIGH  
**Category:** Empty Implementation

**Description:**  
Function contains only `pass` statement, indicating incomplete implementation.

**Bad Example:**
```python
def quantum_encode(data):
    """Advanced quantum encoding algorithm."""
    pass  # ← Not implemented!
```

**Good Example:**
```python
def quantum_encode(data):
    """Encode data using quantum algorithm."""
    # Actual implementation
    encoded = apply_quantum_transform(data)
    return encoded
```

**Why It's Bad:**
- Promises functionality that doesn't exist
- Creates false sense of completeness
- Common AI code generation pattern
- Misleading documentation

**Fix:**
```python
# Either implement it:
def quantum_encode(data):
    return actual_implementation(data)

# Or make it explicitly abstract:
from abc import ABC, abstractmethod

class QuantumEncoder(ABC):
    @abstractmethod
    def encode(self, data):
        """Subclasses must implement."""
        pass  # OK in abstract methods
```

---

### 5. Ellipsis Placeholder

**ID:** `ellipsis_placeholder`  
**Severity:** HIGH  
**Category:** Empty Implementation

**Description:**  
Function contains only `...` (ellipsis), another form of incomplete implementation.

**Bad Example:**
```python
def transform(x):
    """Transform data."""
    ...  # ← Not implemented!
```

**Good Example:**
```python
def transform(x):
    """Transform data by doubling."""
    return x * 2
```

**Why It's Bad:**
- Same issues as `pass` placeholder
- Valid in type stubs (.pyi) but not in implementation
- AI generators use this for "to be implemented" code

---

### 6. TODO Comment

**ID:** `todo_comment`  
**Severity:** MEDIUM  
**Category:** Technical Debt

**Description:**  
Comment indicating incomplete work.

**Example:**
```python
def process_data(data):
    # TODO: implement validation
    return data
```

**Why It's Concerning:**
- Indicates unfinished work
- May hide missing functionality
- Should be tracked in issue tracker instead

**Fix:**
- Implement the TODO
- Or create a ticket and reference it:
  ```python
  # See issue #123 for validation requirements
  ```

---

### 7. FIXME Comment

**ID:** `fixme_comment`  
**Severity:** MEDIUM  
**Category:** Technical Debt

**Description:**  
Comment indicating known issues that need fixing.

**Example:**
```python
def calculate():
    # FIXME: This breaks on negative numbers
    return value / 2
```

**Why It's Concerning:**
- Acknowledges bugs but doesn't fix them
- Technical debt marker
- May indicate rushed AI-generated code

---

### 8. XXX Comment

**ID:** `xxx_comment`  
**Severity:** MEDIUM  
**Category:** Code Smell

**Description:**  
Comment indicating problematic code that needs attention.

**Example:**
```python
def process():
    # XXX: This is hacky, find better solution
    return quick_fix()
```

---

### 9. HACK Comment

**ID:** `hack_comment`  
**Severity:** MEDIUM  
**Category:** Technical Debt

**Description:**  
Comment explicitly marking code as a hack or workaround.

**Example:**
```python
def workaround():
    # HACK: Temporary fix for production
    return dirty_solution()
```

**Why It's Concerning:**
- Explicitly acknowledges poor quality
- Should be refactored properly
- May indicate AI taking shortcuts

---

## Cross-Language Mistakes

### 10. JavaScript Array Push

**ID:** `javascript_array_push`  
**Severity:** HIGH  
**Category:** Cross-Language Contamination

**Description:**  
Using JavaScript's `.push()` method instead of Python's `.append()`.

**Bad Example:**
```python
items = []
items.push(1)  # ← This is JavaScript!
```

**Good Example:**
```python
items = []
items.append(1)  # ← Python way
```

**Why It Happens:**
- AI trained on multiple languages
- Copy-paste from JavaScript examples
- Lack of language-specific validation

**Detection:**
```python
# Pattern matches:
variable.push(arg)
```

---

### 11. JavaScript Array Length

**ID:** `javascript_array_length`  
**Severity:** HIGH  
**Category:** Cross-Language Contamination

**Description:**  
Using JavaScript's `.length()` method instead of Python's `len()` function.

**Bad Example:**
```python
items = [1, 2, 3]
count = items.length()  # ← JavaScript!
```

**Good Example:**
```python
items = [1, 2, 3]
count = len(items)  # ← Python way
```

---

### 12. Java Equals Method

**ID:** `java_equals_method`  
**Severity:** HIGH  
**Category:** Cross-Language Contamination

**Description:**  
Using Java's `.equals()` method instead of Python's `==` operator.

**Bad Example:**
```python
if obj1.equals(obj2):  # ← Java!
    print("equal")
```

**Good Example:**
```python
if obj1 == obj2:  # ← Python way
    print("equal")
```

---

### 13. Java ToString Method

**ID:** `java_tostring_method`  
**Severity:** HIGH  
**Category:** Cross-Language Contamination

**Description:**  
Using Java's `.toString()` method instead of Python's `str()` function.

**Bad Example:**
```python
text = obj.toString()  # ← Java!
```

**Good Example:**
```python
text = str(obj)  # ← Python way
```

---

## Pattern Detection Process

### 1. AST Walking
```python
for node in ast.walk(tree):
    if isinstance(node, ast.ExceptHandler):
        if node.type is None:  # Bare except
            report_issue()
```

### 2. Content Scanning
```python
if re.search(r'#\s*TODO', content):
    report_issue()
```

### 3. Context Analysis
```python
# Check if in abstract method
if has_decorator(node, 'abstractmethod'):
    skip_pass_placeholder()  # OK in ABC
```

---

## Configuration

### Disabling Patterns

```yaml
# .slopconfig.yaml
patterns:
  disabled:
    - "todo_comment"      # Allow TODO comments
    - "fixme_comment"     # Allow FIXME comments
    - "xxx_comment"       # Allow XXX comments
```

### Severity Filtering

```yaml
patterns:
  severity_filter: "high"  # Only report high+ severity
```

---

## Pattern Scoring

### Severity Weights

```python
severity_weights = {
    "critical": 10.0,  # Bare except, mutable defaults
    "high": 5.0,       # Empty functions, cross-language
    "medium": 2.0,     # TODO/FIXME comments
    "low": 1.0         # Minor issues
}
```

### Penalty Calculation

```python
pattern_penalty = sum(
    severity_weights[issue.severity]
    for issue in issues
)
pattern_penalty = min(pattern_penalty, 50)  # Cap at 50 points
```

---

## Adding Custom Patterns

### Example: Custom Pattern

```python
from slop_detector.patterns.base import ASTPattern
from slop_detector.patterns.base import Severity

class GlobalVariablePattern(ASTPattern):
    id = "global_variable"
    severity = Severity.MEDIUM
    message = "Global variable used"
    
    def detect(self, tree, file, content):
        issues = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Global):
                issues.append(
                    self.create_issue(
                        node, 
                        file,
                        suggestion="Use class attributes or function parameters"
                    )
                )
        return issues
```

### Register Pattern

```python
detector = SlopDetector()
detector.pattern_registry.register(GlobalVariablePattern())
```

---

## Pattern Summary Table

| Pattern | ID | Severity | Category | Auto-Fix |
|---------|----|----|----------|----------|
| Bare Except | `bare_except` | Critical | Structural | No |
| Mutable Default | `mutable_default_arg` | Critical | Structural | No |
| Star Import | `star_import` | High | Structural | No |
| Pass Placeholder | `pass_placeholder` | High | Placeholder | No |
| Ellipsis Placeholder | `ellipsis_placeholder` | High | Placeholder | No |
| TODO Comment | `todo_comment` | Medium | Debt | No |
| FIXME Comment | `fixme_comment` | Medium | Debt | No |
| XXX Comment | `xxx_comment` | Medium | Debt | No |
| HACK Comment | `hack_comment` | Medium | Debt | No |
| JS Array Push | `javascript_array_push` | High | Cross-Lang | Yes* |
| JS Array Length | `javascript_array_length` | High | Cross-Lang | Yes* |
| Java Equals | `java_equals_method` | High | Cross-Lang | Yes* |
| Java ToString | `java_tostring_method` | High | Cross-Lang | Yes* |

*Auto-fix available in future versions

---

## References

- [Python AST Documentation](https://docs.python.org/3/library/ast.html)
- [PEP 8 - Style Guide](https://pep8.org/)
- [Architecture Documentation](ARCHITECTURE.md)

---

**Maintained by:** Flamehaven Labs  
**Contact:** info@flamehaven.space
