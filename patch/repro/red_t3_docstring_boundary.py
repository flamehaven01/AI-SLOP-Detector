"""RED for T-3: an equal-length docstring is reported as "more than".

WARNING_RATIO is 1.0 and the comparison includes the boundary, so a function
whose docstring and body are the same length trips a warning whose text asserts
a strict inequality.

Run:  python patch/repro/red_t3_docstring_boundary.py
Exit: 1 while RED, 0 once ratio == 1.0 no longer warns.
"""

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from slop_detector.config import Config  # noqa: E402
from slop_detector.metrics.docstring_inflation import DocstringInflationDetector  # noqa: E402

# docstring 4 lines, body 4 lines -> ratio exactly 1.0
EQUAL = '''
def declare(target, name):
    """Copy the declared record contract.

    The ledger refuses to write without one, so this is not scaffolding --
    it is the same file CI verifies every recorded row against.
    """
    destination = target / "ledgers" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = REPO / "ledgers" / name
    return payload, destination
'''

analyzer = DocstringInflationDetector(Config())
result = analyzer.analyze("equal.py", EQUAL, ast.parse(EQUAL))

print("== T-3: docstring length == implementation length ==")
red = False
for d in result.details:
    ratio = d.inflation_ratio
    print(f"  {d.name}: docstring={d.docstring_lines} impl={d.implementation_lines} "
          f"ratio={ratio:.3f} severity={d.severity}")
    if d.docstring_lines == d.implementation_lines and d.severity in ("warning", "critical"):
        red = True
        print(f"    RED: {d.docstring_lines} is not more than {d.implementation_lines},")
        print("         but question_generator.py:224 says 'more documentation than'.")

if not result.details:
    print("  no details emitted")

print()
print(f"  WARNING_RATIO  = {DocstringInflationDetector.WARNING_RATIO}")
print(f"  CRITICAL_RATIO = {DocstringInflationDetector.CRITICAL_RATIO}")
print("  GREEN requires ratio == 1.0 to fall below the warning band.")

sys.exit(1 if red else 0)
