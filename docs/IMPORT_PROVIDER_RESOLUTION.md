# Import Provider Resolution

**Status: Design for v3.18.0. Not implemented.** Nothing on this page describes
current behavior unless it says "today". The current contract is in
[PHANTOM_IMPORT.md](PHANTOM_IMPORT.md).

**Release boundary.** v3.18.0 ships the provider resolver, its verdict contract
(finding IDs, severities, messages, suggestions, JSON fields) and the tests
that hold it. The new MCP server and the agent collaboration loop that consume
these verdicts are v3.19.0; section 9 is policy for that release, not 3.18
behavior.

**Scope:** `phantom_import`, `phantom_member` and the import-evidence findings
next to them (`runtime_unavailable_dependency`, `undeclared_optional_dependency`,
`declared_outside_primary_metadata`). Python only.

---

## 1. Summary

`phantom_import` is reported as CRITICAL because of what it is meant to catch:
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
| 5 | Name similarity, prefixes (`python-`, `py`), `-` to `_` | A candidate to look up; never the basis of CRITICAL or HIGH | none |

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

Today all declarations are merged into one list (`dependency_declarations.py`),
which is right for the first question and says nothing about the second.

## 8. Verdicts

For an import the project does not provide itself:

| Situation | Finding | Severity | Auto-fix allowed |
|---|---|---|---|
| Resolves in the target environment, provider matches the declaration | none | | |
| Provider known (rank 1-4) and declared; not installed in the target (or the analyzer, if no target) | `runtime_unavailable_dependency` (existing) | MEDIUM | No: environment action |
| Provider known (rank 1-4), **not declared** | provider-level "undeclared dependency" finding, naming the provider and every importing location | HIGH (proposed) | No: a person confirms the provider's identity |
| Provider unknown to every source, not declared, not resolvable | `phantom_import` | see below | No: the author removes, replaces or confirms the import |
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
- whether this state keeps CRITICAL is a separate severity contract (section
  11), decided on labeled cases of both kinds (invented names and real but
  unmapped packages), not by this design.

For `phantom_member`:

| Provider state of the module | Finding |
|---|---|
| Installed provider is the declared provider (or nothing is declared and the provider is known) | `phantom_member` HIGH, as today |
| `PROVIDER_CONFLICT`: installed provider differs from the declared one | no HIGH; a provider-conflict finding naming both distributions, reported as environment evidence |
| `PROVIDER_UNKNOWN` | listed in `unverified_imports` (existing channel, no score effect) |

**Grouping.** Dependency findings are grouped per (project, provider): one item
with N locations in the work order. Whether the score counts the group once or
per location is a scoring-contract decision (section 11).

**Compatibility.** Existing pattern IDs keep their meaning; new situations get
new IDs. The internal provider states are recorded next to each import finding
in the JSON, so a reader (or an agent) can see why a verdict was or was not
reached. The exact keys are fixed by contract tests before implementation.

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
| R9a. `pywin32; sys_platform == "win32"` declared, `import win32api` inside `if sys.platform == "win32":`, non-Windows target | no finding: the dependency is inactive and the import does not run there |
| R9b. Same declaration, `import win32api` at module level, non-Windows target | reported: the import runs on a platform where its only provider is inactive (an inactive dependency is not a reason to excuse an import that always executes) |
| R10. A project with every dependency installed | every field the current JSON has keeps its value and every finding keeps its ID, severity and location; new provider-state fields are checked separately for correctness (not a byte comparison of the whole output) |
| R11. Byte-identical project scanned in two environments (the F5 cases) | the provider state names which environment it came from, and with a target environment configured the verdict is the same in both |

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

- **Severity of an undeclared known provider** (proposed HIGH above).
- **Severity of `phantom_import`** ("provider unknown to every source"):
  whether it stays CRITICAL, measured on labeled invented names and labeled
  real-but-unmapped packages.
- **Scoring.** Whether findings that depend on the environment stay in the
  deterministic score, move to a separate part of it, or count once per
  provider group. This changes the score contract and needs a version policy.
- **Target environment discovery.** Which locations are searched by default
  (only `pyvenv.cfg` directories inside the project root is the conservative
  choice) and the name of the configuration key for an explicit path.
- **Shipped mapping table.** Size, refresh cadence, and how its generation is
  recorded.

## 12. Corrections this implies for the current documentation

[PHANTOM_IMPORT.md](PHANTOM_IMPORT.md) describes the v3.9.3 contract and needs
these corrections when 3.18.0 ships (they are listed here so they are not
lost):

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
