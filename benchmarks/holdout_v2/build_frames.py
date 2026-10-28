"""Fetch the hold-out v2 search frames (GitHub metadata only, no clone).

Each tier is split into star bands. A search sorted by stars only reaches the top
of a band, so instead each band is cut into WINDOWS equal star windows, DRAWN of
them are picked at random (seeded), and each window is searched as a star range:
Python, created on or after 2025-01-01, first PER_WINDOW results. Bands narrower
than WINDOWS get one-star windows (exact counts). Writes frames/<band>.json.

usage: python -P benchmarks/holdout_v2/build_frames.py
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = "holdout-v2-20261026"
BANDS = {
    "A1": (100, 499),
    "A2": (500, 999),
    "A3": (1000, 1999),
    "A4": (2000, 5000),
    "B1": (10, 19),
    "B2": (20, 39),
    "B3": (40, 69),
    "B4": (70, 99),
}
WINDOWS, DRAWN, PER_WINDOW = 20, 10, 50
FIELDS = "fullName,isFork,isArchived,size,stargazersCount,createdAt,pushedAt,description,license"


def search(stars: str) -> list:
    cmd = ["gh", "search", "repos", "--language=python", "--created=>=2025-01-01"]
    cmd += [f"--stars={stars}", f"--limit={PER_WINDOW}", f"--json={FIELDS}"]
    done = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if done.returncode != 0:
        raise SystemExit(f"search failed for stars={stars}: {done.stderr.strip()}")
    return json.loads(done.stdout)


def main() -> int:
    out_dir = HERE / "frames"
    out_dir.mkdir(exist_ok=True)
    for band, (low, high) in BANDS.items():
        rng = random.Random(f"{SEED}:{band}")
        width = max(1, -(-(high - low + 1) // WINDOWS))
        starts = list(range(low, high + 1, width))
        windows = [(s, min(s + width - 1, high)) for s in sorted(rng.sample(starts, DRAWN))]
        queries = []
        for lo, hi in windows:
            stars = str(lo) if lo == hi else f"{lo}..{hi}"
            queries.append({"stars": stars, "repos": search(stars)})
            time.sleep(2.5)  # search API: 30 requests per minute
        frame = {"band": band, "range": [low, high], "snapshot": time.strftime("%Y-%m-%d")}
        frame["queries"] = queries
        path = out_dir / f"{band}.json"
        path.write_text(json.dumps(frame, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"{band}: windows {windows}, {sum(len(q['repos']) for q in queries)} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
