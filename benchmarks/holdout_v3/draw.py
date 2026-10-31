"""Draw the hold-out v3 function sample (PROTOCOL.md section 5). No detector runs.

v2's draw (benchmarks/holdout_v2/draw.py) with the v3 seed, for the
repositories of repos.json with the given role: per repository, with its own
seeded generator, R PER_R functions from the whole population and S PER_S
short ones (at most SHORT statements after the docstring), minus R. A function
of LINEAGE_MIN_NODES nodes or more whose body also occurs in another
repository on disk (the external-repository folder, v1 and v2 snapshots
included) is dropped and its stratum redrawn. The output names snapshot
directories, never local paths.

usage: python -P benchmarks/holdout_v3/draw.py --dest SNAPSHOT_DIR --local EXTERNAL_REPO_DIR
       [--role primary] [--first-id 1]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [
    str(ROOT / "src"),
    str(HERE.parent / "holdout_v2"),
    str(HERE.parent / "holdout"),
    str(HERE.parent / "recall"),
]

from draw import PER_R, PER_S, _disk_index, _is_short, _lineage_key, _state  # noqa: E402
from sample import _functions  # noqa: E402

SEED = "holdout-v3-20261030"


def _draw_repo(name: str, path: Path, index: dict) -> tuple:
    rng = random.Random(f"{SEED}:{name}")
    pool = _functions(path)
    dropped = []

    def draw(candidates: list, k: int, taken: set) -> list:
        out = []
        for f in rng.sample(candidates, len(candidates)):
            if len(out) == k:
                break
            if (f["file"], f["function"]) in taken:
                continue
            key = _lineage_key(f["source"])
            others = (index.get(key, set()) - {path.name}) if key else set()
            if others:
                dropped.append({"function": f"{f['file']}::{f['function']}", "also_in_count": len(others)})
                continue
            out.append(f)
        return out

    r_part = draw(pool, PER_R, set())
    taken = {(f["file"], f["function"]) for f in r_part}
    s_part = draw([f for f in pool if _is_short(f["source"])], PER_S, taken)
    files = {f["file"] for f in r_part + s_part}
    meta = {
        "dir": path.name,
        **_state(path),
        "population": len(pool),
        "short": sum(_is_short(f["source"]) for f in pool),
        "drawn": {"R": len(r_part), "S": len(s_part)},
        "lineage_dropped": dropped,
        "file_sha256": {rel: hashlib.sha256((path / rel).read_bytes()).hexdigest() for rel in sorted(files)},
    }
    return r_part, s_part, meta


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True)
    parser.add_argument("--local", required=True)
    parser.add_argument("--role", default="primary")
    parser.add_argument("--first-id", type=int, default=1)
    parser.add_argument("--repo", action="append", help="draw only these (a replacement)")
    parser.add_argument("--out", default=str(HERE / "sample.json"))
    args = parser.parse_args()
    dest = Path(args.dest)
    chosen = [
        r
        for r in json.loads((HERE / "repos.json").read_text(encoding="utf-8"))["repos"]
        if (r["repo"] in args.repo if args.repo else r["role"] == args.role)
    ]
    index = _disk_index([Path(args.local), dest], skip={dest.name})
    picked, meta = [], {"seed": SEED, "role": args.role, "repos": {}}
    for row in chosen:
        path = dest / row["repo"].replace("/", "__")
        r_part, s_part, info = _draw_repo(row["repo"], path, index)
        for stratum, part in (("R", r_part), ("S", s_part)):
            picked += [dict(f, repo=row["repo"], tier=row["tier"], stratum=stratum) for f in part]
        meta["repos"][row["repo"]] = dict(info, tier=row["tier"])
        print(
            f"{row['tier']} {row['repo']}: pop {info['population']}, R {len(r_part)}, "
            f"S {len(s_part)}, lineage dropped {len(info['lineage_dropped'])}"
        )
    for i, item in enumerate(picked, args.first_id):
        item["id"] = f"T{i:03d}"
    Path(args.out).write_text(json.dumps({"meta": meta, "sample": picked}, indent=1), encoding="utf-8")
    print(f"{len(picked)} functions -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
