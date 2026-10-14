"""Human reports say when files could not be analyzed.

A file whose analysis raised is recorded in scan_coverage.failed and the JSON
says complete=False, but the rich, text and markdown reports showed only
"analyzed=0 ... CLEAN": a scan where every file failed read as a clean
project. (Found through a wrong-typed config value, which is now refused at
startup; here the file analysis itself raises.)
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from slop_detector.core import SlopDetector
from slop_detector.renderer_glossary import incomplete_notes
from slop_detector.renderer_markdown import generate_markdown_report
from slop_detector.renderer_rich import _render_rich_project
from slop_detector.renderer_text import generate_text_report


@pytest.fixture
def failed_scan(tmp_path: Path, monkeypatch):
    (tmp_path / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")

    def raise_inside_analysis(*args, **kwargs):
        raise AttributeError("analysis raised")

    monkeypatch.setattr(SlopDetector, "_build_file_analysis", raise_inside_analysis)
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    assert result.scan_coverage["failed"]["total"] == 1  # acceptance: the trigger is real
    return result


def test_incomplete_notes_name_the_failed_files(failed_scan):
    notes = incomplete_notes(failed_scan.scan_coverage)
    assert notes and "1 file could not be analyzed" in notes[0]


def test_complete_scan_has_no_incomplete_notes(tmp_path: Path):
    (tmp_path / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(tmp_path))
    assert incomplete_notes(result.scan_coverage) == []


def test_text_report_shows_incomplete_scan(failed_scan):
    assert "could not be analyzed" in generate_text_report(failed_scan)


def test_markdown_report_shows_incomplete_scan(failed_scan):
    assert "could not be analyzed" in generate_markdown_report(failed_scan)


def test_rich_report_shows_incomplete_scan(failed_scan):
    buffer = io.StringIO()
    _render_rich_project(Console(file=buffer, width=200), failed_scan)
    assert "could not be analyzed" in buffer.getvalue()
