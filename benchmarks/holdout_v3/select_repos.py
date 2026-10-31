"""Pick the hold-out v3 repositories (PROTOCOL.md sections 1-3). Metadata only.

Eligibility is v2's (`ineligible`: forks, archives, size, lists, excluded
owners, owner/repo and names) against the private v3 exclusion list. Walks:

- A+B: per band, eligible repositories in sha256(SEED:name) order, the AI
  signal ignored; PRIMARY primaries and RESERVE reserves.
- AI_ASSOCIATED: the eligible repositories A+B did not take, all bands pooled,
  same hash order; a repository needs an AI signal (section 2); AI_PRIMARY
  primaries (at most AI_BAND_CAP from one band) and AI_RESERVE reserves.

A walked repository is skipped, with the reason recorded, when safety.json
excludes it for its stated purpose or its commit tree has fewer than MIN_PY
Python files. A description matching v2's SCREEN needs a safety.json decision
first: the walk stops and pending.json lists it. Code is never read here: the
signal comes from the commit tree's paths and the last 100 commit messages
(cached in estimate.json / signals.json, so a rerun does not refetch).

usage: python -P benchmarks/holdout_v3/select_repos.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "holdout_v2"))

from estimate_download import api, selected  # noqa: E402
from select_repos import LINEAGE_WORDS, SAFETY_CODES, SCREEN, ineligible  # noqa: E402

EXCLUSIONS = HERE.parents[1] / ".internal" / "holdout_v3" / "exclusions.json"
SEED = "holdout-v3-20261030"
PRIMARY, RESERVE, MIN_PY = 2, 1, 10
AI_PRIMARY, AI_RESERVE, AI_BAND_CAP = 16, 16, 4
INSTRUCTION_FILES = {
    "claude.md", "agents.md", "gemini.md", ".cursorrules", ".windsurfrules", ".clinerules"
}
TRAILER = re.compile(
    r"^co-authored-by:.*\b(claude|copilot|cursor|gemini|codex|devin|aider)\b", re.I | re.M
)


def _cache(name: str) -> dict:
    path = HERE / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(name: str, data: dict) -> None:
    (HERE / name).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def estimate(name: str, cache: dict) -> dict:
    """Commit, Python file count, sparse size and instruction-file paths."""
    if name not in cache:
        meta = api(f"repos/{name}")
        commit = api(f"repos/{name}/commits/{meta['default_branch']}")["sha"]
        tree = api(f"repos/{name}/git/trees/{commit}?recursive=1")
        blobs = [e for e in tree["tree"] if e["type"] == "blob"]
        paths = [e["path"] for e in blobs]
        cache[name] = {
            "commit": commit,
            "tree_truncated": tree.get("truncated", False),
            "py_files": sum(p.endswith(".py") for p in paths),
            "sparse_bytes": sum(e.get("size", 0) for e in blobs if selected(e["path"])),
            "submodules": sum(e["type"] == "commit" for e in tree["tree"]),
            "instruction_files": sorted(
                p
                for p in paths
                if p.rsplit("/", 1)[-1].lower() in INSTRUCTION_FILES
                or p.lower() == ".github/copilot-instructions.md"
                or p.lower().startswith(".cursor/rules/")
            ),
        }
        _save("estimate.json", cache)
    return cache[name]


def trailers(name: str, commit: str, cache: dict) -> list:
    """AI co-author trailers in the last 100 commit messages up to `commit`."""
    if name not in cache:
        rows = api(f"repos/{name}/commits?sha={commit}&per_page=100")
        found = sorted({m.group(0).strip() for r in rows for m in TRAILER.finditer(r["commit"]["message"])})
        cache[name] = found
        _save("signals.json", cache)
    return cache[name]


def ordered(names) -> list:
    return sorted(names, key=lambda n: hashlib.sha256(f"{SEED}:{n}".encode("utf-8")).hexdigest())


class Walk:
    """Shared skip rules and records for both tiers."""

    def __init__(self, pool: dict, safety: dict) -> None:
        self.pool, self.safety = pool, safety
        self.est, self.sig = _cache("estimate.json"), _cache("signals.json")
        self.picked, self.skipped, self.pending = [], [], []

    def usable(self, tier: str, band: str, rank: int, name: str) -> bool:
        desc = self.pool[name].get("description") or ""
        decision = self.safety.get(name, {}).get("code")
        if SCREEN.search(desc) and decision is None:
            self.pending.append(name)
            return False
        if decision in SAFETY_CODES:
            self.skipped.append({"tier": tier, "band": band, "rank": rank, "repo": name, "reason": decision})
            return False
        est = estimate(name, self.est)
        if est["py_files"] < MIN_PY:
            why = f"{est['py_files']} Python files"
            self.skipped.append({"tier": tier, "band": band, "rank": rank, "repo": name, "reason": why})
            return False
        return True

    def signal(self, name: str) -> dict:
        est = estimate(name, self.est)
        return {
            "instruction_files": est["instruction_files"],
            "co_author_trailers": trailers(name, est["commit"], self.sig),
        }

    def pick(self, tier: str, band: str, rank: int, name: str, role: str, signal=None) -> None:
        r, est = self.pool[name], self.est[name]
        desc = r.get("description") or ""
        self.picked.append(
            {
                "tier": tier,
                "band": band,
                "rank": rank,
                "role": role,
                "repo": name,
                "commit": est["commit"],
                "stars": r["stargazersCount"],
                "size_kb": r["size"],
                "created": r["createdAt"][:10],
                "license": (r.get("license") or {}).get("key"),
                "description": desc,
                "py_files": est["py_files"],
                "signal": signal,
                "safety_decision": self.safety.get(name, {}).get("code"),
                "lineage_words_in_description": bool(LINEAGE_WORDS.search(desc)),
            }
        )


def walk_ab(walk: Walk, bands: dict) -> None:
    for band, names in bands.items():
        filled = 0
        for rank, name in enumerate(ordered(names), 1):
            if filled == PRIMARY + RESERVE or walk.pending:
                break
            if walk.usable("A+B", band, rank, name):
                filled += 1
                walk.pick("A+B", band, rank, name, "primary" if filled <= PRIMARY else "reserve")


def walk_ai(walk: Walk, bands: dict) -> None:
    taken = {p["repo"] for p in walk.picked}
    band_of = {n: b for b, names in bands.items() for n in names}
    per_band, primaries, reserves = {}, 0, 0
    for rank, name in enumerate(ordered(n for n in band_of if n not in taken), 1):
        if reserves == AI_RESERVE or walk.pending:
            break
        band = band_of[name]
        if not walk.usable("AI_ASSOCIATED", band, rank, name):
            continue
        signal = walk.signal(name)
        if not (signal["instruction_files"] or signal["co_author_trailers"]):
            continue
        if primaries < AI_PRIMARY and per_band.get(band, 0) < AI_BAND_CAP:
            primaries += 1
            per_band[band] = per_band.get(band, 0) + 1
            walk.pick("AI_ASSOCIATED", band, rank, name, "primary", signal)
        elif primaries == AI_PRIMARY:
            reserves += 1
            walk.pick("AI_ASSOCIATED", band, rank, name, "reserve", signal)


def main() -> int:
    rules = {k: set(v) for k, v in json.loads(EXCLUSIONS.read_text(encoding="utf-8")).items()}
    safety = _cache("safety.json").get("decisions", {})
    pool, bands, summary = {}, {}, {}
    for path in sorted((HERE / "frames").glob("*.json")):
        frame = json.loads(path.read_text(encoding="utf-8"))
        repos = {r["fullName"]: r for q in frame["queries"] for r in q["repos"]}
        reasons = {n: ineligible(r, rules) for n, r in repos.items()}
        bands[frame["band"]] = [n for n, why in reasons.items() if not why]
        pool.update(repos)
        counts = {}
        for why in reasons.values():
            counts[why or "eligible"] = counts.get(why or "eligible", 0) + 1
        summary[frame["band"]] = {"in_frame": len(repos), **counts}
    walk = Walk(pool, safety)
    walk_ab(walk, bands)
    if not walk.pending:
        walk_ai(walk, bands)
    if walk.pending:
        _save("pending.json", {"decision": walk.pending})
        print(f"pending safety decisions: {walk.pending}")
        return 1
    (HERE / "pending.json").unlink(missing_ok=True)
    out = {"seed": SEED, "bands": summary, "repos": walk.picked, "skipped": walk.skipped}
    (HERE / "repos.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for tier in ("A+B", "AI_ASSOCIATED"):
        for role in ("primary", "reserve"):
            n = sum(p["tier"] == tier and p["role"] == role for p in walk.picked)
            print(tier, role, n)
    print("skipped", len(walk.skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
