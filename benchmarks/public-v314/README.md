# public-v314: public measurement packets for the 3.14 article series

Each folder holds the script, the raw results and the figures behind one
article, measured against a **released** version of AI-SLOP Detector on
**public** inputs only. Nothing here is a benchmark of detection accuracy:
these packets show what the release does on the stated inputs, so the numbers
in an article can be checked and re-run.

| Packet | Article | Release measured | Inputs |
|---|---|---|---|
| [part15/](part15/) | Part 15, *A Finding Is Not a Fix* | `ai-slop-detector==3.14.2` (PyPI) | `examples/demo_project` and this repository's source, both at tag `v3.14.2` |

`manifest.json` lists every file of a packet with its SHA-256, the release and
its wheel digest, the source commit and the environment file.

## Part 15

What it measures:

1. **Surfaces:** the demo project rendered for each reader, sized in bytes, lines and estimated tokens. This takes three CLI invocations on the same fixed input:
   - the default terminal summary;
   - `--report-dir`, which writes `report.md`, `report.html`, `report.pdf`, `ai-report.jsonl`, `ai-report.md` (the auditor work order) and `scan.json` from one analysis;
   - the agent work order (`--format ai-md --ai-mode agent`).

   Each invocation runs its own analysis of identical bytes; the results file lists the three commands under `surfaces.invocations`.
2. **VOID binding:** the work order rendered again from the same scan after one file changed.
3. **prove_state:** one item of `orders/pricing.py` after each of five edits: an unrelated comment, a real fix, a reworded TODO, a deleted function, and the TODO comment deleted on its own.
4. **Token budget:** the tiers (T1 whole function, T2 excerpt, T3 index line) of the auditor work order at 14 budgets on this repository's source, including the budgets that are refused.

Re-run:

```bash
python -m venv v3142
v3142/bin/pip install "ai-slop-detector==3.14.2"          # Windows: v3142\Scripts\pip
mkdir -p in/demo_src in/repo out
git -C <clone> archive v3.14.2 examples/demo_project | tar -x -C in/demo_src
git -C <clone> archive v3.14.2 | tar -x -C in/repo
v3142/bin/python -I part15/m15.py --demo in/demo_src/examples/demo_project --repo in/repo --out out
python part15/plot15.py out/m15_results.json out/figures  # needs matplotlib
```

`m15.py` reads `--demo` and `--repo` and never changes them: it edits copies,
scans with `read_only=True`, and refuses an `--out` that overlaps either input
or that is itself a symbolic link or junction. Its scratch work goes into a new
directory made with `tempfile.mkdtemp` inside `--out` (`m15_work_*`); at the
end it deletes that directory only, after checking that it is a real directory
inside `--out`. It never reuses or deletes a directory it did not create in
the same run, so a link planted under `--out` is never followed.
`part15/test_m15_safety.py` checks this with links and junctions that point
outside (`python -m pytest -q part15/test_m15_safety.py` in the measurement
venv). The tests cover links and junctions that exist before the run; a path
replaced by another process during a run is not covered.

### What varies between runs

- **Sizes include paths.** The CLI was given the relative path `examples/demo_project`. The terminal summary, `report.md`, `ai-report.jsonl` and both work orders name the target and its files by that relative path. `report.html` and `scan.json` name every file by its **absolute** path, so their sizes also depend on the directory the run happens in: a run in a shorter directory gives smaller numbers for these two. Tiers, bindings and `prove_state` results do not depend on paths.
- **PDF size** varies with the browser and between runs; the PDF needs a local Chrome, Edge or Chromium. Without one, the bundle reports `ENV_BLOCKED` for the PDF and writes no PDF.
- **Item counts of the repository source depend on the installed packages**, because import rules judge imports against the environment (see `environments/windows-py312.json`).
- **Tokens are estimated as characters / 4**, the detector's own estimate. This is not the token count of any model's tokenizer.

### What the results file holds

`m15_results.json` stores output sizes, the terminal output of the public demo
(relative paths only), a bounded excerpt of the VOID item block (at most 1,500
characters), the `prove_state` results and the budget tiers. It does not
publish the generated HTML, PDF, Markdown, JSON Lines or full scan JSON. Those
generated files may contain absolute local paths (`report.html`, `scan.json`)
and should be reviewed before sharing.

### What this packet does not show

It does not measure precision or recall, agent behavior, or speed. It
measures two small public targets on one machine.
