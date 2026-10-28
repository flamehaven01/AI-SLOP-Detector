"""Draw the hold-out sample: functions from public repositories never used to build a rule.

The detector is not run here. The sample is labeled first (labels.json), then
scored by score.py. Two strata, drawn with one fixed seed:

  R  random functions: RANDOM_REPOS repositories, then PER_REPO functions each.
     Measures false alarms on ordinary code (and any hollow function it meets).
  M  marker functions: functions whose own text carries a hollow-code marker
     (placeholder, stub, "for now", "in a real ..."; see MARKER), at most
     MARKER_PER_REPO per repository, MARKER_TOTAL in all. The markers are words,
     not detector rules, so this stratum supplies hollow functions for recall
     without selecting them by what the detector looks for.

Population: the Python files the product's own discovery picks for each
repository, and the functions `function_spans` (benchmarks/recall/measure.py)
reports in them. Function source stays local (git-ignored .internal/holdout/);
the committed labels carry repository, commit, file, name, span and digest.

usage: python -P benchmarks/holdout/sample.py --repos EXTERNAL_REPO_DIR
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "src"), str(HERE.parent / "recall")]

from measure import function_spans  # noqa: E402

SEED = 20261026
RANDOM_REPOS, PER_REPO = 12, 10
MARKER_TOTAL, MARKER_PER_REPO = 60, 5
MARKER = re.compile(
    r"placeholder|\bstubs?\b|\bdummy\b|\bfake\b|hard-?coded|for now|simplified|"
    r"in a real\b|in production\b|not (yet )?implemented|\bsimulat|\bmock(ed)? "
    r"(data|response|result|value)|would normally",
    re.IGNORECASE,
)
# Public repositories (git remote, >= 10 .py files) never named in the
# detector's benchmarks, tests, docs, changelog, internal notes or memory.
REPOS = [
    "BioClaw", "BioReason-Pro", "Biomni", "CellAgent", "ClawBio", "ComfyUI", "GEA",
    "HRM", "NAAb", "NOVAGENE", "OpenGauss", "PixelRAG", "RAG-Anything",
    "Reasoning-Embedding", "TheAnalystsProblem", "VideoAgent",
    "academic-observatory-workflows", "agent-governance-toolkit", "andartis",
    "claude-scientific-skills", "claw-code", "cocoindex", "cymyc", "docling", "doctobert",
    "fallow", "fieldbioinformatics", "langflow", "neuroai", "opendataloader-pdf", "openmed",
    "openrag", "rclone", "the_well", "tiktok-agent",
]  # fmt: skip


def _discovered(repo: Path) -> list:
    from slop_detector.core import SlopDetector
    from slop_detector.core_project import project_walk_scope
    from slop_detector.project_context import project_context_scope
    from slop_detector.service.policy import resolve_config_path

    detector = SlopDetector(config_path=resolve_config_path(repo, True, None), read_only=True)
    with project_context_scope(), project_walk_scope():
        return detector._discover_supported_files(
            repo, ["**/*.py"], {".py"}, detector.config.get_ignore_patterns()
        )


def _functions(repo: Path) -> list:
    out = []
    for path in sorted(_discovered(repo)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            spans = function_spans(path)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        rel = path.relative_to(repo).as_posix()
        for name, (first, last) in sorted(spans.items()):
            source = "\n".join(lines[first - 1 : last])
            out.append(
                {
                    "repo": repo.name,
                    "file": rel,
                    "function": name,
                    "span": [first, last],
                    "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                    "source": source,
                }
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", required=True)
    parser.add_argument("--out", default=str(ROOT / ".internal" / "holdout" / "sample.json"))
    args = parser.parse_args()

    rng = random.Random(SEED)
    root = Path(args.repos)
    commits, functions = {}, {}
    for name in REPOS:
        commits[name] = subprocess.run(
            ["git", "-C", str(root / name), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        functions[name] = _functions(root / name)

    picked = []
    for name in sorted(rng.sample(REPOS, RANDOM_REPOS)):
        pool = functions[name]
        picked += [dict(f, stratum="R") for f in rng.sample(pool, min(PER_REPO, len(pool)))]
    taken = {(f["repo"], f["file"], f["function"]) for f in picked}
    marked = []
    for name in REPOS:
        pool = [
            f
            for f in functions[name]
            if MARKER.search(f["source"]) and (name, f["file"], f["function"]) not in taken
        ]
        marked += rng.sample(pool, min(MARKER_PER_REPO, len(pool)))
    picked += [dict(f, stratum="M") for f in rng.sample(marked, min(MARKER_TOTAL, len(marked)))]

    for index, item in enumerate(picked, 1):
        item["id"] = f"H{index:03d}"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "seed": SEED,
        "commits": commits,
        "population": {k: len(v) for k, v in functions.items()},
    }
    out.write_text(json.dumps({"meta": meta, "sample": picked}, indent=1), encoding="utf-8")
    print(f"{len(picked)} functions -> {out}")
    print(
        f"R {sum(f['stratum'] == 'R' for f in picked)}, M {sum(f['stratum'] == 'M' for f in picked)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
