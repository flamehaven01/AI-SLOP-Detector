# Import Evidence Fidelity and Graph-Structure Plan (Proposal)

> Status: **Phase 0 CLOSED** at commit `8be1e73` (pushed to `main`; CI/CD Pipeline
> run 36980062239 and AI Code Quality Gate run 36980062288 both `success`, Python
> 3.8-3.12). **Not a release**: no version bump or tag. Phases 1-3 remain
> proposals. Implementation and closure record: end of Phase 0 in Section 5.
> Drafted: 2026-10-01 against AI-SLOP-Detector `3.8.9` (+ unreleased core split)
> and graphify `0.9.73` (`Graphify-Labs/graphify`, branch `v8`, commit `ef4450d`, 2026-09-30).
> Revised: 2026-10-02 after a full read of README, `docs/*`, and the graph, cleanup,
> MCP, hotspot, and VS Code code paths. Corrections from that pass are marked
> **(revised)**.
> Revision 2: 2026-10-02, an external review was verified item by item against
> the same bytes (its cited SHA-256 values match the whole-file hashes of
> `cross_file.py` and `python_imports.py`). Accepted items are marked **(R2)**;
> the per-item verdicts are in Appendix C.
> Revision 3: 2026-10-02, a re-review of the Revision 2 text (its cited SHA-256
> `4cf6d7f5...` matched this file at that point) raised 3 design defects and 1
> wording fix. All 4 were verified against CPython behaviour and the current code
> and merged, marked **(R3)**; verdicts in Appendix C.
> Revision 4: 2026-10-02, a further review (cited SHA-256 `4a2f884a...`, matched)
> reframed decision 7 as authority-based module roots and added multi-portion
> namespace packages, and a separate assessment ranked the phases by necessity
> for the detector's purpose. Merged as **(R4)** after measurement; one item was
> adjusted because applying it literally would undo a v3.8.7 false-positive fix
> pinned by an existing test. Verdicts in Appendix C.
> Revision 5: 2026-10-02, a final review (cited SHA-256 `cd661387...`, matched)
> made the E4 graph rule more conservative: an undeclared E4 candidate is
> `conditional_internal` and never a hard edge by default. Verified by a launch-
> style experiment and merged as **(R5)**. **The Phase 0 contract is ready to
> freeze** (Section 7); document review ends here and the next step is the 0A
> RED fixtures.

**Scope in one line (R2):** this is an *import-graph fidelity* update, not an
AST engine change. Nothing implicates `ast.parse()`; the defects are in the
layer that turns parsed import statements into project files (module
resolution), and every graph consumer inherits them.

## 1. Why this exists

An external suggestion (2026-10) pointed at two things:

1. graphify's network-analysis measures over AST-derived structure fit the
   detector, and "I haven't seen their measures in your tool".
2. A possible LSP surface, so feedback arrives while code is written instead of
   after the mistakes are made.

This plan answers: which graphify techniques are worth adopting, which are not,
what the detector's current graph actually does, and in what order to change it.

### 1.1 Necessity by phase **(R4)**

The detector's job is to find code that is fabricated, empty, duplicated or
disconnected, with deterministic evidence, and **not** to call real code
fabricated. Phase 0 is required by that job on its own terms; the graphify-
derived phases are not. The graph is an evidence substrate for the detector,
not a new product identity.

| Phase | Necessity | Why, in terms of the detector's purpose |
|---|---|---|
| 0 - Import evidence fidelity | **REQUIRED** (defect fix) | `phantom_import`, a CRITICAL "this does not exist" finding, fires on working namespace-package imports (measured, Section 2). The src-layout graph is near-empty, so cycles, layer violations and cross-file issues are missed and read as clean (false negatives). One source of truth for "what is an internal module" serves both |
| 1 - Structural measures (SCC, fan-in/out, blast radius, runtime vs type-only cycles) | RECOMMENDED | Explains structural slop with evidence. Never added directly to a slop score |
| 2 - `[graph]` extra (betweenness, communities, cohesion) | OPTIONAL | Advanced analytics. High centrality is normal for core modules; "central therefore slop" is not a valid inference. Not in the core |
| 3 - LSP, agent guard | OPTIONAL | Delivery of results that Phases 0-1 make correct; does not change correctness |

Phases 1-3 are each justified separately after Phase 0 is GREEN on its RED
fixtures and self-scan; none of them rides on Phase 0 because it is "the same
patch".

## 2. Measured baseline (this repo, before any change)

Everything below was measured, not inferred. Reproduction is in Appendix A.

| Measurement | Result |
|---|---|
| `CrossFileAnalyzer` on project root `AI-SLOP-DETECTOR/` (src layout, 152 `.py` files) | **1 import edge**, 0 cycles |
| Same analyzer pointed at `src/` (98 files) | **166 edges**, 0 cycles |
| Throwaway prototype resolver on `src/` (absolute + relative + `from pkg import submodule`, `TYPE_CHECKING` marked) | 187 edges (185 runtime, 2 type-only) |
| **(revised)** Paired fixture, same architecture in two layouts (forbidden `domain -> data` import + a seeded 2-file cycle), `sweep boundary-violations` with the `layered` preset | Layout A (`src` as a package, the style existing tests use): `fail`, 1 layer violation found, **seeded cycle missed**. Layout B (real `src/mypkg/`): **`pass`, 0 issues** |
| **(R3)** Packaging-guide namespace project (`src/ns_pkg/` without `__init__.py`), `scan --project`, vs. the same project plus one `src/ns_pkg/__init__.py` | Namespace: **`phantom_import` CRITICAL** on a working import, 0 graph edges. Control: no `phantom_import`, 0 graph edges |
| **(R4)** Multi-portion namespace, both roots **declared** in `pyproject.toml` (`where = ["root_a", "root_b"]`); CPython imports both portions | **2 x `phantom_import` CRITICAL**, one per portion |

What this says:

- **The dominant defect is root-relative resolution, not resolver depth.**
  `_extract_imports` (`analysis/cross_file.py:119`) joins `root / module`, so
  `from slop_detector.x import y` looks for `<root>/slop_detector/x.py`, which
  does not exist under `src/`. Pointed at a src-layout project, the import graph
  is nearly empty (1 vs 166 edges). The gap from resolver depth is small by
  comparison (166 to 187, +21).
- **Every graph consumer sits on that input:** import cycles
  (`operations_cleanup.py`), slop hotspots / propagation (`_detect_hotspots`),
  and layer-boundary violations (`operations_architecture.py:126`). On a
  src-layout project they are reporting on an almost empty graph and cannot say
  so.
- **(R2, measured)** `_extract_imports` handles only `ast.ImportFrom` with a
  `module` and ignores `level`. Relative imports therefore fail in two different
  ways, and the difference matters:
  - `from .foo import Bar` inside `pkg/` is resolved as if it were absolute
    `foo`. With a top-level `foo.py` present, the edge goes to **that wrong
    file**. This is not a missing edge but a false one, which can manufacture
    cycles or layer violations that do not exist.
  - `from . import sib` has `module=None` and is **dropped**.
  (17 relative imports in this repo.)
- **(R2, measured) `ast.Import` is not handled at all.** `import pkg.sib`
  produces no edge. This was missing from the first draft because the
  prototype counted zero internal plain imports in this repo, which hid it.
- **(R2, measured)** Function-level imports and `if TYPE_CHECKING:` imports are
  kept as ordinary edges with no marker, so a cycle that closes only through a
  type-only import is indistinguishable from a runtime cycle today.
- **(revised)** `from pkg import submodule` resolves only to `pkg/__init__.py`,
  never to the submodule (5 in this repo). The paired fixture shows the effect:
  in layout A the seeded cycle `loop_a <-> loop_b` is written as
  `from src.data import loop_b`, so the edge lands on `data/__init__.py` and
  **the cycle is not reported even where the layer check works**.
- **(revised)** `_discover_project_packages` (`patterns/python_imports.py:219`)
  knows about `src/`, but it returns a `frozenset` of package *names*, not module
  roots or file paths. It cannot be called as the resolver; its root-scanning
  logic (`src/`, project root, first-level children, `pyproject.toml`) would have
  to be extracted into a shared helper. That is a refactor, not a reuse.
- **(R2)** That private helper already has a second importer:
  `operations_manifest.py:12` imports `_discover_project_packages` and
  `_find_project_root` from `patterns/python_imports.py`. Adding the graph as a
  third importer would avoid duplicated code but not duplicated *ownership*: a
  pattern module would become the de facto resolution layer for operations and
  analysis. Phase 0 promotes it to a shared module instead.
- No `networkx` in `pyproject.toml`. It was importable in the measurement
  environment (3.6.1) but is not a declared dependency.

Honest limit: on this repo the corrected graph shows **0 cycles**. The detector
is already clean on that axis, so this repo cannot demonstrate the value of the
new measures by itself. Section 6 requires a seeded fixture for that reason.

### 2.1 Why the tests did not catch it **(revised)**

`tests/test_operations_commands.py` (`test_boundary_violations_*`, lines 415-543)
builds `src/__init__.py` and writes `from src.domain import model`, i.e. it treats
`src` as an importable package. Real src-layout projects (`src/mypkg/`, imported
as `mypkg`) are never built by any test. The suite exercises exactly the layout
the resolver happens to handle, so it stays green while the common layout
reports nothing. This is a fixture blind spot, not a flaky test: the paired
fixture in Appendix A reproduces it deterministically.

### 2.2 What the detector already has, and where it surfaces **(revised)**

Read before adding anything, so new work extends contracts instead of
duplicating them (ROADMAP guardrail).

