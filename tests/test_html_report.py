"""The HTML report renders project and file results safely.

getattr(result, "weighted_deficit_score", result.deficit_score) evaluates its
default first, so every project result raised AttributeError and
`--project -o report.html` crashed (only a file result was tested). The text
report went into <pre> unescaped, so a path containing "<" or "&" changed the
page, and the page declared no charset for its UTF-8 bytes.
"""

from __future__ import annotations

from pathlib import Path

from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.renderer_html import generate_html_report

CODE = "def f(x):\n    return x + 1\n"
ODD = "<b>x&y</b>"  # not a valid Windows file name; used as a project folder label only


def test_project_result_renders(tmp_path: Path):
    (tmp_path / "m.py").write_text(CODE, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    result.weighted_deficit_score, result.avg_deficit_score = 42.0, 7.0  # the headline is weighted
    assert "Score: 42.0/100" in generate_html_report(result)


def test_file_result_renders(tmp_path: Path):
    path = tmp_path / "m.py"
    path.write_text(CODE, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    assert f"Score: {result.deficit_score:.1f}/100" in generate_html_report(result)


def test_report_text_is_escaped(tmp_path: Path):
    (tmp_path / "m.py").write_text(CODE, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    result.project_path = ODD
    page = generate_html_report(result)
    assert ODD not in page
    assert "&lt;b&gt;x&amp;y&lt;/b&gt;" in page


def test_no_measurement_shows_not_available(tmp_path: Path):
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    assert "Score: N/A" in generate_html_report(result)


def test_cli_writes_a_utf8_page_for_a_korean_project(tmp_path: Path):
    project = tmp_path / "한글 프로젝트"
    project.mkdir()
    (project / "m.py").write_text(CODE, encoding="utf-8")
    out = tmp_path / "report.html"
    assert main(["--project", str(project), "-o", str(out), "--no-history"]) == 0
    page = out.read_text(encoding="utf-8")
    assert '<meta charset="utf-8">' in page and project.name in page
