# Hold-out v2 protocol

Fixed before any repository below is cloned, labeled or scanned. It measures
the detector on code that no rule was built from, including the rules written
from the v1 misses.

## Status of v1

`benchmarks/holdout/` (180 functions, 3.12.0 baseline: recall 1/9, false alarms
5/170) is frozen and is development data from now on. Its misses may become
rule fixtures; its numbers are never reported again as an independent result.

v1 erratum: H157's note says the AI output is ignored. It is kept in
`ai_response`; what is canned are the `pages`, `tech_stack` and `features`
fields the docstring says the AI produces. The label (HARDCODED_RESULT) stands.

## 1. Repositories

- Exclusions (from `build_exclusions.py`): every GitHub remote of a checkout
  up to three levels under the workspace, normalized to `owner/repo` (HTTPS,
  SSH and `ssh://` spellings alike); every directory name there and in the
  external-repository folder; the v1 repositories; and the author's own
  accounts, excluded entirely. The list names local and private repositories,
  so it is kept in the private store; `exclusions_digest.json` publishes its
  SHA-256 and counts.
- Frames (`frames/<band>.json`, from `build_frames.py`): GitHub search, Python,
  created on or after 2025-01-01, metadata only. Tier A bands 100-499,
  500-999, 1000-1999, 2000-5000 stars; tier B bands 10-19, 20-39, 40-69,
  70-99. Each band is cut into 20 equal star windows and 10 windows are drawn
  (seed `holdout-v2-20261026`); each window's first 50 results are kept. This
  replaces the first frames (top 200 by stars, which only reached the top of
  each range).
- Selection (`select_repos.py` -> `repos.json`): drop forks, archived
  repositories, sizes outside 100 KB - 80 MB, lists, and excluded owners, names
  and `owner/repo`s; order each band by sha256(seed + full name); 2 primary and
  1 reserve per band. A band short of eligible repositories records the
  shortfall and does not borrow from another band.
- Walk: each band is walked in hash order; a repository the safety rule below
  excludes, or whose commit tree has fewer than 10 Python files
  (`estimate.json`), is skipped with its reason and the next one is taken.
  After clone, a primary whose scan is not COMPLETE is replaced by its band's
  reserve.
- Lineage: before labeling, every sampled function's whitespace-normalized body
  digest is looked up in every repository on disk. A match (copied or vendored
  code) drops the function and draws a replacement from the same stratum; the
  drop is recorded.

## 2. Sparse snapshot

What is evaluated is a sparse snapshot of each repository: the files matching
`*.py`, `.slopconfig.yaml`, `pyproject.toml`, `setup.cfg`, `.gitignore` and
`.gitattributes` at one commit. Everything else (history, weights, images,
data) is not fetched. A COMPLETE scan of the snapshot says the snapshot was
fully measured; it is not a statement about files outside it.

Commands (no submodules, no LFS, no filter driver, no symlinks):

```
git -c filter.lfs.smudge= -c filter.lfs.process= -c filter.lfs.required=false \
    -c core.symlinks=false clone --no-checkout --depth 1 --filter=blob:none \
    --no-recurse-submodules https://github.com/OWNER/REPO.git DEST
git -C DEST sparse-checkout set --no-cone '*.py' '.slopconfig.yaml' \
    'pyproject.toml' 'setup.cfg' '.gitignore' '.gitattributes'
git -C DEST -c filter.lfs.smudge= -c filter.lfs.process= \
    -c filter.lfs.required=false -c core.symlinks=false checkout
```

run with `GIT_LFS_SKIP_SMUDGE=1` and `GIT_TERMINAL_PROMPT=0`. The global git
configuration defines no filter driver besides LFS (checked 2026-10-26), so no
external program runs at checkout. Cloned code is only read, never imported,
installed or executed.

Completeness, per repository, before labeling:

1. `git ls-tree -r HEAD` lists every path matching the sparse patterns
   (trees are fetched in full; only blob contents are on demand).
2. Each listed path must exist in the working tree and its `git hash-object`
   must equal the tree's blob id. A missing or different file makes the
   functions in it SOURCE_INCOMPLETE.
3. HEAD must equal the commit in `estimate.json`; if the branch moved, the
   fetched commit is recorded and used, and the move is noted.
4. Receipt: commit, sparse patterns, the full tree path list, the snapshot
   path list with SHA-256 per file, submodule entries (not fetched) and the
   `.git` size in bytes after checkout (stored size, not network transfer).

