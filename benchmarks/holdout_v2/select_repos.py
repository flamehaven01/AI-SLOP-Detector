"""Pick hold-out v2 repositories from the saved search frames (no network).

Inputs: frames/<band>.json (build_frames.py), the private exclusions.json
(build_exclusions.py), safety.json (purpose decisions) and estimate.json
(estimate_download.py, Python file counts).

A repository is ineligible when it is a fork or archived, is outside
100 KB - 80 MB, describes itself as a list, belongs to an excluded owner, or
matches an excluded owner/repo or repository name. Each band's eligible
repositories are walked in sha256(SEED + full name) order. A repository is
skipped, with the reason recorded, when safety.json excludes it for its stated
purpose (SAFETY_CODES) or its commit tree has fewer than MIN_PY Python files;
the walk stops when PRIMARY primaries and RESERVE reserves are filled.

A description matching SCREEN is only routed to review: it needs a safety.json
decision before it can be selected or skipped. Code quality and expected
detector results are never a reason. The walk stops with an error when a
screened repository has no decision, or a walked one has no estimate yet.

usage: python -P benchmarks/holdout_v2/select_repos.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXCLUSIONS = HERE.parents[1] / ".internal" / "holdout_v2" / "exclusions.json"
SEED = "holdout-v2-20261026"
PRIMARY, RESERVE, MIN_PY = 2, 1, 10
LIST_WORDS = re.compile(r"\b(awesome|curated list|list of)\b", re.I)
LINEAGE_WORDS = re.compile(
    r"\b(fork|port|clone|rewrite|reimplementation|mirror|copy) of\b|\bunofficial\b", re.I
)
# Stated purposes that need a decision: licence/auth bypass, piracy, automated trading.
SCREEN = re.compile(
    r"bypass|crack|keygen|free[ -]?vip|machine ?id|unlock|pirat|warez|学习版|破解|"
    r"trading bot|trade bot|auto[- ]?trad|pump\.?fun|sniper|ticket[- ]?grab|抢票|scalp",
    re.I,
)
SAFETY_CODES = {"LICENSE_BYPASS", "PIRACY", "AUTO_TRADING"}


def ineligible(repo: dict, rules: dict) -> str:
    full = repo["fullName"].lower()
    owner, name = full.split("/")
    if repo["isFork"]:
        return "fork"
    if repo["isArchived"]:
        return "archived"
    if not 100 <= repo["size"] <= 80000:
        return "size"
    if LIST_WORDS.search(repo.get("description") or ""):
        return "list"
    if owner in rules["owners"]:
        return "own owner"
    if full in rules["repositories"] or name in rules["names"]:
        return "known repository"
    return ""


def load(name: str, default):
    path = HERE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def main() -> int:
    rules = {k: set(v) for k, v in json.loads(EXCLUSIONS.read_text(encoding="utf-8")).items()}
    safety = load("safety.json", {"decisions": {}})["decisions"]
    py_files = {row["repo"]: row["py_files"] for row in load("estimate.json", [])}
    picked, skipped, summary, missing = [], [], {}, {"decision": [], "estimate": []}
    for path in sorted((HERE / "frames").glob("*.json")):
        frame = json.loads(path.read_text(encoding="utf-8"))
        band = frame["band"]
        pool = {r["fullName"]: r for q in frame["queries"] for r in q["repos"]}
        reasons = {name: ineligible(r, rules) for name, r in pool.items()}
        order = sorted(
            (n for n, why in reasons.items() if not why),
            key=lambda n: hashlib.sha256(f"{SEED}:{n}".encode("utf-8")).hexdigest(),
        )
        filled = 0
        for rank, name in enumerate(order, 1):
            if filled == PRIMARY + RESERVE:
                break
            r = pool[name]
            desc = r.get("description") or ""
            screened = bool(SCREEN.search(desc))
            decision = safety.get(name, {}).get("code")
            if screened and decision is None:
                missing["decision"].append(name)
                break
            if decision in SAFETY_CODES:
                skipped.append({"band": band, "rank": rank, "repo": name, "reason": decision})
                continue
            if name not in py_files:
                missing["estimate"].append(name)
                break
            if py_files[name] < MIN_PY:
                reason = f"{py_files[name]} Python files"
                skipped.append({"band": band, "rank": rank, "repo": name, "reason": reason})
                continue
            filled += 1
            picked.append(
                {
                    "band": band,
                    "rank": rank,
                    "role": "primary" if filled <= PRIMARY else "reserve",
                    "repo": name,
                    "stars": r["stargazersCount"],
                    "size_kb": r["size"],
                    "created": r["createdAt"][:10],
                    "license": (r.get("license") or {}).get("key"),
                    "description": desc,
                    "screened": screened,
                    "safety_decision": decision,
                    "lineage_words_in_description": bool(LINEAGE_WORDS.search(desc)),
                }
            )
        counts = {}
        for why in reasons.values():
            counts[why or "eligible"] = counts.get(why or "eligible", 0) + 1
        summary[band] = {
            "in_frame": len(pool),
            **counts,
            "shortfall": PRIMARY + RESERVE - filled,
        }
    if missing["decision"] or missing["estimate"]:
        (HERE / "pending.json").write_text(json.dumps(missing, indent=1) + "\n", encoding="utf-8")
        print(f"pending: {missing}")
        return 1
    out = {"seed": SEED, "bands": summary, "repos": picked, "skipped": skipped}
    (HERE / "repos.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for band, s in summary.items():
        print(band, s)
    for s in skipped:
        print("skipped", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
