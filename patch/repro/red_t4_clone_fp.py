"""RED for T-4: the clone metric reads shape, not meaning, and scales wrong.

_node_histogram() counts 30 AST node types and then normalises
(stub_density.py:142-145). Normalising discards identifiers, call targets,
return types and -- decisively -- function size. Functions of very different
lengths and unrelated purposes land inside the JSD < 0.05 clone threshold.

Scope note: this measures the underlying metric, not FunctionClonePattern.
The pattern adds guards (_is_dispatcher_pattern, _is_property_accessor_cluster,
a four-function minimum, a four-member clique) that suppress the metric in some
files and not others. Those guards are load-bearing: with the metric colliding
at the densities printed below, whether a file is flagged depends on how many
functions it happens to hold. The pattern does fire on this repository's own
src/ -- five clusters, one of them listing "check_node" four times, which are
sibling implementations of one interface across different classes.

With no argument this scans the detector's own src/ tree, so the defect
reproduces on this checkout alone. Pass a path to measure another file.

Run:  python patch/repro/red_t4_clone_fp.py [path/to/file_or_dir]
Exit: 1 while RED, 0 once unrelated functions stop clustering.
"""

import ast
import itertools
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from slop_detector.metrics.stub_density import (  # noqa: E402
    _CLONE_JSD_THRESHOLD,
    _MIN_FUNCTIONS_FOR_CLONE,
    _jsd,
    _node_histogram,
)

# A pair this far apart in length is not "near-identical" under any reading.
SIZE_RATIO_FLOOR = 2.0
# Density of colliding pairs that a shape-only metric should not exceed.
DENSITY_CEILING_PCT = 0.5


def measure(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None

    funcs = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(funcs) < _MIN_FUNCTIONS_FOR_CLONE:
        return None

    hist = {f.name: _node_histogram(f) for f in funcs}
    size = {f.name: f.end_lineno - f.lineno + 1 for f in funcs}
    pairs = list(itertools.combinations(hist, 2))
    if not pairs:
        return None

    under = [(a, b, _jsd(hist[a], hist[b])) for a, b in pairs
             if _jsd(hist[a], hist[b]) < _CLONE_JSD_THRESHOLD]
    mismatched = [(a, b, d) for a, b, d in under
                  if max(size[a], size[b]) >= SIZE_RATIO_FLOOR * min(size[a], size[b])]

    return {
        "path": path,
        "functions": len(funcs),
        "pairs": len(pairs),
        "under": under,
        "mismatched": mismatched,
        "density": len(under) / len(pairs) * 100,
        "size": size,
    }


target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "src"
files = sorted(target.rglob("*.py")) if target.is_dir() else [target]

print("== T-4: unrelated functions inside the clone threshold ==")
print(f"   target: {target}")
print(f"   JSD threshold {_CLONE_JSD_THRESHOLD}, "
      f"density ceiling {DENSITY_CEILING_PCT}%, size floor {SIZE_RATIO_FLOOR}x")
print()

results = [r for r in (measure(f) for f in files) if r]
results.sort(key=lambda r: -r["density"])

red = False
for r in results[:8]:
    flag = ""
    if r["density"] > DENSITY_CEILING_PCT and r["mismatched"]:
        flag = "  <-- RED"
        red = True
    rel = r["path"].relative_to(REPO) if REPO in r["path"].parents else r["path"]
    print(f"  {rel}{flag}")
    print(f"    functions {r['functions']}, pairs {r['pairs']}, "
          f"under threshold {len(r['under'])} ({r['density']:.1f}%), "
          f"size-mismatched {len(r['mismatched'])}")
    for a, b, d in sorted(r["mismatched"], key=lambda t: -t[2])[:3]:
        sa, sb = r["size"][a], r["size"][b]
        print(f"      {a}({sa}L) vs {b}({sb}L)  JSD={d:.4f}  "
              f"size ratio {max(sa, sb) / min(sa, sb):.1f}x")

print()
if red:
    print("  RED: pairs differing 2x or more in length score as near-identical,")
    print("       and the colliding-pair density is far above the ceiling.")
    print("       Cause: stub_density.py:142-145 normalises the histogram, which")
    print("       removes magnitude; nothing else in the vector carries meaning.")
    print("  GREEN: add a discriminating channel -- log size, or the set of call")
    print("         targets -- and hold density at or under "
          f"{DENSITY_CEILING_PCT}% with no size-mismatched pairs.")
else:
    print("  GREEN")

sys.exit(1 if red else 0)
