"""Estimate what the sparse snapshot of each candidate would fetch (metadata only).

Reads the default branch's commit tree through the GitHub API and sums the blob
sizes the sparse checkout would materialize (SPARSE_PATTERNS). Also records the
total tree size, Python file count, submodule entries and whether .gitattributes
exists (a possible LFS or filter declaration). Nothing is cloned.

usage: python -P benchmarks/holdout_v2/estimate_download.py
"""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Kept identical to PROTOCOL.md section 2.
SPARSE_PATTERNS = [
    "*.py",
    ".slopconfig.yaml",
    "pyproject.toml",
    "setup.cfg",
    ".gitignore",
    ".gitattributes",
]


def api(path: str) -> dict:
    done = subprocess.run(["gh", "api", path], capture_output=True, encoding="utf-8")
    if done.returncode != 0:
        raise SystemExit(f"{path}: {done.stderr.strip()}")
    return json.loads(done.stdout)


def selected(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in SPARSE_PATTERNS)


def main() -> int:
    """Estimate the repositories select_repos.py walked (repos.json) or is waiting
    for (pending.json); rows already in estimate.json are kept, not refetched."""
    path = HERE / "estimate.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    known = {row["repo"] for row in rows}
    wanted = []
    if (HERE / "repos.json").exists():
        wanted += [r["repo"] for r in json.loads((HERE / "repos.json").read_text())["repos"]]
    if (HERE / "pending.json").exists():
        wanted += json.loads((HERE / "pending.json").read_text())["estimate"]
    for name in dict.fromkeys(n for n in wanted if n not in known):
        meta = api(f"repos/{name}")
        branch = meta["default_branch"]
        commit = api(f"repos/{name}/commits/{branch}")["sha"]
        tree = api(f"repos/{name}/git/trees/{commit}?recursive=1")
        blobs = [e for e in tree["tree"] if e["type"] == "blob"]
        chosen = [e for e in blobs if selected(e["path"])]
        rows.append(
            {
                "repo": name,
                "commit": commit,
                "tree_truncated": tree.get("truncated", False),
                "files_total": len(blobs),
                "bytes_total": sum(e.get("size", 0) for e in blobs),
                "py_files": sum(e["path"].endswith(".py") for e in blobs),
                "sparse_files": len(chosen),
                "sparse_bytes": sum(e.get("size", 0) for e in chosen),
                "submodules": sum(e["type"] == "commit" for e in tree["tree"]),
                "has_gitattributes": any(e["path"].endswith(".gitattributes") for e in blobs),
            }
        )
        r = rows[-1]
        print(
            f"{name}: py {r['py_files']}, sparse "
            f"{r['sparse_bytes'] / 1e6:.2f} MB of {r['bytes_total'] / 1e6:.1f} MB, "
            f"submodules {r['submodules']}, gitattributes {r['has_gitattributes']}"
            + (", TREE TRUNCATED" if r["tree_truncated"] else "")
        )
    path.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
