# AI-SLOP Detector Roadmap

> Last updated: 2026-11-26 (after v3.18.1)

## North Star

**Finding slop, and helping fix it.**

When AI-SLOP Detector says code is hollow, a developer or a coding agent can
check the evidence, fix the code, and prove that the problem, not just the
warning, is gone. How often that verdict is right is measured on code the tool
was not built on, against labels written by people.

| Value | What it means |
|---|---|
| Detect | Find code that looks finished but does not do what it says: stubs, ignored inputs, failures reported as success, promises the body cannot keep |
| Explain | Show the source, the rule, what was measured and what was not |
| Fix | Hand a developer or an agent a concrete, bounded work item |
| Verify | Re-measure after the change and tell a real fix from a suppressed, deleted or unmeasured one |

Independent validation underpins all four.

A change is worth making when it does one of these:

1. catches a real hollow case the shipped detector misses;
2. removes a documented false accusation without hiding real hollow code;
3. makes a fix verifiable that was not before;
4. enables a bounded behavior check that does one of the above.

Count verified true findings and false alarms separately, and never optimize a
score without reading the changed source cases.

**Not the goal:** more rules for their own sake, or replacing ESLint, go vet,
Staticcheck, Clippy or Semgrep. Those tools check style, types and known bug
patterns; this one checks whether an implementation does what it claims, and
works alongside them.

---

## Where it stands (v3.18.1)

How deeply each language is read today:

| Level | Meaning |
|---|---|
| L0 lexical | text, regular expressions, tokens |
| L1 syntactic | a parse tree: functions, declarations, scopes |
| L2 semantic | symbols, imports and calls resolved, types where available |
| L3 behavioral | control and data flow, effects across functions |

| Language | Default reader | With the extra | Level |
|---|---|---|---|
| Python | `ast` | — | L1, with bounded L2/L3: hollow review channel (effects within a module), call resolution, import provider resolution |
| JavaScript / TypeScript | regex | `[js]`: tree-sitter, all 8 rules | L0 / L1 |
| Go | regex | `[go]` installs tree-sitter-go, which the analyzer does not use yet | L0 |
| Rust | token scanner | `[rust]`: tree-sitter | L0 / L1 |

The remediation building blocks exist: the AI work order, source binding by
SHA-256, `prove_state` (`FIXED_CANDIDATE`, `HOLD`, `PERSISTS`), `fp:`
declarations and `review --base`. What is missing is the loop that connects
them for an agent, and an MCP server that follows the specification (the
current `slop-detector mcp` frames messages with `Content-Length`; see the
README).

---

## Now: v3.19 — Agent remediation loop

The goal is an agent that can take a finding, fix it, and get an independent
answer to "is it fixed?". MCP is the delivery channel; the value is the
contract behind it, shared by the CLI, JSON, the work order and VS Code.

- **MCP server on the official SDK** as an optional extra; the base install
  and its Python range stay as they are. A missing SDK or Python version is an
  explicit error, not a silently empty server. Tested with a real client over
  stdio.
- **Before/after verification** built on the existing work order and
  `prove_state`, not a parallel engine. A disappeared finding is not proof.
  The receipt separates a fix from:
  - a suppression added (config, inline comment, `fp:` without approval);
  - the code removed or the function deleted;
  - a smaller scan (excluded paths, fewer files, a narrower include);
  - a file that no longer parses or could not be measured;
  - a new finding introduced by the change.
- **Evidence completeness per finding**: what was measured, what was not, and
  what stayed unknown, using the existing measurement states.
- **Adversarial checks**: deliberate fake fixes (weakened assertions, deleted
  paths, renamed functions, catch-all success, disabled rules) must not come
  back as fixed.
- The tool never edits code or opens pull requests; the agent patches, a
  person approves.

**Acceptance:** the loop runs end to end on real repositories with the
resolution rate measured, every planted fake fix is caught, and CLI and JSON
output stay compatible.

---

## Next

Each step moves on when its acceptance check passes, not on a date.

