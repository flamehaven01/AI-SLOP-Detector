"""Thin re-export shim — rendering logic lives in the renderer_* modules."""

from slop_detector.renderer_html import generate_html_report
from slop_detector.renderer_markdown import generate_markdown_report, get_mitigation
from slop_detector.renderer_rich import RICH_AVAILABLE, list_patterns, print_rich_report
from slop_detector.renderer_text import generate_text_report

__all__ = [
    "RICH_AVAILABLE",
    "generate_html_report",
    "generate_markdown_report",
    "generate_text_report",
    "get_mitigation",
    "list_patterns",
    "print_rich_report",
]