| Existing signal | What it is | Surfaces in |
|---|---|---|
| `structural_coherence` / `coherence_level` | MST max edge over pairwise Jensen-Shannon distances between per-file **AST node-type distributions** (DCF). A graph in *feature space*, not a dependency graph | `scan` JSON, MCP project snapshot |
| `PriorityHotspot` | `deficit 0.5 / churn 0.3 / coverage_gap 0.2` (config `hotspot_weights`) | `scan`, `pulse`, MCP |
| `SlopHotspot` (cross-file) | slop score >= 40 and imported by >= 2 files | only the `--cross-file` text output (`cli_commands.py:146`) |
| `slop_propagation` | file -> importers of a sloppy file | built, serialized by `to_dict`, **consumed nowhere else** |
| Import cycles, layer violations | DFS cycles; opt-in `layered` preset | `sweep boundary-violations`, and `--cross-file` text for cycles |
| `CrossFileReport.risk_score` | `cycles*0.10` (cap .40) + `dups*0.05` (cap .30) + `hotspots*0.08` (cap .30), hardcoded | only `--cross-file` text output |

Consequences for this plan:

- "AST measures" today means DCF/MST coherence. `VALIDATION.md` states it is
  **unknown** whether the AST node-type distribution is a meaningful signal. The
  import-graph work is a different, deterministic structure (who imports whom)
  and does not inherit that uncertainty, but it also does not resolve it.
- Two different things are called "hotspot" (`PriorityHotspot` vs `SlopHotspot`).
  A centrality factor must go through `hotspot_weights` in config, not a new
  hardcoded constant (CLAUDE.md Config-First). `CrossFileReport.risk_score`
  already hardcodes its constants; that is existing debt, noted and not widened.
- **An empty graph reads as a clean result.** `--cross-file` prints
  `[+] No cross-file issues detected.` whenever cycles, duplicates and hotspots
  are all empty, with no mention of how many imports were actually resolved. On
  a src-layout project that is the 1-edge case above. The same absence of a
  coverage caveat applies to `sweep boundary-violations` (`verdict: pass`).
- **The graph has no JSON channel of its own.** `scan` never runs
  `CrossFileAnalyzer` unless `--cross-file` is passed, and that path prints text.
  `pulse`/`health` does not use it. Only `sweep` emits graph-derived issues.
- **MCP exposes 3 tools** (`slop_schema`, `slop_analyze_file`,
  `slop_analyze_project`); the project snapshot has no cycles, cleanup families,
  `review`, or `pulse`. README says agent tooling can use "the same semantics"
  over MCP after describing cleanup families; the code does not support that
  reading. Flagged as drift, not changed here.
- `CLAIM_VERIFICATION.md` is dated 2026-04-15 / v3.5.0 and cites
  `patterns/python_advanced.py`, which was later split. Stale, not part of this
  plan.

## 3. What graphify does (reviewed code, `0.9.73`)

Pipeline: `detect -> extract -> build (NetworkX) -> cluster -> analyze -> report -> export`.
The measures live in `graphify/analyze.py` and `graphify/cluster.py`.

| # | Technique | Where | What it actually computes |
|---|---|---|---|
| G1 | Edge confidence labels | `build.py`, `analyze.py` | Every edge carries `EXTRACTED` / `INFERRED` / `AMBIGUOUS` |
| G2 | Runtime-only cycles | `analyze.find_import_cycles` | File-level digraph from `imports_from` / `re_exports`; skips edges marked `deferred` or `type_only`; `nx.simple_cycles(length_bound=5)`, shortest first, rotation-deduplicated |
| G3 | God nodes | `analyze.god_nodes` | Top-N by degree, after filtering file-hub nodes, builtins, JSON keys |
| G4 | Bridge nodes | `analyze.suggest_questions` | `nx.betweenness_centrality`, sampled `k=100` when nodes > 1000, `seed=42` |
| G5 | Communities + cohesion | `cluster.py` | Leiden (native, then graspologic) with Louvain fallback; split communities > 25% of graph; `cohesion = intra edges / n(n-1)/2` (self-loops excluded) |
| G6 | Determinism work | `cluster._partition` | Edges sorted by canonical endpoint pair before partitioning; their note: identical input gave 70 vs 69 communities under `PYTHONHASHSEED=1` vs `=2` before this fix |
| G7 | Deterministic labels | `cluster.label_communities_by_hub` | Community named after its highest-degree member, no LLM |
| G8 | Blast radius | `affected.py` | BFS over a fixed relation set (`calls`, `imports_from`, `re_exports`, `inherits`, `dynamic_import`, ...) returning depth and `via_relation` |
| G9 | Snapshot diff | `analyze.graph_diff` | Added/removed nodes and edges between two graphs |
| G10 | Surprise score | `analyze._surprise_score` | Composite: confidence + cross file-type + cross-directory + cross-community + peripheral-to-hub |
| G11 | PreToolUse guard | `cli._run_hook_guard`, `install._claude_pretooluse_hooks` | See below |
| G12 | MCP query surface | `serve.py` | `query_graph`, `get_node`, `get_neighbors`, `get_community`, `god_nodes`, `graph_stats`, `shortest_path` |

### G11 in detail (the part relevant to the LSP idea)

The guard is a hook that runs **before** the agent searches or reads, and injects
graph context instead of correcting afterwards. The design choices worth keeping:

- **Fail open.** Any error or non-matching call prints nothing and the tool call
  proceeds. A bug in the guard can never block work.
- **Nudge, do not block.** The optional strict mode denies at most the *first*
  raw read per session, then falls back to a nudge, so an agent is never stranded.
- **Freshness-aware.** A graph that is stale for the target file softens to a
  non-mandatory nudge.
