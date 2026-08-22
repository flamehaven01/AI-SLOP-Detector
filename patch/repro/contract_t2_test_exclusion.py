"""P4 output contract for T-2: default test exclusions remain visible.

The original red_t2_test_exclusion.py is preserved as historical evidence. This
script tests the remediated output contract rather than requiring test files to
stop being excluded by default.
"""

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from slop_detector.core import SlopDetector  # noqa: E402
from slop_detector.renderer_text import generate_text_report  # noqa: E402


with tempfile.TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    (root / "module.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_module.py").write_text(
        "def test_run():\n    assert True\n", encoding="utf-8"
    )

    detector = SlopDetector()
    default_result = detector.analyze_project(str(root))
    default_coverage = default_result.to_dict()["scan_coverage"]

    assert default_coverage["analyzed"]["python"] == 1
    assert default_coverage["excluded"]["total"] == 1
    assert default_coverage["excluded"]["files"] == [
        {
            "path": "tests/test_module.py",
            "language": "python",
            "reason": "pattern:tests/**",
        }
    ]
    assert "Scan Coverage: analyzed=1, excluded=1" in generate_text_report(default_result)

    assert detector.config.include_default_tests() is True
    included_result = detector.analyze_project(str(root))
    included_coverage = included_result.to_dict()["scan_coverage"]
    assert included_coverage["analyzed"]["python"] == 2
    assert included_coverage["excluded"]["total"] == 0

print("GREEN: T-2 exclusion count, reason, text visibility, and --include-tests contract hold.")