### v3.20 — JS/TS hollow analysis

Bring the Python hollow review concepts (success without effect, input never
used, failure reported as success, promises the body cannot keep) to JS/TS on
the existing tree-sitter path, with JS/TS semantics rather than translated
Python rules. Regex stays as the fallback for files that do not parse, and the
report keeps saying which reader ran.

**Acceptance:** replay on real JS/TS repositories, every changed finding read
in its source, genuine implementations not flagged, and the regex-era false
alarms not replaced by new ones.

### v3.21 — Go structural analysis (L0 to L1)

Connect tree-sitter-go, which the `[go]` extra already installs, and move the
applicable Go rules from text to structure (ignored errors, empty functions,
panics). Syntax alone does not prove what a type implements or whether an
error is handled elsewhere: such cases stay unknown or unscored candidates.
Type information (go/types) is prepared as a later, optional mode.

**Acceptance:** the parser path is used for real files, every existing Go
contract is preserved, and false alarms are compared against the regex reader.

### v3.22 and later — semantic deepening

Optional type, symbol, control-flow and effect evidence for JS/TS and Go where
it measurably improves findings. Rust deepens when there is demand and the
capacity to validate it. Toolchains, dependency downloads and build-time code
(build scripts, proc macros) stay outside the default analysis.

### v4.0 — Evidence-driven remediation

Declared when, and only when, all of these hold: meaning-level analysis in
Python and at least two more languages (a parser alone does not count), the
remediation loop validated on real repositories, and independent evaluation
results published. Not a rule count.

---

## Independent validation (from v3.19, every release)

Evaluation data is prepared before the analyzers it will judge, so it cannot be
chosen to suit them.

- **Public benchmark**: publication-safe code (permissively licensed public
  repositories chosen for this purpose, and synthetic cases), labels written
  and reviewed by people, the method and scripts, and per-rule results anyone
  can rerun.
- **Private holdout**: kept unpublished to prevent tuning to it; only
  aggregate results are reported.

What is measured, starting from a baseline rather than a target picked in
advance:

| Area | Measure |
|---|---|
| Detection | precision, recall, F1 per rule |
| Coverage | share of code the tool could judge; share left unknown |
| Remediation | verified fixes / fix attempts; fake fixes caught; new findings introduced |
| Evidence | findings bound to source and scan state |
| Reproducibility | identical results under fixed conditions |
| Cost | time, memory, install size |
| Usefulness | fixes developers accept |

---

## Earlier plans

The 3.13 to 3.18 plans are done: the hollow review channel and docstring
promises (3.14), report identity and source binding (3.14 to 3.15), Go, JS/TS
and Rust in the CI gate (3.15 to 3.16), the developer screen (3.17), import
provider resolution (3.18). The CHANGELOG records what each release changed.
Two older ideas remain open, behind the work above:

- **Evidence-gated work protocol** (after the 3.19 loop exists and is
  measured): each work item asks the agent to verify the finding with a
  citation and predict the outcome before patching, then explain any
  disagreement with the tool's before/after receipt; the receipt, not the
  agent's account, decides the state. An external harness would measure
  wrong-patch rejection and false acceptance. It enters the product only if it
  lowers false acceptance without adding a bottleneck.
- **Native acceleration** on measured hot paths only, with Python keeping
  semantic authority.

---

## Guardrails

These rules stay fixed while the roadmap evolves.

- Extend existing contracts (JSON, CLI, work order, measurement states) before
  inventing new ones; keep one engine behind every interface.
- The default analyzer stays light and offline; deeper analysis is opt-in.
- Absence that was observed and evidence that is missing are different
  results; an unverified candidate is never promoted to a scored finding.
- Keep the math model and enforcement policy separate.
- Preserve canonical CLI simplicity: `scan`, `review`, `pulse`, `sweep`.
- People decide on source changes and releases; the tool measures.
- Never install or declare a package an agent suggests without a person
  confirming which package was meant.
- Treat self-dogfood regressions as product regressions.
- Use native acceleration only for measured hot paths.
