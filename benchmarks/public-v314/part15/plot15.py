"""Draw the two Part 15 figures from m15_results.json.

    python plot15.py m15_results.json figures/

Every value in the figures is read from the results file; nothing is typed in.
"""
import json, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
d = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10.5, "axes.spines.top": False, "axes.spines.right": False})
C = {"T1": "#2f5d8a", "T2": "#7fa7cc", "T3": "#d9dde3", "refused": "#b5483c"}
# Figure 1: tiers per budget
b = d["budget"]; rows = b["rows"]
labels = [f"{r['budget']//1000}k" for r in rows]
fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160)
x = range(len(rows))
for i, r in enumerate(rows):
    if "refused" in r:
        ax.bar(i, b["items"], color="white", edgecolor=C["refused"], hatch="///", linewidth=1)
        ax.text(i, b["items"] + 2, "refused", ha="center", va="bottom", fontsize=8, color=C["refused"], rotation=90)
        continue
    bottom = 0
    for t in ("T1", "T2", "T3"):
        ax.bar(i, r[t], bottom=bottom, color=C[t], edgecolor="white", linewidth=0.5, label=t if i == 5 else None)
        bottom += r[t]
ax.set_xticks(list(x)); ax.set_xticklabels(labels)
ax.set_xlabel("--ai-token-budget (estimated tokens, characters / 4)")
ax.set_ylabel(f"items ({b['items']} in every row)")
ax.set_ylim(0, b["items"] * 1.32)
least = rows[0]["refused"].split("at least ")[1].split(" ")[0]
ax.set_title(f"How {b['items']} work-order items are drawn as the budget grows\n"
             f"AI-SLOP-Detector's own source at v3.14.2 ({b['files']} files); below {least} tokens the work order is refused", fontsize=10.5, loc="left")
h = [plt.Rectangle((0, 0), 1, 1, color=C[t]) for t in ("T1", "T2", "T3")] + [plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor=C["refused"], hatch="///")]
ax.legend(h, ["T1 whole function", "T2 signature + evidence + range to read", "T3 index line", "BUDGET_UNSATISFIABLE"], loc="upper left", fontsize=8.5, frameon=False, ncol=2)
fig.tight_layout(); fig.savefig(out / "part15_budget_tiers.png"); plt.close(fig)
# Figure 2: every surface of the same input (three CLI invocations)
s = d["surfaces"]["rows"]
order = ["terminal (default)", "report.md", "ai-report.jsonl", "ai-report.md", "ai-work.md (agent)", "report.html", "scan.json"]
names = {"terminal (default)": "terminal summary", "report.md": "report.md", "ai-report.jsonl": "ai-report.jsonl (--format ai)",
         "ai-report.md": "work order, auditor", "ai-work.md (agent)": "work order, agent", "report.html": "report.html", "scan.json": "scan.json (--json)"}
reader = {"terminal (default)": "person", "report.md": "person", "report.html": "person", "ai-report.jsonl": "program", "scan.json": "program", "ai-report.md": "agent", "ai-work.md (agent)": "agent"}
col = {"person": "#4f7f5a", "program": "#8a8f98", "agent": "#2f5d8a"}
fig, ax = plt.subplots(figsize=(9, 3.9), dpi=160)
vals = [s[k]["est_tokens"] for k in order]
ax.barh(range(len(order)), vals, color=[col[reader[k]] for k in order])
for i, v in enumerate(vals):
    ax.text(v + 60, i, f"{v:,}  ({s[order[i]]['lines']} lines)", va="center", fontsize=8.5)
ax.set_yticks(range(len(order))); ax.set_yticklabels([names[k] for k in order]); ax.invert_yaxis()
ax.set_xlabel("estimated tokens (characters / 4)"); ax.set_xlim(0, max(vals) * 1.42)
ax.set_title("examples/demo_project (3 files, 13 items) for seven readers - 3.14.2\n"
             f"three CLI runs on the same input; report.pdf: {s['report.pdf']['bytes']:,} bytes, printed from report.html",
             fontsize=10.5, loc="left")
h = [plt.Rectangle((0, 0), 1, 1, color=col[k]) for k in ("person", "program", "agent")]
ax.legend(h, ["for a person", "for a program", "for an agent"], loc="upper right", fontsize=8.5, frameon=False)
fig.tight_layout(); fig.savefig(out / "part15_surfaces.png"); plt.close(fig)
print("ok")
