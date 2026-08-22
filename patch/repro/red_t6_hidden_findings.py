"""RED for T-6: the text report hides pattern hits that the analysis found.

A file whose deficit score lands under the threshold is printed as "clean" and
its pattern issues are never rendered. At project scale the summary can read
CLEAN while the run holds critical-severity hits, visible only in --json.

Run:  python patch/repro/red_t6_hidden_findings.py [path]
Exit: 1 while RED, 0 once the text report accounts for every hit.
"""

import collections
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "src"

out = Path(tempfile.mkdtemp()) / "scan.json"
env_src = str(REPO / "src")

print("== T-6: pattern hits found vs pattern hits shown ==")
print(f"   target: {target}  (this runs a full scan; it takes a minute)")

code = (
    "from slop_detector.cli import main; import sys; "
    f"sys.argv=['slop-detector', r'{target}', '--project', '--json', '-o', r'{out}']; "
    "main()"
)
subprocess.run([sys.executable, "-c", code], cwd=str(REPO),
               env={**__import__("os").environ, "PYTHONPATH": env_src},
               capture_output=True, text=True)

if not out.exists():
    print("  scan produced no JSON; cannot measure")
    sys.exit(1)

data = json.loads(out.read_text(encoding="utf-8"))
results = data.get("file_results", [])

severity = collections.Counter()
hidden = 0
for f in results:
    issues = f.get("pattern_issues") or []
    for p in issues:
        severity[p.get("severity", "?")] += 1
    if f.get("status") == "clean":
        hidden += len(issues)

total = sum(severity.values())
print()
print(f"  files analysed        : {data.get('total_files')}")
print(f"  project overall_status: {data.get('overall_status')}")
print(f"  deficit files         : {data.get('deficit_files')}")
print(f"  pattern hits found    : {total}  {dict(severity)}")
print(f"  hits inside 'clean' files (not rendered in the text report): {hidden}")

if total and hidden:
    print()
    print("  RED: the analysis produced findings that the human-facing report")
    print("       does not mention. Severity is irrelevant to visibility -- a")
    print("       critical hit in a file scoring under the deficit threshold is")
    print("       printed nowhere. Only --json carries it.")
    print("  GREEN: the text report states the pattern-hit total and severity")
    print("         breakdown for the whole run, independent of per-file score.")
    sys.exit(1)

print("  GREEN")
sys.exit(0)
