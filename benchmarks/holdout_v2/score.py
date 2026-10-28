"""Score the detector on the frozen hold-out v2 labels (PROTOCOL.md sections 5-7).

Each repository is scanned like a user scans it (full CLI, --project --json
--read-only, empty home) on its snapshot. Before anything is counted the source
binding is checked: repository HEAD and dirty count, and every sampled file and
function digest, must equal labels.json, or scoring stops. A function is
MEASURED when its repository scan is COMPLETE and its file was analyzed;
otherwise it is ENV_BLOCKED (the scan did not run) or NOT_MEASURED, and is
counted but never scored. The scored patterns are v1's eight (HOLLOW_PATTERNS of
benchmarks/holdout/score.py); a version that adds hollow patterns lists them
in ADDED_PATTERNS before it is scored.

Tier L labels and the full results stay in the private store (PRIVATE, git
ignored); the published results.json is public_view() of the full report: tier
L appears in it as aggregate counts only.

usage: python -P benchmarks/holdout_v2/score.py --dest SNAPSHOT_DIR --local LOCAL_REPO_DIR
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"
_spec = importlib.util.spec_from_file_location(
    "holdout_v1_score", HERE.parent / "holdout" / "score.py"
)
v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v1)

ADDED_PATTERNS: frozenset = frozenset()  # hollow patterns the version under test adds
SCORED = v1.HOLLOW_PATTERNS | ADDED_PATTERNS
BOOTSTRAP_DRAWS, BOOTSTRAP_SEED = 2000, 20261026
PRIVATE = HERE.parents[1] / ".internal" / "holdout_v2"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_view(report: dict, full_sha256: str) -> dict:
    """The report without tier L rows, repository names or paths."""
    public = dict(report)
    for key in ("rows", "missed_hollow", "flagged_genuine", "caught_hollow"):
        public[key] = [r for r in report[key] if r["tier"] != "L"]
    named = {r["repo"] for r in public["rows"]}
    for key in ("measurement_states", "hollow_per_repo"):
        public[key] = {n: v for n, v in report[key].items() if n in named}
    public["private_tier_L"] = {
        "functions": sum(r["tier"] == "L" for r in report["rows"]),
        "full_results_sha256": full_sha256,
        "note": "tier L rows, repository names and paths are in the private store; "
        "tier L appears here only as aggregate counts (groups)",
    }
    return public


def scan(repo: Path) -> dict:
    """{state, analyzed, found: file -> [(line, pattern, message)]} from the full CLI."""
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, HOME=home, USERPROFILE=home, PYTHONPATH=str(SRC))
        env["PYTHONHASHSEED"] = "1"
        env.pop("SLOP_CONFIG", None)
        cmd = [sys.executable, "-m", "slop_detector.cli", "--project", str(repo)]
        done = subprocess.run(
            cmd + ["--json", "--read-only"], capture_output=True, env=env, cwd=home
        )
    # Without --fail-threshold or a CI gate a completed scan exits 0; anything
    # else is a failed run, whatever it printed.
    blocked = {"state": "ENV_BLOCKED", "analyzed": set(), "found": {}}
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        return dict(blocked, exit_code=done.returncode, stderr_tail=tail)
    try:
        data = json.loads(done.stdout.decode("utf-8"))
    except ValueError:
        return dict(blocked, exit_code=0, stderr_tail=["stdout was not JSON"])
    found, analyzed = defaultdict(list), set()
    for result in data.get("file_results", []):
        rel = Path(result["file_path"]).resolve().relative_to(repo.resolve()).as_posix()
        analyzed.add(rel)
        for issue in result.get("pattern_issues", []):
            if issue.get("line"):
                found[rel].append((issue["line"], issue["pattern_id"], issue.get("message", "")))
    state = (data.get("scan_coverage") or {}).get("measurement_state")
    return {"state": state, "analyzed": analyzed, "found": found}


def _git(path: Path, *args) -> str | None:
    done = subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, encoding="utf-8", errors="replace"
    )
    return done.stdout.strip() if done.returncode == 0 else None


def _check_binding(rows: list, dirs: dict) -> None:
    for name in sorted({r["repo"] for r in rows}):
        first = next(r for r in rows if r["repo"] == name)
        status = _git(dirs[name], "status", "--porcelain")
        state = (
            _git(dirs[name], "rev-parse", "HEAD"),
            None if status is None else len(status.splitlines()),
        )
        if state != (first["head"], first["dirty"]):
            raise SystemExit(
                f"{name}: HEAD/dirty {state} differs from labeling {first['head'], first['dirty']}"
            )
    for r in rows:
        path = dirs[r["repo"]] / r["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != r["file_sha256"]:
            raise SystemExit(f"{r['id']}: file changed since labeling ({path})")
        first, last = r["span"]
        lines = path.read_text(encoding="utf-8").splitlines()[first - 1 : last]
        if hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest() != r["sha256"]:
            raise SystemExit(f"{r['id']}: function changed since labeling ({path})")


def _rate(rows: list, key: str) -> dict:
    hits = sum(bool(r[key]) for r in rows)
    return {"flagged": hits, "total": len(rows), "ci95": v1.wilson(hits, len(rows))}


def _bootstrap(rows: list, key: str) -> dict:
    """Resample repositories; the pooled rate per draw. Draws with no rows are skipped.

    When the observed rate is 0 or 1 every draw repeats it, so the interval has
    no width and says nothing about uncertainty: it is reported as not
    informative and the Wilson interval stands alone.
    """
    by_repo = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)
    repos = sorted(by_repo)
    if not repos:
        return {"ci95": [None, None], "draws_used": 0}
    hits = sum(bool(r[key]) for r in rows)
    if hits in (0, len(rows)):
        return {
            "ci95": None,
            "draws_used": 0,
            "note": f"not informative: {hits}/{len(rows)} observed",
        }
    rng, rates = random.Random(BOOTSTRAP_SEED), []
    for _ in range(BOOTSTRAP_DRAWS):
        picked = [x for name in rng.choices(repos, k=len(repos)) for x in by_repo[name]]
        if picked:
            rates.append(sum(bool(x[key]) for x in picked) / len(picked))
    rates.sort()
    lo, hi = rates[int(0.025 * len(rates))], rates[min(len(rates) - 1, int(0.975 * len(rates)))]
    return {"ci95": [round(lo, 3), round(hi, 3)], "draws_used": len(rates)}


def _summary(rows: list) -> dict:
    hollow = [r for r in rows if r["label"] not in ("GENUINE", "UNCLEAR")]
    genuine = [r for r in rows if r["label"] == "GENUINE"]
    out = {}
    for name, key in (("scored", "flags"), ("eight_v1_patterns", "flags_v1")):
        out[name] = {
            "recall": dict(_rate(hollow, key), repo_bootstrap=_bootstrap(hollow, key)),
            "false_alarms": dict(_rate(genuine, key), repo_bootstrap=_bootstrap(genuine, key)),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True)
    parser.add_argument("--local", required=True)
    parser.add_argument("--out", default=str(HERE / "results.json"))
    parser.add_argument("--out-private", default=str(PRIVATE / "results_full.json"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    labels_path, private_labels = HERE / "labels.json", PRIVATE / "labels_L.json"
    rows = json.loads(labels_path.read_text(encoding="utf-8"))["functions"]
    if private_labels.exists():
        rows += json.loads(private_labels.read_text(encoding="utf-8"))["functions"]
    dirs = {
        r["repo"]: (
            (Path(args.local) / r["repo"])
            if r["tier"] == "L"
            else Path(args.dest) / r["repo"].replace("/", "__")
        )
        for r in rows
    }
    _check_binding(rows, dirs)
    names = sorted(dirs)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        scans = dict(zip(names, pool.map(lambda n: scan(dirs[n]), names)))

    for r in rows:
        s = scans[r["repo"]]
        if s["state"] == "ENV_BLOCKED":
            r["state"] = "ENV_BLOCKED"
        elif s["state"] != "COMPLETE" or r["file"] not in s["analyzed"]:
            r["state"] = "NOT_MEASURED"
        else:
            r["state"] = "MEASURED"
        first, last = r["span"]
        hits = [h for h in s["found"].get(r["file"], []) if first <= h[0] <= last]
        r["findings"] = [{"line": h[0], "pattern": h[1], "message": h[2]} for h in hits]
        r["flags"] = sorted({h[1] for h in hits if h[1] in SCORED})
        r["flags_v1"] = sorted({h[1] for h in hits if h[1] in v1.HOLLOW_PATTERNS})

    measured = [r for r in rows if r["state"] == "MEASURED"]
    excluded = len(rows) - len(measured)
    groups = {
        "A+B": [r for r in measured if r["tier"] in "AB"],
        "L": [r for r in measured if r["tier"] == "L"],
    }
    for tier in "ABL":
        for stratum in "RS":
            groups[f"{tier}/{stratum}"] = [
                r for r in measured if r["tier"] == tier and r["stratum"] == stratum
            ]
    groups["all"] = measured
    hollow = [r for r in measured if r["label"] not in ("GENUINE", "UNCLEAR")]
    genuine = [r for r in measured if r["label"] == "GENUINE"]
    report = {
        "labels_sha256": _sha(labels_path),
        "private_labels_sha256": _sha(private_labels) if private_labels.exists() else None,
        "detector_version": v1._version(),
        "src_sha256": v1._src_digest(),
        "scored_patterns": sorted(SCORED),
        "measurement_states": {n: s["state"] for n, s in scans.items()},
        "functions": len(rows),
        "excluded": excluded,
        "valid": excluded <= 0.10 * len(rows),
        "groups": {name: _summary(g) for name, g in groups.items()},
        "hollow_per_repo": {
            n: sum(1 for r in hollow if r["repo"] == n)
            for n in names
            if any(r["repo"] == n for r in hollow)
        },
        "per_pattern": {
            p: {
                "true": sum(p in r["flags"] for r in hollow),
                "false": sum(p in r["flags"] for r in genuine),
            }
            for p in sorted(SCORED)
        },
        "missed_hollow": [r for r in hollow if not r["flags"]],
        "flagged_genuine": [r for r in genuine if r["flags"]],
        "caught_hollow": [r for r in hollow if r["flags"]],
        "rows": rows,
    }
    full = Path(args.out_private)
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    public = public_view(report, _sha(full))
    Path(args.out).write_text(json.dumps(public, indent=1) + "\n", encoding="utf-8")
    print(
        f"detector {report['detector_version']}  labels {report['labels_sha256'][:12]}  "
        f"excluded {excluded}/{len(rows)}  valid {report['valid']}"
    )
    for name in ("A+B", "L", "all"):
        s = report["groups"][name]["scored"]
        print(
            f"{name:4} recall {s['recall']['flagged']}/{s['recall']['total']} {s['recall']['ci95']}"
            f"  false alarms {s['false_alarms']['flagged']}/{s['false_alarms']['total']} {s['false_alarms']['ci95']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
