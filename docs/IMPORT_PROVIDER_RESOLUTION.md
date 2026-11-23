# Import Provider Resolution

**Status: implemented in v3.18.0.** Sections 1-7 are the design
as written before the code; where a paragraph says "today" it describes v3.17.
Sections 8 and 10-12 describe what v3.18.0 implements. The finding contract is
also in [PHANTOM_IMPORT.md](PHANTOM_IMPORT.md). Not yet done: an evaluation on
labeled projects that played no part in building it (section 11).

**Release boundary.** v3.18.0 ships the provider resolver, its verdict contract
(finding IDs, severities, messages, suggestions, JSON fields) and the tests
that hold it. The new MCP server and the agent collaboration loop that consume
these verdicts are v3.19.0; section 9 is policy for that release, not 3.18
behavior.

**Scope:** `phantom_import`, `phantom_member` and the import-evidence findings
next to them (`runtime_unavailable_dependency`, `undeclared_optional_dependency`,
`declared_outside_primary_metadata`, and the new `undeclared_dependency` and
`provider_conflict`). Python only.

---

## 1. Summary

Through v3.17, `phantom_import` is reported as CRITICAL because of what it is meant to catch:
an import of a package that an AI model invented. That claim is strong. What the
rule checks today is weaker: "this import does not resolve in the analyzer's
own environment, and no declaration of the project has the same name". Between
the claim and the check there is a missing piece of evidence, and every false
positive described below falls into that gap:

> **Which distribution provides this import name, and what shows that this
> distribution is present where the analyzed code runs?**

