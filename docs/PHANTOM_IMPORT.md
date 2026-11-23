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
project: a top-level name of the project's internal packages, a name in
`phantom_import_allowlist`, a module the project's module index resolves to an
actual file (`src/` layouts and namespace packages included), or, for a script
outside a regular package, a sibling `.py` file or package directory (the
script's directory is `sys.path[0]` when it runs). Inside a regular package
`import name` is absolute: a module or subpackage of that name next to the file
is not what it loads (only `from . import name` is), so it does not make the
import local (3.18; sibling directories since v3.10).

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
| In a module of a regular package that also runs as a script (a top-level `if __name__ == "__main__":`, or an absolute fallback `except ImportError: from x import ...` after `from .x import ...`), naming a sibling module or package | listed in `unverified_imports` (reason `depends_on_run_mode`, the sibling in `local_candidates`): imported, the module loads the distribution; run directly, the sibling | - |
| Runs after the file adds a directory to `sys.path` (earlier in its scope or an enclosing scope), and that directory is built from `__file__`, lies inside the scanned project and holds the module | no finding: the module is provided there | - |
| Runs after the file adds a directory whose real location (links resolved) is outside the scan boundary, or one in which the module's entry leads out | listed in `unverified_imports` (reason `out_of_boundary`, with `blocked_paths`), no score effect: that directory is not read | - |
| Runs after the file adds a directory that is not known statically (a relative string such as `"../"` or `os.getcwd()` depends on the working directory; a variable), and the project has a module or package of that name somewhere | listed in `unverified_imports` (reason `sys_path_modified`, with `local_candidates`), no score effect | - |
| Any other import after a `sys.path` change, and every import before the change or in a scope it does not precede | judged as usual; when a directory added before it is not known statically, the finding's `evidence.sys_path_unresolved` is `true` | as below |
| Declared only outside `pyproject.toml` project metadata (e.g. `requirements.txt`) while the file's nearest resolution root has a `pyproject.toml` | `declared_outside_primary_metadata` | LOW |
| Declared as a dependency but not installed in the target environment (or where the analyzer runs, when there is none) | `runtime_unavailable_dependency` | MEDIUM |
| Inside `try/except ImportError` and not declared | `undeclared_optional_dependency` | MEDIUM |
| Not declared, and a provider is known | `undeclared_dependency` | MEDIUM; HIGH only when the target environment's own files identify the one provider |
| Not declared, and no provider is known | `phantom_import` | HIGH |

An import under a platform test that is false in the target environment does
not run there and is not reported.

Two fields carry what a `sys.path` change leaves open:

- `evidence.sys_path_unresolved` (`true`, present only then): a directory the
  file adds before the import could not be seen. The verdict and severity
  stand; the field says the search path they rest on was not fully known. It
  is not evidence that no provider exists outside the project (a plugin
  directory from an environment variable, a separate checkout next to it).
- `local_candidates` on a `sys_path_modified` row in `unverified_imports`: an
  optional `list[str]` of sorted, unique POSIX paths relative to the root the
  project's module index was built from (the outermost resolution root: the
  scan root when it is a project root containing the file's own, otherwise
  the file's project root). A module is listed by its `.py` file
  (`tools/plugins/name.py`), a package or namespace directory by its
  directory (`tools/plugins/name`); a path whose real location is outside the
  project is left out. These are files and directories the project's layout
  could supply the import from, not modules shown to be the ones imported.

`evidence.same_named_sibling` (3.18): when a finding's file is inside a regular
package and a module or package of the import's name sits beside it, the
finding carries it (`path`, `kind` module/package/namespace_package, `sha256`
of the file or its `__init__.py`, `hash_state`, `relationship`
`SIBLING_IN_PACKAGE`, `verification_state` `CONTEXT_ONLY`). `hash_state` says
why a `sha256` is or is not there: `HASHED`; `NO_INIT` (a namespace package has
no file standing for it); `OUT_OF_BOUNDARY` (the file links out of the scan
root and is not read); `UNREADABLE`. The absolute import does not load it,
but the author may have meant it (`from . import name`); a wrapper module
named after the package it
wraps is the opposite case, where a relative import would import itself. The
verdict and score do not change.

A first-level directory that is itself a regular package is not a module root
(only a non-package directory holding packages is, as in a `backend/app`
monorepo): its subpackages do not answer an absolute import of their name
(3.18).

`evidence.related_declarations` (3.18) points whoever fixes a finding to
where else the project already declares the package. It appears on
`phantom_import`, `undeclared_dependency` and `undeclared_optional_dependency`
when a declaration file in another subtree of the project (not on the file's
own path, not inside an environment directory, not behind a link out of the
scan boundary) declares a distribution that could provide the import. Each
entry:

| Key | Meaning |
|---|---|
| `source_path` | The declaration file, POSIX path relative to the outermost resolution root |
| `line` | Present only when the file holds the name on exactly one line; otherwise not known and left out |
| `declared_distribution` | The name as written there |
| `match_basis` | `SAME_NAME` (the distribution's own name matches the import; not evidence that it provides it) or `KNOWN_PROVIDER` (installed metadata or the shipped mapping says it provides the import) |
| `provider_state` | The evidence state of that match (`NAME_CANDIDATE`, `MAPPING_SUPPORTED`, ...) |
| `marker` | The environment marker as written, when there is one |
| `relationship` | `OTHER_SUBTREE` |
| `verification_state` | `CONTEXT_ONLY`: a declaration for another part of the project is not this file's provider |
| `source_sha256` | SHA-256 of the declaration file's bytes |

The finding itself (pattern, severity, message, suggestion, score, identity)
is unchanged by it. Build requirements (`[build-system] requires`) are not
runtime declarations and are not listed.

### What is read: the scan boundary (3.18)

Import resolution reads the project only inside one boundary: the scan root
you pass (`slop-detector --project <root>`), or for a single file its project
root. Paths are compared by their real location, links resolved. A directory
or file link (a symlink, or on Windows a junction) is followed only when it
leads to a place inside the boundary. An alias keeps its own path (two links
to one package both resolve, and so does the original); a link back up its
own path (a cycle) is not walked again. One directory is walked through at
most 8 links besides its own path, which is always walked; this guard keeps
chains of aliases finite, and the aliases it stops are recorded in the
project snapshot rather than dropped. A link that leads out is not opened,
listed or tested: the module index, the project fingerprint, sibling modules,
`sys.path` directories, declaration files, the project's virtual environment
and the scan's file collection all stop there.

Not looking is not evidence that something is missing. An import that only
such a link could supply is listed in `unverified_imports` with reason
`out_of_boundary` and `blocked_paths` (the links, as POSIX paths relative to
the boundary; `../x` outside it), no score effect. The same holds for every
declaration-based verdict of a file when a declaration file on its path
(`requirements.txt`, `requirements/`, `pyproject.toml`, ...) is a link out, and
when the project's environment is: a link out named `.venv`, `venv`, `env`,
`.env` or `virtualenv` directly in the project root, with no environment
inside it. A link's target is part of the project fingerprint, so pointing it
elsewhere is a new cache context.

Link detection uses one check on Python 3.8 to 3.14: `S_ISLNK` for symlinks,
and on Windows the reparse-point attribute, which also covers junctions
(`os.path.islink` does not report a junction; `os.path.isjunction` exists only
from 3.12). Resolving where a link points reads the link's own metadata
(`lstat`, `realpath`); nothing behind a link that leads out is listed or
opened.

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
