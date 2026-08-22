"""RED for T-2: a project scan drops test files and still reports CLEAN.

Builds a two-file package -- one module, one test -- and asks the scanner how
many files it found. The exclusion itself may be intentional; the defect is that
nothing in the output says a file was skipped.

Run:  python patch/repro/red_t2_test_exclusion.py
Exit: 1 while RED, 0 once the report names the excluded files.
"""

import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from slop_detector.config import Config  # noqa: E402
from slop_detector.core import SlopDetector  # noqa: E402

MODULE = '''
def add(a, b):
    """Return the sum."""
    return a + b
'''

TEST = '''
from mod import add


def test_add():
    assert add(1, 2) == 3
'''

root = Path(tempfile.mkdtemp())
(root / "mod.py").write_text(MODULE, encoding="utf-8")
(root / "tests").mkdir()
(root / "tests" / "test_mod.py").write_text(TEST, encoding="utf-8")

on_disk = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py"))
print("== T-2: files on disk vs files analysed ==")
print(f"  on disk  ({len(on_disk)}): {on_disk}")

detector = SlopDetector()
patterns = detector.config.get_ignore_patterns()
kept = [p for p in root.rglob("*.py") if not detector._should_ignore(p, patterns, root=root)]
kept_rel = sorted(p.relative_to(root).as_posix() for p in kept)
print(f"  analysed ({len(kept_rel)}): {kept_rel}")

dropped = [f for f in on_disk if f not in kept_rel]
print(f"  dropped  ({len(dropped)}): {dropped}")
print()
print("  default ignore patterns:")
for pat in Config.DEFAULT_CONFIG["ignore"]:
    print(f"    {pat}")

shutil.rmtree(root, ignore_errors=True)

if dropped:
    print()
    print("  RED: files were dropped. The report must state how many and why.")
    print("  GREEN requires an 'Excluded Files: N' line in the project summary")
    print("  and the dropped paths in --json / --verbose.")
    sys.exit(1)

print("  GREEN")
sys.exit(0)
