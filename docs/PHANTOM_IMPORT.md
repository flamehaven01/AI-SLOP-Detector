# Phantom Import Detection

**Current contract:** v3.18.0 (unreleased). The original pattern was introduced
in v2.9.0; this page describes its current resolution boundary. How the
provider of an import is found, and why, is in
[IMPORT_PROVIDER_RESOLUTION.md](IMPORT_PROVIDER_RESOLUTION.md).

**Pattern ID:** `phantom_import`
**Severity:** HIGH (at most; 3.18)
**Axis:** QUALITY
**Language:** Python only — JS/TS, Go and Rust have their own rules (see [PATTERNS.md](PATTERNS.md#javascript--typescript))
**Module:** `slop_detector.patterns.python_imports`

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

What the analyzer can observe is narrower than "the package does not exist":
no installed distribution, no dependency declaration and no known provider
supplies the name. That is what an invented name looks like, and also what a
real package looks like that is new, rare, private or missing from the shipped
mapping. The finding states what was observed; it is never proof that no
package exists, and it never suggests installing or declaring the name.

---

## Detection

### What is flagged

```python
import tensorflow_magic          # HIGH: no provider known, not declared
from requests_async_v2 import get  # HIGH: no provider known, not declared
import numpy_extended            # HIGH: no provider known, not declared
import fake_llm_sdk              # HIGH: no provider known, not declared
```

### What is not flagged

```python
import numpy                     # installed — OK
from os.path import join         # stdlib — OK
import sys                       # built-in — OK
from . import utils              # relative import — excluded by design
from ..models import Base        # relative import — excluded by design
import mypackage.core            # project module — resolved in the project
```

---

## Resolution Strategy

### Project modules are never checked as packages

Before the four sources below, an import is skipped when it belongs to the
project: a top-level name of the project's internal packages, a sibling `.py`
file (flat-module projects), a name in `phantom_import_allowlist`, or a module
the project's module index resolves to an actual file (`src/` layouts and
namespace packages included). A package directory next to a script (regular
or namespace) is local too, unless the file is inside a regular package, where
imports are absolute (v3.10).

### Declarations

"Declared" means named by a dependency declaration of the file's project
(v3.10): PEP 621 and Poetry `pyproject.toml` (dependencies, dev and groups),
PEP 735 `[dependency-groups]` and `[tool.uv] dev-dependencies` (3.18), and, for a
`setup.py` only, `[build-system] requires` of the `pyproject.toml` beside it (build-time
dependencies; they never excuse an import in the package's modules),
`setup.py` `install_requires` / `extras_require` (literals or module-level
names, read with `ast`, never executed), `setup.cfg`, `Pipfile`,
`requirements*.txt` / `.in`, and conda `environment*.yml` with its pip list,
at each project root and in the directories between the file and its root. A
declaration in another subtree says nothing about the file.

### Unresolved does not always mean phantom

An import that none of the sources resolves is reported by the first row that
applies. "Declared" means a declaration whose distribution provides the import
name (provider resolution, below), not a declaration with the same spelling:

| Situation | Reported as | Severity |
|---|---|---|
| Under a platform test (`if sys.platform == ...`) that the target environment does not decide | listed in `unverified_imports` (reason `platform_guard_undecided`), no score effect | - |
| Under `if TYPE_CHECKING:` (does not run) | listed in `unverified_imports` (reason `type_checking_only`), no score effect | - |
| Runs after the file changes `sys.path` earlier in its scope or an enclosing scope (the static search path is not the one it uses) | listed in `unverified_imports` (reason `sys_path_modified`), no score effect; imports before the change, or in scopes it does not precede, are judged as usual | - |
| Declared only outside `pyproject.toml` project metadata (e.g. `requirements.txt`) while the file's nearest resolution root has a `pyproject.toml` | `declared_outside_primary_metadata` | LOW |
| Declared as a dependency but not installed in the target environment (or where the analyzer runs, when there is none) | `runtime_unavailable_dependency` | MEDIUM |
| Inside `try/except ImportError` and not declared | `undeclared_optional_dependency` | MEDIUM |
| Not declared, and a provider is known | `undeclared_dependency` | MEDIUM; HIGH only when the target environment's own files identify the one provider |
| Not declared, and no provider is known | `phantom_import` | HIGH |

An import under a platform test that is false in the target environment does
not run there and is not reported.

### Provider resolution (3.18)

Which distribution provides an import name is established from evidence,
strongest first, and recorded in each finding's `evidence`
(`import_name`, `provider`, `provider_state`, `environment`,
`target_platform`, and `marker_evaluation` when the declaration has a marker):

1. the target environment's installed files: a virtual environment directly
   inside the project root (a directory with `pyvenv.cfg`), read as files and
   never executed (`ARTIFACT_VERIFIED`; `METADATA_DECLARED` for PEP 794
   `Import-Name`);
2. mapping knowledge: the analyzer environment's installed metadata and the
   shipped table `config/import_providers.json` (`MAPPING_SUPPORTED`; each
   finding that uses a table entry also carries the entry's audit state,
   `mapping_audit`: `ARTIFACT_VERIFIED` when a local artifact's files matched
   their RECORD hashes, else `AUDIT_PENDING`);
3. the declared name itself (`NAME_CANDIDATE`), never the basis of a CRITICAL
   or HIGH verdict.

Distribution names compare after PEP 503 normalization; import names compare
exactly (case-sensitive). When several distributions are known to provide a
name and nothing selects one, no provider is named (`candidates` lists them).
With a target environment, presence is decided there only: the analyzer's own
installs are not evidence about the project. The target platform and Python
version (for environment markers and platform tests) come from the target
environment too; without one they are unknown.

`phantom_member` checks names against the installed provider only when it is the
declared one; when another distribution supplies the module, it reports
`provider_conflict` (MEDIUM; no score effect when seen only in the analyzer's
environment).

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

### 4. Fallback — the import system's finders
```python
# What importlib.util.find_spec(module_name) does, over the analyzer's environment:
# the meta-path finders, and sys.path without two kinds of entry
# Handles: namespace packages, editable installs (pip install -e .)
# Used only when the module is not found in sources 1–3
```

Two kinds of `sys.path` entry are not evidence that a package is installed:

- the directory the analyzer runs from (`""` or the working directory itself,
  which `python -m` and the pre-commit hooks put on `sys.path`). A `models/`
  directory next to where the analyzer runs says nothing about the analyzed
  project;
- the analyzed project's own roots. What is project code is decided by the
  project's module index (above), not by whether the project is on `sys.path`.

The same target in the same environment gives the same result from any working
directory. Nothing is imported or executed.

### Error policy
A lookup that raises is not an answer (v3.10): the module is not assumed
installed. The pattern is recorded as unmeasured for that file
(`pattern_errors`, state `unmeasured`), the file is listed in
`scan_coverage.unmeasured`, and the scan is not complete (a hard CI gate fails
closed, a soft gate warns). A partial result is not cached. Before v3.10 such a
lookup answered "installed", which made two import findings vanish under
resource exhaustion.

### A source with no location
`SlopDetector.analyze_code_string(content)` without `project_root` analyzes a
source that has no place on disk: no sibling module, project root or
declaration is read for it (before v3.10 its virtual filename resolved to the
working directory). An import the environment cannot resolve may be local
code, so it is not reported; it is listed in `unverified_imports` with reason
`no_project_context` and no score effect. Standard-library and installed
packages, and the names they define (`phantom_member`), are still checked.
With `project_root`, the source is analyzed as the file
`project_root/filename`.

---

## False Positive Avoidance

| Scenario | Handled |
|---|---|
| Relative imports | Excluded (`node.level > 0`) |
| Editable installs | Finder fallback |
| Namespace packages | Finder fallback |
| `PIL` declared as `Pillow`, `sklearn` as `scikit-learn` (installed or not) | provider resolution links the declaration to the import name (installed metadata, then the shipped mapping) |
| `PyPDF2` (case) | distribution names are normalized, import names are compared as written |
| A distribution in `[dependency-groups]` (PEP 735) | read as a declaration (3.18) |
| An installed module from a different distribution than the declared one | `phantom_member` reports `provider_conflict` instead of checking that distribution's names |
| Resolution errors | the pattern is unmeasured for the file (see Error policy), never "assume resolvable" |
| Python 3.8/3.9 (no `stdlib_module_names`) | Finder fallback covers stdlib; installed providers are read from dist-info files |

---

## Performance

The resolution index is built **once per process** and cached as a module-level
`frozenset`. Subsequent files share the same index with O(1) lookup per import.
The finder lookup is called only as a last resort, never for modules already in the index.

---

## Relationship to DDC (Dependency Density Check)

DDC measures the **ratio of imported packages that are actually used** in the file.
`phantom_import` is orthogonal — it observes whether **any provider of the import
is known** where the code runs.

| | DDC | PhantomImport |
|---|---|---|
| Question | "Is this import used?" | "Does any installed distribution, declaration or known provider supply this import?" |
| Signal | Noise / dead imports | Unresolved, undeclared, provider unknown (what an invented package name looks like; not proof of one) |
| Severity | LOW–MEDIUM | HIGH (at most) |
| Scope | Usage analysis | Resolution and declaration evidence |

A file can have low DDC (imports present but unused) AND phantom imports
simultaneously. Both contribute to the deficit score.

---

## Example Output

```
[HIGH] phantom_import — src/pipeline.py:4
  Phantom import: no installed distribution, dependency declaration or known
  provider supplies 'tensorflow_magic'
  Suggestion: Confirm which package 'tensorflow_magic' was meant to come from
  before installing or declaring anything: a name that can be found on a
  package index is not proof that it is the intended package. AI models
  sometimes generate plausible-looking package names.
```

---

## Disabling

To disable the pattern for a project:

```yaml
# .slopconfig.yaml
patterns:
  disabled:
    - phantom_import
```

To accept a module name that is known to exist where the code runs:

```yaml
# .slopconfig.yaml
phantom_import_allowlist:
  - platform_specific_pkg
```

To suppress one line, with a reviewable comment (a `# noqa` comment does not
suppress it, and is itself reported by `lint_escape`):

```python
# slop-disable-next-line phantom_import
import platform_specific_pkg
```
