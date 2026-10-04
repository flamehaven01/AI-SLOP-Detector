# Import Graph

**Current contract:** v3.9.0. This page describes what the
cross-file import graph does today. It is not a benchmark and it makes no accuracy claim.

## What it is for

The detector reads every Python file's import statements and resolves each one to a
project file when it can. That graph feeds:

- **import cycles** and **layer-boundary findings** (`sweep boundary-violations`),
- **`phantom_import`**, so a module that really exists in your project is not reported as
  a package that does not exist,
- **structure measures**: circular groups, most-imported files, and how far a change reaches.

Everything is reported in one block, `structure_evidence`. It does **not** change any slop
score or status, `import_cycles`, a sweep `verdict`, or its `issues`
(`score_effect` is always `"none"`), and a file that many others import is not a defect by
itself.

## Where it appears

| Surface | What you get |
|---|---|
| `slop-detector --project <dir> --cross-file` | Text summary: import resolution counts, import cycles, circular groups, most imported file, connection evidence summary with a few disconnected candidates |
| `slop-detector sweep <family> <dir> --json` (every family) | `summary.structure_evidence` |
| `CrossFileAnalyzer().analyze(...)` (Python API) | `import_graph` (unchanged), `import_edges` (one row per import), `structure_evidence` |

The default `scan`, `pulse`, `review`, and the MCP tools do not include this block.

## How project files are found

A dotted name such as `pkg.sub` is looked up under the project's **module roots**, in this order:

1. **Declared roots**: directories named in `[tool.setuptools.packages.find] where = [...]`
   in `pyproject.toml`.
2. **`src/`**, when it holds Python sources and has no `src/__init__.py` (a `src/` with an
   `__init__.py` is itself a package, so imports like `from src.x import y` resolve from the
   project root).
3. **The project root**, when nothing above applies (flat layout).
4. **First-level child directories that contain a package** (for example `backend/app/`).
   These are *conditional*: the module exists on disk, but whether it is importable depends on
   how the program is launched, so it is recorded but not treated as a dependency edge until
   you declare the root.

To include a conditional root, declare it:

```toml
[tool.setuptools.packages.find]
where = ["backend"]
```

On Python older than 3.11 the `tomli` package is installed with the tool to read this file.
If no TOML reader is available, a warning is logged and declared roots are not applied.

## How imports are read

Every `import` statement in a file is read, wherever it appears (including inside `if` and
`try`). Runtime conditions are not evaluated. Resolution follows Python's own rules:

- **Absolute imports** (`import a.b`, `from a.b import c`) are resolved one segment at a
  time. A module file shadows a same-named directory, so `foo.py` next to `foo/bar.py` does not
  make `import foo.bar` resolve. A module or package on any root wins over a namespace
  directory on another.
- **Relative imports** climb the *package* hierarchy, not the folder tree. A relative import
  that would leave the top-level package is not a link (Python raises `ImportError` for it).
- **`from pkg import name`** checks for an attribute called `name` in `pkg/__init__.py`
  first, and only then for a submodule `pkg/name.py`, as Python does. When `__init__.py`
  defines a module-level `__getattr__`, uses `import *`, or binds the name conditionally,
  the result is *ambiguous* and no link is made.
- **Namespace packages** (directories without `__init__.py`) are supported at any depth and
  across several declared roots.
- **Wildcard imports** link to the package.

Each import also has an **execution phase**:

| Phase | Meaning |
|---|---|
| `import_time` | Runs when the importing module is imported |
| `deferred_runtime` | Runs when a function containing the import is called |
| `type_only` | Inside `if TYPE_CHECKING:`; never runs, even inside a function |

Several imports between the same two files count once, at the strongest phase. A file
importing itself is ignored.

## Evidence coverage

Every import ends in one of these states, counted in `structure_evidence.coverage`:

| State | Meaning |
|---|---|
| `resolved` | Resolved to a project file; becomes a dependency link |
| `conditional_internal` | Found under a first-level child that is not a declared root |
| `ambiguous` | Python's rules cannot be decided statically (see above), or several undeclared roots provide the same name |
| `unresolved_internal` | Looks internal but no file was found (including a relative import past the top-level package) |
| `external` | Not part of the project (standard library or installed package) |

`evidence_complete` is `false` when any internal import is conditional, ambiguous, or
unresolved. Those imports are listed in `unknowns` (file, line, requested module and name,
state; the first 10 by file and line, with the full count in `totals.unknown_imports`). A
result of "no cycles" then covers resolved links only, and `--cross-file` says so instead of
reporting a clean result.

## Structure measures

`structure_evidence` also contains:

