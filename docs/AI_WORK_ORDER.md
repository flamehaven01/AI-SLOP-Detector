# AI work order (`--format ai-md`)

The AI work order is a Markdown document written for an AI agent or reviewer,
not for a person skimming a report. It holds everything an agent needs to
verify each item, fix or reject it, prove the fix and report back, and it
states what the agent may and may not do. It is built from the same records as
the AI report (`--format ai`, JSON Lines), so both have the same items, ids and
bindings.

| Output | Reader | Use it for |
|---|---|---|
| terminal, `report.md`, `report.html`, `report.pdf` | a person | what matters in one screen; see [REPORTS.md](REPORTS.md) |
| `--format ai` (`ai-report.jsonl`) | a program | one validated JSON record per item |
| `--format ai-md` (`ai-report.md`) | an agent | a work order: rules, evidence and a response form in one document |
| `--json` (`scan.json`) | a program | the full result |

## Producing it

```bash
# auditor work order (the default mode): evidence excerpts, read-only
slop-detector --project . --format ai-md -o ai-report.md

# agent work order: no code copied, holds until its preconditions pass
slop-detector --project . --format ai-md --ai-mode agent -o ai-work.md

# auditor work order within an estimated token budget
slop-detector --project . --format ai-md --ai-token-budget 32000 -o ai-report.md

# every output at once; the bundle writes the auditor work order
slop-detector --project . --report-dir slop-report
```

The work order for `examples/demo_project` is reproduced in part below.

## Two modes from the same records

| | auditor (default) | agent |
|---|---|---|
| purpose | evaluate the evidence of each item | verify, fix or reject, prove and report each item |
| authority | read-only: no file of the target is changed, no code or test from it is run | none granted by the document: changes need the operator's approval for this work order |
| code | the analyzed code of each item's span, with line numbers | none copied; each item names the span to open and the check to make first |
| preconditions | none | P1-P4 (below), each starting `NOT-MEASURED` |
| allowed | read, judge each item TP / FP / UNSURE | after P1-P4 pass: edit inside the item's span, add a test that proves the fix, reword a docstring for `claim_without_mechanism`; splitting across files or changing dependencies needs a decision first |

Agent preconditions:

```
P1 the target repository is readable at the paths of this document NOT-MEASURED
P2 sha256 of the file of every worked item equals its bound_to NOT-MEASURED
P3 the operator approved changes to the target for this work order NOT-MEASURED
P4 an approved test profile exists for PROVE NOT-MEASURED
rule: each precondition starts NOT-MEASURED; any FAIL or NOT-MEASURED -> HOLD every item, do not partially proceed
```

The detector does not measure P1-P4; the agent or its operator does. Both
modes print the same items, ids, bindings, score, measurement table, rules,
backlog and response form.

## Layout

| Section | Tag | Content |
|---|---|---|
| header | | the format (`ai-slop-work-order/2`, items from `ai-slop-report/1` records), tool and engine version, target, score, item counts, the ruleset id and digest, the mode |
| CONTRACT | `[FORMAT]` | precedence, tag meanings, empty values, the per-item loop, how an item is invalidated, how a fix is proved |
| AUTHORITY, PRECONDITIONS | `[NORM]` | what the mode allows; the agent's P1-P4 |
| HARD-STOP, FORBID, INVARIANTS, ALLOWED | `[NORM]` | when to stop, what never to do (suppression comments, threshold or config changes, deleting a function to make its item vanish), what always holds |
| LIMITS | `[FACT]` | what the document cannot show |
| MEASUREMENT | `[FACT]` | per channel: state and denominator (files, functions, docstring promises) |
| RULES | `[NORM]` | one VERIFY question per rule present in the work order |
| FILES | `[FACT]` | every file of the work order once: `B01`, its scan-time SHA-256 and its binding; items point to their file's row |
| WORK-ORDER | | families in order (critical, high, review candidates, medium, low); in each family, one block per item |
| BACKLOG | | items beyond `--ai-limit` or below the token budget, one index line each |
| RESPONSE-FORM | `[FORMAT]` | one line per item worked, then a summary line |

