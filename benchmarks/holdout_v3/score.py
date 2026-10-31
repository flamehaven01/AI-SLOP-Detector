"""Score the frozen detector once on the frozen hold-out v3 labels (PROTOCOL.md 6-9).

v2's scan, source binding, Wilson and repository-bootstrap intervals
(benchmarks/holdout_v2/score.py). Before any scan the detector source digest must
equal FROZEN_SRC_SHA256, the digest recorded when the detector was frozen; a
different source is refused. Groups are reported per tier, per stratum and, for
AI_ASSOCIATED, per signal family; recall is split by evidence kind. A tier with
more than 10% of its functions excluded is invalid. Writes results.json and the
evaluation receipt (receipt.json).

usage: python -P benchmarks/holdout_v3/score.py --dest SNAPSHOT_DIR
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("holdout_v2_score", HERE.parent / "holdout_v2" / "score.py")
v2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v2)

FROZEN_COMMIT = "13f08e31af46023fd0889d9e18c3b50d2d272c7d"
FROZEN_SRC_SHA256 = "87a9c63b10d142af982859eeb6a914a1cde2e054970f27fe40913d2cd013fcb2"
SCORED = v2.SCORED  # v1's eight; the frozen version adds no hollow pattern id
TIERS = ("A+B", "AI_ASSOCIATED")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha(paths: list) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(f"{p.relative_to(HERE).as_posix()}\0{_sha(p)}\n".encode("utf-8"))
    return h.hexdigest()


def _groups(measured: list) -> dict:
    groups = {}
    for tier in TIERS:
        in_tier = [r for r in measured if r["tier"] == tier]
        groups[tier] = in_tier
        for stratum in "RS":
            groups[f"{tier}/{stratum}"] = [r for r in in_tier if r["stratum"] == stratum]
    ai = groups["AI_ASSOCIATED"]
    groups["AI_ASSOCIATED/instruction_file"] = [r for r in ai if r["ai_signal"]["instruction_file"]]
    groups["AI_ASSOCIATED/co_author_trailer"] = [r for r in ai if r["ai_signal"]["co_author_trailer"]]
    return groups


def _by_evidence(hollow: list) -> dict:
    out = {}
    for kind in ("STATIC", "SEMANTIC"):
        rows = [r for r in hollow if r["evidence"] == kind]
        out[kind] = v2._rate(rows, "flags")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    src = v2.v1._src_digest()
    if src != FROZEN_SRC_SHA256:
        raise SystemExit(f"detector source {src[:12]} is not the frozen {FROZEN_SRC_SHA256[:12]}")
    labels_path = HERE / "labels.json"
    rows = json.loads(labels_path.read_text(encoding="utf-8"))["functions"]
    dirs = {r["repo"]: Path(args.dest) / r["dir"] for r in rows}
    v2._check_binding(rows, dirs)
    names = sorted(dirs)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        scans = dict(zip(names, pool.map(lambda n: v2.scan(dirs[n]), names)))

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
        r["flags_v1"] = list(r["flags"])

    measured = [r for r in rows if r["state"] == "MEASURED"]
    validity = {}
    for tier in TIERS:
        total = sum(r["tier"] == tier for r in rows)
        excluded = total - sum(r["tier"] == tier for r in measured)
        validity[tier] = {"functions": total, "excluded": excluded, "valid": excluded <= 0.10 * total}
    groups = _groups(measured)
    hollow = [r for r in measured if r["label"] not in ("GENUINE", "UNCLEAR")]
    genuine = [r for r in measured if r["label"] == "GENUINE"]
    report = {
        "detector_commit": FROZEN_COMMIT,
        "detector_version": v2.v1._version(),
        "src_sha256": src,
        "labels_sha256": _sha(labels_path),
        "scored_patterns": sorted(SCORED),
        "measurement_states": {n: s["state"] for n, s in scans.items()},
        "validity": validity,
        "groups": {name: v2._summary(g)["scored"] for name, g in groups.items()},
        "recall_by_evidence": {
            tier: _by_evidence([r for r in hollow if r["tier"] == tier]) for tier in TIERS
        },
        "unclear": sum(r["label"] == "UNCLEAR" for r in measured),
        "hollow_per_repo": {
            n: sum(r["repo"] == n for r in hollow) for n in names if any(r["repo"] == n for r in hollow)
        },
        "per_pattern": {
            p: {"true": sum(p in r["flags"] for r in hollow), "false": sum(p in r["flags"] for r in genuine)}
            for p in sorted(SCORED)
        },
        "caught_hollow": [r for r in hollow if r["flags"]],
        "missed_hollow": [r for r in hollow if not r["flags"]],
        "flagged_genuine": [r for r in genuine if r["flags"]],
        "rows": rows,
    }
    results = HERE / "results.json"
    # LF, as git stores it, so the receipt digests match a fresh checkout
    results.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    receipt = {
        "scored_at_repository_head": head,
        "detector_commit": FROZEN_COMMIT,
        "detector_src_sha256": src,
        "scorer_sha256": _sha(Path(__file__)),
        "protocol_sha256": _sha(HERE / "PROTOCOL.md"),
        "frames_sha256": _tree_sha(list((HERE / "frames").glob("*.json"))),
        "selection_sha256": _sha(HERE / "repos.json"),
        "snapshot_receipts_sha256": _tree_sha(list((HERE / "receipts").glob("*.json"))),
        "exclusions_digest_sha256": _sha(HERE / "exclusions_digest.json"),
        "labels_sha256": _sha(labels_path),
        "results_sha256": _sha(results),
        "single_use": "v3 is scored once; any rule change after these results makes it development data",
    }
    (HERE / "receipt.json").write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8", newline="\n")
    for tier in TIERS:
        s = report["groups"][tier]
        print(
            f"{tier:14} recall {s['recall']['flagged']}/{s['recall']['total']} {s['recall']['ci95']}"
            f"  false alarms {s['false_alarms']['flagged']}/{s['false_alarms']['total']}"
            f" {s['false_alarms']['ci95']}  valid {validity[tier]['valid']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
