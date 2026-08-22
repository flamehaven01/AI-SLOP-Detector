"""P4 output contract for T-5: scan coverage distinguishes unsupported code."""

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
    (root / "native.rs").write_text("fn main() {}\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests" / "test_module.py").write_text(
        "def test_run():\n    assert True\n", encoding="utf-8"
    )

    result = SlopDetector().analyze_project(str(root))
    coverage = result.to_dict()["scan_coverage"]

    assert coverage["analyzed"]["python"] == 1
    assert coverage["excluded"]["total"] == 1
    assert coverage["unsupported"] == {
        "total": 1,
        "files": [{"path": "native.rs", "extension": ".rs"}],
        "omitted_file_details": 0,
    }
    assert "unsupported=1" in generate_text_report(result)

print("GREEN: T-5 reports analyzed, excluded, and unsupported source coverage.")
