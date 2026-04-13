# PhantomImportPattern — Hallucinated Package Detection (v2.9.0)

**Pattern ID:** `phantom_import`
**Severity:** CRITICAL
**Axis:** QUALITY
**Language:** Python only — Go/JS/TS have language-specific error patterns (see [PATTERNS.md](PATTERNS.md#go))
**Module:** `slop_detector.patterns.python_advanced`

---

## Problem

AI code generators occasionally produce `import` statements for packages
that do not exist in the Python ecosystem. The model may:

- Invent a plausible-sounding name (`tensorflow_utils`, `numpy_extended`)
- Conflate two real package names (`requests_async_v2` instead of `httpx`)
- Reference a package from a different language ecosystem
- Generate a package name from outdated training data that no longer exists on PyPI

These phantom imports pass syntax checking and appear legitimate until runtime,
when they raise `ModuleNotFoundError`. In large codebases with conditional imports
or lazy loading, they may go undetected for months.

---

## Detection

### What is flagged

```python
import tensorflow_magic          # CRITICAL — does not exist
from requests_async_v2 import get  # CRITICAL — does not exist
import numpy_extended            # CRITICAL — does not exist
import fake_llm_sdk              # CRITICAL — does not exist
```

### What is not flagged

```python
import numpy                     # installed — OK
from os.path import join         # stdlib — OK
import sys                       # built-in — OK
from . import utils              # relative import — excluded by design
from ..models import Base        # relative import — excluded by design
```

---

## Resolution Strategy

The pattern builds a resolution index once per process from four sources:

### 1. Built-in C modules
```python
sys.builtin_module_names
# e.g.: ('_abc', '_ast', '_bisect', 'sys', 'builtins', ...)
```

### 2. Standard library (Python 3.10+)
```python
sys.stdlib_module_names
# e.g.: frozenset({'os', 'sys', 'pathlib', 'json', 'ast', ...})
```
On Python 3.8/3.9, this source is absent; sources 1, 3, and 4 cover the gap.

### 3. Installed distributions
```python
from importlib.metadata import packages_distributions
# Returns: {'numpy': ['numpy'], 'Pillow': ['PIL'], 'scikit-learn': ['sklearn'], ...}
# Maps distribution name → list of importable top-level names
```

### 4. Fallback — find_spec
```python
importlib.util.find_spec(module_name)
# Handles: namespace packages, editable installs (pip install -e .)
# Used only when the module is not found in sources 1–3
```

### Error policy
On any resolution error, the pattern returns `True` (module assumed resolvable).
This errs toward **False Negative** — missing a phantom import is preferable
to falsely flagging a legitimate one.

---

## False Positive Avoidance

| Scenario | Handled |
|---|---|
| Relative imports | Excluded (`node.level > 0`) |
| Editable installs | find_spec fallback |
| Namespace packages | find_spec fallback |
| `PIL` (installed as `Pillow`) | `packages_distributions()` maps import names |
| `sklearn` (installed as `scikit-learn`) | `packages_distributions()` maps import names |
| Resolution errors | Returns True (assume resolvable) |
| Python 3.8/3.9 (no `stdlib_module_names`) | find_spec fallback covers stdlib |

---

## Performance

The resolution index is built **once per process** and cached as a module-level
`frozenset`. Subsequent files share the same index with O(1) lookup per import.
`find_spec` is called only as a last resort, never for modules already in the index.

---

## Relationship to DDC (Dependency Density Check)

DDC measures the **ratio of imported packages that are actually used** in the file.
`phantom_import` is orthogonal — it measures whether the import target **exists at all**.

| | DDC | PhantomImport |
|---|---|---|
| Question | "Is this import used?" | "Does this import exist?" |
| Signal | Noise / dead imports | Hallucination |
| Severity | LOW–MEDIUM | CRITICAL |
| Scope | Usage analysis | Existence analysis |

A file can have low DDC (imports present but unused) AND phantom imports (imports
that don't exist) simultaneously. Both contribute to the deficit score.

---

## Example Output

```
[CRITICAL] phantom_import — src/pipeline.py:4
  Phantom import: 'tensorflow_magic' cannot be resolved
  (not in stdlib, built-ins, or installed packages)
  Suggestion: Verify 'tensorflow_magic' exists on PyPI and is listed
  in your project dependencies. AI models sometimes generate
  plausible-looking but non-existent package names.
```

---

## Disabling

To disable for a specific line (e.g., conditional platform import):

```python
# .slopconfig.yaml
disabled_patterns:
  - phantom_import
```

Or per-file inline (flagged by `lint_escape` — use sparingly):
```python
import platform_specific_pkg  # noqa: phantom_import
```