- **`circular_groups`**: groups of files that import each other in a loop, directly or
  through other files. Each group has:
  - `execution_phase`: the strongest phase in which **all** its files are still one loop. A
    group that needs a `TYPE_CHECKING` import to stay connected is `type_only`.
  - `inner_cycles`: stronger loops strictly inside the group, so a smaller import-time loop is
    not hidden by a weaker label on the whole group. The group's own phase is never promoted.
- **`dependency_hubs`**: files imported by the most other files (fan-in).
  **`dependency_load`**: files that import the most others (fan-out). Counts are distinct
  files and include all resolved links.
- **`change_reach`**: for the most-imported files, how many files depend on them directly or
  through others (`dependents`) and how many steps away the farthest one is (`max_depth`).
- **`totals`** and a short **`guide`** that explains each measure in plain words.

Lists keep the top 10 rows. High fan-in is normal for a core module.

`import_cycles` is unchanged: an ordered path such as `a.py -> b.py -> a.py`, built from
imports that actually run (it leaves out `type_only` links; function-level imports are included).
It is deterministic: each cycle starts at its smallest path and keeps its direction, the list is
sorted, and at most 20 cycles are kept.

## Classification

Every row says how to read it:

| `classification` | Rows | Meaning |
|---|---|---|
| `finding` | Circular groups and inner cycles whose phase is `import_time` or `deferred_runtime` | The structural view of an `import_cycle` already in `import_cycles` and in sweep `issues`. Carries `finding_kind: "import_cycle"`. Never a second finding. |
| `context` | `type_only` circular groups, `dependency_hubs`, `dependency_load`, `change_reach` | Description, not a problem. Creates no issue. |
| `unknown` | `unknowns` | An internal import that could not be checked. |

Count findings from `import_cycles` or `issues`, not from `structure_evidence`.

## Connection evidence (`--cross-file` only)

`structure_evidence.connections` says, for every top-level function and class in a
non-test file, what connects it to the rest of the code. It is computed only by
`--cross-file` (or `CrossFileAnalyzer().analyze(..., connections=True)`); the default scan,
`sweep`, and the MCP tools never run it. It creates no finding and changes no score or
status (`score_effect: "none"`). Methods are not evaluated.

Evidence is kept by kind:

| Kind | Meaning |
|---|---|
| `direct_call`, `direct_reference` | The name is called or used (passed, subclassed, annotated) in another place. An import alone is not a use, and a symbol's own body does not count. |
| `registry_reference` | The name is an entry of an assigned dict, list, tuple, or set. |
| `decorator_registration` | A decorator that registers with a framework: `route`, `get`/`post`/..., `command`, `group`, `task`, `register`, `fixture`, `hookimpl`, and a few more (a leading `_` is ignored). `@dataclass`, `@property`, `@lru_cache` and similar are evidence of nothing. |
| `public_export` | Listed in `__all__`. |
| `package_reexport` | Bound by a package `__init__.py` (read even when the scan skips `__init__.py`). |
| `pyproject_script`, `pyproject_entry_point` | Named by `[project.scripts]`, `[project.gui-scripts]`, `[project.entry-points]`, or the Poetry equivalents. |

One state per symbol, the first that applies:

