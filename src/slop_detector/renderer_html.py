"""The HTML report: one self-contained page that is also the PDF (A4 print).

Formats a `ReportView` (docs/REPORTS.md 6). Every string from the analyzed
repository is escaped; the page loads nothing from the network (its Content
Security Policy allows only its own inline style and script).
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import List

from slop_detector import __version__
from slop_detector.report_view import REVIEW_CANDIDATE, Item, ReportView, brief_items, build_report_view, short_path

_CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:"
_PATH_CHARS = 72  # body text shortens longer paths in the middle; the appendix keeps them whole

_CSS = """
:root { --ink:#1d2329; --muted:#5b6670; --line:#d9dee3; --card:#f6f8fa; --accent:#2457a6;
  --critical:#a3161b; --high:#c2410c; --medium:#a16207; --low:#55606b; --review:#6b3fa0; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; color: var(--ink); background: #fff;
  font: 14px/1.45 -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 16px 20px 40px; }
nav.bar { position: sticky; top: 0; z-index: 2; background: #fff; border-bottom: 1px solid var(--line);
  display: flex; flex-wrap: wrap; gap: 14px; align-items: center; padding: 8px 20px; }
nav.bar a { color: var(--accent); text-decoration: none; font-weight: 600; }
.chips { margin-left: auto; display: flex; gap: 6px; flex-wrap: wrap; }
.chips button { font: inherit; font-size: 12px; border: 1px solid var(--line); background: #fff;
  border-radius: 12px; padding: 2px 10px; cursor: pointer; }
