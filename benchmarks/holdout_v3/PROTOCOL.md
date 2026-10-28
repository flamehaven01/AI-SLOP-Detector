# Hold-out v3 protocol

Fixed before any v3 repository is searched, cloned, labeled or scanned, and
before the detector version under test is chosen. v3 is the independent
measurement for the work that follows hold-out v1 and v2, both of which are
development data now (v1: recall 1/9 -> 7/9 after its fixes; v2: 3/12 before
and after them).

## 0. Order of work

1. This protocol is committed.
2. Rule work (P0 placeholder/stub semantics, P1 structural contract
   violations) uses only v1, v2, the recall corpus and the replay
   repositories.
3. The detector under test is frozen: one commit SHA, recorded with its source
   digest before any v3 function is drawn. The labeler, who is also the rule
   author, sees no v3 code before this point, so no rule can be fitted to it.
4. Frames, selection, snapshots, draw and labels (sections 1-5); labels are
   committed before any scan.
5. One scan and one score (sections 6-8). No rule change is made on v3 results;
   once results are read, v3 is development data too.

## 1. Tiers

| Tier | Role | Population |
|---|---|---|
| A+B | primary | Python repositories on GitHub, created on or after 2025-01-01, drawn from star bands as in v2 (A 100-5000 stars, B 10-99 stars) |
| AI_ASSOCIATED | auxiliary | repositories from the same frames that carry a predefined AI-tool signal (section 2) |

AI_ASSOCIATED says that a repository shows signs of an AI coding tool, not
that any function in it was written by one. It is reported separately and is
never pooled with A+B into a headline figure: selecting on a signal is itself
a selection, so its rates describe that population only.

## 2. AI_ASSOCIATED signals (metadata only, decided from the commit tree and log)

A repository carries the signal when, at the snapshot commit:

- its tree contains a file named `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`,
  `.cursorrules`, `.windsurfrules`, `.clinerules`, `.github/copilot-instructions.md`,
  or any path under `.cursor/rules/`; or
- one of its last 100 commits carries a `Co-Authored-By:` trailer naming an AI
  coding assistant (Claude, Copilot, Cursor, Gemini, Codex, Devin, Aider).

The signals are read from the GitHub tree and commits APIs before selection;
code content plays no part. Each selected repository records which signals it
carries, and results are broken down by signal family (instruction file vs
commit trailer).

## 3. Frames, exclusions, selection

- Frames: the v2 method (`benchmarks/holdout_v2/build_frames.py`), 8 star bands,
  20 windows per band, 10 drawn, 50 results per window, with the seed
  `holdout-v3` plus the snapshot date, which is recorded.
- Exclusions: the private exclusion list (rebuilt on the snapshot date), every
  v1 and v2 repository and every repository walked in v2 selection, forks,
  archived repositories, sizes outside 100 KB - 80 MB, lists, fewer than 10
  Python files, and the stated-purpose safety rule of v2 (LICENSE_BYPASS,
  PIRACY, AUTO_TRADING; REVIEW_REQUIRED not judged).
- A+B: per band, eligible repositories in sha256(seed + full name) order,
  ignoring the AI signal; 2 primary and 1 reserve per band (16 + 8).
- AI_ASSOCIATED: the eligible repositories carrying a signal that A+B did not
  take, pooled over all bands and walked in the same hash order; 16 primary and
  16 reserve. A band contributing more than 4 primaries is capped at 4 and the
  walk continues, so no star band dominates.
- Lineage: before labeling, a function whose body (AST, 40 nodes or more)
  occurs in any repository on disk, v1 and v2 snapshots included, is dropped
  and redrawn.

## 4. Snapshots and source binding

As v2 (`benchmarks/holdout_v2/PROTOCOL.md` section 2): sparse snapshots of
`*.py` and project configuration at one commit, no history, submodules, LFS,
filter drivers, symlinks or line-ending conversion; completeness against the
commit tree; receipts with commit, tree paths and file SHA-256. At labeling,
each repository's HEAD and dirty count and each function's file and function
SHA-256 are recorded; scoring refuses to run when any differs. Cloning needs a
separate approval.

