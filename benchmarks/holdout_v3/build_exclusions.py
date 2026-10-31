"""Write the private hold-out v3 exclusion list, rebuilt on the snapshot date.

The v2 list's sources (benchmarks/holdout_v2/build_exclusions.py: every git
checkout up to three levels under the workspace, by remote and directory name;
every directory in the external-repository folder; the v1 repositories; the
author's own accounts), plus every v2 repository and every repository v2
selection walked (its estimate.json). Remotes are read per checkout with that
one path trusted, so checkouts made by another Windows account are not skipped.
The list names local and private repositories: it is written to the private
store; exclusions_digest.json publishes its SHA-256 and counts.

usage: python -P benchmarks/holdout_v3/build_exclusions.py --root WORKSPACE
       --external EXTERNAL_REPO_DIR
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
V2 = HERE.parent / "holdout_v2"
PRIVATE = HERE.parents[1] / ".internal"
sys.path.insert(0, str(V2))

from build_exclusions import checkouts, normalize  # noqa: E402


def remote(path: Path):
    trust = "safe.directory=" + path.resolve().as_posix()
    url = subprocess.run(
        ["git", "-c", trust, "-C", str(path), "remote", "get-url", "origin"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout
    return normalize(url)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--external", required=True)
    args = parser.parse_args()
    config = json.loads((PRIVATE / "holdout_v2" / "private_config.json").read_text("utf-8"))
    owners = sorted(o.lower() for o in config["owners"])

    remotes, names = set(), set()
    for repo in checkouts(Path(args.root)):
        names.add(repo.name.lower())
        if remote(repo):
            remotes.add(remote(repo))
    names.update(p.name.lower() for p in Path(args.external).iterdir() if p.is_dir())
    v1 = json.loads((HERE.parent / "holdout" / "labels.json").read_text(encoding="utf-8"))
    names.update(f["repo"].lower() for f in v1["functions"])
    v2_walked = {row["repo"].lower() for row in json.loads((V2 / "estimate.json").read_text())}
    remotes |= v2_walked
    names |= {r.split("/", 1)[1] for r in v2_walked}

    out = {"owners": owners, "repositories": sorted(remotes), "names": sorted(names)}
    body = json.dumps(out, indent=1) + "\n"
    path = PRIVATE / "holdout_v3" / "exclusions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    digest = {
        "private_file": ".internal/holdout_v3/exclusions.json",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "counts": {k: len(v) for k, v in out.items()},
        "v2_walked_repositories": len(v2_walked),
        "note": "the list names local and private repositories, so only its digest "
        "and counts are published; select_repos.py reads the private file",
    }
    (HERE / "exclusions_digest.json").write_text(json.dumps(digest, indent=1) + "\n", "utf-8")
    print(digest["counts"], digest["sha256"][:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
