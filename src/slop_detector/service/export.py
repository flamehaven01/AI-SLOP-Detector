"""ExportService: render or write a scan outcome with the CLI's own renderers.

Rendering writes nothing. export() is a separate, explicit write that produces
the same bytes as the CLI's `-o` / `--json -o` for the same result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Union

from slop_detector.cli_output import _write_file, render_json
from slop_detector.cli_renderer import (
    generate_html_report,
    generate_markdown_report,
    generate_text_report,
)

_RENDERERS: Dict[str, Callable[[Any], str]] = {
    "json": render_json,
    "md": generate_markdown_report,
    "html": generate_html_report,
    "text": generate_text_report,
}


class ExportService:
    FORMATS = tuple(_RENDERERS)

    @staticmethod
    def render(outcome: Any, fmt: str) -> str:
        if fmt not in _RENDERERS:
            raise ValueError(f"unknown export format {fmt!r}; use one of {', '.join(_RENDERERS)}")
        return _RENDERERS[fmt](outcome.result)

    @staticmethod
    def export(outcome: Any, fmt: str, path: Union[str, Path]) -> Path:
        _write_file(str(path), ExportService.render(outcome, fmt))
        return Path(path)
