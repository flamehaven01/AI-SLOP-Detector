"""Score the detector on the frozen hold-out labels (benchmarks/holdout/labels.json).

Each repository is scanned the way a user scans it: the full CLI with
`--project --json --read-only` and an empty home directory. A function counts as
flagged when a finding of a hollow-code pattern (HOLLOW_PATTERNS) lies inside its
span; findings of any pattern are reported separately. Before counting, every
function's source digest is checked against the label, so a moved or edited
repository fails instead of being scored against the wrong code.

usage: python -P benchmarks/holdout/score.py --repos EXTERNAL_REPO_DIR [--out FILE]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"

# The patterns that claim a body does not do its job. Comment markers (TODO,
# FIXME, HACK, XXX) are left out: stratum M was drawn by marker words.
HOLLOW_PATTERNS = frozenset(
    {
        "pass_placeholder",
        "ellipsis_placeholder",
        "not_implemented",
        "return_none_placeholder",
        "return_constant_stub",
        "return_input_stub",
        "failure_as_success",
        "ignored_parameter",
    }
)


def scan(repo: Path) -> dict:
    """file (relative, posix) -> list of (line, pattern_id) from the full CLI."""
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, HOME=home, USERPROFILE=home, PYTHONPATH=str(SRC))
        env["PYTHONHASHSEED"] = "1"
        env.pop("SLOP_CONFIG", None)
        cmd = [sys.executable, "-m", "slop_detector.cli", "--project", str(repo)]
        done = subprocess.run(
            cmd + ["--json", "--read-only"], capture_output=True, env=env, cwd=home
        )
    data = json.loads(done.stdout.decode("utf-8"))
    found = defaultdict(list)
    analyzed = set()
    for result in data.get("file_results", []):
        rel = Path(result["file_path"]).resolve().relative_to(repo.resolve()).as_posix()
        analyzed.add(rel)
        for issue in result.get("pattern_issues", []):
            if issue.get("line"):
                found[rel].append((issue["line"], issue["pattern_id"]))
    state = (data.get("scan_coverage") or {}).get("measurement_state")
    return {"found": found, "analyzed": analyzed, "state": state}


def _version() -> str:
    text = (SRC / "slop_detector" / "__init__.py").read_text(encoding="utf-8")
    return text.split("__version__", 1)[1].split('"')[1]


def _src_digest() -> str:
    files = sorted(p for p in (SRC / "slop_detector").rglob("*.py") if "__pycache__" not in p.parts)
    lines = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(SRC).as_posix()}"
        for p in files
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def wilson(hits: int, total: int) -> list:
    """95% Wilson score interval for hits/total."""
    if not total:
        return [None, None]
    z, p = 1.96, hits / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return [round(centre - half, 3), round(centre + half, 3)]


def rate(rows: list) -> dict:
    hits = sum(bool(r["hollow_findings"]) for r in rows)
    return {"flagged": hits, "total": len(rows), "ci95": wilson(hits, len(rows))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repos", required=True)
    parser.add_argument("--out", default=str(HERE / "results.json"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    # The published labels redact one local path (H150); the private copy is complete.
    private = HERE.parents[1] / ".internal" / "holdout" / "labels_full.json"
    labels_path = private if private.exists() else HERE / "labels.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8"))["functions"]
    root = Path(args.repos)
    repos = sorted({f["repo"] for f in labels})
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        scans = dict(zip(repos, pool.map(lambda name: scan(root / name), repos)))

    rows = []
    for f in labels:
        path = root / f["repo"] / f["file"]
        first, last = f["span"]
        lines = path.read_text(encoding="utf-8").splitlines()[first - 1 : last]
        if hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest() != f["sha256"]:
            raise SystemExit(f"{f['id']}: source changed since labeling ({path})")
        hits = [
            p for line, p in scans[f["repo"]]["found"].get(f["file"], []) if first <= line <= last
        ]
        rows.append(
            {
                "id": f["id"],
                "stratum": f["stratum"],
                "label": f["label"],
                "where": f"{f['repo']}/{f['file']}::{f['function']}",
                "file_analyzed": f["file"] in scans[f["repo"]]["analyzed"],
                "hollow_findings": sorted({p for p in hits if p in HOLLOW_PATTERNS}),
                "other_findings": sorted({p for p in hits if p not in HOLLOW_PATTERNS}),
            }
        )

    hollow = [r for r in rows if r["label"] not in ("GENUINE", "UNCLEAR")]
    genuine = [r for r in rows if r["label"] == "GENUINE"]
    report = {
        "labels_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        "detector_version": _version(),
        "src_sha256": _src_digest(),
        "functions_in_unanalyzed_files": sum(not r["file_analyzed"] for r in rows),
        "measurement_states": {name: s["state"] for name, s in scans.items()},
        "hollow_patterns": sorted(HOLLOW_PATTERNS),
        "recall": rate(hollow),
        "false_alarms": rate(genuine),
        "false_alarms_by_stratum": {
            s: rate([r for r in genuine if r["stratum"] == s]) for s in "RM"
        },
        "any_pattern_on_genuine": sum(
            bool(r["other_findings"] or r["hollow_findings"]) for r in genuine
        ),
        "recall_by_class": {
            label: rate([r for r in hollow if r["label"] == label])
            for label in sorted({r["label"] for r in hollow})
        },
        "findings_by_pattern": dict(Counter(p for r in rows for p in r["hollow_findings"])),
        "unclear": [r for r in rows if r["label"] == "UNCLEAR"],
        "missed_hollow": [r for r in hollow if not r["hollow_findings"]],
        "flagged_genuine": [r for r in genuine if r["hollow_findings"]],
        "functions": rows,
    }
    Path(args.out).write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(f"detector {report['detector_version']}  labels {report['labels_sha256'][:12]}")
    print(f"recall        {report['recall']}")
    print(f"false alarms  {report['false_alarms']}")
    for r in report["missed_hollow"]:
        print(f"  missed   {r['id']} {r['label']:20} {r['where']}")
    for r in report["flagged_genuine"]:
        print(f"  flagged  {r['id']} {r['hollow_findings']} {r['where']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
