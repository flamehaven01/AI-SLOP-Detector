"""Fetch the hold-out v3 sparse snapshots and write receipts (PROTOCOL.md section 4).

v2's `fetch` (benchmarks/holdout_v2/fetch.py: shallow, blob-less, no
submodules, LFS, filter drivers, symlinks or line-ending conversion; only the
sparse patterns checked out; every pattern path checked against its tree blob)
for the repositories in repos.json, at the commit select_repos.py recorded.
Cloned code is never executed.

usage: python -P benchmarks/holdout_v3/fetch.py --dest SNAPSHOT_DIR
       [--role primary] [--tier A+B|AI_ASSOCIATED] [--repo OWNER/NAME ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "holdout_v2"))

from fetch import fetch  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True)
    parser.add_argument("--role", default="primary")
    parser.add_argument("--tier")
    parser.add_argument("--repo", action="append", help="fetch only these")
    args = parser.parse_args()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    chosen = json.loads((HERE / "repos.json").read_text(encoding="utf-8"))["repos"]
    rows = [
        r
        for r in chosen
        if (args.repo and r["repo"] in args.repo)
        or (not args.repo and r["role"] == args.role and args.tier in (None, r["tier"]))
    ]
    out_dir = HERE / "receipts"
    out_dir.mkdir(exist_ok=True)
    failed = []
    for row in rows:
        try:
            receipt = fetch(row["repo"], row["commit"], dest)
        except RuntimeError as err:
            failed.append(row["repo"])
            print(f"{row['repo']}: FAILED {err}")
            continue
        receipt["tier"] = row["tier"]
        path = out_dir / f"{receipt['dir']}.json"
        path.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
        print(
            f"{row['repo']}: {len(receipt['snapshot_files'])} files, "
            f"{len(receipt['source_incomplete'])} incomplete, "
            f".git {receipt['git_dir_bytes'] / 1e6:.2f} MB"
            + (", BRANCH MOVED" if receipt["branch_moved"] else "")
        )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