.chips button[aria-pressed="false"] { opacity: .45; }
h1 { font-size: 22px; margin: 4px 0 2px; }
h2 { font-size: 17px; margin: 26px 0 8px; padding-bottom: 4px; border-bottom: 1px solid var(--line); }
.meta { color: var(--muted); font-size: 12.5px; overflow-wrap: anywhere; }
.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 14px 0 6px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
.card .k { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.card .v { font-size: 22px; font-weight: 700; margin: 2px 0; }
.card .s { font-size: 12.5px; color: var(--muted); }
.item { border-left: 3px solid var(--line); padding: 4px 0 5px 10px; margin: 0 0 6px; }
.item .l1 { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
.item .l2 { color: #333; font-size: 13px; overflow-wrap: anywhere; }
.item .fix { color: var(--muted); }
.badge { font-size: 11px; font-weight: 700; padding: 0 6px; border-radius: 4px; color: #fff; }
.loc { font: 12.5px ui-monospace, Consolas, monospace; }
.rule { font: 12.5px ui-monospace, Consolas, monospace; color: var(--muted); }
.sev-critical { border-left-color: var(--critical); } .sev-critical .badge { background: var(--critical); }
.sev-high { border-left-color: var(--high); } .sev-high .badge { background: var(--high); }
.sev-medium { border-left-color: var(--medium); } .sev-medium .badge { background: var(--medium); }
.sev-low { border-left-color: var(--low); } .sev-low .badge { background: var(--low); }
.sev-review { border-left-color: var(--review); } .sev-review .badge { background: var(--review); }
.note { background: #f3effa; border: 1px solid #ddd1ee; border-radius: 6px; padding: 6px 10px;
  font-size: 13px; margin: 6px 0 10px; }
.rest { color: var(--muted); font-size: 13px; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); padding: 5px 6px; text-align: left; vertical-align: top;
  overflow-wrap: anywhere; }
th { background: var(--card); font-weight: 600; }
td.num, th.num { text-align: right; }
.brief .item .l2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
body.hide-critical .item[data-sev="critical"], body.hide-high .item[data-sev="high"],
body.hide-medium .item[data-sev="medium"], body.hide-low .item[data-sev="low"],
body.hide-review .item[data-sev="review"] { display: none; }
@media (max-width: 720px) { .kpis { grid-template-columns: repeat(2, 1fr); } }
@page { size: A4; margin: 14mm 12mm 15mm; }
@media print {
  body { font-size: 10pt; }
  main { max-width: none; padding: 0; }
  nav.bar, .chips { display: none; }
  h1 { font-size: 16pt; } h2 { font-size: 12.5pt; margin-top: 14pt; }
  .card .v { font-size: 15pt; }
  .brief { break-after: page; }
  h2, h3 { break-after: avoid; }
  .item, .card, .note, tr, .keep { break-inside: avoid; }
  thead { display: table-header-group; }
  body[class] .item { display: block; }
}
"""

_JS = """
document.querySelectorAll('.chips button').forEach(function (b) {
  b.addEventListener('click', function () {
    var on = b.getAttribute('aria-pressed') !== 'false';
    b.setAttribute('aria-pressed', on ? 'false' : 'true');
    document.body.classList.toggle('hide-' + b.dataset.sev, on);
  });
});
"""


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _middle(text: str, limit: int = _PATH_CHARS) -> str:
    if len(text) <= limit:
        return text
    keep = (limit - 3) // 2
    return text[:keep] + "..." + text[-keep:]


def _root(view: ReportView) -> str:
    from pathlib import Path

    return view.target if view.is_project else str(Path(view.target).parent)


def _item(item: Item, root: str) -> str:
    review = item.kind == REVIEW_CANDIDATE
    sev = "review" if review else item.severity
    where = f"{short_path(item.file, root)}:{item.line}"
    fix = f' <span class="fix">- {_e(item.suggestion)}</span>' if item.suggestion else ""
    return (
        f'<div class="item sev-{sev}" data-sev="{sev}"><div class="l1">'
        f'<span class="badge">{"REVIEW" if review else _e(item.severity.upper())}</span>'
        f'<code class="loc" title="{_e(item.file)}:{item.line}">{_e(_middle(where))}</code>'
        f'<span class="rule">{_e(item.rule)}</span></div>'
        f'<div class="l2">{_e(item.message)}{fix}</div></div>'
    )


def _cards(view: ReportView) -> str:
    score = "N/A" if view.score is None else f"{view.score:.1f}"
    sev = view.severity
    sem = view.semantic
    if sem.state in ("MEASURED", "PARTIAL"):
        hollow_v = str(len(view.candidates))
        hollow_s = f"review candidates, not scored; {sem.functions} functions, {sem.unknown} not decidable"
        if sem.state == "PARTIAL":
            hollow_s += "; " + ", ".join(f"{n} files {state}" for state, n in sorted(sem.files.items()))
    else:
        hollow_v = "-"
        hollow_s = {"SKIPPED": "skipped", "UNMEASURED": "not measured (analysis failed)"}.get(
            sem.state, "not applicable (no Python file)"
        )
    cards = [
        ("Score", score, f"{view.status} (score band, out of 100)"),
        ("Findings", str(len(view.findings)),
         f"critical {sev['critical']} / high {sev['high']} / medium {sev['medium']} / low {sev['low']}"),
        ("Hollow", hollow_v, hollow_s),
        ("Measurement", view.measurement, f"hollow channel: {sem.state}"),
    ]
    return '<div class="kpis">' + "".join(
        f'<div class="card"><div class="k">{_e(k)}</div><div class="v">{_e(v)}</div><div class="s">{_e(s)}</div></div>'
        for k, v, s in cards
    ) + "</div>"


def _brief(view: ReportView, root: str, when: str) -> str:
    chosen, rest = brief_items(view)
    unit = "files" if view.files != 1 else "file"
    parts = [
        '<section id="summary" class="brief">',
        "<h1>AI SLOP Detector report</h1>",
        f'<div class="meta">{_e(view.target)} &middot; {view.files} {unit} &middot; {_e(when)} '
        f"&middot; ai-slop-detector {_e(__version__)}</div>",
        _cards(view),
        '<p class="meta">The score and its band come from the pattern and metric channel. Hollow '
        "review candidates are reported separately, are not scored, and are evidence for a review, "
        "not a verdict.</p>",
        "<h2>Top items</h2>",
    ]
    parts += [_item(i, root) for i in chosen] or ['<p class="rest">No finding and no review candidate.</p>']
    if rest:
        parts.append(f'<p class="rest">{rest} more item(s) in the sections below.</p>')
    if view.next_steps:
        parts.append("<h2>Next steps</h2><ol>" + "".join(f"<li>{_e(s)}</li>" for s in view.next_steps) + "</ol>")
    parts.append("</section>")
    return "".join(parts)


def _findings(view: ReportView, root: str) -> str:
    body = "".join(_item(i, root) for i in view.findings) or '<p class="rest">No pattern finding.</p>'
    return f'<section id="findings"><h2>Findings ({len(view.findings)})</h2>{body}</section>'


def _hollow(view: ReportView, root: str) -> str:
    from slop_detector.renderer_terminal import claim_line, hollow_line

    sem = view.semantic
    reasons = ", ".join(f"{_e(k)} {v}" for k, v in sorted(sem.unknown_reasons.items(), key=lambda kv: -kv[1]))
    parts = [
        f'<section id="hollow"><h2>Hollow review candidates ({len(view.candidates)}, not scored)</h2>',
        f'<div class="note">{_e(hollow_line(view))}. A candidate is evidence for a review, '
        "not a verdict, and it does not change the score.",
    ]
    if reasons:
        parts.append(f"<br>Why functions were not decidable: {reasons}")
    parts.append(f"<br>Docstring promises: {_e(claim_line(view))}")
    parts.append("</div>")
    parts += [_item(i, root) for i in view.candidates]
    parts.append("</section>")
    return "".join(parts)


def _table(head: List[str], rows: List[List[str]], widths: List[int], numeric: frozenset = frozenset()) -> str:
    """A table with fixed column widths (percent): a fixed layout keeps a long
    cell from widening its column and pushing the table off the page."""
    def cell(tag: str, i: int, text: str) -> str:
        cls = ' class="num"' if i in numeric else ""
        return f"<{tag}{cls}>{text}</{tag}>"

    thead = "<tr>" + "".join(cell("th", i, _e(h)) for i, h in enumerate(head)) + "</tr>"
    tbody = "".join("<tr>" + "".join(cell("td", i, c) for i, c in enumerate(r)) + "</tr>" for r in rows)
    cols = "".join(f'<col style="width:{w}%">' for w in widths)
    return f"<table><colgroup>{cols}</colgroup><thead>{thead}</thead><tbody>{tbody}</tbody></table>"


def _score_details(view: ReportView) -> str:
    if not view.metrics:
        return '<section id="score"><h2>Score details</h2><p class="rest">Not evaluated: nothing was measured.</p></section>'
    rows = [[_e(m["label"]), _e(m["value"]), _e(m["direction"]), _e(m["means"])] for m in view.metrics]
    table = _table(["Metric", "Value", "Healthy", "Meaning"], rows, [30, 13, 11, 46])
    return f'<section id="score" class="keep"><h2>Score details</h2>{table}</section>'


def _coverage(view: ReportView) -> str:
    labels = {"analyzed": "Analyzed", "excluded": "Excluded", "unsupported": "Unsupported",
              "failed": "Failed", "unmeasured": "Not fully measured"}
    rows = [[labels[k], str(v)] for k, v in view.coverage.items()]
    rows += [[f"Hollow channel: {_e(state)}", str(n)] for state, n in sorted(view.semantic.files.items())]
    notes = "".join(f"<li>{_e(n)}</li>" for n in view.coverage_notes)
    return (
        '<section id="coverage" class="keep"><h2>Coverage</h2>'
        + _table(["Files", "Count"], rows, [80, 20], frozenset({1}))
        + (f"<ul>{notes}</ul>" if notes else "")
        + "</section>"
    )


def _appendix(view: ReportView, root: str) -> str:
    rows = [
        [f'<code class="loc">{_e(short_path(path, root))}</code>', "N/A" if score is None else f"{score:.1f}",
         _e(status.replace("_", " ")), str(n)]
        for path, score, status, n in sorted(view.file_rows, key=lambda r: -(r[1] or 0))
    ]
    return (
        f'<section id="files" class="appendix"><h2>Appendix: files ({len(rows)})</h2>'
        f'<p class="meta">Paths relative to {_e(root)}; highest score first.</p>'
        + _table(["File", "Score", "Status", "Findings"], rows, [56, 10, 22, 12], frozenset({1, 3}))
        + "</section>"
    )


def _chips() -> str:
    sevs = ["critical", "high", "medium", "low", "review"]
    return '<div class="chips">' + "".join(
        f'<button type="button" data-sev="{s}" aria-pressed="true">{s}</button>' for s in sevs
    ) + "</div>"


def render_view_html(view: ReportView, when: str = "") -> str:
    """The page for a view (`when`: the report time shown in the header)."""
    root = _root(view)
    when = when or datetime.now().strftime("%Y-%m-%d %H:%M")
    nav = "".join(
        f'<a href="#{i}">{t}</a>'
        for i, t in (("summary", "Summary"), ("findings", "Findings"), ("hollow", "Hollow"),
                     ("score", "Score"), ("coverage", "Coverage"), ("files", "Files"))
    )
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>AI SLOP Detector report - {_e(view.target)}</title><style>{_CSS}</style></head><body>"
        f'<nav class="bar">{nav}{_chips()}</nav><main>'
        + _brief(view, root, when)
        + _findings(view, root)
        + _hollow(view, root)
        + _score_details(view)
        + _coverage(view)
        + _appendix(view, root)
        + f"</main><script>{_JS}</script></body></html>"
    )


def generate_html_report(result) -> str:
    """The HTML report of an analysis result."""
    timestamp = getattr(result, "timestamp", None)
    when = timestamp.strftime("%Y-%m-%d %H:%M") if timestamp else ""
    return render_view_html(build_report_view(result), when)
