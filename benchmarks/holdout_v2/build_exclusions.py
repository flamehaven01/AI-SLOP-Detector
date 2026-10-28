"""Write the private exclusions.json: every repository hold-out v2 must not sample.

Collected from disk: each git checkout up to three levels under ROOT (remote
normalized to owner/repo, HTTPS, SSH and ssh:// alike, plus the directory name),
and every directory in the external-repository folder by name. Added: the
owners whose repositories are the detector author's own (all of them are
excluded; read from the private config) and the v1 hold-out repositories
(benchmarks/holdout/labels.json). The list names local and private
repositories, so it is written to the private store and never committed; the
public side keeps its digest and counts (exclusions_digest.json).

usage: python -P benchmarks/holdout_v2/build_exclusions.py --root WORKSPACE
       --external EXTERNAL_REPO_DIR [--private-config FILE]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIVATE = HERE.parents[1] / ".internal" / "holdout_v2"
GITHUB = re.compile(r"github\.com[:/]+(?:[^/@]+@)?([^/]+)/([^/]+?)(?:\.git)?/*$", re.I)


def normalize(url: str):
    """owner/repo (lower case) for a GitHub remote in any of its spellings."""
    match = GITHUB.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}".lower() if match else None


def checkouts(root: Path, depth: int = 3):
    pending = [(root, 0)]
    while pending:
        path, level = pending.pop()
        if (path / ".git").exists():
            yield path
        if level < depth:
            try:
                children = [p for p in path.iterdir() if p.is_dir() and p.name != ".git"]
            except OSError:
                continue
            pending += [(p, level + 1) for p in children]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--external", required=True)
    parser.add_argument("--private-config", default=str(PRIVATE / "private_config.json"))
    args = parser.parse_args()
    owners = json.loads(Path(args.private_config).read_text(encoding="utf-8"))["owners"]

    remotes, names = set(), set()
    for repo in checkouts(Path(args.root)):
        names.add(repo.name.lower())
        url = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        ).stdout
        if normalize(url):
            remotes.add(normalize(url))
    names.update(p.name.lower() for p in Path(args.external).iterdir() if p.is_dir())
    v1 = json.loads((HERE.parent / "holdout" / "labels.json").read_text(encoding="utf-8"))
    names.update(f["repo"].lower() for f in v1["functions"])

    out = {
        "owners": owners,
        "repositories": sorted(remotes),
        "names": sorted(names),
    }
    path = PRIVATE / "exclusions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"{len(remotes)} remotes, {len(names)} names, {len(owners)} owners")
    return 0


if __name__ == "__main__":
    sys.exit(main())
