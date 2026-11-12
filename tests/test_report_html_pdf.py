"""The HTML report and its PDF print (docs/REPORTS.md 6, O3)."""

import re
import sys
from types import SimpleNamespace

import pytest

from slop_detector.cli import main
from slop_detector.core import SlopDetector
from slop_detector.renderer_html import generate_html_report, render_view_html
from slop_detector.report_pdf import (
    BROWSER_ENV,
    PdfFailedError,
    PdfUnavailableError,
    find_browser,
    write_pdf,
)
from slop_detector.report_view import (
    BRIEF_LIMITS,
    FINDING,
    REVIEW_CANDIDATE,
    Item,
    brief_items,
    build_report_view,
)

HOLLOW = """
def persist(record):
    return None


def save_record(record):
    persist(record)
    return True
"""


def _project(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def test_strings_from_the_repository_are_escaped_and_nothing_is_loaded(tmp_path):
    result = _project(tmp_path, {"pkg/store.py": HOLLOW})
    view = build_report_view(result)
    hostile = Item(
        FINDING,
        "x",
        "high",
        str(tmp_path / "<img src=x onerror=alert(1)>.py"),
        1,
        '<script>alert("x")</script>',
        'fix "<b>"',
    )
    page = render_view_html(view.__class__(**{**view.__dict__, "findings": [hostile]}))
    assert "<script>alert" not in page and "&lt;script&gt;alert" in page
    assert "<img src=x" not in page
    assert "default-src 'none'" in page  # the page's own CSP: no network request
    assert not re.search(r'(src|href)="(https?:)?//', page)


def test_page_one_lists_the_top_items_with_at_most_three_candidates():
    def item(kind, severity, n):
        return Item(kind, f"r{n}", severity, "a.py", n, "m")

    findings = [item(FINDING, "medium", i) for i in range(4)] + [item(FINDING, "high", 9)]
    candidates = [item(REVIEW_CANDIDATE, "", 20 + i) for i in range(5)]
    view = SimpleNamespace(findings=findings, candidates=candidates)
    chosen, rest = brief_items(view)
    assert len(chosen) == BRIEF_LIMITS["items"] == 5
    assert sum(i.kind == REVIEW_CANDIDATE for i in chosen) == BRIEF_LIMITS["candidates"] == 3
    assert chosen[0].severity == "high"  # critical / high first, then candidates, then the rest
    assert [i.kind for i in chosen[1:4]] == [REVIEW_CANDIDATE] * 3
    assert rest == len(findings) + len(candidates) - 5


def test_the_report_keeps_score_and_hollow_apart_and_never_shows_unmeasured_as_zero(tmp_path):
    result = _project(tmp_path, {"pkg/store.py": HOLLOW})
    page = generate_html_report(result)
    assert "Hollow review candidates (" in page and "not scored" in page
    for f in result.file_results:
        f.semantic_coverage = {"state": "UNMEASURED"}
        f.semantic_findings = []
    page = generate_html_report(result)
    card = re.search(
        r'<div class="k">Hollow</div><div class="v">(.*?)</div><div class="s">(.*?)</div>', page
    )
    assert card.groups() == ("-", "not measured (analysis failed)")  # not "0"


def test_no_browser_is_env_blocked_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(BROWSER_ENV, str(tmp_path / "missing-browser"))
    target = tmp_path / "report.pdf"
    with pytest.raises(PdfUnavailableError, match="ENV_BLOCKED"):
        write_pdf("<html></html>", str(target))
    assert not target.exists()


def test_a_browser_that_writes_no_pdf_fails_and_leaves_the_target_alone(tmp_path, monkeypatch):
    monkeypatch.setenv(BROWSER_ENV, sys.executable)  # runs, prints nothing to PDF
    target = tmp_path / "report.pdf"
    target.write_bytes(b"previous")
    with pytest.raises(PdfFailedError):
        write_pdf("<html></html>", str(target))
    assert target.read_bytes() == b"previous"


def test_a_file_that_is_not_a_pdf_is_never_written(tmp_path, monkeypatch):
    import slop_detector.report_pdf as report_pdf

    def fake_browser(cmd, **kwargs):
        out = next(arg.split("=", 1)[1] for arg in cmd if arg.startswith("--print-to-pdf="))
        with open(out, "wb") as handle:
            handle.write(b"<html>an error page, not a PDF</html>")

    monkeypatch.setenv(BROWSER_ENV, sys.executable)
    monkeypatch.setattr(report_pdf.subprocess, "run", fake_browser)
    target = tmp_path / "report.pdf"
    with pytest.raises(PdfFailedError):
        write_pdf("<html></html>", str(target))
    assert not target.exists()


def test_the_cli_says_env_blocked_and_exits_2_without_a_pdf(tmp_path, monkeypatch, capsys):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text(HOLLOW, encoding="utf-8")
    monkeypatch.setenv(BROWSER_ENV, str(tmp_path / "missing-browser"))
    target = tmp_path / "out.pdf"
    with pytest.raises(SystemExit) as stop:
        main([str(tmp_path / "pkg"), "-o", str(target), "--no-history"])
    assert stop.value.code == 2
    assert "ENV_BLOCKED" in capsys.readouterr().err
    assert not target.exists()


@pytest.mark.skipif(find_browser() is None, reason="no Chromium-based browser installed")
def test_an_installed_browser_prints_an_a4_pdf(tmp_path):
    result = _project(tmp_path / "src", {"pkg/store.py": HOLLOW})
    target = tmp_path / "report.pdf"
    write_pdf(generate_html_report(result), str(target))
    data = target.read_bytes()
    assert data[:5] == b"%PDF-"
    box = re.search(rb"/MediaBox\s*\[\s*0 0 ([\d.]+) ([\d.]+)\s*\]", data)
    assert (
        box and abs(float(box.group(1)) - 595) < 1 and abs(float(box.group(2)) - 842) < 1
    )  # A4 in points
