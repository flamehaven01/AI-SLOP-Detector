"""HTML report generation for the SLOP detector CLI."""

from __future__ import annotations

from slop_detector.renderer_text import generate_text_report


def generate_html_report(result) -> str:
    """Generate HTML report (simplified; production use: Jinja2 templates)."""
    html = f"""
<!DOCTYPE html>
<html>
<head>
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
    <div class="score">Score: {getattr(result, 'weighted_deficit_score', result.deficit_score):.1f}/100</div>
    <pre>{generate_text_report(result)}</pre>
</body>
</html>
    """
    return html