## 5. Draw and labels

- Per repository: R 8 random functions and S 16 short functions (at most 5
  statements after the docstring), seeded per repository, as v2.
- Positives: the primary target is 30 hollow labels in AI_ASSOCIATED. If its
  primaries give fewer, its reserves are drawn and labeled, in order, until
  the target or the end of the reserves. A+B is not extended: its recall is
  reported with its count and interval, however small. No stratum or
  extension is chosen by words or structures in the code.
  Derivation of 30: at a recall near 0.5 the Wilson 95% half-width is about
  0.17 with 30 positives and about 0.25 with 11. Applying v2's rates as a
  planning figure only (v2 was not selected by AI signal, so its rate is not
  evidence about AI_ASSOCIATED): the 768 AI_ASSOCIATED functions would give
  about 11, and A+B's 384 about 3 (4/557).
- Sizes are fixed: A+B 384 functions (16 repositories), AI_ASSOCIATED at most
  768 (16 primary and 16 reserve repositories). 30 is a target, not a
  condition: a shortfall after the reserves is reported as it is, and no
  repository is added after labeling or scoring has begun.
- A+B with few positives: its recall is exploratory (count, Wilson interval,
  every missed function listed) and is not release evidence for a recall
  claim. A+B is read for false alarms: their number, patterns and fix
  direction.
- Classes and rules: v1's (`benchmarks/holdout/labels.json` meta). A hollow
  label names exactly what is fabricated, ignored or unchecked, and records
  its evidence kind:
  - STATIC: a line-level fact confirms it (a constant or canned return, a
    parameter never read, a computed value discarded, a failure swallowed
    before a fabricated value, `raise NotImplementedError` on a promised path);
  - SEMANTIC: it needs the meaning of names or docstrings (a sample count
    that counts files, a mail sent to nobody).
- UNCLEAR is counted and excluded from rates.
- Labels are written from the source with no detector output and committed;
  the commit SHA and file SHA-256 go into the receipt.

## 6. Detection

Full CLI, `--project --json --read-only`, empty home, on each snapshot, at the
frozen detector commit. The scored set is v1's eight hollow patterns plus
every hollow-detection pattern the frozen version adds, listed in the scorer
before scoring; the eight-pattern score is reported as well.

## 7. Measurement states

MEASURED, SOURCE_INCOMPLETE, ENV_BLOCKED (including a CLI exit code other than
0), NOT_MEASURED, as v2. Only MEASURED functions are scored. More than 10% of
a tier's functions excluded makes that tier's result invalid.

## 8. Report

Per tier, and per stratum and class within it:

- recall and false-alarm rate with the Wilson 95% interval and a
  repository-level bootstrap (2000 draws, fixed seed), the bootstrap marked
  not informative when the observed rate is 0 or 1;
- false alarms per stratum first: S takes 16 short functions per repository
  and R 8 at random, so short functions are over-represented and a tier total
  is a figure of this sample design, labelled as such, not the rate over all
  Python functions; R alone is the closest to that rate;
- recall split by evidence kind (STATIC, SEMANTIC); a SEMANTIC miss is
  reported as an analysis limit, not as a rule target;
- per pattern: true and false flags; hollow functions per repository;
- every flagged or missed function with the evidence line and the fix
  direction.

## 9. Evaluation receipt

One JSON file binds: the detector commit SHA and source digest, the scorer
SHA-256, this protocol's SHA-256, the frame, selection, receipt and label
digests, the result digest, and the private-store digests if any. AI_ASSOCIATED
and A+B are public repositories, so v3's labels and results are published in
full; nothing in v3 depends on a private repository list except the exclusion
list, published as a digest.

## 10. Reuse

v3 is scored once. A rule change made after its results are read makes v3
development data, and the next independent measurement needs a new draw.
