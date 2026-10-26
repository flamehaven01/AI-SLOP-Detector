"""Run the test suite in balanced parallel shards and keep per-file timings.

Files are assigned longest-first to the least-loaded of N workers, using the
seconds recorded by the previous run (`.pytest_durations.json`, git-ignored); a file
without a record counts as 1 s. After the run the
per-file seconds are rewritten from pytest's own report.

usage: python -P scripts/dev/parallel_tests.py [--workers 4] [pytest file ...]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DURATIONS = REPO / ".pytest_durations.json"
# --tb=line prints one "path.py:123: reason" line per failure.
TRACE_LINE = re.compile(r"^\S+\.py:\d+: ")
LINE = re.compile(r"^\s*([0-9.]+)s (?:call|setup|teardown)\s+(\S+?)::")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()

    files = args.files or sorted(
        p.relative_to(REPO).as_posix() for p in (REPO / "tests").rglob("test_*.py")
    )
    known = json.loads(DURATIONS.read_text(encoding="utf-8")) if DURATIONS.exists() else {}
    shards = [[] for _ in range(args.workers)]
    load = [0.0] * args.workers
    for name in sorted(files, key=lambda f: -known.get(f, 1.0)):
        i = load.index(min(load))
        shards[i].append(name)
        load[i] += known.get(name, 1.0)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "src"), str(REPO / "envs" / "treesitter"), env.get("PYTHONPATH", "")]
    )
    started = time.perf_counter()
    procs = []
    run_temp = Path(tempfile.mkdtemp(prefix="parallel_tests_"))
    for index, shard in enumerate(shards):
        if not shard:
            continue
        # HOME is not replaced: git refuses a fresh HOME ("dubious ownership"), and
        # tests that need an isolated HOME set their own.
        # Each worker gets its own --basetemp: pytest prunes old numbered temp
        # directories under a shared root, which deleted another worker's tmp_path.
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *shard,
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-cov",
            "--durations=0",
            "--durations-min=0",
            "--tb=line",
            f"--basetemp={run_temp / f'worker{index}'}",
        ]
        # A wide terminal keeps pytest's "FAILED test - reason" lines whole.
        procs.append(
            subprocess.Popen(
                cmd,
                cwd=REPO,
                env=dict(env, COLUMNS="300"),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        )
    outputs = [p.communicate()[0].decode("utf-8", "replace") for p in procs]
    wall = time.perf_counter() - started

    seconds = defaultdict(float)
    summaries, failures = [], []
    for out in outputs:
        for line in out.splitlines():
            match = LINE.match(line)
            if match:
                seconds[match.group(2).replace("\\", "/")] += float(match.group(1))
            if line.startswith(("FAILED", "ERROR")) or TRACE_LINE.match(line):
                failures.append(line)
        summaries.append(out.strip().splitlines()[-1] if out.strip() else "(no output)")
    known.update({k: round(v, 2) for k, v in seconds.items()})
    DURATIONS.write_text(json.dumps(known, indent=1, sort_keys=True), encoding="utf-8")

    for i, summary in enumerate(summaries):
        print(f"shard {i}: {summary}")
    for line in failures:
        print(line)
    codes = [p.returncode for p in procs]
    print(f"wall {wall:.1f} s, workers {len(procs)}, exit codes {codes}")
    return 0 if all(c == 0 for c in codes) else 1


if __name__ == "__main__":
    sys.exit(main())
