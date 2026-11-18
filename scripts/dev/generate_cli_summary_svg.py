"""Regenerate the README terminal image from a real, read-only demo scan.

The image shows the base install (`pip install ai-slop-detector`, the README
Quick Start): JavaScript is read by the regex fallback, so the screen carries
the note that names the `[js]` extra. Run it in an environment without the
`[js]` extra, from the repository root:

    python scripts/dev/generate_cli_summary_svg.py

tests/test_readme_cli_svg.py compares the stored image with this rendering.
"""

from __future__ import annotations

import io
import re
import sys
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from slop_detector import __version__
from slop_detector.core import SlopDetector
from slop_detector.languages import js_analyzer
from slop_detector.renderer_terminal import print_summary
from slop_detector.report_view import build_report_view

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "demo_project"
ASSET = ROOT / "docs" / "assets" / "cli-summary.svg"
DISPLAY_TARGET = "examples/demo_project"
WIDTH = 110


def base_install() -> bool:
    """True when JavaScript is read as the base install reads it (no [js] extra)."""
    return not js_analyzer._TS_AVAILABLE


def render_svg() -> str:
    """The production summary of a real demo scan, as an SVG."""
    result = SlopDetector(read_only=True).analyze_project(str(DEMO))
    view = replace(build_report_view(result), target=DISPLAY_TARGET)
    console = Console(
        file=io.StringIO(),
        width=WIDTH,
        record=True,
        force_terminal=True,
        legacy_windows=False,  # the UTF-8 VT screen, not the ASCII fallback
        color_system="truecolor",
    )
    print_summary(view, console=console)
    svg = console.export_svg(title=f"AI SLOP Detector {__version__}")
    # Rich puts a per-process terminal id in the SVG; keep the stored file stable.
    svg = re.sub(r"terminal-\d+", "terminal-readme", svg)
    # The image must render offline: drop Rich's remote font faces.
    svg = re.sub(r"@font-face\s*\{[^}]*\}\s*", "", svg)
    svg = svg.replace(
        "font-family: Fira Code, monospace;",
        'font-family: "DejaVu Sans Mono", Consolas, monospace;',
    )
    return svg.rstrip() + "\n"


def main() -> int:
    if not base_install():
        print(
            "The [js] extra is installed here; the README image shows the base install. "
            "Run this in an environment without it.",
            file=sys.stderr,
        )
        return 2
    ASSET.write_bytes(render_svg().encode("utf-8"))
    print(f"Updated {ASSET.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