| `state` | When |
|---|---|
| `connected` | Any of the first four kinds. Every other kind found is kept beside it. |
| `externally_exposed` | No internal connection, but an export, re-export, script, or entry point. |
| `dynamic_unknown` | The code can reach the name in a way static reading cannot follow: an unknown decorator, `getattr` with a computed name, `importlib`/`__import__`, `globals()`, a module `__getattr__`, `eval`/`exec`, a package scan through `__path__`, a module object stored and used through attributes, a string equal to the name, or a dotted string naming the module. |
| `unmeasured` | Evidence this symbol needs was not collected: an unresolved import, or one that resolves only with part of the project on `sys.path` (a script directory, an app root, a plugin's `src`), an unparsed file, or an unreadable `pyproject.toml` that may name it. |
| `disconnected_candidate` | The collectors ran and found none of the above. |

`dynamic_unknown` and `unmeasured` are local to the symbol: an unresolved import elsewhere
that cannot name it changes nothing. `test_referenced` records a use from a test file and
never changes the state; `summary.test_files_seen` says whether any test file was in the scan
(the default configuration excludes `tests/`). Each row carries `reasons` for the dynamic and
unmeasured states and up to five evidence sites (`evidence_counts` has the totals).

A disconnected candidate is a question for a person, not a verdict. It does not see:

- code generated or run from strings (a hook script written from a template),
- names loaded by another program from configuration (a framework that imports a connector
  class named in its settings),
- public library API that nothing in the repository calls, when there is no `__all__`,
- uses from files outside the scan, such as tests under the default configuration,
- a local variable that shadows a top-level name (it reads as a use, so the error leans toward
  `connected`).

## Example

A project where `a` and `b` import each other, `c` imports `a` only under `TYPE_CHECKING`,
and all three import `core`:

```text
[Cross-File Analysis]
  Files: 4
  Imports: 7 resolved, 0 conditional, 0 ambiguous, 0 unresolved internal

  Import Cycles (1):
    a.py -> b.py -> a.py

  Circular Groups (1):
    3 files, type-checking only: a.py, b.py, c.py
      inner import-time cycle: a.py, b.py
  Most imported: core.py (3 files)

  Connections (0 top-level functions/classes): 0 connected, 0 exposed, 0 dynamic, 0 unmeasured, 0 disconnected candidates
```

A monorepo whose `backend/app/` is not declared:

```text
[Cross-File Analysis]
  Files: 2
  Imports: 0 resolved, 1 conditional, 0 ambiguous, 0 unresolved internal
  [!] No cross-file issues among resolved imports; 1 internal imports (conditional, ambiguous or unresolved) were not checked.
      To include conditional ones, declare the module roots in pyproject.toml: [tool.setuptools.packages.find] where = [...]

  Connections (1 top-level functions/classes): 0 connected, 0 exposed, 0 dynamic, 1 unmeasured, 0 disconnected candidates
```

The one function, `ping`, is called through the undeclared import, so it is `unmeasured`
rather than a disconnected candidate.

For the first project, `sweep boundary-violations --json` gives `verdict: "fail"` with one
`import_cycle` issue and this `summary.structure_evidence`. In the real output paths are
absolute; here lists are cut to their first row and `guide` is left out:

```json
{
  "evidence_complete": true,
  "coverage": {"resolved": 7, "conditional_internal": 0, "unresolved_internal": 0,
               "external": 1, "ambiguous": 0},
  "unknowns": [],
  "circular_groups": [
    {"files": ["a.py", "b.py", "c.py"], "size": 3, "execution_phase": "type_only",
     "classification": "context", "score_effect": "none",
     "inner_cycles": [
       {"files": ["a.py", "b.py"], "execution_phase": "import_time",
        "classification": "finding", "finding_kind": "import_cycle", "score_effect": "none"}
     ]}
  ],
  "dependency_hubs": [{"file": "core.py", "count": 3, "classification": "context"}],
  "dependency_load": [{"file": "a.py", "count": 3, "classification": "context"}],
  "change_reach": [{"file": "core.py", "dependents": 3, "max_depth": 1,
                    "classification": "context"}],
  "totals": {"files": 4, "links": 7, "components": 1, "import_time_components": 1,
             "unknown_imports": 0},
  "score_effect": "none"
}
```

The whole group is `type_only`: it is one loop only through `c`'s `TYPE_CHECKING` import, so
it is context. The `a`/`b` loop inside it runs at import time, so it is the finding, and it is
the same cycle as the single `import_cycle` issue.

## What it does not see

- Imports made at run time by string: `importlib.import_module(...)`, `__import__(...)`,
  plugin loading by name.
- Changes to `sys.path`, `.pth` files, or `PYTHONPATH`. Only roots declared in `pyproject.toml`
  and the layouts above are considered.
- Conditions: an import inside `if sys.platform == ...` counts as a statement whether or not
  it would run.
- Other languages. The graph covers `.py` files only; JS/TS and Go files are not part of it.
- Whether a dependency structure is good. The measures do not judge design.

## When upgrading

- Projects whose graph used to be nearly empty (many `src/`-layout projects scanned from the
  project root) can now report `import_cycle` and `layer_boundary_violation` findings, and
  `sweep boundary-violations` can return `verdict: fail` with no change in the code. The
  command's exit code is unchanged. Check `structure_evidence.evidence_complete` and
  `coverage` before suppressing a new finding.
- `phantom_import` no longer fires on working namespace-package imports, or on a top-level
  module file of a module root imported from another directory. Imports of names that exist
  under no module root are still reported.
- Imports under an undeclared first-level child (`backend/app/...`) stay silent for
  `phantom_import`, as before, but are not dependency links until the root is declared.

## Related

- [HOW_IT_WORKS.md](HOW_IT_WORKS.md): scoring and pattern overview
- [PHANTOM_IMPORT.md](PHANTOM_IMPORT.md): the `phantom_import` pattern
- [CONFIGURATION.md](CONFIGURATION.md): `architecture` layer rules used by `boundary-violations`
- [API.md](API.md): local API surface
