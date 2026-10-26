"""Recall of the detector on labeled hollow functions, and false alarms on genuine ones.

A function counts as caught when at least one pattern finding falls inside its
line span. Findings without a line (file-level claim checks) are listed per
file but not attributed to a function.

usage: python benchmarks/recall/measure.py [--json OUT] [--python PYTHON]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases"
REPO_SRC = HERE.parents[1] / "src"


def function_spans(path: Path) -> dict:
    """Qualified name -> (first line, last line) for every function in a file."""
    spans = {}

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                spans[prefix + child.name] = (start, child.end_lineno)

    visit(ast.parse(path.read_text(encoding="utf-8")), "")
    return spans


def scan(python: str, path: Path) -> dict:
    """Run the detector on one file, read-only, with an empty home directory."""
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, HOME=home, USERPROFILE=home, PYTHONHASHSEED="1")
        env.pop("SLOP_CONFIG", None)
        env["PYTHONPATH"] = str(REPO_SRC) + os.pathsep + env.get("PYTHONPATH", "")
        done = subprocess.run(
            [python, "-m", "slop_detector.cli", str(path), "--json", "--read-only"],
            capture_output=True,
            env=env,
            cwd=home,
            timeout=300,
        )
    return json.loads(done.stdout.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", dest="out")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()

    labels = json.loads((HERE / "labels.json").read_text(encoding="utf-8"))["functions"]
    rows = []
    file_level = {}
    version = None
    for name, expected in sorted(labels.items()):
        path = CASES / name
        result = scan(args.python, path)
        version = version or result.get("detector_version") or result.get("version")
        spans = function_spans(path)
        findings = result.get("pattern_issues", [])
        file_level[name] = {
            "status": result.get("status"),
            "deficit_score": round(result.get("deficit_score", 0.0), 2),
            "inflation": (result.get("inflation") or {}).get("status"),
            "unlocated_findings": [f.get("pattern_id") for f in findings if not f.get("line")],
        }
        for qualname, label in expected.items():
            first, last = spans[qualname]
            hits = sorted(
                {f["pattern_id"] for f in findings if f.get("line") and first <= f["line"] <= last}
            )
            rows.append({"file": name, "function": qualname, "label": label, "findings": hits})

    by_class = defaultdict(lambda: [0, 0])
    for row in rows:
        by_class[row["label"]][0] += 1
        by_class[row["label"]][1] += bool(row["findings"])

    hollow = [r for r in rows if r["label"] != "GENUINE"]
    genuine = [r for r in rows if r["label"] == "GENUINE"]
    caught = sum(bool(r["findings"]) for r in hollow)
    false_alarms = sum(bool(r["findings"]) for r in genuine)
    print(f"detector {version or 'unknown'}")
    print(f"hollow caught: {caught}/{len(hollow)}   genuine flagged: {false_alarms}/{len(genuine)}")
    for label in sorted(by_class):
        total, hit = by_class[label]
        print(f"  {label:24} {hit}/{total}")
    for row in rows:
        mark = "x" if row["findings"] else "."
        print(f"  [{mark}] {row['label']:24} {row['file']}::{row['function']} {row['findings']}")
    if args.out:
        summary = {
            "detector_version": version,
            "hollow_caught": caught,
            "hollow_total": len(hollow),
            "genuine_flagged": false_alarms,
            "genuine_total": len(genuine),
            "by_class": {k: {"total": v[0], "caught": v[1]} for k, v in sorted(by_class.items())},
            "functions": rows,
            "files": file_level,
        }
        Path(args.out).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
