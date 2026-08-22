# CuraFrame Revalidation — Current Baseline

**Date:** 2026-08-21
**Detector:** AI-SLOP-Detector v3.8.8, local commit `c869a29`
**Target:** CuraFrame `governance/verdict-ledger`, commit `b891ad9`
**Method:** default project scan, JSON evidence review, source inspection, and the
target test suite. This document records observed behavior. It does not claim an
independent precision benchmark.

---

## Executive Result

The earlier statement of approximately 40% was an **audit-subset yield**, not a
global detector precision claim:

```text
Manually reviewed CuraFrame audit items: 7
  confirmed actionable: 3
  false positive:       3
  informational:        1
```

That is `3 / 7 = 42.9%` when the informational item remains in the denominator.
It must not be reused as a precision score for every detector finding.

The current baseline produces **60 emitted pattern findings at 42 source
locations** across 27 scanned Python files. Several emitted rows describe the
same source location: eight locations each produce the `god_function`,
`deep_nesting`, and `nested_complexity` trio. Counting all 60 rows as
independent defects would inflate both failure and success rates.

The current project result is also misleading:

```text
overall_status:          clean
weighted_deficit_score:  26.80
pattern findings:        60
critical findings:       10
findings in clean files: 29
critical findings in clean files: 1
excluded Python test files: 10
```

The target suite produced `177 passed, 1 failed`. The failing test imports
`streamlit`, which is declared in `requirements.txt` but absent from the active
environment. This matters when interpreting the detector's `phantom_import`
output.

---

## Rechecked Finding Families

| Family | Current count | Revalidation | Evidence and interpretation |
|---|---:|---|---|
| ML scorer unavailable | capability-wide | **Confirmed P0** | The shipped model uses `type` / `features` / statistics keys while `SlopClassifier.load()` requires `model_type` / `rf_model` / `xgb_model`. The loader logs and returns `None`; reports do not surface unavailable ML scoring. |
| Hidden project findings | 29 hidden rows | **Confirmed P0** | `renderer_text.py` only renders file details when `status != clean`. The text surface therefore omits findings in clean-status files. |
| Silent test exclusion | 10 target test files | **Confirmed P0** | Default ignore rules exclude `tests/**` and `test_*.py`; the report does not state the exclusion envelope. |
| Clone clusters | 2 | **Confirmed false positives** | `comparators.py` contains intentional symmetric comparator functions. `constraints_library.py` contains domain-specific declarative constraint factories; the current histogram ignores their names, constants, provenance, and comparator targets. |
| Protocol/fallback placeholders | 5 | **Confirmed false positives** | `CandidateProtocol` uses `...` intentionally. The SQLAlchemy fallback in `apps/web/db/database.py` uses a minimal compatibility `Session`, `configure()`, and `__exit__`; `__exit__ -> False` is required context-manager semantics, not a stub. |
| Optional/dependency imports | 8 | **Misclassified; not all false** | `streamlit`, `psycopg`, and `psycopg-pool` are listed in `requirements.txt`, but `pyproject.toml` has no dependency metadata. This is a packaging-metadata concern and one active-environment failure, not proof of a phantom import. The current `phantom_import` category and severity overstate the evidence. |
| Complexity family | 35 rows / 19 locations | **Actionable candidates, not confirmed defects** | The composite pattern emits three rows for eight locations. `core.evaluate` (157 lines, CC 29) and several advisor functions are credible maintainability targets. Endpoint handlers and the Streamlit modifier require context-sensitive review before being called slop. |
| Lint escapes / empty except | 10 | **Informational review signals** | Some are deliberate best-effort boundaries, including the governance ledger recorder. A suppression is not automatically a structural defect. |
| Docstring boundary | fixture repro | **Confirmed wording/threshold defect** | `ratio == 1.0` currently enters the warning band while the message says "more documentation than implementation." |

---

## What The Recheck Proves

1. The reporting issues in T-1, T-2, and T-6 are genuine trust defects. They
   affect how a human interprets the scan, regardless of any individual pattern's
   precision.
2. Clone detection has confirmed domain-appropriate false positives in CuraFrame.
   The required fix is a discriminating signal plus a corpus, not another
   filename-based exception.
3. Dependency findings need three separate states:
   `unavailable in this runtime`, `declared outside pyproject metadata`, and
   `not declared anywhere known`. The current one-label `phantom_import` result
   collapses them.
4. The current `clean` project status is only a weighted deficit classification.
   It is not a statement that no pattern findings exist or that the whole tree
   was scanned.

---

## Required Measurement Contract Before Claiming Improvement

The existing `red_t2`, `red_t5`, and `red_t6` scripts prove that files or
findings exist, but they cannot become green after a reporting-only fix. Their
exit conditions must be replaced before using them as release gates.

| Case | Correct green contract |
|---|---|
| T-1 | A deliberately incompatible model yields `ml_scoring.status=unavailable`, an actionable reason, and a non-silent gate capability state. |
| T-2 | Default JSON/text expose excluded count and reason; `--include-tests` analyzes default-excluded test files without disabling unrelated artifact excludes. |
| T-3 | `4 / 4` follows the chosen documented policy and its message uses the same comparison semantics. |
| T-4 | A labeled corpus measures both intentional comparator/factory/interface cases and real copied logic; report qualified method names. |
| T-5 | JSON/text show a coverage envelope split into analyzed, opt-in supported, excluded, and unsupported candidate files. |
| T-6 | Text and JSON expose identical aggregate pattern totals and severity counts, independent of file deficit status. |

---

## Release Recommendation

Treat `3.8.9` as a trust-and-measurement release:

1. Land T-1, T-2, T-5 disclosure, T-6 aggregate visibility, and T-3 boundary
   semantics first.
2. Build the CuraFrame cases above into a labeled clone/dependency corpus.
3. Change clone and dependency classification only after the corpus provides both
   false-positive and true-positive controls.
4. Publish a new result as separate metrics: reporting coverage, capability
   availability, root-cause precision, and actionability. Do not publish one
   aggregate "accuracy" percentage.
