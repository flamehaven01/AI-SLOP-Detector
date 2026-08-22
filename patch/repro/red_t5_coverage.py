"""RED for T-5: only Python is scanned, and the report does not say so.

cli_analysis.py:23 walks `scan_root.rglob("*.py")`. Markdown, YAML and JSON are
never opened. Nothing in the summary tells the reader how much of the tree went
unexamined.

Run:  python patch/repro/red_t5_coverage.py [path]
Exit: 1 while RED, 0 once the report accounts for unscanned files.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCANNED_SUFFIXES = {".py"}                      # cli_analysis.py:23
OPT_IN_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".go"}   # --js / go, off by default
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
             "build", "dist", ".tox", "htmlcov", ".pytest_cache"}

target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "src"

counts = {"scanned": 0, "opt_in": 0, "unscanned": 0}
lines = {"scanned": 0, "opt_in": 0, "unscanned": 0}
by_suffix = {}

for path in target.rglob("*"):
    if not path.is_file():
        continue
    if any(part in SKIP_DIRS for part in path.parts):
        continue
    suffix = path.suffix.lower()
    if suffix in SCANNED_SUFFIXES:
        bucket = "scanned"
    elif suffix in OPT_IN_SUFFIXES:
        bucket = "opt_in"
    else:
        bucket = "unscanned"
    try:
        n = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError:
        n = 0
    counts[bucket] += 1
    lines[bucket] += n
    if bucket == "unscanned":
        by_suffix[suffix or "(none)"] = by_suffix.get(suffix or "(none)", 0) + n

total_lines = sum(lines.values()) or 1

print("== T-5: what a scan of this tree actually reads ==")
print(f"   target: {target}")
print()
print(f"  scanned (.py)        {counts['scanned']:5d} files  {lines['scanned']:7d} lines  "
      f"{lines['scanned'] / total_lines * 100:5.1f}%")
print(f"  opt-in  (--js / go)  {counts['opt_in']:5d} files  {lines['opt_in']:7d} lines  "
      f"{lines['opt_in'] / total_lines * 100:5.1f}%")
print(f"  never read           {counts['unscanned']:5d} files  {lines['unscanned']:7d} lines  "
      f"{lines['unscanned'] / total_lines * 100:5.1f}%")
print()
print("  never-read lines by extension:")
for suffix, n in sorted(by_suffix.items(), key=lambda kv: -kv[1])[:8]:
    print(f"    {suffix:8s} {n:7d}")

print()
if lines["unscanned"]:
    print("  RED: the summary reports no figure for any of this. A reader sees")
    print("       'Total Files N / Overall Status CLEAN' and cannot tell that")
    print(f"       {lines['unscanned']} lines were never opened.")
    print("  GREEN: print 'Unscanned: N files (unsupported types)' in the project")
    print("         summary and carry the same figure in --json.")
    sys.exit(1)

print("  GREEN")
sys.exit(0)
