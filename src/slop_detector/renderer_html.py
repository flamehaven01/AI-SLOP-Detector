"""HTML report generation for the SLOP detector CLI."""

from __future__ import annotations

import html

from slop_detector.core_project import score_is_valid
from slop_detector.renderer_text import generate_text_report


def _score_text(result) -> str:
    """The headline score: weighted for a project, the file's own otherwise."""
    if not score_is_valid(result):
        return "N/A"
    is_project = hasattr(result, "project_path")
    score = result.weighted_deficit_score if is_project else result.deficit_score
    return f"{score:.1f}/100"


def generate_html_report(result) -> str:
    """Generate HTML report (simplified; production use: Jinja2 templates)."""
    page = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>SLOP Detection Report</title>
    <style>
        body {{ font-family: monospace; max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .score {{ font-size: 2em; font-weight: bold; }}
        .clean {{ color: green; }}
        .suspicious {{ color: orange; }}
        .critical {{ color: red; }}
    </style>
</head>
<body>
    <h1>AI Code Quality Report</h1>
    <div class="score">Score: {_score_text(result)}</div>
    <pre>{html.escape(generate_text_report(result))}</pre>
</body>
</html>
    """
    return page