Estimated before clone (`estimate.json`, from the tree API): the 16 primaries'
snapshot blobs total about 16.4 MB of their 148 MB trees (1,757 Python files);
the 8 reserves 4.7 MB of 43 MB. It is an estimate until the receipt measures it.

## Tier L (local, added 2026-10-26 before any draw)

Twelve repositories already on disk that no rule, benchmark, calibration or v1
draw used, and that share no lineage with one that was: five v1 candidates of
which no function was drawn, and seven never used. Left out: a v1
repository's second version, two copies of a v1 repository's sub-project, a
relative of a development repository, the author's own repository, and one of
unknown origin. Tier L is reported separately from A/B: it was collected by
interest rather than drawn from a frame, and seven of its repositories have no
git remote, so their snapshot is bound by file SHA-256 only. It has no
reserves.

Publication: the tier L list, its labels and its rows of the results are kept
in the private store (`draw.py` reads the list from the private config). The
published `labels.json` and `results*.json` carry tier L only as aggregate
counts and digests, so tier L cannot be reproduced from the public files.

## 3. Strata (per repository, seed `holdout-v2-20261026`)

| Stratum | Draw | Per repository |
|---|---|---|
| R | random functions from the product's discovered files | 8 |
| S | random functions whose body, after the docstring, has at most 5 statements | 16 |

R and S do not overlap. No stratum is drawn by words in the code. If labeling
finds fewer than 20 hollow functions in all, the reserve repositories of both
tiers are drawn and labeled too, still before any scan.

## 4. Labels

Classes and rules are v1's (`benchmarks/holdout/labels.json` meta). The note on
a hollow label names exactly what is fabricated, ignored or unchecked, so an AI
reading the source can confirm it line by line. Labels are written by reading
the source with no detector output, committed, and the commit SHA and file
SHA-256 go into the results. At labeling time each repository's HEAD and
`git status --porcelain` count, and each sampled function's file and function
SHA-256, are recorded; scoring refuses to run when any differs.

## 5. Detection

Scanned like a user does: full CLI, `--project --json --read-only`, empty home,
on the sparse snapshot. A function is flagged when a finding of the scored
pattern set lies in its span. The scored set is fixed in `score.py` before
scoring: v1's eight hollow patterns plus every hollow-detection pattern the
version under test adds. Results report the eight-pattern score as well, for
comparison with v1.

## 6. Measurement states

| State | Meaning | Counted as |
|---|---|---|
| MEASURED | file analyzed, repository COMPLETE | scored |
| SOURCE_INCOMPLETE | the file is missing from or differs in the snapshot | excluded, counted |
| ENV_BLOCKED | the scan could not run (crash, timeout, missing analyzer) | excluded, counted |
| NOT_MEASURED | repository not COMPLETE, or file not analyzed | excluded, counted |

None of the excluded states is scored as missed or clean. More than 10% of the
sampled functions excluded makes the run invalid.

## 7. Report

- Recall and false-alarm rate for each tier x stratum and in total, with the
  Wilson 95% interval and a repository-level bootstrap interval (resample
  repositories, 2000 draws, seed fixed) for clustering.
- Hollow functions per repository.
- Per pattern: true and false flags.
- Every flagged or missed function with its evidence (the line and value that
  make it hollow or genuine) and the fix direction.

## 8. Reuse

Once v2 results inform a rule change, v2 is development data as well, and the
next independent measurement needs a new draw.

## Safety rule (adopted 2026-10-26)

A repository is excluded for its stated purpose only, never for its code
quality or the results it is expected to give:

| Code | Purpose | Treatment |
|---|---|---|
| LICENSE_BYPASS | bypassing a service limit, paid licence or authentication | excluded |
| PIRACY | copyright infringement | excluded |
| AUTO_TRADING | a bot that can submit real orders or trades | excluded |
| NOT_EXCLUDED | research, analysis, simulation, dry-run trading | kept |
| REVIEW_REQUIRED | purpose unclear from description, licence and README | not judged; not cloned until decided |

`select_repos.py` routes a description matching its `SCREEN` pattern to review;
the decision and its evidence (description, licence, README, read through the
API) are recorded in `safety.json` before selection completes. Excluded and
replaced repositories are listed under `skipped` in `repos.json`, and the list
before the rule is kept as `repos_before_safety.json`.

Applied: `hovanhoa/cursor-free-vip` LICENSE_BYPASS, `panyiwei-home/Freedeck`
PIRACY, `zostaff/grokbot-pumpfun` NOT_EXCLUDED (live execution is a stub, dry
run by default), `xi-xiaoran/CP31-ticket-grabbing` REVIEW_REQUIRED (dropped
anyway: 1 Python file).
