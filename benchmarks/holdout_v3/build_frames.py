"""Fetch the hold-out v3 search frames (GitHub metadata only, no clone).

The v2 method (benchmarks/holdout_v2/build_frames.py, same bands, windows and
search) with the v3 seed: each band is cut into WINDOWS star windows, DRAWN are
picked (seeded) and each is searched as a star range, Python, created on or
after 2025-01-01, first PER_WINDOW results. Writes frames/<band>.json.

usage: python -P benchmarks/holdout_v3/build_frames.py
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "holdout_v2"))

from build_frames import BANDS, DRAWN, WINDOWS, search  # noqa: E402

SEED = "holdout-v3-20261030"


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
        frame = {"band": band, "range": [low, high], "seed": SEED}
        frame["snapshot"] = time.strftime("%Y-%m-%d")
        frame["queries"] = queries
        path = out_dir / f"{band}.json"
        path.write_text(json.dumps(frame, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"{band}: windows {windows}, {sum(len(q['repos']) for q in queries)} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
