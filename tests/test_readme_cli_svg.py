"""The README terminal image is the screen a base install prints for the demo.

The README Quick Start installs `ai-slop-detector` without extras, so the image
shows that screen: JavaScript read by the regex fallback, with the note that
names the `[js]` extra. Two environments, two tests:

- base install (CI `test` job, every Python version): the stored SVG equals a
  fresh rendering byte for byte. Python 3.8 (rich 14) and 3.14 (rich 15)
  render the same bytes there.
- `[js]` extra (CI `test-js` job): the same screen without the fallback note.

Regenerate the image with `python scripts/dev/generate_cli_summary_svg.py` in
an environment without the `[js]` extra, and review the diff.
"""

from __future__ import annotations

import re

import pytest

from scripts.dev.generate_cli_summary_svg import ASSET, DEMO, base_install, render_svg
from slop_detector import __version__
from slop_detector.core import SlopDetector

FALLBACK_NOTE = "javascript: regex_fallback"


def _js_mode() -> str:
    """How the demo's JavaScript file was actually read (not only what is installed)."""
    result = SlopDetector(read_only=True).analyze_project(str(DEMO))
    return result.scan_coverage["analysis_modes"]["javascript"]["mode"]


def _text(svg: str) -> str:
    """The characters the SVG shows, line breaks dropped (&#160; is a space)."""
    shown = "".join(re.findall(r">([^<>]*)</text>", svg))
    return shown.replace("&#160;", " ").replace("&amp;", "&")


def _lines(svg: str) -> list:
    """The screen's lines in order: Rich clips each text run to its line."""
    lines: dict = {}
    for number, run in re.findall(
        r'<text [^>]*clip-path="url\(#terminal-readme-line-(\d+)\)"[^>]*>([^<]*)</text>', svg
    ):
        lines[int(number)] = lines.get(int(number), "") + run
    return [lines[n].replace("&#160;", " ").replace("&amp;", "&").rstrip() for n in sorted(lines)]


@pytest.mark.skipif(not base_install(), reason="the image shows the base install; [js] is here")
def test_the_readme_image_is_the_base_install_screen():
    assert _js_mode() == "regex_fallback"
    stored = ASSET.read_bytes()
    assert stored == render_svg().encode("utf-8"), (
        "README terminal image has drifted; regenerate it without the [js] extra "
        "(python scripts/dev/generate_cli_summary_svg.py) and review the diff"
    )
    shown = _text(stored.decode("utf-8"))
    assert f"AI SLOP Detector {__version__}" in shown
    assert FALLBACK_NOTE in shown and "ai-slop-detector[js]" in shown
    assert "13.5 / 100" in shown and "CLEAN" in shown and "Fix first" in shown


@pytest.mark.skipif(base_install(), reason="needs the [js] extra")
def test_with_the_js_extra_the_screen_is_the_image_without_the_fallback_note():
    assert _js_mode() == "tree_sitter_ast"
    stored = _lines(ASSET.read_text(encoding="utf-8"))
    note = next(i for i, line in enumerate(stored) if FALLBACK_NOTE in line)
    assert "ai-slop-detector[js]" in stored[note + 1]
    assert _lines(render_svg()) == stored[:note] + stored[note + 2 :]


def test_the_stored_image_is_self_contained():
    svg = ASSET.read_text(encoding="utf-8")
    assert svg.startswith("<svg ")
    assert "@font-face" not in svg
    assert 'url("http' not in svg and "url('http" not in svg
    assert "<script" not in svg.lower()
    assert b"\r" not in ASSET.read_bytes()