- **Decide on executed tokens, not substrings.** Their fix (#3121): the first
  version matched `"ag "` inside `git commit -m "add flag support"`. Parsing
  executed command tokens removed that class of false trigger.
- **Bounded cost.** Each hook has a 10s timeout; the default is 600s. The
  author reports about 170 ms warm for the guard. That figure is theirs and is
  not measured here.

## 4. Adopt / adapt / skip

Decision rule from `ROADMAP.md` Guardrails: *false confidence is worse than a
missing candidate*, and *extend existing JSON and CLI contracts rather than
inventing parallel ones*.

| Technique | Decision | Reason |
|---|---|---|
| G1 edge confidence | **Adapt, not copy (R2)** | graphify's `EXTRACTED / INFERRED / AMBIGUOUS` grades *certainty* of LLM- or resolver-inferred edges. The detector resolves Python imports deterministically, so it records separate axes instead of one certainty label. **(R3)** The R2 draft still packed three meanings into one `resolution` enum (addressing, target kind, outcome); Phase 0 now splits them into `import_scope`, `target_kind`, `resolution_state` (with `ambiguous`), plus `type_only` / `deferred` for execution |
| G2 runtime-only cycles | **Adopt, additive (R2)** | `TYPE_CHECKING` and function-level imports are visible in `ast`. Avoids reporting cycles that cannot exist at runtime. SCCs are **added alongside** the existing ordered cycles, not swapped in (see Phase 1: an SCC is a node set, `import_cycles` is an ordered path that `sweep` JSON and CLI text already consume) |
| G3 god nodes | **Adapt** | The detector already has fan-in x slop hotspots. Add fan-out and the noise filters; do not rename a high-degree module to "slop" |
| G4 betweenness | **Adapt**, optional tier | New signal (bridge modules). Keep their size caps and fixed seed |
| G5 communities + cohesion | **Adapt**, optional tier | Useful only as *package-vs-community mismatch*, not as a verdict. Louvain, not Leiden (Leiden brings `graspologic`; their own measurement: 7-19 s import cost without the native shortcut) |
| G6 determinism | **Adopt as a requirement** | The detector's core is deterministic by policy. Any community step must pass a `PYTHONHASHSEED` test |
| G7 hub labels | **Adopt with G5** | Deterministic, no LLM |
| G8 blast radius | **Adapt** | Current `slop_propagation` is one hop. Multi-hop with `depth` and `via` |
| G9 snapshot diff | **Defer** | Matches the "regression diffs" Vision item; needs a snapshot store decision first |
| G10 surprise score | **Skip** | Depends on LLM/semantic edges the detector does not have |
| G11 guard design | **Adopt design, not code** | Applies to the agent/LSP track (Phase 3) |
| G12 MCP surface | **Adapt**, small | Detector already ships `slop-detector mcp`; add only what Phase 1 data supports |
| Not adopted | - | 25-language tree-sitter extractors, LLM semantic extraction, HTML/Obsidian/Neo4j/wiki exports, hosted platform |

### Claims deliberately not used

- graphify's README benchmarks (LOCOMO, LongMemEval-S) measure **agent memory /
  QA**, not code-quality detection. They are not evidence for this plan.
- `graphify/benchmark.py` estimates tokens as `len(text) // 4`. Any "token
  savings" figure from it is an approximation.
- A graph measure describes **structure**, not **slop**. A high-degree module is
  not a defect. Measures enter the detector only as context attached to an
  existing finding or as an explicitly labelled structural signal.

## 5. Phased plan

Each step is `[change] -> verify: [falsifiable check]`. Version numbers are
proposals only.

### Phase 0 - Import evidence fidelity / project-resolution correctness (REQUIRED, patch-level)

Nothing else is worth building on a graph that is 1 edge on a src-layout project.

- **(R2) Promote module resolution to a shared substrate.** Module-root
  discovery and project-root lookup move out of `patterns/python_imports.py`
  into one module that the phantom-import pattern, `operations_manifest.py`, and
  the graph all call. Deliverable order **(R4)**: **0A** shared module index and
  root discovery + namespace `phantom_import` regression fix, **0B** graph
  resolver on top of it, **0C** coverage reporting and output wording.
- **(R4) Module roots carry an authority tier; "is the project root a root?" is
  not a yes/no question.** Python's `sys.path[0]` is the script's directory for
  `python path/app.py` and the current directory for `python -m` (measured), so a
  static analyzer cannot assume any directory is importable. Discovery records
  where each root came from:

  ```text
  E1 DECLARED      packaging config names it, e.g.
                   [tool.setuptools.packages.find] where = ["src"]
  E2 CONVENTIONAL  <project>/src exists, holds Python sources, and has NO
                   src/__init__.py (absorbed into E1 when metadata also declares it)
  E3 FLAT_LAYOUT   no E1/E2 root; the project root itself has top-level .py files
                   or regular packages. A src/ WITH __init__.py is a regular package
                   named `src`, so its project is flat (E3), not E2 (impl note below)
  E4 CONDITIONAL   a first-level child holding packages (backend/app), a bare
                   namespace directory at the project root, anything that only
                   resolves under a particular runtime sys.path / PYTHONPATH
  ```

  **Adjusted from the review (measured):** the review proposed that E4 roots
  never resolve. Taken literally that would break
  `tests/test_fp_reduction.py::test_monorepo_backend_package_not_flagged_as_phantom`
  (a root `pyproject.toml` with no package declaration and `backend/app/`), i.e.
  it would bring back the v3.8.7 monorepo false positive. The two consumers need
  different strength of evidence, so E4 is applied asymmetrically:

  | Consumer | E1-E3 | E4 |
  |---|---|---|
  | `phantom_import` (accuses code of importing something that does not exist) | resolves | **enough to withhold the accusation**: the module exists on disk under a plausible root |
  | `import_edges` (record) | `resolved` | **(R5)** unique top-level name -> `conditional_internal`, with the on-disk candidate; two or more roots (`backend/app` and `worker/app`) -> `ambiguous` |
  | `import_graph` (feeds cycles, layer violations, blast radius) | hard edge | **(R5) never by default.** Promoted to a hard edge only when the root is declared by packaging config, by analyzer config, or by an explicitly supplied import path for the run |

  **(R5) Why E4 stays out of `import_graph`, measured:** the same tree with the
  same `from app.services.jobs import run` succeeds when launched as
  `cd backend && python -m app.main` and raises `ModuleNotFoundError` when
  launched as `python -m backend.app.main` from the repository root. A unique
  name on disk proves the module exists, not that it is importable at run time.
  Turning it into a hard edge would open a new false-positive path into cycles
  and layer violations. "Do not assert it is missing" and "do not assert it is
  connected" are the same evidence rule applied to the two consumers.

  Two consequences that must be stated, not hidden:
  1. The same experiment shows that withholding `phantom_import` at E4 also hides
     a real `ModuleNotFoundError` for projects launched from the root. That is the
     trade-off v3.8.7 already chose; it is a path-configuration defect, not a
     hallucinated package, and is out of `phantom_import`'s scope.
  2. A monorepo without declared roots will have its E4 edges outside
     `import_graph`, which is exactly the "empty graph reads as clean" failure
     from Section 2.2 unless the output says so. Deliverable 0C must report the
     `conditional_internal` count and how to declare the roots, wherever a clean
     graph result is shown.

  Analyzer-config promotion needs a new `.slopconfig.yaml` key (working name
  `module_roots`; nothing equivalent exists today, only
  `phantom_import_allowlist`). Config schema, `SCHEMA_VALIDATION.md` and
  `CONFIGURATION.md` change in the same commit (CLAUDE.md drift rule).

  Each edge records its root's tier. The pinned monorepo test is a required
  regression gate for 0A.
- **(R4) PEP 420 portions.** A namespace package can be split across several
  roots, and CPython merges them into one `__path__` (measured: two declared
  roots `root_a/ns_pkg/alpha` and `root_b/ns_pkg/beta` both import). The index
  therefore maps `module_name -> ordered tuple[ModuleLocation, ...]`, not to a
  single path. Today the same fixture, with both roots declared in
  `pyproject.toml`, gets **two `phantom_import` CRITICALs** (Section 2).
- Proposed shape (names are a proposal, not a contract):

  ```text
  src/slop_detector/
      project_resolution.py      # ProjectModuleIndex, discover_module_roots(),
                                 # discover_project_packages(), module_name_for_file(),
                                 # resolve_import(), find_project_root()
      analysis/
          import_graph.py        # ImportEdge, ImportGraphCoverage, build_import_graph()
          graph_metrics.py       # Phase 1: SCC, fan-in/out, blast radius
          cross_file.py          # duplicates, hotspots, compatibility facade
  ```

  `_discover_project_packages` returns package *names* only today, and it feeds
  `phantom_import` (a CRITICAL pattern). Moving it is a refactor of a tested,
  high-severity path: the phantom-import suite and the manifest-hygiene suite
  must pass unchanged before any graph change lands on top.
- Resolve all four statement shapes: absolute `from a.b import c`,
  `import a.b` (`ast.Import`, currently ignored), relative with a module
  (`from .b import X`, against the importer's package), and relative without one
  (`from . import b`).
- **(R3) `from pkg import name` follows CPython's order, not "submodule first".**
  The language reference checks for an attribute `name` on `pkg` first and only
  then imports a submodule. Measured on CPython (Appendix A): with
  `name = ...` in `pkg/__init__.py` and a `pkg/name.py` on disk, `pkg.name` is
  **not** imported, so a "submodule first" edge would be false. The rule:

  ```text
  from pkg import name
  1. pkg itself is imported      -> regular package: pkg/__init__.py runs, but it
                                    becomes an edge only when steps 2-4 yield no
                                    more specific file (impl note below)
                                    namespace package: no file edge for pkg
  2. name is bound at top level of pkg/__init__.py
     a. bound by `from . import name` / `from .name import ...`
                                 -> submodule (measured: it IS imported)
     b. bound any other way      -> package_member, no submodule edge
  3. name not bound, pkg/name.py (or pkg/name/) exists
                                 -> submodule
  4. not decidable statically: module-level __getattr__, `import *` in
     __init__, conditional bindings
                                 -> ambiguous
  ```

  **Implementation notes (0A/0B, before code; both found while designing
  against the existing tests):**
  - *E2 excludes `src/__init__.py`.* With "any `src/` is E2", the layout used
    by `test_boundary_violations_respects_opt_in_layered_architecture`
    (`src/__init__.py`, `from src.domain import model`) would put its own
    imports at E4 and drop its layer violation. A `src` with `__init__.py` is a
    regular package, so the import root is the project root (E3).
  - *Ancestor `__init__` files are implicit, not edges.* The old resolver never
    added `pkg/__init__.py` for `from pkg.sub import x`; adding it only for
    `from pkg import name` would be inconsistent and would report one import
    statement as two layer violations (`data/__init__.py` and `data/repo.py`),
    breaking the paired-fixture acceptance (1 violation). Rule: each import
    alias yields an edge to its most specific resolved file. The package
    `__init__` is the edge only when the name is a member, ambiguous, or
    unresolved (then an `ambiguous` edge is recorded in addition).

  An `ambiguous` edge is recorded in `import_edges` and counted in
  `graph_coverage`, but is **not** written to `import_graph`, so it can never
  become a hard runtime cycle or layer violation on its own (missing a candidate
  is preferred over a fabricated one; ROADMAP guardrail). Step 2a is a
  refinement of the external proposal, which would have classified that case as
  a member; the measured behaviour says otherwise.
- **(R3) PEP 420 namespace packages are in scope.** A directory without
  `__init__.py` under a module root is an importable package (verified on
  CPython). Today `_discover_project_packages` requires `__init__.py`
  (`python_imports.py:234`), and the effect is not limited to the graph: in a
  Packaging-guide namespace layout, **`phantom_import` reports a CRITICAL
  "cannot be resolved" for an import that runs**, while the same project with
  one added `src/ns_pkg/__init__.py` reports nothing (Appendix A). Namespace
  detection is limited to declared or discovered module roots (`src/`,
  `[tool.setuptools.packages.find] where`), never "any directory", so that
  namespace support cannot silently switch `phantom_import` off for real
  phantoms. Whether the bare project root counts as a module root is answered by
  the authority tiers above (R4): it is E3 only in a flat layout; a bare
  namespace directory at the project root is E4.
- **(R2, wording R3) Keep the existing contract and add beside it.**
  `import_graph: Dict[str, List[str]]` stays exactly as it is: it is read
  directly by `operations_architecture.py:135`, and it is a field of
  `CrossFileReport`, which `slop_detector.analysis` exports publicly via
  `__all__`. Preserve the shape for compatibility.
  (`CrossFileReport.to_dict()` has no in-repo consumer; `ml/pipeline.py:351`
  serializes a different `PipelineReport`.) New, additive fields, with
  **(R3)** the observation, the addressing, the outcome and the execution
  semantics on separate axes so that, for example, `from . import sib` is
  `relative` + `resolved` + `module` at once:

  ```text
  ImportEdge
    importer, imported, line
    statement_kind:   import | from                       # observed
    requested_module, requested_name, relative_level      # observed
    import_scope:     absolute | relative                 # addressing
    resolution_state: resolved | conditional_internal     # outcome (R5: conditional_internal)
                      | unresolved_internal | external | ambiguous
    root_authority:   E1 | E2 | E3 | E4 | none            # (R5) where the root came from
    target_kind:      module | package | package_member | namespace_package
    type_only: bool, deferred: bool                       # execution

  CrossFileReport
    import_graph     # unchanged: only resolved (E1-E3 or promoted), internal, file-backed
    import_edges     # new: every observed import, including conditional / ambiguous
    graph_coverage   # new: counts per resolution_state
  ```

  Example, the pinned monorepo layout: `from app.services.jobs import run` ->
  `root_authority=E4`, `resolution_state=conditional_internal`, candidate
  `backend/app/services/jobs.py`; `phantom_import` withheld; in `import_edges`,
  not in `import_graph`.

  `external` and `ambiguous` are counted in `graph_coverage` and never added to
  `import_graph`, whose values have always been project files.
- Report **resolved / unresolved internal imports** in the existing scan
  coverage envelope (3.8.9), and make `--cross-file` and `sweep` say so instead
  of printing a bare "No cross-file issues detected" / `pass`.

Verify:

1. **(revised)** RED first, using the paired fixture from Appendix A as the
   acceptance test: layouts A and B hold the same architecture and must produce
   the **same** findings (1 layer violation + 1 import cycle). Today: A finds 1
   of 2 (misses the cycle), B finds 0 of 2.
2. **(R2)** Fixture matrix, one assertion per row. Current behaviour is
   measured (Appendix A), not assumed:

   | Case | Must hold after Phase 0 | Today |
   |---|---|---|
   | `src/pkg/a.py`: `from pkg import b`, scanned from project root | resolves to `src/pkg/b.py` | no edge |
   | `pkg/a.py`: `from .foo import Bar`, **with a decoy top-level `foo.py`** | `pkg/foo.py`, never the decoy | edge to the decoy |
   | `pkg/b.py`: `from . import sib` | `pkg/sib.py`, `resolution=relative` | no edge |
   | `pkg/c.py`: `import pkg.sib` | `pkg/sib.py` | no edge |
   | **(R3)** `from pkg import name`, `pkg/__init__.py` empty, `pkg/name.py` exists | `pkg/name.py`, `target_kind=module` (ancestor `__init__` implicit, impl note) | `pkg/__init__.py` only |
   | **(R3)** same, but `pkg/__init__.py` has `name = ...` | `pkg/__init__.py` only, `target_kind=package_member`; **no** edge to `pkg/name.py` | `pkg/__init__.py` only (right by accident) |
   | **(R3)** same, but `pkg/__init__.py` has `from . import name` | `pkg/__init__.py` + `pkg/name.py` (step 2a) | `pkg/__init__.py` only |
   | **(R3)** same, but `pkg/__init__.py` defines module `__getattr__` | `resolution_state=ambiguous`, not in `import_graph`, counted in coverage | `pkg/__init__.py` only |
   | **(R3)** namespace: `src/ns_pkg/` without `__init__.py`, `from ns_pkg.feature import api` | `src/ns_pkg/feature/api.py`; **no `phantom_import`** | no edge; `phantom_import` CRITICAL |
   | **(R3)** negative control: import of a name that exists nowhere under any module root | still `phantom_import` | `phantom_import` |
   | **(R4)** multi-portion namespace: `where = ["root_a", "root_b"]`, `root_a/ns_pkg/alpha`, `root_b/ns_pkg/beta`; `from ns_pkg.alpha import x` and `from ns_pkg.beta import y` | both resolve, `target_kind=namespace_package` for `ns_pkg`, no `phantom_import` | 2 x `phantom_import` CRITICAL |
   | **(R4)** monorepo E4: root `pyproject.toml` without package declaration, `backend/app/services/jobs.py`, `from app.services.jobs import run` (the pinned v3.8.7 test) | **(R5)** no `phantom_import`; `conditional_internal`, tier E4, in `import_edges`, **not** in `import_graph` | no `phantom_import`; no graph edge |
   | **(R4)** E4 collision: `backend/app/x.py` and `worker/app/x.py`, `from app.x import f` | no `phantom_import`; `ambiguous`, not in `import_graph` | no `phantom_import`; no graph edge |
   | **(R5)** promotion: the monorepo layout above, then `backend` declared as a root (packaging config or `module_roots`) | before: `conditional_internal`, no hard edge; after: `resolved`, hard edge in `import_graph` | (no declaration mechanism exists) |
   | **(R5)** 0C wording: any of the conditional cases above with no hard edges left | `--cross-file` / `sweep` show the `conditional_internal` count and how to declare roots instead of a bare clean message | bare "No cross-file issues detected" / `pass` |
   | `if TYPE_CHECKING:` import | edge kept, `type_only=True` | edge, no marker |
   | import inside a function | edge kept, `deferred=True` | edge, no marker |
   | seeded `a <-> b` | exactly one runtime cycle | missed when written as `from pkg import b` |
   | cycle closed only by a type-only edge | not a runtime cycle | would be reported as one |

   **(R5) Minimum RED -> GREEN gate for 0A/0B.** All rows above are required;
   these six carry the false-positive and graph-correctness argument together
   and must be the first tests written:
   1. real `src/pkg` layout from the project root;
   2. single-root PEP 420 namespace (`phantom_import` gone);
   3. declared multi-portion namespace (both portions resolve);
   4. v3.8.7 `backend/app` monorepo (pinned test stays green);
   5. `backend/app` + `worker/app` collision (accusation withheld, `ambiguous`);
   6. undeclared unique E4 root (withheld, no hard edge), then declared (hard edge).

   The decoy is required: without a same-named top-level module, mis-resolution
   and omission both look like "no edge" and the test cannot tell them apart.
   Keep the existing `src`-as-package tests; they must still pass.
3. Mutation check: remove each resolution rule in turn; the matching assertion
   must fail (a green test that survives mutation is measuring the cheapest path).
4. Self-scan from project root: edge count must be the same order as the `src/`
   scan (baseline 1 -> expected in the 160-190 range, Appendix A), not exact.
5. Existing JSON contracts unchanged except additive keys; `import_graph` values
   byte-identical for any project the old resolver already handled correctly.
   Existing self-dogfood gate stays green.

Behaviour note **(revised)**: `sweep boundary-violations` returns
`verdict: fail` whenever any issue exists. A src-layout project that has been
getting `pass` because the graph was empty can start getting `fail` after this
fix. Observed: `sweep boundary-violations` exits **0** even when the payload
verdict is `fail` (Appendix A, layout A), so a gate keyed on the process exit
status is unaffected, but one that reads the JSON `verdict` will turn red with no
change in the project's code. This is a correction, not a regression, but it
changes a documented output. It must be called out in the changelog, and the release note should tell
users how to confirm a finding is real (the new resolved-import count) before
suppressing it.

**(R3)** The shared resolver also changes a CRITICAL pattern's output in the
other direction: namespace-package projects that currently get a
`phantom_import` CRITICAL for working imports will stop getting it. That is a
false-positive removal in a shipped pattern and belongs in the same changelog
entry, with the negative control above as the evidence that real phantoms are
still reported.

#### Phase 0 implementation record (2026-10-02)

Files: new `src/slop_detector/project_resolution.py` (roots, tiers, package
names, module location, `load_pyproject`), new
`src/slop_detector/analysis/import_graph.py` (`ImportEdge`, statement rules,
coverage); changed `analysis/cross_file.py`, `patterns/python_imports.py`,
`operations_manifest.py`, `operations_payloads.py`, `cli_commands.py`;
controls in `tests/test_import_evidence_fidelity.py`; `CHANGELOG.md`
[Unreleased].

| Check | Result |
|---|---|
| Controls written first | 24 written before code: 21 failed by assertion, 3 preservation passed. 2 added during 0C (RED first) and 1 after a mutation finding (below). Total 26 |
| Phase 0 controls | 26 / 26 pass; after Revision 6: **35 / 35** (8 R6 controls written first, 7 failed by assertion and 1 positive control passed; plus 1 name-listing owner) |
| Full suite | 504 passed, 4 skipped; after Revision 6: **513 passed, 4 skipped** (baseline 478; +35, no regressions) |
| Mutation | 13 / 13 killed before Revision 6. After Revision 6: 21 mutants including one per R6 rule; 20 killed by owners on the first run; the 21st was a mis-designed mutant (it did not reproduce "relative resolved against the project root") and its replacement was killed by the decoy control. **21 / 21 valid mutants killed by their declared owners** |
| Self-scan, project root | 1 -> 282 edges before Revision 6, **285 after** (155 files incl. tests); importer-in-`src/` edges 191; 0 cycles; coverage all `resolved`/`external` (complete) |
| Cost | `CrossFileAnalyzer` on this repo: 3.08 s (HEAD) -> 3.22 s median of 3; 2.56 s in a later run after Revision 6 (run-to-run variance on this machine is of the same size; read as "no measurable increase", not as a speed-up) |
| Self-dogfood | `import_graph.py` 0.0 clean (was 54.5 before the refactor below); `project_resolution.py` 7.0; `python_imports.py` 42.0 -> 9.0; no new findings in the other changed files |
| Style | ruff clean; black clean on all owned files (only owned files formatted, by path) |
| Python 3.8 | syntax checked with `ast.parse(feature_version=(3, 8))` on all changed files; runtime exercised on 3.12 and 3.14 only locally. **3.8-3.11 runtime was unverified until CI; CI later passed on 3.8-3.12 (closure record)** |

Found while doing it:

- *Mutation found a mis-declared owner.* With namespace detection disabled,
  `test_namespace_package_resolves_in_graph` still passed: its target is a
  regular package and CPython never checks intermediate directories. It was
  reclassified (docstring) and `test_namespace_package_as_import_target_is_detected`
  was added as the owner.
- *Self-dogfood found the first `import_graph.py` at 54.5 (`inflated_signal`,
  two CRITICAL `nested_complexity`).* Fixed by splitting functions, not by
  adding overrides to `.slopconfig.yaml`.
- *A third TOML loader had been introduced.* `python_imports.py` now uses the
  shared `load_pyproject`; this also removed that file's pre-existing
  `phantom_import` on its `tomli` fallback line.

Deviations from this plan, stated rather than hidden:

1. **0C scan envelope not wired.** `--cross-file` and `sweep` disclose
   `graph_coverage`; a default `scan` does not, because it does not build the
   graph and adding that would change default scan cost. *Decision at closure:
   leave as is; this is an observability enhancement, not a Phase 0 defect.*
2. **`module_roots` config key deferred.** Promotion of an E4 root works through
   packaging declaration (`[tool.setuptools.packages.find] where`), which is
   tested (control: declared E4 root promoted to a hard edge). *Decision at
   closure: do not add the key until a user needs a route that packaging
   metadata cannot express; each new key adds schema and docs surface.*
3. **Docs not updated where the working tree already had uncommitted edits**
   (`PHANTOM_IMPORT.md`, `ARCHITECTURE.md`, `CLI_USAGE.md`), to avoid mixing
   with those changes. *Still open: do once those edits are committed.*

### Phase 1 - Tier-1 measures, standard library only (RECOMMENDED)

- **(R2)** Cycles with a runtime vs type-only/deferred split (G2), as two
  separate outputs because they are two different objects:

  ```text
  import_cycles                  # unchanged: ordered representative path a -> b -> c -> a
  strongly_connected_components  # new, additive: node sets {a, b, c}
  ```

  `import_cycles` is consumed as an ordered path: `operations_cleanup.py:510-516`
  emits it as the `cycle` list and `display` string of `sweep` issues, and
  `cli_commands.py:134` prints it. Replacing it with SCC sets would change both
  outputs. `import_cycles` already feeds `CrossFileReport.risk_score`
  (`cycles*0.10`, cap 0.40) and keeps doing so unchanged; the new SCC output
  does **not** enter `risk_score` or any slop score.
- Fan-in and fan-out per module with noise filters (G3).
- Multi-hop blast radius over reverse edges with `depth` and `via` (G8).
- New module `analysis/graph_metrics.py` rather than growing `cross_file.py`
  (381 lines, already carrying five responsibilities).
- Output follows the dual-audience policy: plain human wording, full-fidelity
  machine keys, entries in `metric_guide` (value / direction / meaning).
- **(revised)** Decide the channel first (Section 7): today the graph reaches
  neither `scan` JSON, `pulse`, nor MCP. A new `graph` block should be additive
  and opt-in (`--cross-file` or a config flag) so default `scan` cost and JSON
  shape do not change.
- **(revised)** Any centrality input to prioritization goes through
  `hotspot_weights` in config, defaulting to weight 0 so existing hotspot
  rankings stay byte-identical until a user opts in.

Verify:

1. Seeded fixture where SCC finds a 3-cycle that the current DFS+`frozenset`
   dedup is expected to report differently; assert both behaviours explicitly.
   (Expectation only: the current DFS back-edge logic is not yet shown to miss
   it. Write the test first and record what actually happens.)
2. A type-only-only cycle is reported as non-runtime, not as a runtime cycle.
3. No new runtime dependency (`pyproject.toml` diff is empty for `dependencies`).

### Phase 2 - Optional `[graph]` extra (OPTIONAL)

- Betweenness with graphify's caps (sample above 1000 nodes, fixed seed).
- Louvain communities, cohesion, hub labels, package-vs-community mismatch.
- Declared as an optional extra beside `[js]` and `[go]`; absent extra degrades
  to a structured "unavailable" state, like the existing `ml_scoring=unavailable`.
- **(R2, verified) NetworkX stays out of the core, and its version is a
  Python-support decision.** AI-SLOP-Detector declares `requires-python >=3.8`
  with classifiers 3.8-3.14. PyPI `requires_python` per NetworkX release:
  `3.1 >=3.8`, `3.2 >=3.9`, `3.3 / 3.4 >=3.10`, `3.5 >=3.11`. graphify pins
  `networkx>=3.4` with `requires-python >=3.10`. Copying graphify's floor would
  make `[graph]` uninstallable on 3.8 and 3.9. The extra's range (single range,
  environment markers, or "3.10+ only" stated in the docs) is chosen against
  the CI matrix, and any API used (for example a length bound on cycle
  enumeration) must be checked on the oldest version allowed, not assumed.

Verify:

1. Determinism: same input, `PYTHONHASHSEED` in {0,1,2,3}, identical communities.
2. Seeded fixture with two clear packages and one deliberately mis-placed module;
   mismatch must name that module and no other.
3. Wall time on a large real project recorded before any default-on decision.
   This repo's own numbers (98 nodes: 6 ms Louvain, 4 ms betweenness) do not
   extrapolate and must not be quoted as a scaling claim.

### Phase 3 - Agent and editor guidance (OPTIONAL, design only, decide later)

Two separate things that share a goal:

- **LSP diagnostics server** (`slop-detector lsp`): push diagnostics while code
  is being written. ROADMAP already lists "optional LSP server". Diagnostics-only,
  so it runs next to Pyright, Ruff and others; editors attach several servers
  themselves, and a proxy LSP is the user's choice, not something this project
  needs to build.
- **Agent pre-action guard** modelled on G11: before an agent edits a file, inject
  "this module has N dependents / is in a cycle". Fail-open, nudge-only, freshness
  aware, executed-token matching.

**(R2) Order: ML lazy-load, then LSP, then the guard.** The guard needs a stable,
fresh graph cache to say anything true about dependents; the LSP is what forces
that cache to exist and is already on the ROADMAP. Neither is justified on
latency until the lazy-load item (Section 7) is measured. Inside the LSP, keep
two speeds apart so no expensive measure runs per keystroke:

```text
keystroke                     -> current-file AST diagnostics only
debounce / save / dep change  -> incremental import-graph update
                              -> recompute dependents of the changed file
                              -> graph diagnostics (cycles, fan-in)
on demand / CI                -> [graph] extra measures (betweenness, communities)
```

The guard then reads from the same cache: target module -> dependents -> SCC
membership -> bounded blast radius -> freshness state -> nudge only.

**(revised) What already exists.** The VS Code extension already lints on type
(`extension.ts:100`, 1500 ms debounce) and on save, by calling the CLI through the
`ai-slop-detector` npm wrapper, one file per call. So "feedback while writing"
exists for single files in one editor. An LSP is not what unlocks it; what an LSP
would add is (a) reuse by other editors and agents, (b) no per-call process
start, and (c) cross-file context that a single-file call cannot have.

**(revised) Measured latency of the existing path** (one machine: Windows 11,
Python 3.14, scikit-learn installed, 2026-10-01/02; Appendix A):

| Step | Observed |
|---|---|
| Single-file CLI call, wall clock | median **~3.4 s** (min 3.2 s) |
| `import slop_detector.core` | 0.4-0.6 s |
| `SlopDetector()` construction | **2.1-2.4 s** (profile: ~3.5 s of a 4.0 s profiled run is `import sklearn`, reached via `ml/scorer.py` -> `ml/classifier.py`) |
| First analysis call in a fresh process | ~1.3 s |
| Steady-state analysis, cache bypassed | **~165 ms** (384-line file), ~370 ms (693-line file) |
| Analysis-cache hit | 1-3 ms |

Implications, kept separate on purpose:

1. Most of the per-call cost is a process-start cost, mostly an eager
   scikit-learn import for an optional ML scorer. A persistent process removes it,
   **and so would lazy-loading the ML scorer inside the existing CLI**, which is
   a much smaller change that benefits `lintOnType`, MCP calls
   (`_analyze_file` builds a new `SlopDetector` per call), and CI alike. It
   should be evaluated before an LSP is justified on latency grounds.
2. ~165 ms steady-state is for one file on one machine. It is not a per-keystroke
   budget and says nothing about cross-file analysis, which has no incremental
   path today (project aggregation recomputes from the live file set).
3. Confirmed 2026-10-02 in this environment: the ML model does not load
   (`models/slop_classifier.pkl` has keys `class_priors, class_stats, ...`; the
   loader expects `feature_names, model_type, rf_model, xgb_model`), and the
   result reports `ml_scoring.status = unavailable`. The scikit-learn import is
   still paid on every construction, so about 3 s is spent to learn that the
   optional scorer cannot be used.

graphify's guard measures about 170 ms warm by its author's account; that is a
different workload and is not transferable.

Open before any build: lazy-load result, which current checks are computable
from a single file fast enough per keystroke (pattern checks likely; cross-file
ones need a cached graph), and what latency budget is acceptable, measured on
this codebase.

## 6. Risks and guardrails

- **Working tree is not clean.** At drafting time 15 tracked files carry
  uncommitted changes (`README.md`, ten `docs/*`, `cli.py`, `cli_parsers.py`, two
  tests). Implementation should start from a committed baseline.
- **Self-dogfood is a release gate.** New modules are subject to the detector's
  own file-size and cohesion findings.
- **Python-only first.** The JS/TS and Go paths use tree-sitter and have no
  import-edge extraction that feeds `CrossFileAnalyzer`. Cross-language graphs
  are out of scope until Phase 0 is proven on Python.
- **Do not collapse structure into a score.** No composite "graph health"
  number without a derivation (CLAUDE.md: measure, do not claim).
- **A clean self-scan proves little.** Value of Phases 1-2 is shown on seeded
  fixtures and on external projects, not on this repo's own 0-cycle graph.
- **(revised) A fixed graph can turn existing gates red.** See the Phase 0
  behaviour note. Release-note wording and a resolved-import count are part of
  the fix, not follow-up.
- **(revised) Do not let new structural signals borrow unvalidated credibility.**
  `VALIDATION.md` says the tool is not independently validated and the AST
  distribution signal is an open question. Graph measures are structure
  descriptors; they enter reports as context on an existing finding or as an
  explicitly labelled structural signal, never as evidence that code is
  AI-generated or defective.
- **(revised) Doc drift to leave alone, not widen.** README's MCP sentence, the
  stale `CLAIM_VERIFICATION.md`, and hardcoded constants in
  `CrossFileReport.risk_score` are existing issues outside this plan's scope.
  They should be tracked separately so this work does not silently absorb them.

## 7. Decisions needed

1. **Phase 0 as its own patch release** before any feature work? (Recommended:
   yes. It is a correctness fix with user-visible output changes. A version label
   such as `3.8.10` for Phase 0 and `3.9.x` for the `[graph]` extra is a proposal.)
2. **(R2) `networkx` - core part resolved by evidence:** not in the core and not
   in Phases 0-1 (stdlib SCC, fan-in/out, bounded BFS cover them). Still open:
   the `[graph]` extra's version range against the Python 3.8-3.14 CI matrix
   (Phase 2), or vendored pure-Python versions of the two algorithms instead.
3. **Phase 3 scope**: LSP and agent guard in that order (R2); open is whether
   either belongs in this repo or in the VS Code extension track.
4. **(revised) Lazy-load the ML scorer first?** It is independent of the graph
   work, removes about 3 s of the ~3.4 s single-file call in the measured
   environment, and should be measured before an LSP is justified on latency.
   Separate change, separate release note.
5. **(revised) Graph output channel**: opt-in `graph` block in `scan --json`
   (recommended), a new `sweep` family, or both. Decides whether MCP gains
   anything (it currently has 3 tools and no graph data).
6. **(R3, closed R4) The namespace `phantom_import` false positive.** Inside
   Phase 0, as deliverable **0A** together with the shared module index. A
   narrower patch inside `python_imports.py` would add a second root rule that
   0A would then remove. (Plan and both reviews agree; overridable by the
   maintainer.)
7. **(R3, reframed R4, closed R5) Module roots.** Authority tiers E1-E4 with an
   asymmetric E4 rule: E4 withholds `phantom_import` (keeps the v3.8.7 fix and
   its pinned test) and is recorded as `conditional_internal`, but never enters
   `import_graph` unless the root is declared (packaging config, `module_roots`,
   or an explicit import path for the run). The R4 draft's "unique name -> hard
   edge" was withdrawn: uniqueness is not runtime importability (measured).
   (Plan and review agree; overridable by the maintainer.)

**Phase 0 contract status (R5): ready to freeze.** No open decision blocks 0A.
Decisions 1-5 concern release packaging and later phases.

## Appendix A - Reproduction

Baseline (current code, no repo changes required):

```bash
cd D:/Sanctum/AI-SLOP-DETECTOR
PYTHONPATH=src python - <<'EOF'
from pathlib import Path
from slop_detector.analysis.cross_file import CrossFileAnalyzer

class FA:
    def __init__(self, p): self.file_path = str(p); self.deficit_score = 0.0

SKIP = {".venv", "build", "dist", "__pycache__", "htmlcov", ".mypy_cache", "node_modules"}
for target in ("D:/Sanctum/AI-SLOP-DETECTOR", "D:/Sanctum/AI-SLOP-DETECTOR/src"):
    root = Path(target).resolve()
    files = [p for p in root.rglob("*.py") if not SKIP & set(p.parts)]
    rep = CrossFileAnalyzer().analyze(str(root), [FA(p) for p in files])
    print(root.name, len(files), "files,", sum(map(len, rep.import_graph.values())), "edges,",
          len(rep.import_cycles), "cycles")
EOF
```

Observed on 2026-10-01: root = 152 files / 1 edge; `src` = 98 files / 166 edges.

**(revised)** Paired layout fixture (acceptance test for Phase 0). Build the same
architecture twice. A mirrors the existing tests (`src` as a package), B is a real
src layout:

```bash
python - <<'EOF'
from pathlib import Path
def w(p, t): p = Path(p); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t, encoding="utf-8")
Path("arch.yaml").write_text("architecture:\n  enabled: true\n  preset: layered\n", encoding="utf-8")
for d in ("", "api/", "domain/", "data/"):
    w(f"A/src/{d}__init__.py", ""); w(f"B/src/mypkg/{d}__init__.py", "")
w("A/src/api/controller.py", "from src.domain import model\n")
w("A/src/domain/model.py",   "from src.data import repo\n")          # domain -> data: forbidden
w("A/src/data/repo.py",      "VALUE = 1\n")
w("A/src/data/loop_a.py",    "from src.data import loop_b\n")        # seeded cycle
w("A/src/data/loop_b.py",    "from src.data import loop_a\n")
w("B/src/mypkg/api/controller.py", "from mypkg.domain import model\n")
w("B/src/mypkg/domain/model.py",   "from mypkg.data import repo\n")
w("B/src/mypkg/data/repo.py",      "VALUE = 1\n")
w("B/src/mypkg/data/loop_a.py",    "from mypkg.data import loop_b\n")
w("B/src/mypkg/data/loop_b.py",    "from mypkg.data import loop_a\n")
EOF
for L in A B; do
  slop-detector boundary-violations $L --config arch.yaml --json -o out_$L.json
done
```

Observed 2026-10-02: A -> `verdict: fail`, `{layer_boundary_violation: 1}` (cycle
missed); B -> `verdict: pass`, no issues; both exit 0. Target after Phase 0: both
report 1 layer violation and 1 `import_cycle`. In the observing environment,
`slop-detector` is an editable install of this working tree (`__version__`
`3.8.9`); run `python -m slop_detector.cli` with `PYTHONPATH=src` if yours is not.

Latency method: wall-clock `python -m slop_detector.cli <file> --json` x5 after a
warm-up (history on and off); in-process, `SlopDetector()` construction and
`analyze_file` timed separately with a **unique file content per call** to bypass
the analysis cache (an unmodified file returns in 1-3 ms from cache and must not
be quoted as analysis time). A first measurement of 12 s for the first call under
`cProfile` did not reproduce in two fresh processes (about 1.3 s) and is not used.
Single machine, single run set; treat as an order of magnitude, not a benchmark.

**(R2)** Statement-shape fixture (relative, plain, deferred, type-only). Flat
layout so that root resolution is *not* the variable under test, with a decoy
top-level `foo.py`:

```bash
PYTHONPATH=src python - <<'EOF'
import tempfile
from pathlib import Path
from slop_detector.analysis.cross_file import CrossFileAnalyzer
R = Path(tempfile.mkdtemp()).resolve()
def w(p, t): p = R / p; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t, encoding="utf-8"); return p
w("pkg/__init__.py", ""); w("pkg/sib.py", "X = 1\n"); w("pkg/foo.py", "Bar = 1\n")
w("foo.py", "DECOY = 1\n")
cases = {
    "rel_with_module": w("pkg/a.py", "from .foo import Bar\n"),
    "rel_no_module":   w("pkg/b.py", "from . import sib\n"),
    "plain_import":    w("pkg/c.py", "import pkg.sib\n"),
    "func_level":      w("pkg/d.py", "def f():\n    from pkg import sib\n    return sib\n"),
    "type_checking":   w("pkg/e.py", "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pkg.sib import X\n"),
}
class FA:
    def __init__(self, p): self.file_path = str(p); self.deficit_score = 0.0
g = CrossFileAnalyzer().analyze(str(R), [FA(p) for p in R.rglob("*.py")]).import_graph
for name, p in cases.items():
    print(name, [Path(t).relative_to(R).as_posix() for t in g.get(str(p.resolve()), [])])
EOF
```

Observed 2026-10-02: `rel_with_module -> ['foo.py']` (the decoy),
`rel_no_module -> []`, `plain_import -> []`, `func_level -> ['pkg/__init__.py']`
(no `deferred` marker), `type_checking -> ['pkg/sib.py']` (no `type_only`
marker). The 1 / 166 baseline above was re-run the same day with the same result.

**(R3)** CPython semantics for `from pkg import name` (stdlib only, any
directory):

```bash
python - <<'EOF'
import sys, pathlib
def w(p, t): p = pathlib.Path(p); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t, encoding="utf-8")
w("p1/__init__.py", "name = 'attr-from-init'\n");                  w("p1/name.py", "LOADED = True\n")
w("p2/__init__.py", "");                                            w("p2/name.py", "LOADED = True\n")
w("p3/__init__.py", "from . import name\n");                        w("p3/name.py", "LOADED = True\n")
w("p4/__init__.py", "def __getattr__(n):\n    return 'dynamic-' + n\n"); w("p4/name.py", "LOADED = True\n")
sys.path.insert(0, ".")
for p in ("p1", "p2", "p3", "p4"):
    ns = {}; exec(f"from {p} import name", ns)
    print(p, "submodule imported:", f"{p}.name" in sys.modules)
EOF
```

Observed 2026-10-02 (CPython 3.14): `p1 False`, `p2 True`, `p3 True`,
`p4 False`. These map to Phase 0 rule steps 2b, 3, 2a and 4.

**(R3)** Namespace `phantom_import` pair. Create a project with
`pyproject.toml` (`[tool.setuptools.packages.find] where = ["src"]`),
`src/ns_pkg/feature/{__init__.py, api.py, use.py}` where `use.py` does
`from ns_pkg.feature import api` and calls it, and **no** `src/ns_pkg/__init__.py`.
Copy it and add an empty `src/ns_pkg/__init__.py` as the control. Run
`slop-detector --project <dir> --json --no-history -o <out>.json` on both and
count `pattern_id == "phantom_import"`. Observed 2026-10-02: namespace = 1
(CRITICAL, "cannot be resolved"), control = 0; graph edges 0 in both (src
layout). One control run first exited 1 without output and succeeded on rerun;
the failure did not reproduce and is not used as evidence.

**(R4)** Multi-portion namespace. `pyproject.toml` with
`[tool.setuptools.packages.find] where = ["root_a", "root_b"]`;
`root_a/ns_pkg/alpha/{__init__.py, x.py}`, `root_b/ns_pkg/beta/{__init__.py, y.py}`,
no `ns_pkg/__init__.py` anywhere; `root_a/ns_pkg/alpha/use.py` imports
`ns_pkg.alpha.x` and `ns_pkg.beta.y` and calls both. With
`sys.path[:0] = ["root_a", "root_b"]`, CPython imports both and
`ns_pkg.__path__` lists both roots. `scan --project` observed 2026-10-02:
2 x `phantom_import` CRITICAL (`ns_pkg.alpha`, `ns_pkg.beta`).

**(R4)** `sys.path[0]`: a `tools/show.py` printing `sys.path[0]` gives the
`tools/` directory under `python tools/show.py` and the current directory under
`python -m tools.show`.

**(R4)** Monorepo E4 and collision, via `PhantomImportPattern().check(...)` and
`CrossFileAnalyzer` (clear `python_imports._PROJECT_PACKAGES_CACHE` between
projects): the pinned-test layout (`backend/app/services/jobs.py`, root
`pyproject.toml` without package declaration) -> 0 phantom, 0 graph edges; two
children `backend/app` and `worker/app` both providing `app.x` -> 0 phantom,
0 graph edges.

**(R5)** Uniqueness is not importability. Tree: `backend/__init__.py`,
`backend/app/__init__.py`, `backend/app/services/{__init__.py, jobs.py}`,
`backend/app/main.py` containing `from app.services.jobs import run`.
Observed 2026-10-02: from the repository root, `python -m backend.app.main` ->
`ModuleNotFoundError: No module named 'app'`; from `backend/`,
`python -m app.main` -> import succeeds. Same files, same import statement, two
outcomes decided only by the launch directory.

The 187-edge, 9-community figures came from a one-off prototype (longest-prefix
module resolution, `src/` as module root, relative-import level handling,
`TYPE_CHECKING` marking, `networkx 3.6.1`, Louvain `seed=42`). It was not
committed and is a lower-fidelity estimate, not a specification. **(R3)** It
resolved `from pkg import name` "submodule first", which Revision 3 shows is not
CPython's rule, so it may include package-member false edges; it remains an
order-of-magnitude estimate only.

## Appendix B - graphify source index

Reviewed at `ef4450d` (`v0.9.73`). Paths relative to the graphify repo.

- `graphify/analyze.py` - `god_nodes`, `surprising_connections`, `_surprise_score`,
  `suggest_questions`, `graph_diff`, `find_import_cycles`
- `graphify/cluster.py` - `cluster`, `_partition`, `cohesion_score`,
  `label_communities_by_hub`, `remap_communities_to_previous`
- `graphify/affected.py` - blast-radius traversal, `DEFAULT_AFFECTED_RELATIONS`
- `graphify/cli.py` - `_run_hook_guard`, `_bash_invokes_search`
- `graphify/install.py` - `_claude_pretooluse_hooks`
- `graphify/serve.py` - MCP tool definitions
- `graphify/cache.py` - stat-signature and content-hash incremental cache
  (relevant to Phase 3 latency, not reviewed in depth)

## Appendix C - External review, per-item verdicts (Revision 2)

An external read-only review (2026-10-02) of this plan was checked item by item
before any of it was merged. Identity check: the review's SHA-256 values for
`analysis/cross_file.py` (`6c59cfb3...`) and `patterns/python_imports.py`
(`a09beac9...`) equal the whole-file hashes in the working tree, so it reviewed
the same bytes. The four graph files and `pyproject.toml` had no tracked diff.

| # | Review claim | Verdict | Evidence from this pass |
|---|---|---|---|
| R1 | Defect is module resolution, not `ast.parse` (AST-G01) | ACCEPT | Already measured (1 vs 166 edges); stated as scope line at the top |
| R2 | Relative imports are partly mis-resolved, partly omitted, not "skipped" (AST-G02) | ACCEPT, strengthened | Fixture: `from .foo import Bar` -> edge to the top-level decoy `foo.py`; `from . import sib` -> no edge |
| R3 | `ast.Import` is never handled | ACCEPT, new to the plan | Fixture: `import pkg.sib` -> no edge |
| R4 | Private `_discover_project_packages` already shared; promote, do not add a third importer (AST-G03) | ACCEPT | `operations_manifest.py:12` imports it and `_find_project_root` |
| R5 | Proposed `project_resolution.py` / `import_graph.py` / `graph_metrics.py` layout | PARTIAL | Direction adopted; names stay proposals; added the phantom-import (CRITICAL) and manifest regression requirement the review did not state |
| R6 | Keep `import_graph` shape, add `import_edges` / `graph_coverage` (AST-G05) | ACCEPT, rationale corrected | Consumers are `operations_architecture.py:135` and the public `analysis.__all__`; `CrossFileReport.to_dict()` has no in-repo consumer (`ml/pipeline.py:351` serializes a `PipelineReport`) |
| R7 | Deterministic `resolution` enum, separate `type_only` / `deferred`, do not copy graphify confidence labels | ACCEPT; PARTIAL on `external` | `external` is counted in coverage, not added as an `import_graph` edge, to keep that mapping file-to-file |
| R8 | Existing architecture tests cannot falsify the defect; nine-case matrix (AST-G04) | ACCEPT, extended | Matrix adopted; added the decoy requirement, without which mis-resolution and omission are indistinguishable |
| R9 | Graph measures are structural signals, not slop score (AST-G06) | ACCEPT | Already a guardrail; new SCC output kept out of `risk_score` |
| R10 | NetworkX floor conflicts with Python 3.8/3.9 support (AST-G07) | ACCEPT | PyPI `requires_python`: 3.1 `>=3.8`, 3.2 `>=3.9`, 3.3/3.4 `>=3.10`, 3.5 `>=3.11`; graphify `networkx>=3.4`, `requires-python >=3.10`; this project `>=3.8`, classifiers 3.8-3.14 |
| R11 | SCC is not a cycle; keep `import_cycles`, add SCC | ACCEPT | `import_cycles` consumed as an ordered path at `operations_cleanup.py:510-516` and `cli_commands.py:134` |
| R12 | LSP before agent guard; keystroke vs debounce split; no proxy to build | PARTIAL | Order and split adopted; the review does not use the measured latency, so ML lazy-load stays ahead of both |
| R13 | `3.8.10` / `3.9.x` release mapping | PARTIAL | Kept as a proposal; release numbering is the maintainer's decision |
| R14 | Line ranges `python_imports.py:225-264`, `operations_architecture.py:129-168` | Minor inaccuracy, no impact | Definitions start at 219 and 126; content cited is the same |
| R15 | graphify `ef4450d` not re-certified in the review | Resolved | Local `git rev-parse HEAD` = `ef4450d`, exact tag `v0.9.73`, clean tree |
| R16 | Edge counts treated as user-reported, not re-run | Resolved | 1 / 166 re-run on 2026-10-02, identical. The 187 figure remains a labelled prototype estimate |

Result: 16 items, 0 rejected, 4 partial (corrections to rationale or scope), 2
open questions closed by re-running checks. Accepted content is marked **(R2)**
in the body.

### Revision 3 re-review

The re-review confirmed the R2 table (16 items) and raised four new items.
Identity check: its cited SHA-256 values for this plan (`4cf6d7f5...`),
`analysis/__init__.py` (`58a1971e...`), `cross_file.py` and `python_imports.py`
all matched the working tree at the time.

| # | Review claim | Verdict | Evidence from this pass |
|---|---|---|---|
| R3-01 | The R2 `resolution` enum mixes addressing, target kind and outcome; `from . import sib` cannot be expressed | ACCEPT | Logical check holds (it is relative, a module, and resolved at once). Split into `import_scope` / `target_kind` / `resolution_state` + `type_only` / `deferred` |
| R3-02 | `from pkg import name` must check the package attribute before the submodule; "submodule first" fabricates edges | ACCEPT, refined | CPython: attribute in `__init__` -> submodule not imported (`p1`); no attribute -> imported (`p2`); `__getattr__` -> not imported (`p4`). Refinement: `from . import name` inside `__init__` binds the name *and* imports the submodule (`p3`), so it resolves to the submodule, not to a member as the review's step 2 implied |
| R3-03 | PEP 420 namespace packages are outside the resolver's scope | ACCEPT, strengthened | Discovery requires `__init__.py` (`python_imports.py:234`). Beyond the graph, a namespace project gets a **`phantom_import` CRITICAL** on a working import; the identical project with one `__init__.py` gets none. Added a negative control so namespace support cannot mask real phantoms |
| R3-04 | `import_graph` is not itself in `analysis.__all__` | ACCEPT | `__all__ = ["CrossFileAnalyzer", "CrossFileReport"]`; `import_graph` is a field of the exported `CrossFileReport`. Wording fixed; conclusion unchanged |
| - | Keep the document whole until Phase 0 evidence grows; then split to `docs/evidence/GRAPH_STRUCTURE_PHASE0_EVIDENCE.md` | ACCEPT | No split now |

Result: 4 items, 0 rejected, 2 refined or strengthened by measurement. New open
decisions 6-7 in Section 7 gate the Phase 0 contract freeze.

### Revision 4 review and necessity assessment

Identity check: cited plan SHA-256 `4a2f884a...` matched the file at that point;
`cross_file.py`, `python_imports.py` and `analysis/__init__.py` unchanged.

| # | Claim | Verdict | Evidence from this pass |
|---|---|---|---|
| R4-00 | R3-01..04 stand | ACCEPT | No contrary evidence |
| R4-D6 | Close decision 6: namespace fix is Phase 0 deliverable 0A, ordered substrate -> phantom fix -> graph resolver | ACCEPT | Matches the plan's own recommendation; recorded as 0A/0B/0C |
| R4-01 | Module roots by authority tier E1-E4; project root is neither always nor never a root; arbitrary first-level children are not roots without config evidence | **PARTIAL** | Tiers and the `sys.path[0]` premise verified. The last clause, applied literally, would fail `test_fp_reduction.py::test_monorepo_backend_package_not_flagged_as_phantom` (root `pyproject.toml` declares no package; `backend/app` is E4) and reverts the v3.8.7 fix. Adopted as asymmetric: E4 withholds `phantom_import`; E4 yields a graph edge only when its top-level name is unique, else `ambiguous`. *(Graph half superseded by R5-01: no hard edge from E4 without a declared root.)* |
| R4-02 | PEP 420 portions: index must map a name to several locations | ACCEPT, strengthened | CPython merges two declared roots into one `__path__`; the detector reports 2 CRITICAL `phantom_import` on that project **even though both roots are declared** |
| N-1 | Phase 0 is required by the detector's purpose (false CRITICAL on real code; src-layout false negatives read as clean) | ACCEPT | Both facts measured in Section 2 |
| N-2 | Phase 1 recommended, Phases 2-3 optional; graph measures are evidence, never slop score; the detector must not become a graph analyzer | ACCEPT | Consistent with existing guardrails; added as Section 1.1 and phase labels |
| N-3 | Phase 0 is better named "import evidence fidelity / project-resolution correctness" | ACCEPT | Title and Phase 0 heading changed; file name kept so existing references stay valid |

Result: 7 items, 0 rejected, 1 partial (adjusted to keep an existing,
test-pinned false-positive fix), 1 strengthened by measurement.

### Revision 5 review

Identity check: cited plan SHA-256 `cd661387...` matched the file at that point.

| # | Claim | Verdict | Evidence from this pass |
|---|---|---|---|
| R5-00 | R4 stands; R4-01 PARTIAL was right (v3.8.7 fix, pinned test) | ACCEPT | Pinned test passes today (`1 passed`) |
| R5-01 | E4 + unique name is not evidence of runtime importability; record as `conditional_internal`, keep out of `import_graph`; promote only on declared packaging root, analyzer config, or explicit import path | ACCEPT | Launch-style experiment: same tree and import succeed from `backend/`, fail with `ModuleNotFoundError` from the root. R4 rule withdrawn |
| R5-02 | Add `conditional_internal` to `resolution_state` | ACCEPT | Added, with `root_authority` on each edge |
| R5-03 | Six-case minimum RED gate | ACCEPT | Mapped onto the fixture matrix; promotion row added |
| R5-04 | Multi-portion namespace with declared roots is E1, hard-resolvable | ACCEPT | Declared in `pyproject.toml` in the measured fixture |
| R5-05 | Decisions 6 and 7 resolved; contract ready to freeze; stop document review | ACCEPT | Section 7 updated |
| R5-A1 | (added in this pass) Withholding at E4 also hides real launch-path `ModuleNotFoundError`s | NOTE | Same experiment; stated as the v3.8.7 trade-off, out of `phantom_import` scope |
| R5-A2 | (added in this pass) Omitting E4 edges recreates "empty graph reads clean" unless reported | REQUIREMENT | 0C must show the `conditional_internal` count and how to declare roots; matrix row added |
| R5-A3 | (added in this pass) Analyzer-config promotion has no existing key | REQUIREMENT | Only `phantom_import_allowlist` exists; new `module_roots` key ships with schema and docs in one commit |

Result: 6 review items accepted, 0 rejected; 3 items added from this pass's own
measurements. Document review is closed at Revision 5.

### Revision 6 review (post-implementation)

Identity check: cited SHA-256 for `project_resolution.py` (`a574f255...`),
`import_graph.py` (`89b97331...`), `operations_payloads.py` (`c892a9c...`) and
`pyproject.toml` (`a7038211...`) matched the working tree. Every finding was
reproduced before any change (CPython behaviour first, then the detector).

| # | Claim | Verdict | Evidence from this pass |
|---|---|---|---|
| R6-01 | On Python 3.8-3.10 without `tomli`, declared roots are silently ignored | ACCEPT, strengthened | With `tomllib`/`tomli` blocked, `where = ["backend"]` drops from E1 to E4. `tomli` is not declared. Also found: `operations_manifest.py:17` imports `tomli` unconditionally at module import on < 3.11, so a clean 3.8-3.10 install cannot import that module at all (pre-existing). Fix: declare `tomli; python_version < "3.11"` |
| R6-02 | Relative imports climb the filesystem, not the package hierarchy | ACCEPT | CPython: `from .. import x` in top-level `pkg/a.py` raises "attempted relative import beyond top-level package"; the detector linked it to a project-root decoy `x.py`. `pkg/sub/b.py: from .. import y` -> `pkg/y.py` is correct and kept as a positive control |
| R6-03 | `unresolved_internal` still allows a bare clean line; sweep stays `pass` | ACCEPT; PARTIAL on sweep | Reproduced: coverage `{unresolved_internal: 1}` printed "[+] No cross-file issues detected.". CLI fixed to count it. Sweep `verdict` is NOT changed (consumers read pass/fail as "issues found"); an additive `summary.graph_evidence_complete` flag carries the gap |
| R6-04 | Function-level (deferred) imports are runtime, but were removed from cycles | ACCEPT; PARTIAL on remedy | CPython: the deferred import executes when the function is called; the detector reported no cycle. `import_cycles` now excludes only `type_only` edges (which never execute). A separate import-time cycle list is Phase 1 work, not added here. CHANGELOG wording corrected |
| R6-05 | Namespace detection depends on an arbitrary depth of 4 | ACCEPT | A namespace whose first `.py` is 6 levels down imports in CPython and got a CRITICAL `phantom_import`. Fix: `phantom_import` and module probing resolve the requested path segment by segment (any directory is a namespace portion, as in CPython); the bounded scan remains only for listing top-level package names |
| R6-06 | Dynamic `__getattr__` without a submodule file resolves to a member, not `ambiguous` | ACCEPT | Reproduced (`package_member`). The package `__init__` edge stays resolved; the requested name is recorded as `ambiguous` |

Controls for each finding are written before the fix (one owner per finding).

Outcome: all six fixed in the working tree. R6-04 changed the cycle rule
recorded earlier in this document: `import_cycles` now excludes only
`type_only` edges. R6-05 removed the depth heuristic from resolution; the
bounded scan remains only for listing top-level names. Clean-install runtime on
Python 3.8 and 3.10 (R6-01) is still unverified locally and needs CI.

### Revision 7 review (post-implementation)

Identity check: cited SHA-256 for `project_resolution.py` (`dc2e9444...`),
`import_graph.py` (`83e70cc1...`) and `pyproject.toml` (`592c16d6...`) matched.
The review re-ran the 35 Phase 0 controls and 58 related tests independently
(pass) and confirmed R6-01..06 closed. Its full-suite run was blocked by a
missing `pydantic` in its own virtualenv (environment, not product).

| # | Claim | Verdict | Evidence from this pass |
|---|---|---|---|
| R7-01 | Dotted names are joined into one filesystem path, skipping CPython's segment-by-segment import (an intermediate module is not a package) | ACCEPT | `foo.py` + `foo/bar.py`, `import foo.bar`: CPython "No module named 'foo.bar'; 'foo' is not a package"; the detector made an edge to `foo/bar.py`. Multi-root: `root_a/ns/x.py` (namespace) vs `root_b/ns.py` (module): CPython binds `ns` to `root_b/ns.py` and `import ns.x` fails; the detector linked `root_a/ns/x.py`. Fix: resolve one segment at a time over a search path, CPython finder order (regular package, then module, namespace portions only when nothing else is found on any root) |
| R7-02 | The depth-4 scan still feeds shared consumers | ACCEPT, strengthened | Beyond manifest hygiene (reproduced: deep namespace -> `undeclared_import: ns`, shallow -> none), the same scan decides whether `src/` is a module root: with only a deep namespace under `src/`, E2 is lost, the graph is empty and `phantom_import` reports a CRITICAL on a working import. Fix: no depth limit; the source scan walks with pruning (skip dirs, hidden dirs) and stops at the first `.py` |

Controls for both are written before the fix.

Outcome (Revision 7): both fixed. `_find_spec` / `_resolve_chain` in
`project_resolution.py` resolve one segment at a time; `_holds_python_sources`
walks without a depth limit (pruned, stops at the first `.py`). Discovery cost
measured: 14 ms on this repository, 31 ms on graphify (429 files).

Found while verifying Revision 7, both now with owner controls:

- **A crash introduced by this Phase 0 work.** `declared_package_roots` chained
  `.get()` through `[tool.setuptools]`; with `packages = [...]` (a list, as in
  graphify's own `pyproject.toml`) it raised `AttributeError`. The old code
  hid the same chain inside a broad `try`; consolidating the TOML loader moved
  it outside. In a real scan the pattern runner swallowed the exception, exit
  code 0, and `phantom_import` silently did not run for that whole project.
  Fixed by checking the shape of every level. Control:
  `test_explicit_setuptools_packages_list_does_not_break_resolution`. Lesson
  already recorded elsewhere in this workspace: parsing is not shape, and a
  checker must not degrade to silence.
- **A mutant survived for the right reason.** After R7-02, top-level name
  listing also covers deep namespaces, so the deep-namespace control no longer
  owned `phantom_import`'s exact-path check. The check is not dead: it is the
  only thing that resolves a top-level module *file* of a root imported from
  another directory (`src/helpers.py` as `import helpers` from `src/pkg/`),
  which was a CRITICAL false positive at HEAD too. New owner:
  `test_top_level_module_file_under_a_root_is_not_phantom`.

| Check | Result after Revision 7 |
|---|---|
| Phase 0 controls | **41 / 41** |
| Full suite | **519 passed, 4 skipped** (baseline 478; +41, no regressions) |
| Mutation | 23 mutants; 22 killed by declared owners, 1 (exact-path off) re-owned by the new control and confirmed killed by it |
| Self-scan, this repo | 285 edges, 0 cycles, coverage complete |
| External repo (graphify, 429 files, flat layout) | 806 edges (HEAD 743), 4 cycles, `ambiguous` 85 (dynamic `__getattr__` exports), 1 `unresolved_internal`. Time 17.43 s HEAD -> 18.75 s; about 90 % of it is the pre-existing duplicate-function hashing, not import resolution |
| Python 3.8 / 3.10 clean install | unverified locally at this point; **verified in CI after push, see Phase 0 closure record** |

### Phase 0 closure record (2026-10-02)

| Item | Value |
|---|---|
| Commit | `8be1e73f1c3fa18e6c7754e804668b7cbd3f41ff` on `main` (parent `81219d2`) |
| CI/CD Pipeline, run 36980062239 | `completed / success`: Tests on Python 3.8, 3.9, 3.10, 3.11, 3.12; Black, Ruff, MyPy; Self SLOP Detection; JS/TS, Go, Rust, NPM wrapper; Docker build |
| AI Code Quality Gate (Fixed), run 36980062288 | `completed / success`: Quality Check (Basic), Quality Gate (Threshold), PR Analysis Comment |
| Pre-push check | the same 11 files on a clean HEAD worktree: 512 passed, 4 skipped, ruff and black clean (the working tree's 519 includes 7 tests from unrelated uncommitted edits) |
| Revisions closed | R2-R7 (review verdict tables in Appendix C and in the Revision sections) |
| Release | **none**. No version bump, no tag. Behaviour changes are recorded in CHANGELOG `[Unreleased]` |

What the CI gate settled: the `tomli` declaration for Python < 3.11 works on
clean 3.8 and 3.10 installs, declared multi-portion namespace roots resolve
there, and `operations_manifest` imports without an undeclared `tomli`.

Non-blocking deferred items after Phase 0 closure: the three deviations above;
none re-opens the Phase 0 gate. Items 1 and 2 are recorded decisions to leave
as they are; only item 3 (three documents) is unfinished work. Not covered by
CI or by any test: real-world layouts beyond the fixtures and the two
repositories measured.

Policy recorded with this closure: a review that repeats findings already closed
at a newer commit is checked against the current commit and hash once; it is not
re-opened unless the code bytes or the evidence changed.