A distribution name (`Pillow`) and the name you import (`PIL`) are different
things. An environment that is present (the analyzer's) and the environment
the code is written for (the project's) are different things. Today the rule
links them by string equality and by whatever the analyzer happens to have
installed. This design replaces that link with an explicit **provider
resolution** step that records where each piece of evidence came from and
allows a strong verdict only when the evidence covers the claim.

## 2. Three claims that one rule mixes

| Claim | What would prove it | Right fix | Who can act safely |
|---|---|---|---|
| C1. The import does not resolve **in the target environment** | The target environment's installed files | Install the declared dependency | A person or CI that controls that environment |
| C2. The project **does not declare** the distribution that provides it | The provider's name, compared with the declarations | Declare the provider | A person who has confirmed which distribution is meant |
| C3. **No legitimate package provides it** (a hallucinated name) | Knowledge of the package ecosystem | Remove or replace the import | The author, after checking |

Each claim needs different evidence and calls for a different fix. Reporting
all three under one ID with one severity has two consequences:

- the severity of C3 is attached to findings that only establish C1 or C2;
- an agent that follows the finding applies the C2 fix ("declare it") where the
  C1 fix or the C3 fix was needed.

The second consequence is a supply-chain problem, not only an accuracy one. A
model that invents a package name tends to invent it again, and an attacker can
publish a package under that name ("slopsquatting"; Spracklen et al. measured
at least 5.2% hallucinated packages for commercial models and 21.7% for
open-source models, USENIX Security 2025). Today the suggestion of
`phantom_import` reads *"Verify '<name>' exists on PyPI and add it to
[project.dependencies]"*. A name that exists on PyPI is not proof that it is
the intended package: that a name exists is exactly what an attacker arranges
by publishing it. An agent loop that runs "declare it, install it, rescan" on
that advice runs the attack for the attacker.

## 3. Failure classes

Every example below is reproducible with a two-file project (a `pyproject.toml`
and one module) and an analyzer environment that does not have the package
installed. That is the situation of a CI job or an agent sandbox that has not
installed the project's dependencies.

### F1. The distribution name differs from the import name

```toml
dependencies = ["Pillow", "scikit-learn", "absl-py", "dm-haiku",
                "beautifulsoup4", "biopython", "PyOpenGL", "py-cpuinfo"]
```
```python
import PIL, sklearn, absl, haiku, bs4, Bio, OpenGL, cpuinfo
```

All eight are declared. Today each is reported as `phantom_import` CRITICAL
("not declared anywhere"), because the declaration-to-import step
(`_dependency_import_names` in `patterns/python_imports.py`) knows two aliases
(`grpcio` -> `grpc`, `pyyaml` -> `yaml`) and otherwise assumes the import name
equals the distribution name. The pattern's own contract says a declared but
unavailable import is `runtime_unavailable_dependency` (MEDIUM). When the
package is installed, the finding disappears, because the installed metadata
answers first; the defect is visible only where dependencies are not installed.

### F2. Case: distribution names are normalized, import names are not

With `PyPDF2` declared, today:

```python
import PyPDF2   # correct import      -> phantom_import CRITICAL
import pypdf2   # fails at runtime    -> runtime_unavailable_dependency MEDIUM ("declared")
```

The verdicts are inverted. The declaration side lowercases names (`pypdf2`)
and the import side does not, so the correct import is accused and the wrong
one is excused as declared.

Distribution names compare after PEP 503 normalization (case-insensitive, runs
of `-`, `_`, `.` are equal). Import names are case-sensitive identifiers. The
fix is to normalize **distribution names only** and keep import names exactly
as written. Lowercasing both sides would make `import pypdf2` (which fails at
runtime) match a declaration of `PyPDF2`.

### F3. Namespace packages

`google-generativeai` provides `google.generativeai`, a portion of the shared
namespace `google`. Matching on the top-level name alone cannot tell which of
the many `google-*` distributions provides the import, and a mapping that
assigns `google` to one distribution would mark every other `google.*` import
as provided by it. Namespaces have to be matched on the shortest name a
distribution owns exclusively (PEP 794 states this rule; the pyproject-udeps
mapping follows it).

### F4. Two distributions provide the same import name

```toml
dependencies = ["jwt>=1.3.1,<2"]
```
```python
from jwt import JWT, jwk_from_pem
```

The project declares the distribution `jwt`, which defines `JWT` and
`jwk_from_pem`. If the analyzer environment has the unrelated distribution
`PyJWT` installed (it also provides the module `jwt`), `phantom_member` reads
PyJWT's source and reports both names as HIGH "not defined in 'jwt'". The
message even names the wrong distribution: `(installed PyJWT 2.x)`. Nothing
checks that the installed provider is the declared one. This is an instance of
a known ecosystem-wide class: ModuleGuard (ICSE 2024) studies module conflicts,
where different PyPI packages install the same module names.

### F5. The analyzer environment is not the target environment

The same input gets a different verdict depending on what the analyzer has
installed. Measured with the 3.17.0 source (`PYTHONPATH` set to the same
source tree in both runs) on two virtual environments of the same interpreter
(CPython 3.14.10): environment A has `PyJWT` and `black` installed,
environment B has neither. Each case is one module (`import <name>` and one
function with a docstring and a `return`) and a `pyproject.toml` beside it;
the files are byte-identical between the two runs. Command:
`scan <module> --json --read-only`.

| Declared | Import | Environment A | Environment B |
|---|---|---|---|
| `PyJWT` | `jwt` | no finding, `deficit_score` 0.0 | `runtime_unavailable_dependency` MEDIUM, 2.0 |
| `black` | `black` | no finding, 0.0 | `runtime_unavailable_dependency` MEDIUM, 2.0 |
| `black` | `blib2to3` (a second top-level name of `black`) | no finding, 0.0 | `phantom_import` CRITICAL, 14.88 |

The first two rows are the documented behavior (declared, not installed where
the analyzer runs). The third is F1 again, now caused by the environment alone:
with `black` installed, its metadata shows that it provides `blib2to3`;
without it, the declaration is not linked to the import and the same code is
reported as importing something that is declared nowhere.

What a CRITICAL costs in the score depends on the file. For scale, another
module (one import and `def total(values)` returning `sum(values)`) scored 84.15 with an installed and
declared import, 86.15 with a declared import that is not installed (MEDIUM),
and 94.92 with an undeclared one (CRITICAL). Those three runs differ in their
input, not only in the environment, so they show the weight of each finding,
not the effect of the environment.

The analysis cache already treats import evidence as environment-dependent (its
key includes an environment fingerprint, `core.py`), but scores, gates and
reports do not say which environment they were measured in. A CI job without
dependencies and a developer machine with them can reach different verdicts on
the same commit.

### F6. One cause, many findings

A missing declaration of one distribution produces one finding per importing
line, across every file. The fix is one line in one declaration file. Counting
each import as a separate CRITICAL inflates the score and the work order with
a single cause.

### F7. A declaration format the analyzer does not read

```toml
[dependency-groups]
scripts = ["scikit-learn>=1.7.2"]
```

PEP 735 dependency groups are a standard place to declare dependencies (uv
writes development dependencies there). Today `pyproject.toml` is read for PEP
621 dependencies and optional dependencies and for Poetry tables, not for
`[dependency-groups]`, so an import of a dependency declared only in a group is
reported as declared nowhere (`phantom_import` CRITICAL), even when the
distribution and import names are equal. This class was found by comparing
the analyzer with an independent reading of the declaration files, not by
reading the analyzer's code.

## 4. Two fixes that do not work

**Grow the alias table.** It helps F1 and does nothing for F3, F4 or F5. A
hand-written table is the last-resort strategy of other tools (FawltyDeps calls
it identity mapping, and resolves through the installed environment first). It
also goes stale.

**Withhold the verdict whenever any declaration is unmapped.** The idea: if a
declared distribution's import names are unknown, it might provide the
unresolved import, so absence is not proven. The rule is sound but takes
unrelated evidence as relevant: a declaration of `requests` with unknown import
names is no evidence that it provides `nonexistent_ai_module`. One
declaration whose import name differs from its distribution name (a framework
declared as `langchain` and imported as `langchain_core`) is enough to
withhold every unresolved import of the project, the true ones included.
Applied to real projects, the rule shows how sensitive the verdict is to the
burden of proof, not how accurate it is.

## 5. Principle

Two boundaries carry the design:

1. **Presence of evidence strengthens a link; absence of evidence does not
   prove absence.** Metadata that says "distribution D provides import name X"
   is positive evidence. No metadata saying so is not proof that D does not
   provide X. PEP 794 says the same of its own fields: a missing field means
   "no information", and tools "should treat the metadata as potentially
   inaccurate".
2. **Mapping knowledge is not presence.** That the analyzer's environment has
   `Pillow` installed shows that the distribution `Pillow` provides `PIL`. That
   is knowledge about the distribution, usable for any project. It does not
   show that `Pillow` is installed where the analyzed project runs. The
   analyzer environment answers "who provides X", never "is X present for this
   project".

A strong verdict (CRITICAL, HIGH) is allowed only when the evidence for it is
bound to the target: the target's declarations and, where the claim is about
the environment, the target's environment.

## 6. Evidence ladder

Evidence about **which distribution provides an import name**, strongest first.
Each source is read without importing or executing anything.

| Rank | Source | Conclusion it allows | Provider state |
|---|---|---|---|
| 1 | The target environment's installed files: `*.dist-info/RECORD` and `top_level.txt`, matched to the module file on disk | This distribution, at this version, provides this import name here | `ARTIFACT_VERIFIED` |
| 2 | PEP 794 metadata: `Import-Name` / `Import-Namespace` (core metadata 2.5) of an installed distribution, and the project's own `[project] import-names` / `import-namespaces` | The distribution states that it provides the name | `METADATA_DECLARED` |
| 3 | A wheel the user supplies, or a wheel already in a local cache, bound to name, version and hash | That artifact provides the name | `ARTIFACT_VERIFIED` (for that artifact) |
| 4 | Installed metadata of the analyzer environment (`importlib.metadata.packages_distributions()`), and a mapping table shipped with the tool, generated offline from wheel contents | The distribution is known to provide the name (mapping knowledge only, see principle 2) | `MAPPING_SUPPORTED` |
| 5 | Name similarity, prefixes (`python-`, `py`), `-` to `_` | A candidate to look up; never the basis of CRITICAL or HIGH | `NAME_CANDIDATE` |

When two sources disagree (rank 1 says the installed `jwt` comes from `PyJWT`,
the declaration names `jwt`), the state is `PROVIDER_CONFLICT`. When none
applies, the state is `PROVIDER_UNKNOWN`.

Notes on each rank:

- **Rank 1, "target environment"** is the project's own environment when the
  tool can identify one without guessing: a virtual environment inside the
  project root (a directory with `pyvenv.cfg`), or an interpreter or
  environment path the user configures. It is read as files; it is never
  activated, imported from, or trusted as code. With no target environment, the
  analyzer environment is used for rank 4 only, and claims of kind C1 are
  reported as "not installed where the analyzer runs" (the current wording of
  `runtime_unavailable_dependency`), not as facts about the project.
- **Rank 2** is written by package authors and cannot be validated
  programmatically (PEP 794, Security Implications). It ranks below the files
  themselves.
- **Rank 3, caches.** pip and uv caches can hold wheels, but their layout is
  internal to each tool and changes between versions. A cache is a place to
  look for an artifact, not an interface. Reading it is optional and must not
  be required for any verdict.
- **Rank 4, shipped table.** Generated by a separate audit step that reads the
  file lists of wheels (pyproject-udeps does this for the 5,000 most-downloaded
  PyPI packages by range-reading each wheel's ZIP central directory; Bazel
  `rules_python` generates a `modules_mapping` manifest from wheels). The audit
  needs the network; the shipped table and every scan do not. The table lives
  in configuration (Config-First), records its generation date and source, and
  maps namespace portions at their shortest exclusive name.

## 7. Declared versus active

"Is a provider declared?" and "is it active in the target environment?" are
separate questions.

- **Declaration evidence** keeps every declared distribution with its source:
  main dependencies, optional dependencies (extras), dependency groups, and
  requirement files, each labelled. Any of them counts as "declared".
- **Activation evidence** evaluates environment markers and extras for the
  target environment, when it is known: `pywin32; sys_platform == "win32"` is
  inactive on Linux, so its absence there is expected and is not a finding. An
  optional dependency is not assumed to be installed.

Implemented (3.18.0): the target platform and Python version come only from
the target environment's files. A `Lib/site-packages` layout establishes
Windows; a `lib/pythonX.Y/site-packages` layout establishes POSIX (so "not
Windows", while which POSIX platform stays unknown); `pyvenv.cfg` gives the
Python version. With no target environment they are unknown: the analyzer's
own platform is not evidence about where the analyzed code runs. A marker that
cannot be decided is `UNKNOWN` (the declaration still counts as declared). An
import under a platform test the target does not decide is listed in
`unverified_imports` (reason `platform_guard_undecided`, no score effect), not
reported. `environment` (where provider evidence came from) and
`target_platform` / `marker_evaluation` (what the markers were evaluated for)
are separate fields.

## 8. Verdicts

For an import the project does not provide itself:

| Situation | Finding | Severity | Auto-fix allowed |
|---|---|---|---|
| Resolves in the target environment, provider matches the declaration | none | | |
| Under a platform test the target environment does not decide | `unverified_imports` entry `platform_guard_undecided` | no score | No |
| Provider declared; not installed in the target (or the analyzer, if no target) | `runtime_unavailable_dependency` (existing; `declared_outside_primary_metadata` LOW when declared only outside `pyproject.toml`) | MEDIUM | No: environment action |
| Provider known, **not declared**, one provider identified from the target environment's own files | `undeclared_dependency` naming the provider | HIGH | No: a person confirms the provider's identity |
| Provider known only from mapping knowledge (shipped table, analyzer metadata), or several providers known | `undeclared_dependency`; several: no provider named, `candidates` listed | MEDIUM (review candidate) | No |
| Provider unknown to every source, not declared, not resolvable | `phantom_import` | HIGH (at most, 3.18; see below) | No: the author removes, replaces or confirms the import |
| Under `if TYPE_CHECKING:` | `unverified_imports` entry (`type_checking_only`) | no score | No |
| After a `sys.path` change in its scope that adds a directory not known statically, and the project has a module of that name | `unverified_imports` entry (`sys_path_modified`, `local_candidates`) | no score | No |
| After a `sys.path` change that adds a `__file__`-based directory holding the module | none (provided there) | - | - |
| Inside `try/except ImportError` | `undeclared_optional_dependency` (existing) | MEDIUM | No |

`phantom_import` becomes narrower: it is reported only for the last observable
state, **no evidence source the tool has knows a provider for this name**. That
is what a hallucinated name looks like, but it is not proof of one: a real
package that is new, rare, private, or absent from the shipped table looks the
same. The tool can establish "unresolved, undeclared, provider unknown"; it
cannot establish "no legitimate package exists". So:

- the message states what was observed (no installed distribution, no
  declaration and no mapping entry provides the name), never "does not exist";
- the suggestion stops saying "add it to dependencies" and says: confirm which
  package was meant before installing or declaring anything;
- its severity is HIGH, at most (3.18). On labeled projects not used to build the
  resolver, most imports in this state were real, undeclared dependencies, and
  invented names and real but unmapped packages were indistinguishable. CRITICAL
  would need evidence the static analysis does not have (the import failing in
  the target environment, with its consequence); that is left to a future
  design, not inferred.

For `phantom_member`:

| Provider state of the module | Finding |
|---|---|
| Installed provider is the declared provider (or nothing is declared and the provider is known) | `phantom_member` HIGH, as today |
| `PROVIDER_CONFLICT`: installed provider differs from the declared one | no HIGH; `provider_conflict` MEDIUM naming both distributions, reported as environment evidence |
| `PROVIDER_UNKNOWN` | listed in `unverified_imports` (existing channel, no score effect) |

**Score contract (`SCORE_CONTRACT_VERSION = "3.18"`, `core_scoring.py`).**
Severity weights are unchanged, and every finding is still reported. Three
rules decide which findings add to the pattern penalty (`_scored`). One is not
part of this contract: since 3.10.0, a `deep_nesting` finding at the location
of a `nested_complexity` finding (the same function) adds nothing, because
`nested_complexity` is that deep nesting plus a complexity condition; 3.18 only
moved it next to the two rules it adds for provider findings:

- `provider_conflict` seen only in the analyzer's environment adds nothing: an
  analysis environment that differs from the project's is not a defect of the
  code;
- `undeclared_dependency` counts once per (file, provider): one missing
  declaration is one cause, however many lines import it. Every location stays
  in the finding list.

- `phantom_import` is HIGH, at most (it was CRITICAL through 3.17). This is a
  change of the finding's severity, not of a weight, so every consumer of
  CRITICAL changes with it: the CI gate's `critical_patterns_fail`, purity,
  `has_critical`, history and governance no longer see a `phantom_import` as
  CRITICAL. The score changes by the HIGH/CRITICAL weight difference per
  finding. That lower score reflects a weaker claim (no provider known), not
  fewer defects, and is not reported as an improvement.

Scores therefore differ from 3.17 where these findings occur; a finding that
did not change keeps its weight. The contract version is `3.18`, released with
3.18.0; the `phantom_import` severity was changed under it before that release.

**Compatibility.** Existing pattern IDs keep their meaning; new situations get
new IDs (`undeclared_dependency`, `provider_conflict`). Every import-evidence
finding carries `evidence` in the JSON (`import_name`, `provider`,
`provider_state`, `environment`, `target_platform`, and `marker_evaluation` or
`candidates` where they apply); a finding of any other rule serializes exactly
as before. The keys are fixed by `tests/test_import_provider_resolution.py`.

## 9. Agent loop rules (policy for v3.19.0)

These rules bind the v3.19.0 agent integration, which hands findings to coding
agents. v3.18.0 implements only what they rely on: the provider states in the
JSON and the changed suggestions. For import evidence:

1. No dependency finding is an automatic fix. Installing or declaring a
   package is a supply-chain action and needs a person's approval.
2. The tool never installs anything to verify a finding. A provider is
   established from files that are already there (ranks 1-4), or the finding
   stays unverified.
3. The work order explains the evidence: which distribution provides the name,
   what is declared, what is installed where, and what therefore is or is not
   needed. "Install the package" without that is not an instruction the tool
   gives.
4. A finding that disappears after a change is checked like any other: a
   removed import, a suppression or a narrowed scan scope is not a fix.

## 10. Falsification plan

The implementation starts from failing tests, and the new resolver first runs
read-only beside the current one (a shadow evaluation) on a frozen set of real
projects, with results compared per finding before any verdict changes.

### Controls (each must fail before the change and pass after)

| Control | Expected after the change |
|---|---|
| R1. F1 project, packages not installed | each import: `runtime_unavailable_dependency`, not `phantom_import` |
| R2. `PyPDF2` declared and imported | not `phantom_import` |
| R3. `import pypdf2` with `PyPDF2` declared | not excused as declared (today: MEDIUM "declared"); no source provides the import name `pypdf2` |
| R4. `google.generativeai` with `google-generativeai` declared; a second `google-*` declared | each import attributed to its own provider, none to the other |
| R5. `jwt` declared, `PyJWT` installed in the analyzer | no `phantom_member` HIGH; provider conflict reported with both names |
| R6. Same as R5, the declared `jwt` installed in a target environment that lacks a name | `phantom_member` HIGH remains |
| R7. A name no source knows, undeclared | `phantom_import` remains (its severity is the section 11 contract) |
| R8. A known provider, undeclared | undeclared-dependency finding naming the provider; not CRITICAL |
| R9a. `pywin32; sys_platform == "win32"` declared, `import win32api` inside `if sys.platform == "win32":` | POSIX target: no finding; Windows target: `runtime_unavailable_dependency` (marker ACTIVE); no target: no finding, an `unverified_imports` entry `platform_guard_undecided` |
| R9b. Same declaration, `import win32api` at module level | POSIX target: reported (the import runs where its only provider is inactive; marker INACTIVE); no target: marker UNKNOWN, reported as declared but unavailable |
| R9c. `zz-backport; python_version < "3.8"` | marker evaluated for the target's Python from `pyvenv.cfg` (3.11: INACTIVE, 3.7: ACTIVE); no target: UNKNOWN |
| R10. A project with every dependency installed | every field the current JSON has keeps its value and every finding keeps its ID, severity and location; new provider-state fields are checked separately for correctness (not a byte comparison of the whole output) |
| R12. A dependency declared only in `[dependency-groups]`, same name and another name (`scikit-learn` -> `sklearn`) | `runtime_unavailable_dependency` naming the provider, not `phantom_import` |
| R11. Byte-identical project scanned in two environments (the F5 cases) | the provider state names which environment it came from, and with a target environment configured the verdict is the same in both |
| R13. A target environment's METADATA edited in place (same dist-info directory and version) | a new context: the cache is keyed by the content of the files read, not the directory listing |
| R14. Target environment without the module, analyzer environment with it | not checked against the analyzer's copy; declared but unavailable in the target |
| R15. `import cv2` / `import faiss` undeclared (several known providers) | no provider named, `candidates` listed, MEDIUM |
| R16. Score contract | an analyzer-only `provider_conflict` adds 0; `undeclared_dependency` adds once per (file, provider) |
| R17. `[tool.uv] dev-dependencies` (same name, another name) | declared: `runtime_unavailable_dependency` |
| R18. `[build-system] requires` | declares for the `setup.py` beside the `pyproject.toml`, not for the package's modules |
| R19. A name no source knows | `phantom_import` HIGH |
| R20. Imports under `if TYPE_CHECKING:` / `typing.TYPE_CHECKING` | unverified `type_checking_only`; the `else` branch is judged |
| R21. A `sys.path` change | only the imports after it in its scope are unverified (`sys_path_modified`) |
| R23a. `sys.path.append("../")`, then a name no project file has | judged as before (the working directory is never assumed) |
| R23b. A `__file__`-based directory holding `foo` | `foo` provided there; other imports judged as before |
| R23c. A `__file__`-based directory without the module | judged as before |
| R23d. An import before the change | judged as before |
| R23e. A change inside a function | imports of the enclosing scope judged as before |
| R23f. A directory not known statically, a name the project has | unverified, `local_candidates` lists the project files; kept after a cache round trip |
| R23g. A `__file__`-based path out of the scan boundary | not opened or listed; unverified (`out_of_boundary`) for a name present there or not |
| R23h. A directory, or its entry for the module, that is a link out of the scan boundary | not read through; unverified (`out_of_boundary`) |
| S1a. A link in the project to a package outside | not in the module index or the fingerprint; the import is unverified (`out_of_boundary`) |
| S1b. A link that stays inside | followed; the package resolves as before |
| S1c. A deeper link out inside a namespace package | not walked; unverified |
| S1d. A link cycle | each real directory walked once |
| S1e. A link pointed elsewhere | a new fingerprint |
| S1f. Direct lookups (probe_module, `__init__.py`, the top-level name test) | refuse a link out |
| S1g. A script's sibling that is a link out | not a sibling module; unverified |
| S1h. A declaration file or `requirements/` that is a link out | not read; the file's declaration-based verdicts are unverified |
| S1i. The project's `.venv` as a link out | not read; verdicts that rest on presence are unverified |
| R23i. `sys_path_unresolved` | only on findings after a directory not known statically; not after a resolved one, before a change, or in another scope; kept after a cache round trip |
| R24a/b. A declaration of the import in another subtree | listed in `related_declarations` (`SAME_NAME` or `KNOWN_PROVIDER`, `CONTEXT_ONLY`); the finding unchanged |
| R24c. Declared on the file's own path | declared (no finding to inform), nothing listed |
| R24d. Several subtrees, markers, a name on more than one line | one entry per file, marker as written, no line when ambiguous |
| R24e. With and without the other declaration | identical finding and score |
| R24f. The other declaration edited | the next analysis lists the new one |
| R24g/h/i. Behind a link out, build-only, inside an environment directory | not listed |
| R25a/f. A sibling module or subpackage of the same name inside a regular package | no evidence: the absolute import is judged as external |
| R25b/c. `from . import name`; a sibling in a script directory | not judged / local, as before |
| R25d. The same under `TYPE_CHECKING` | unverified `type_checking_only` |
| R25e. A package module with a `__main__` block | unverified `depends_on_run_mode`, the sibling as candidate |
| R25g. A package module without one | absolute import (package membership is the default reading, not proof of how it runs) |
| R25h. `try: from .x import f / except ImportError: from x import f` | the fallback is unverified `depends_on_run_mode` when x is a sibling; judged otherwise |
| R25i. Python itself (synthetic package, run both ways) | runs directly: the sibling loads; `python -m`: it does not |
| R25j. The relative module itself fails to import | the cause is reported in that module; the fallback stays unverified |
| R26a. A first-level regular package holding subpackages | not a module root: its subpackages do not answer an absolute import |
| R26b. A non-package directory holding a package (`backend/app`) | a conditional module root, as before |
| R27a/b. A same-named module or package beside a package file | listed in `same_named_sibling` (`CONTEXT_ONLY`); verdict and score unchanged (R27c) |
| R27d. The same-named sibling is a namespace package | `kind` `namespace_package`, `hash_state` `NO_INIT`, no hash |
| R27e. The sibling's `__init__.py` links out of the scan root | not opened: no hash, `hash_state` `OUT_OF_BOUNDARY` (needs file-symlink rights) |
| R26c. A first-level `__init__.py` that is a link | the entry marks the package; the link is not followed (needs file-symlink rights) |
| R22. A provider from the shipped mapping | evidence carries the entry's `mapping_audit` |

### Experiments on the frozen set

| Experiment | Hypothesis | Fails if |
|---|---|---|
| A. Metadata first | Ranks 1-2 attribute providers more accurately than the alias table | a provider is missed or attributed to the wrong distribution |
| B. Target binding | Checking the installed provider removes provider-conflict false positives | a correct member finding is lost |
| C. Activation | Evaluating markers and extras removes environment-only findings | an inactive dependency is treated as active |
| D. Detection kept | Fewer false positives without losing true unresolved imports | true findings turn into "unverified" |
| E. Reuse | A provider index built once per (environment, metadata state) keeps large scans fast | output or scan coverage changes, or no speed gain |

Results are reported per measure, never merged into one accuracy number:
confirmed false positives removed, true findings kept, new "unverified"
verdicts, run time, cache agreement, and agreement between two environments
(with and without dependencies installed).

## 11. Open decisions

Decided for 3.18.0: the severity of an undeclared known provider and of
`phantom_import` (at most HIGH), the score rules (section 8), the source of the
target platform (section 7), and the scope of "a pyproject.toml exists" for
`declared_outside_primary_metadata`: the file's nearest primary resolution root,
not any ancestor directory. Open:

- **Explicit target.** Only a virtual environment directly inside a project root
  is discovered; a configuration key for an explicit environment path or
  platform (including "the analyzer is the target") does not exist yet.
- **Shipped mapping table.** Hand-curated; a bounded audit against artifacts
  already on the audit machine (no download) marks each entry
  `ARTIFACT_VERIFIED` (files matched their RECORD hashes) or `AUDIT_PENDING`,
  and findings carry that state. Auditing the pending entries, size and refresh
  cadence are open.
- **Other declaration formats.** PDM `[tool.pdm.dev-dependencies]`, Rye
  `[tool.rye] dev-dependencies` and Hatch environment dependencies are not read.
- **`sys.path` targets.** Only a directory written inline from `__file__`
  (`Path(__file__).parent`, `os.path.dirname(__file__)`, joined with string
  constants) is evaluated; a variable, a relative string (`"../"`, resolved
  against the working directory, which the source does not fix) or
  `os.getcwd()` is not. Under such a directory an import is withheld only when
  a module of that name exists in the project; otherwise the finding carries
  `evidence.sys_path_unresolved: true`, a bounded static verdict, not proof
  that no provider exists outside the project.
- **Members named by a relative import.** `from .x import f` is not checked for
  an `f` in `x`, so a missing member (an ImportError whenever the package imports
  it) is not reported, and a withheld `except ImportError` fallback after it can
  rest on that failure. Pinned by a strict expected-failure test.
- **Scan boundary.** Import resolution reads only inside the scan root (for a
  single file, its project root), by real path (PHANTOM_IMPORT.md, "What is
  read"). An environment behind a link out is recognised only under a
  conventional name (`.venv`, `venv`, `env`, `.env`, `virtualenv`): one under
  another name is not known to be an environment, so presence falls back to
  the analyzer's. A file symlink needs privileges Windows accounts usually
  lack, so that case is tested only where it can be created. The scan's file
  collection stops at a link out too; other walks (the JavaScript analyzer,
  connection resolution, `init`, the operations manifest) are not yet bound.

## 12. Corrections this implies for the current documentation

These corrections to [PHANTOM_IMPORT.md](PHANTOM_IMPORT.md) (written for the
v3.9.3 contract) are made in 3.18.0:

- "False Positive Avoidance" lists `PIL` and `sklearn` as handled by
  `packages_distributions()`. That holds only when the package is installed in
  the analyzer environment (F1).
- The same table says resolution errors "Return True (assume resolvable)",
  which contradicts the "Error policy" section of the same page (since v3.10 an
  error leaves the file unmeasured).
- The DDC comparison calls the signal "Hallucination" and the question "Does
  this import exist?". What is checked is resolution in the analyzer
  environment plus a declaration match (section 2).
- The example suggestion ("Verify it exists on PyPI and add it") is the advice
  section 9 replaces.

## References

- PEP 794, Import Name Metadata (accepted 2025-09-05; core metadata 2.5,
  `Import-Name`, `Import-Namespace`, `[project] import-names`,
  `import-namespaces`): https://peps.python.org/pep-0794/
- Spracklen et al., *We Have a Package for You! A Comprehensive Analysis of
  Package Hallucinations by Code Generating LLMs* (arXiv 2406.10279):
  https://arxiv.org/abs/2406.10279
- Zhu et al., *ModuleGuard: Understanding and Detecting Module Conflicts in
  Python Ecosystem* (ICSE 2024, arXiv 2401.02090):
  https://arxiv.org/abs/2401.02090
- FawltyDeps, mapping strategy (installed environment, temporary install,
  identity mapping, user mapping):
  https://tweag.github.io/FawltyDeps/explanation
- pyproject-udeps, `src/name_map.toml` and `contrib/name-map-audit` (wheel
  file lists read by HTTP range requests, namespaces mapped below the shared
  root): https://github.com/lukehsiao/pyproject-udeps
- Bazel `rules_python`, Gazelle `modules_mapping` (mapping generated from
  wheels): https://github.com/bazelbuild/rules_python
- Chowdhury et al., *Breaking the Dependency Chaos: A Constraint-Driven Python
  Dependency Resolution Strategy with Selective LLM Imputation* (FSE 2026,
  arXiv 2605.11772): a tiered import-to-package resolver that consults PyPI
  before any model. https://arxiv.org/abs/2605.11772
- Poweska et al., *Escaping Python Dependency Hell: A Hybrid Replay-and-Repair
  Pipeline for Python Dependency Resolution* (arXiv 2609.26952): deterministic
  steps and reuse of known configurations first, a model only as fallback.
  https://arxiv.org/abs/2609.26952
- Python documentation, `importlib.metadata.packages_distributions()`:
  https://docs.python.org/3/library/importlib.metadata.html
