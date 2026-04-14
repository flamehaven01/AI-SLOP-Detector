"""Generate PyPI download chart for AI-SLOP Detector.

Fetches daily download data from pypistats.org, aggregates by week,
and saves an SVG chart to docs/assets/downloads.svg.

Usage:
    python scripts/generate_download_chart.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

PACKAGE = "ai-slop-detector"
API_URL = f"https://pypistats.org/api/packages/{PACKAGE}/overall?mirrors=false"
OUTPUT = Path(__file__).parent.parent / "docs" / "assets" / "downloads.svg"


def fetch_data() -> list[dict]:
    req = urllib.request.Request(
        API_URL,
        headers={"User-Agent": "generate-download-chart/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    return [r for r in payload["data"] if r["category"] == "without_mirrors"]


def aggregate_weekly(records: list[dict]) -> tuple[list[datetime], list[int]]:
    weekly: dict[datetime, int] = defaultdict(int)
    for r in records:
        d = datetime.strptime(r["date"], "%Y-%m-%d")
        # ISO week start (Monday)
        week_start = d - timedelta(days=d.weekday())
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        weekly[week_start] += r["downloads"]

    sorted_weeks = sorted(weekly.items())
    # Drop the current incomplete week
    if sorted_weeks:
        sorted_weeks = sorted_weeks[:-1]

    dates = [w for w, _ in sorted_weeks]
    counts = [c for _, c in sorted_weeks]
    return dates, counts


def make_chart(dates: list[datetime], counts: list[int]) -> None:
    fig, ax = plt.subplots(figsize=(10, 3.6))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")

    xs = mdates.date2num(dates)

    # Gradient fill using polygon
    ax.fill_between(
        dates,
        counts,
        alpha=0.18,
        color="#f78166",
        linewidth=0,
    )
    ax.plot(
        dates,
        counts,
        color="#f78166",
        linewidth=2.0,
        solid_capstyle="round",
    )

    # Peak annotation
    if counts:
        peak_idx = int(np.argmax(counts))
        ax.annotate(
            f"{counts[peak_idx]:,}",
            xy=(dates[peak_idx], counts[peak_idx]),
            xytext=(8, 8),
            textcoords="offset points",
            fontsize=8,
            color="#f0f6fc",
            fontfamily="monospace",
        )

    # Latest week annotation
    if len(counts) >= 1:
        ax.annotate(
            f"latest: {counts[-1]:,}/wk",
            xy=(dates[-1], counts[-1]),
            xytext=(-60, 10),
            textcoords="offset points",
            fontsize=7.5,
            color="#8b949e",
            fontfamily="monospace",
        )

    # Axes style
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b '%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda x, _: f"{int(x):,}"))

    for spine in ax.spines.values():
        spine.set_visible(False)

    ax.tick_params(colors="#8b949e", labelsize=8)
    ax.yaxis.set_tick_params(length=0)
    ax.xaxis.set_tick_params(length=0)
    ax.grid(axis="y", color="#21262d", linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)

    ax.set_ylim(bottom=0)
    ax.set_xlim(left=dates[0] if dates else None)

    # Title
    total = sum(counts)
    ax.set_title(
        f"PyPI Downloads — ai-slop-detector  ({total:,} total)",
        color="#c9d1d9",
        fontsize=9,
        loc="left",
        pad=10,
        fontfamily="monospace",
    )

    fig.tight_layout(pad=0.6)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT, format="svg", bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[+] Chart saved to {OUTPUT}")


def main() -> None:
    try:
        records = fetch_data()
    except Exception as exc:
        print(f"[-] Failed to fetch data: {exc}", file=sys.stderr)
        sys.exit(1)

    dates, counts = aggregate_weekly(records)
    if not dates:
        print("[-] No data to chart.", file=sys.stderr)
        sys.exit(1)

    make_chart(dates, counts)


if __name__ == "__main__":
    main()
