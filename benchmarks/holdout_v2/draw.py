"""Draw the hold-out v2 function sample (PROTOCOL.md section 3). No detector runs.

Repositories: the primaries of repos.json (sparse snapshots under --dest, see
fetch.py) and the local tier L (names read from the private config, under
--local). Population per
repository: the functions benchmarks/holdout/sample.py extracts from the files
the product discovers. Per repository, with its own seeded generator:

  R  PER_R functions drawn from the whole population;
  S  PER_S functions drawn from the short ones (at most SHORT statements in
     the body after the docstring, nested statements counted), minus R.

Lineage: a function whose body (AST, positions and docstring stripped) has at
least LINEAGE_MIN_NODES nodes and also occurs in another repository on disk is
copied or vendored code; it is dropped and the stratum redrawn. Short bodies
coincide by chance, so they are not compared.

usage: python -P benchmarks/holdout_v2/draw.py --dest SNAPSHOT_DIR --local LOCAL_REPO_DIR
       [--private-config .internal/holdout_v2/private_config.json]
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import random
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(HERE.parent / "holdout"), str(HERE.parent / "recall")]

from sample import _functions  # noqa: E402

SEED = "holdout-v2-20261026"
PER_R, PER_S, SHORT, LINEAGE_MIN_NODES = 8, 16, 5, 40
# Tier L (PROTOCOL.md "Tier L") is a private list: {"tier_L": [names]}.
PRIVATE_CONFIG = ROOT / ".internal" / "holdout_v2" / "private_config.json"


def _body(source: str):
    """The function's body statements without the docstring, or None."""
    try:
        node = ast.parse(textwrap.dedent(source)).body[0]
    except (SyntaxError, IndexError, ValueError):
        return None
    body = node.body
    first = body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        body = body[1:]
    return body


def _is_short(source: str) -> bool:
    body = _body(source)
    if body is None:
        return False
    return sum(isinstance(n, ast.stmt) for s in body for n in ast.walk(s)) <= SHORT


def _lineage_key(source: str):
    body = _body(source)
    if not body:
        return None
    nodes = sum(1 for s in body for _ in ast.walk(s))
    if nodes < LINEAGE_MIN_NODES:
        return None
    dumped = "\n".join(ast.dump(s, include_attributes=False) for s in body)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _disk_index(roots: list, skip: set) -> dict:
    """lineage key -> set of repository names, over every repository on disk."""
    index = {}
    for root in roots:
        for repo in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in skip):
            for path in repo.rglob("*.py"):
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
                except (SyntaxError, ValueError, RecursionError):
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        key = _lineage_key(ast.unparse(node))
                        if key:
                            index.setdefault(key, set()).add(repo.name)
    return index


def _state(repo: Path) -> dict:
    def git(*args):
        done = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, encoding="utf-8", errors="replace"
        )
        return done.stdout.strip() if done.returncode == 0 else None

    status = git("status", "--porcelain")
    return {
        "head": git("rev-parse", "HEAD"),
        "dirty": None if status is None else len(status.splitlines()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True)
    parser.add_argument("--local", required=True)
    parser.add_argument("--private-config", default=str(PRIVATE_CONFIG))
    parser.add_argument("--role", default="primary")
    parser.add_argument("--first-id", type=int, default=1)
    parser.add_argument("--out", default=str(ROOT / ".internal" / "holdout_v2" / "sample.json"))
    args = parser.parse_args()

    chosen = json.loads((HERE / "repos.json").read_text(encoding="utf-8"))["repos"]
    targets = [
        (r["band"][0], r["repo"], Path(args.dest) / r["repo"].replace("/", "__"))
        for r in chosen
        if r["role"] == args.role
    ]
    if args.role == "primary":  # tier L has no reserves
        tier_l = json.loads(Path(args.private_config).read_text(encoding="utf-8"))["tier_L"]
        targets += [("L", name, Path(args.local) / name) for name in tier_l]
    dest, local = Path(args.dest), Path(args.local)
    index = _disk_index([local, dest], skip={dest.name})

    picked, meta = [], {"seed": SEED, "repos": {}}
    for tier, name, path in targets:
        rng = random.Random(f"{SEED}:{name}")
        pool = _functions(path)
        dropped = []

        def draw(candidates: list, k: int, taken: set) -> list:
            out = []
            order = rng.sample(candidates, len(candidates))
            for f in order:
                if len(out) == k:
                    break
                if (f["file"], f["function"]) in taken:
                    continue
                key = _lineage_key(f["source"])
                others = (index.get(key, set()) - {path.name}) if key else set()
                if others:
                    dropped.append(
                        {"function": f"{f['file']}::{f['function']}", "also_in": sorted(others)}
                    )
                    continue
                out.append(f)
            return out

        r_part = draw(pool, PER_R, set())
        taken = {(f["file"], f["function"]) for f in r_part}
        s_part = draw([f for f in pool if _is_short(f["source"])], PER_S, taken)
        for f in r_part:
            picked.append(dict(f, repo=name, tier=tier, stratum="R"))
        for f in s_part:
            picked.append(dict(f, repo=name, tier=tier, stratum="S"))
        files = {f["file"] for f in r_part + s_part}
        meta["repos"][name] = {
            "tier": tier,
            "dir": str(path),
            **_state(path),
            "population": len(pool),
            "short": sum(_is_short(f["source"]) for f in pool),
            "drawn": {"R": len(r_part), "S": len(s_part)},
            "lineage_dropped": dropped,
            "file_sha256": {
                rel: hashlib.sha256((path / rel).read_bytes()).hexdigest() for rel in sorted(files)
            },
        }
        print(
            f"{tier} {name}: pop {len(pool)}, R {len(r_part)}, S {len(s_part)}, lineage dropped {len(dropped)}"
        )

    for i, item in enumerate(picked, args.first_id):
        item["id"] = f"V{i:03d}"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"meta": meta, "sample": picked}, indent=1), encoding="utf-8")
    print(f"{len(picked)} functions -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
