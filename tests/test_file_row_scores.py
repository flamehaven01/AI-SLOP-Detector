"""A JS/TS, Go or other adapter file shows its own score in the report files list.

Up to 3.15.2 the report view read `deficit_score` only, the name of the Python
score; an adapter's score is `slop_score`. Its files were listed with score
N/A in the HTML appendix and the report.md files table, although that score
counts toward the project score.
"""

from pathlib import Path

from slop_detector.core import SlopDetector
from slop_detector.renderer_html import generate_html_report
from slop_detector.renderer_markdown import generate_markdown_report
from slop_detector.report_view import build_report_view, short_path

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_project"


def test_an_adapter_file_shows_its_own_score():
    result = SlopDetector(read_only=True).analyze_project(str(DEMO))
    (cart,) = [r for r in result.js_file_results if r.file_path.endswith("cart.js")]
    rows = {
        short_path(path, result.project_path): score
        for path, score, _, _ in build_report_view(result).file_rows
    }
    assert rows["web/cart.js"] == float(cart.slop_score), rows
    shown = f"{cart.slop_score:.1f}"
    md = generate_markdown_report(result)
    assert f"| `web/cart.js` | {shown} |" in md, md[md.index("### Files") :][:400]
    html = generate_html_report(result)
    assert "web/cart.js" in html and "N/A" not in html.split("Appendix: files", 1)[1]