Tags: `[FACT]` is measured by the detector; `[DERIVED]` is the detector's fix
direction (advisory); `[NORM]` is a rule for the agent; `[NULL]` is measured as
nothing. An empty value is never left blank: it reads `NOT-MEASURED`,
`NOT-APPLICABLE: <why>` or `MISSING`.

## One item

```
## FILES [FACT]
- B01 binding:MATCH sha256:df9a47d1...de64b48a file:orders/pricing.py

## WORK-ORDER
### G03 REVIEW_CANDIDATE claim_without_mechanism review | items 1
family [FACT]: same kind, rule, severity, fix, channel and evidence shape: total_parallel: promises <n> (parallel); no call that could run concurrently
channel [FACT]: MEASURED
fix [DERIVED]: implement the mechanism, or change the docstring to what the function does

#### W03 C56ca6a2c17eb REVIEW_CANDIDATE claim_without_mechanism review
at [FACT]: orders/pricing.py:7
locator [FACT]: (the symbol itself) semantic_key=8ba21dc309b8b5f1
bound_to [FACT]: B01 (the file is the content the scan analyzed)
evidence [FACT]: total_parallel: promises "Sum the order values in parallel." (parallel); no call that could run concurrently
promise [FACT]: "Sum the order values in parallel." (docstring line 8, parallel; basis no_concurrent_call)
verify [NORM]: the body needs a concurrent call (pool, thread, process, task) or an await; found: no call that could run concurrently. ACK: implement the mechanism, or change the docstring to what the function does; REJECT: name the mechanism the detector missed (file:line)
span [FACT]: orders/pricing.py:7-12 `total_parallel`
 7| def total_parallel(values):
 8|     """Sum the order values in parallel."""
 ...
```

(The SHA-256 is shortened here; the document prints all 64 characters. A
path comes last on a FILES row and an index line, since it may hold spaces.)

- **id**: `F` for a pattern finding, `C` for a review candidate, then 12 hex
  characters of the SHA-256 of the semantic key and the locator.
- **semantic_key**: what the item is: kind, rule, file path, enclosing symbol,
  subject (the parameter, module, member or clone group it names) and the text
  of its line. It has no line number, so blank lines and comments added
  elsewhere keep the id.
- **locator**: which copy, in this snapshot: the statement path inside the
  symbol (`body[0]/handlers[0]`). A comment is addressed by the statement after
  it (`body[1]~before0`) or before it (`~after<k>`). Two identical blocks in
  one function get different locators. JS/TS and Go items use the line, so a
  line shift moves them; two findings of one rule on one line add the column
  (JS/TS, `L38C12`) or their order on the line (Go, `L7#2`).
- **cause_key** (in the JSON Lines record): kind, rule, path, symbol and
  subject without the line's text; a reworded TODO keeps it.
- Two items with the same id are a defect: the report fails closed instead of
  numbering them.

## Families

Items are grouped for display: a family holds the items that share kind,
rule, severity, fix, channel state and evidence shape (the evidence sentence
with quoted names and numbers replaced, so `returns constant 0.1` and
`returns constant 0.3` share a shape and `returns constant 'x'` does not).
Severity stands in for a fix-risk tier, which the detector does not compute
yet. The family header states the shared fix and channel once; every item
keeps its own block (id, location, locator, binding, evidence, promise,
code), its own verdict and its own response line. One component differing
makes another family.

The work order is lossless, and the renderer checks it before writing:
reading the document back, every item appears exactly once and every field
it shows equals its record: in an item block the kind, rule and severity,
the file and line, the locator and semantic key, the evidence and the
promise; on an index line the severity, rule, file and line. Each is bound to
its file's scan-time hash through FILES, under a family whose fix and channel
are its own, and the family counts add up. A document that fails any of these is refused (`the work
order is not lossless`), and nothing is written.

