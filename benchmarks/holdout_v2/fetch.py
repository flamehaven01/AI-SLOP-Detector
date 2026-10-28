"""Fetch the sparse snapshots of the selected repositories and write receipts.

PROTOCOL.md section 2: shallow, blob-less, no submodules, no LFS or other filter
driver, no symlinks, no line-ending conversion; only SPARSE_PATTERNS are checked
out. Then every tree path matching the patterns must exist with the tree's blob
id (`git hash-object`), HEAD must be the commit in estimate.json, and the receipt
records commit, patterns, full tree path list, snapshot files with SHA-256,
submodule entries and the measured .git size. Cloned code is never executed.

usage: python -P benchmarks/holdout_v2/fetch.py --dest SNAPSHOT_DIR
       [--role primary]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from estimate_download import SPARSE_PATTERNS, selected  # noqa: E402

SAFE = [
    "-c",
    "filter.lfs.smudge=",
    "-c",
    "filter.lfs.process=",
    "-c",
    "filter.lfs.required=false",
    "-c",
    "core.symlinks=false",
    "-c",
    "core.autocrlf=false",
    "-c",
    "core.eol=lf",
]
ENV = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1", GIT_TERMINAL_PROMPT="0")


def git(*args, cwd=None) -> str:
    done = subprocess.run(
        ["git", *SAFE, *args],
        cwd=cwd,
        env=ENV,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def fetch(repo: str, commit: str, dest: Path) -> dict:
    target = dest / repo.replace("/", "__")
    if not target.exists():
        url = f"https://github.com/{repo}.git"
        git(
            "clone",
            "--no-checkout",
            "--depth",
            "1",
            "--filter=blob:none",
            "--no-recurse-submodules",
            url,
            str(target),
        )
    tip = git("rev-parse", "HEAD", cwd=target).strip()
    moved = tip != commit
    if moved:
        try:
            git("fetch", "--depth", "1", "--filter=blob:none", "origin", commit, cwd=target)
            tip = commit
        except RuntimeError:
            pass  # recorded below: the fetched tip is used and the move is noted
    git("sparse-checkout", "set", "--no-cone", *SPARSE_PATTERNS, cwd=target)
    git("checkout", "--force", tip, cwd=target)

    entries = []
    # -z: NUL-separated and unquoted; otherwise non-ASCII paths come back quoted.
    for line in filter(
        None, git("ls-tree", "-r", "-z", "--full-tree", tip, cwd=target).split("\0")
    ):
        meta, path = line.split("\t", 1)
        mode, kind, oid = meta.split()
        entries.append((mode, kind, oid, path))
    wanted = [(oid, path) for mode, kind, oid, path in entries if kind == "blob" and selected(path)]
    files, incomplete = [], []
    for oid, path in wanted:
        local = target / path
        if not local.is_file():
            incomplete.append({"path": path, "why": "missing"})
            continue
        if git("hash-object", "--no-filters", str(local), cwd=target).strip() != oid:
            incomplete.append({"path": path, "why": "differs from tree blob"})
            continue
        files.append({"path": path, "sha256": hashlib.sha256(local.read_bytes()).hexdigest()})
    git_bytes = sum(p.stat().st_size for p in (target / ".git").rglob("*") if p.is_file())
    return {
        "repo": repo,
        "dir": target.name,
        "commit": tip,
        "estimate_commit": commit,
        "branch_moved": moved and tip != commit,
        "sparse_patterns": SPARSE_PATTERNS,
        "tree_paths": [path for _, kind, _, path in entries if kind == "blob"],
        "submodules": [path for _, kind, _, path in entries if kind == "commit"],
        "snapshot_files": files,
        "source_incomplete": incomplete,
        "git_dir_bytes": git_bytes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True)
    parser.add_argument("--role", default="primary")
    parser.add_argument("--repo", action="append", help="fetch only these (default: all of --role)")
    args = parser.parse_args()
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    commits = {r["repo"]: r["commit"] for r in json.loads((HERE / "estimate.json").read_text())}
    chosen = json.loads((HERE / "repos.json").read_text(encoding="utf-8"))["repos"]
    names = args.repo or [r["repo"] for r in chosen if r["role"] == args.role]
    out_dir = HERE / "receipts"
    out_dir.mkdir(exist_ok=True)
    for name in names:
        receipt = fetch(name, commits[name], dest)
        path = out_dir / f"{receipt['dir']}.json"
        path.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
        print(
            f"{name}: {len(receipt['snapshot_files'])} files, "
            f"{len(receipt['source_incomplete'])} incomplete, "
            f".git {receipt['git_dir_bytes'] / 1e6:.2f} MB"
            + (", BRANCH MOVED" if receipt["branch_moved"] else "")
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
