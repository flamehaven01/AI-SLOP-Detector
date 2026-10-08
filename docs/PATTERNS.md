# AI-SLOP Detector - Pattern Catalog

**Version:** `main` after v3.9.1 (includes unreleased pattern changes)
**Last Updated:** 2026-10-04

Complete reference of all anti-patterns detected by AI-SLOP Detector.

---

## Pattern Categories

1. [Structural Issues](#structural-issues)
2. [Placeholder Indicators](#placeholder-indicators)
3. [Cross-Language Mistakes](#cross-language-mistakes)
4. [Python Advanced (v2.8.0+)](#python-advanced)
5. [Phantom Import (v2.9.0)](#phantom-import)
6. [Clone Detection (v3.1.0)](#clone-detection)
7. [JavaScript / TypeScript (v3.4.0)](#javascript--typescript)
8. [Go (v3.5.0)](#go)

---

## Quick Reference

Every rule the detectors currently report. This table is the current-state contract:
`tests/test_patterns_doc_consistency.py` checks it against the Python pattern registry,
the ids the Python patterns emit, the JS/TS and Go analyzers, and the autofix registry.
Severity shows the default first; other severities a rule can emit follow it.
The detailed sections below explain the main rules and may not cover every id.

<!-- ACTIVE_PATTERN_REGISTRY:START -->
| ID | Language | Severity | Category | Auto-Fix | Description |
|---|---|---|---|---|---|
| `bare_except` | Python | Critical | Structural | Yes | Catches all exceptions including SystemExit |
| `mutable_default_arg` | Python | Critical | Structural | Yes | Mutable default argument (list/dict) |
| `star_import` | Python | High | Structural | No | `from module import *` |
| `global_statement` | Python | High | Structural | No | `global` keyword usage |
| `empty_except` | Python | Critical | Placeholder | No | Exception handler with only `pass` |
| `not_implemented` | Python | High | Placeholder | No | `raise NotImplementedError` stub |
| `pass_placeholder` | Python | High | Placeholder | Yes | Function/class body is only `pass` |
| `ellipsis_placeholder` | Python | High | Placeholder | Yes | Function body is only `...` (skips `@abstractmethod`) |
| `return_none_placeholder` | Python | Medium | Placeholder | No | `return None` as only statement (skips `Optional[T]` annotations) |
| `return_constant_stub` | Python | High | Placeholder | No | Function body is a single `return <constant>` |
| `interface_only_class` | Python | High | Placeholder | No | Class with only abstract or placeholder methods |
| `todo_comment` | Python | Medium | Placeholder | No | `# TODO` comment |
| `fixme_comment` | Python | Medium | Placeholder | No | `# FIXME` comment |
| `hack_comment` | Python | High | Placeholder | No | `# HACK` comment |
| `xxx_comment` | Python | Low | Placeholder | No | `# XXX` comment |
| `js_push` | Python | High | Cross-Language | Yes | `.push()` on a value proven to be a built-in (`items = []; items.push(x)`) |
| `java_equals` | Python | High | Cross-Language | No | `.equals()` on a value proven to be a built-in |
| `ruby_each` | Python | High | Cross-Language | No | `.each()` on a value proven to be a built-in |
| `csharp_length` | Python | High | Cross-Language | Yes | `.Length` on a value proven to be a built-in |
| `go_println` | Python | Medium | Cross-Language | No | `fmt.Println()` (Go print) |
| `php_strlen` | Python | High | Cross-Language | No | `strlen()` (PHP function) |
| `god_function` | Python | High (Medium or Low when only long) | Complexity | No | Function over the logic-line or complexity limit |
| `dead_code` | Python | Medium | Complexity | No | Unreachable statements after return/raise |
| `deep_nesting` | Python | High | Complexity | No | Control-flow depth over the limit |
| `nested_complexity` | Python | Critical | Complexity | No | Control-flow depth and cyclomatic complexity both over their limits |
| `lint_escape` | Python | High (bare `# noqa`); Medium or Low for narrower suppressions | Lint | No | `# noqa`, `# type: ignore`, `# pylint: disable` |
| `phantom_import` | Python | Critical | Imports | No | Import targets a package or module that does not exist |
| `undeclared_optional_dependency` | Python | Medium | Imports | No | ImportError-guarded import not listed in optional dependencies |
| `runtime_unavailable_dependency` | Python | Medium | Imports | No | Declared dependency unavailable in the analyzer runtime (environment evidence) |
| `declared_outside_primary_metadata` | Python | Low | Imports | No | Dependency declared outside pyproject.toml project metadata |
| `phantom_member` | Python | High | Imports | No | Imported name that the installed package does not define |
| `placeholder_variable_naming` | Python | High | Naming | No | Variables named `x`, `tmp`, `dummy`, `foo` in production code |
| `exact_duplicate_pair` | Python | High (Critical for 4 or more functions) | Clones | No | Same-file duplicate functions after normalizing local names |
| `function_clone_cluster` | Python | High (Critical for 6 or more functions) | Clones | No | Near-identical function clusters via AST JSD |
| `js_var_usage` | JS/TS | Medium | JS/TS | No | `var` declaration |
| `js_console_log` | JS/TS | Low | JS/TS | No | `console.log` / `warn` / `error` / `info` |
| `js_any_type` | JS/TS | High | JS/TS | No | TypeScript `any` type |
| `js_empty_arrow` | JS/TS | Medium | JS/TS | No | Empty arrow function body |
| `js_double_equals` | JS/TS | Medium | JS/TS | No | Loose equality (`==` instead of `===`) |
| `js_god_function` | JS/TS | High | JS/TS | No | Function over the size or complexity threshold |
| `js_dead_code` | JS/TS | Medium | JS/TS | No | Unreachable statement after return/throw/break |
| `js_callback_hell` | JS/TS | High | JS/TS | No | Callback nesting over the depth threshold |
| `go_empty_func` | Go | High | Go | No | Empty function body (stub) |
| `go_panic` | Go | Medium / Critical (from the 3rd panic in a file) | Go | No | `panic()` used as the error path |
| `go_fmt_print` | Go | Medium | Go | No | Debug print via `fmt.Println` / `Printf` / `Print` |
| `go_ignored_error` | Go | High | Go | No | Blank-identifier error suppression (`_ = expr`) |
| `go_todo_comment` | Go | Low | Go | No | `// TODO` / `FIXME` / `HACK` comment |
| `go_god_function` | Go | High | Go | No | Function over the line limit |
<!-- ACTIVE_PATTERN_REGISTRY:END -->

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

### 5. Not Implemented Error (v2.6+)

**ID:** `not_implemented`
**Severity:** HIGH
**Category:** Empty Implementation

**Description:**
Function raises `NotImplementedError`, indicating incomplete or interface-only implementation.

**Bad Example:**
```python
def advanced_algorithm(data):
    """State-of-the-art processing."""
    raise NotImplementedError  # ← Not implemented!
```

**Good Example:**
```python
# Either implement it:
def advanced_algorithm(data):
    """Process data using XYZ algorithm."""
    result = actual_processing(data)
    return result

# Or use ABC for interfaces:
from abc import ABC, abstractmethod

class DataProcessor(ABC):
    @abstractmethod
    def process(self, data):
        """Subclasses must implement."""
        raise NotImplementedError  # OK in abstract methods
```

**Why It's Bad:**
- Promises functionality without delivering
- Crashes at runtime if called
- Common AI code generation placeholder
- Should use ABC for proper interfaces

---

### 6. Empty Exception Handler (v2.6+)

**ID:** `empty_except`
**Severity:** CRITICAL
**Category:** Error Handling

**Description:**
Exception handler catches errors but does nothing (empty `except: pass`), silently swallowing all errors.

**Bad Example:**
```python
try:
    critical_operation()
except ValueError:
    pass  # ← Errors silently ignored!
except IOError:
    pass  # ← No logging, no handling!
```

**Good Example:**
```python
try:
    critical_operation()
except ValueError as e:
    logger.warning(f"Invalid value: {e}")
    use_default_value()
except IOError as e:
    logger.error(f"I/O error: {e}")
    raise  # Re-raise if can't handle
```

**Why It's Bad:**
- Silently ignores errors
- Makes debugging impossible
- Hides critical failures
- Violates error handling best practices
- Even worse than bare except

**Fix:**
```python
except ValueError as e:
    logger.error(f"Error: {e}")
    # Take corrective action
```

---

### 7. Return None Placeholder (v2.6+)

**ID:** `return_none_placeholder`
**Severity:** MEDIUM
**Category:** Empty Implementation

**Description:**
Function only returns `None` with no other logic, indicating placeholder implementation.

**Bad Example:**
```python
def calculate_result(x, y):
    """Compute advanced calculation."""
    return None  # ← Not implemented!
```

**Good Example:**
```python
def calculate_result(x, y):
    """Compute sum of x and y."""
    return x + y
```

**Why It's Concerning:**
- Indicates incomplete implementation
- Misleading function signature
- May cause None-related errors downstream
- Common AI placeholder pattern

**Exclusions (v3.7.4):**
- `@abstractmethod` decorated methods — skipped (correct ABC contract)
- Return annotation is `Optional[T]` or `T | None` — skipped (intentional Null Object pattern)

---

### 8. Interface-Only Class (v2.6+)

**ID:** `interface_only_class`
**Severity:** HIGH
**Category:** Empty Implementation

**Description:**
Class where ≥50% of non-dunder, non-abstract methods have placeholder bodies (`pass`, `...`, `return None`, `raise`), indicating an incomplete implementation masquerading as a class.

**Bad Example:**
```python
class DataProcessor:
    """Advanced data processing system."""

    def load(self):
        pass

    def validate(self):
        pass

    def process(self):
        pass

    def save(self):
        pass
    # 4/4 methods are placeholders = 100% placeholder class!
```

**Good Example:**
```python
# Option 1: Implement the methods
class DataProcessor:
    def load(self):
        self.data = read_file()

    def process(self):
        return transform(self.data)

# Option 2: Use ABC for proper interfaces
from abc import ABC, abstractmethod

class DataProcessor(ABC):
    @abstractmethod
    def load(self):
        """Load data from source."""
        pass  # OK in abstract methods

    @abstractmethod
    def process(self):
        """Process loaded data."""
        pass  # OK in abstract methods
```

**Why It's Bad:**
- Fake implementation with no functionality
- Misleads about class capabilities
- Common AI code scaffolding pattern

**Exclusions (v3.7.4):** `@abstractmethod` decorated methods are not counted as placeholders — a pure ABC with all abstract methods is a valid interface definition and will not trigger this pattern.

---

### 9. Ellipsis Placeholder

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

**Exclusion (v3.7.4):** `@abstractmethod` decorated methods are skipped — `def method(self) -> None: ...` in an ABC is the correct Python interface idiom.

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
**Severity:** LOW  
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
**Severity:** HIGH  
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

`js_push`, `java_equals`, `ruby_each`, and `csharp_length` are reported only when the
receiver is proven to be a Python built-in: a built-in literal, or a name bound exactly
once in the same scope, by a top-level statement before the use, to a built-in literal
or an unshadowed built-in constructor (`list()`, `str()`, ...). On a built-in these
members do not exist, so the call fails at run time. A parameter, an attribute
(`self.pool.push(x)`), a factory result, or a name bound in a branch or rebound is not
proven and is not reported: many real APIs are called `push` or `equals`
(pandas `DataFrame.equals`, SymPy). `go_println` and `php_strlen` match the call itself.

### 10. JavaScript Array Push

**ID:** `js_push`  
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

**Not reported:**
```python
self.pool.push(item)   # an attribute: its type is not proven
def add(stack, x):
    stack.push(x)      # a parameter: its type is not proven
```

**Auto-fix:** `--fix` rewrites the reported `.push(` to `.append(` (that occurrence only).

---

### 11. Java Equals Method

**ID:** `java_equals`  
**Severity:** HIGH  
**Category:** Cross-Language Contamination

**Description:**  
Using Java's `.equals()` method instead of Python's `==` operator.

**Bad Example:**
```python
name = "slop"
if name.equals(other):  # ← Java! str has no .equals()
    print("equal")
```

**Good Example:**
```python
name = "slop"
if name == other:  # ← Python way
    print("equal")
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

The same ids work on the command line (`--disable todo_comment`); an unknown id there is
an error (exit code 2), and `--list-patterns` prints the Python ids.

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

A `deep_nesting` finding at the same function location as a `nested_complexity`
finding adds no penalty: `nested_complexity` is that deep nesting plus a
complexity condition, so the construct is charged once (10, not 15). Both
findings are reported, and `nested_complexity` still counts as CRITICAL for
purity. `god_function` (length or its own complexity limit) keeps its penalty.

---

## Adding Custom Patterns

### Example: Custom Pattern

```python
import ast

from slop_detector.patterns.base import ASTPattern, Axis, Severity


class PrintCallPattern(ASTPattern):
    id = "print_call"
    severity = Severity.LOW
    axis = Axis.NOISE
    message = "print() call left in library code"

    def check_node(self, node, file, content):
        # Called for every AST node; return an Issue, a list of Issues, or None.
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
            return self.create_issue_from_node(node, file, suggestion="Use logging instead")
        return None
```

### Register Pattern

```python
detector = SlopDetector()
detector.pattern_registry.register(PrintCallPattern())
```

---

## Pattern Summary Table

The current table, with severity, language, and auto-fix for every active rule, is the
[Quick Reference](#quick-reference) at the top of this page.

`--fix --dry-run` is the safe way to discover whether a detected pattern has a
registered patcher. Only a limited set of line-oriented fixes is available;
clone, cleanup-family, and most structural findings require review.

---

## References

- [Python AST Documentation](https://docs.python.org/3/library/ast.html)
- [PEP 8 - Style Guide](https://pep8.org/)
- [Architecture Documentation](ARCHITECTURE.md)

---

## Python Advanced

Patterns added in v2.8.0, using Python `ast` module for structural analysis.

### god_function

**Severity:** HIGH | **Axis:** STYLE

Function exceeds `logic_lines > 50` OR `cyclomatic_complexity > 10`.
Cyclomatic complexity = `1 + count(If, For, While, ExceptHandler, With, BoolOp)`.
God functions are primary carriers of slop: they combine unrelated responsibilities
and resist meaningful testing.

```python
# Flagged:
def do_everything(data, config, user, db, cache, logger):  # 200 lines, complexity 15
    ...

# Fix: break into single-responsibility functions
```

---

### dead_code

**Severity:** MEDIUM | **Axis:** QUALITY

Statements following a terminal node (`return`, `raise`, `break`, `continue`) in any
block — including `orelse`, `finalbody`, and exception handler bodies.

```python
# Flagged:
def process(x):
    return x * 2
    print("done")  # never reached
```

---

### deep_nesting

**Severity:** HIGH | **Axis:** STYLE

Control-flow nesting depth > 4 within a single function.
Depth computed recursively over `If/For/While/With/Try` bodies.

```python
# Flagged (depth 5):
for item in data:
    if item:
        for sub in item:
            if sub:
                try:
                    if sub.valid:  # depth 5
                        ...
```

---

### lint_escape

**Severity:** HIGH / MEDIUM / LOW | **Axis:** QUALITY

Detects lint and type suppression comments. Three sub-signals:

| Comment | Severity | Rationale |
|---|---|---|
| `# noqa` (bare) | HIGH | Silences ALL warnings — no documentation of what or why |
| `# noqa: CODE` | LOW | Targeted — legitimate in some cases |
| `# type: ignore` | MEDIUM | Hides real type errors from static analysis |
| `# pylint: disable=` | MEDIUM | Inline disables harder to audit than config entries |

---

## Phantom Import

*Full documentation: [PHANTOM_IMPORT.md](PHANTOM_IMPORT.md)*

### phantom_import

**Severity:** CRITICAL | **Axis:** QUALITY | **Added:** v2.9.0

Detects imports referencing packages that cannot be resolved in the current
environment — a direct signal of AI-hallucinated code.

**Resolution index** (built once per process):
1. `sys.builtin_module_names` — C extensions
2. `sys.stdlib_module_names` — stdlib (Python 3.10+)
3. `importlib.metadata.packages_distributions()` — pip-installed packages
4. The import system's finders, as `importlib.util.find_spec` would use them, over
   `sys.path` without the analyzer's working directory and without the analyzed
   project's own roots — namespace packages, editable installs

Relative imports are excluded by design. Declared `[project.optional-dependencies]`
entries are recognised after stripping PEP-508 extras specifiers (`psycopg[binary]`
→ `psycopg`), so guarded imports for properly declared optional packages are not flagged.

```python
# CRITICAL:
import tensorflow_magic        # does not exist
from requests_async_v2 import get  # does not exist

# OK:
import numpy                   # installed
from os import path            # stdlib
from . import utils            # relative — excluded
```

See [PHANTOM_IMPORT.md](PHANTOM_IMPORT.md) for full specification.

---

## Clone Detection

*Added: v3.1.0*

### exact_duplicate_pair

**Severity:** HIGH | **Axis:** STRUCTURE

Detects exact duplicate functions inside the same file after normalizing local
variable names and parameter names. This catches copy-paste logic even when the
author renamed `tally` to `marker` or `readings` to `bucket`.

This is a strict detector. It does **not** try to infer semantic similarity, and
it skips tiny trivial wrappers to reduce noise.

### function_clone_cluster

**Severity:** HIGH (CRITICAL for 6 or more functions) | **Axis:** QUALITY

Detects clusters of near-identical function bodies — the most common structural
sign of AI-generated code that was copy-pasted instead of abstracted.

Detection uses 30-dim normalized AST node-type histograms and Jensen-Shannon
Divergence (JSD). Functions with pairwise JSD < 0.05 are grouped into a clone
cluster via BFS connected components.

**Dispatcher exemptions** (not flagged):
- Functions dispatched via a dict lookup table (≥40% of group referenced)
- Functions sharing a naming prefix ≥3 chars at ≥80% uniformity (`cmd_*`, `handle_*`)
- FastAPI / Flask route files (module-level `app` or `router` assignment)
- `@abstractmethod` stubs (excluded from histogram before clustering)

```python
# Flagged: clone cluster (similarity 0.92)
def process_user(user):
    result = []
    for item in user.items:
        if item.active:
            result.append(item.value)
    return result

def process_order(order):
    result = []
    for item in order.items:    # Nearly identical body
        if item.active:
            result.append(item.value)
    return result

# Fix: extract the shared logic
def _collect_active_values(container):
    return [item.value for item in container.items if item.active]
```

---

### placeholder_variable_naming

**Severity:** HIGH | **Axis:** QUALITY | **Added:** v3.1.0

Detects placeholder variable names in production code: `x`, `y`, `z`, `tmp`,
`temp`, `dummy`, `foo`, `bar`, `baz`, `data2`, `result2`, etc. Single-letter
variables in loops are excluded (standard Python idiom).

```python
# Flagged:
tmp = fetch_user()
result2 = process(tmp)

# OK:
user = fetch_user()
processed = process(user)
```

---

### return_constant_stub

**Severity:** HIGH | **Axis:** QUALITY | **Added:** v3.1.0

Function always returns the same constant regardless of input — a classic stub
pattern. Excludes known constant-returning idioms (e.g., `__bool__`, `__len__`,
sentinel factories).

```python
# Flagged:
def calculate_score(metrics):
    """Complex scoring algorithm."""
    return 42   # always 42 regardless of input

# OK:
def is_enabled():
    return True  # explicit toggle — not a stub
```

---

## JavaScript / TypeScript

*Added: v3.4.0 — `.js`, `.ts`, `.jsx`, `.tsx` files. Uses tree-sitter when the `js` extra is
installed and a regex fallback otherwise; both emit the same ids and severities.*

| ID | Severity | What it flags |
|---|---|---|
| `js_var_usage` | MEDIUM | `var` declaration (use `let` / `const`) |
| `js_console_log` | LOW | `console.log` / `warn` / `error` / `info` left in code |
| `js_any_type` | HIGH | TypeScript `any` type: erases type information |
| `js_empty_arrow` | MEDIUM | Arrow function with an empty body |
| `js_double_equals` | MEDIUM | Loose equality `==` instead of `===` |
| `js_god_function` | HIGH | Function over 50 lines or cyclomatic complexity 10 |
| `js_dead_code` | MEDIUM | Statement after `return` / `throw` / `break` |
| `js_callback_hell` | HIGH | Nesting deeper than 4 levels |

---

## Go

*Added: v3.5.0 — `.go` files.*

| ID | Severity | What it flags |
|---|---|---|
| `go_empty_func` | HIGH | Function with an empty body (stub) |
| `go_panic` | MEDIUM, CRITICAL from the 3rd `panic()` in a file | `panic()` used as the error path instead of returning an error |
| `go_fmt_print` | MEDIUM | Debug print via `fmt.Println` / `Printf` / `Print` |
| `go_ignored_error` | HIGH | Error discarded with the blank identifier (`_ = expr`) |
| `go_todo_comment` | LOW | `// TODO` / `FIXME` / `HACK` comment |
| `go_god_function` | HIGH | Function over 60 lines |

```go
// go_ignored_error:
_ = os.Remove(tmpFile)     // error silently discarded

// Fix:
if err := os.Remove(tmpFile); err != nil {
    log.Printf("failed to remove temp file: %v", err)
}
```

---
**Contact:** info@flamehaven.space