## Bound to the scanned bytes

Each file's SHA-256 is taken from the bytes the scan analyzed, at scan time
(`source_sha256`, with `content_origin` `file_bytes` or `string_utf8`). The
work order never reads the file again to fill it in.

| binding | meaning | the item |
|---|---|---|
| `MATCH` | the file on disk still has the scanned content | shown with its code (auditor) |
| `VOID HOLD` | the file changed after the scan | no code shown; HOLD it, re-scan |
| `MISSING HOLD` | the result has no scan-time hash (an older cached result) | no code shown; HOLD it, re-scan |

A cache hit is used only when its stored hash equals the file's current hash.

## Proving a fix

PROVE re-scans the item's file with the same configuration. `prove_state`
compares the item before and after:

- `HOLD` when the item's symbol is gone, the match is ambiguous, or its
  `cause_key` is still there as often as before (the violation was reworded).
- `PERSISTS` when its id is still there, or its `semantic_key` appears under
  another id as often as before (the code moved; a locator is an address in
  one snapshot).
- `FIXED_CANDIDATE` only when its `semantic_key` and its `cause_key` both
  appear fewer times and every other item sharing them kept its id, or none is
  left. A fix still needs the project's tests to pass with no new item.

## The ruleset

Every rule text of the work order (contract, hard stops, forbid list,
invariants, VERIFY questions, the two modes) comes from
`slop_detector/config/work_order_rules.json` (schema
`ai-slop-work-order-rules/2`). The header prints its id and a SHA-256 of its
canonical JSON, so a rule change changes the digest and a reformat does not.
The schema is strict (unknown keys, empty text, a rule in two families and a
missing mode are rejected). A missing or invalid ruleset fails every AI report
closed; there is no built-in fallback text.

## Token budget (auditor)

`--ai-token-budget N` fits the auditor work order in N estimated tokens.
Tokens are estimated as characters / 4; this is not a tokenizer count, and the
header says so.

| tier | an item is drawn as |
|---|---|
| T1 | the whole function (its AST span) |
| T2 | the signature, the evidence lines and the range to read |
| T3 | one index line: id, severity, rule, its FILES row (SHA-256 and binding), channel, location |

Every item gets at least its index line; none is left out. Items are
allocated in priority order, breadth first: every item gets its evidence form
before any item gets more, and both passes stop at the first item that does
not fit. An item's evidence form is the cheaper of T2 and T1: for a short
function the whole body costs less than the excerpt with its range to read,
and it carries the same evidence, so such an item is drawn whole wherever it
stands. The second pass upgrades the remaining T2 items to T1. The rendered
document is then checked against the budget; when it is over, the last T1
whose excerpt is cheaper gives way to T2 before any item loses its evidence. A budget smaller than the index of every item is
refused with `BUDGET_UNSATISFIABLE` and the least budget that would hold, and
nothing is written:

```
[!] BUDGET_UNSATISFIABLE: the index of every item needs at least 2264 estimated tokens; the budget is 1500; nothing was written
```

`--ai-limit N` (N full blocks, the rest as backlog lines) and
`--ai-token-budget` bound the document in two different ways; giving both is
refused. Without either, the work order holds every item in full.

## Repository text

Text that comes from the analyzed repository (evidence, fix, promise, file
path, target name) is printed on one line; a line break in it is shown as a
visible `\n`, so repository text cannot open a section of the work order. Code
excerpts cannot close their fence either, because every excerpt line starts
with its line number.

## Limits

- A review candidate (`REVIEW_CANDIDATE`) is evidence for a review, not a
  defect, and never moves the score.
- An excerpt may not show the whole span; a "not shown" line names the range
  to read.
- JS/TS and Go locators are lines.
- The token estimate is characters / 4.
- The detector does not check the agent's preconditions or its response; the
  response form only makes the answer comparable.
