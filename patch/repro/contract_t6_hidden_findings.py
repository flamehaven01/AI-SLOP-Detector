"""P4 output contract for T-6: project finding totals are never detail-gated."""

import collections
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from slop_detector.core import SlopDetector  # noqa: E402
from slop_detector.renderer_text import generate_text_report  # noqa: E402

target = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "src"
project = SlopDetector().analyze_project(str(target))
payload = project.to_dict()

severity = collections.Counter()
for file_result in payload["file_results"]:
    for issue in file_result.get("pattern_issues") or []:
        severity[issue["severity"]] += 1

summary = payload["finding_summary"]
assert summary["total"] == sum(severity.values())
assert summary["severity"] == {
    level: severity.get(level, 0) for level in ("critical", "high", "medium", "low")
}

text = generate_text_report(project)
assert "Finding Summary:" in text
for level, count in summary["severity"].items():
    assert f"{level}={count}" in text

print("GREEN: T-6 JSON and text expose identical aggregate finding totals.")
