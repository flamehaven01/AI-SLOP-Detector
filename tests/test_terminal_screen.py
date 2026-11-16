"""The default terminal screen (3.17): the verdict first, one line per item.

What the screen must do, whatever it looks like:

- say the score, its band and which way is worse, with a meter of the score;
- count findings by severity and name the languages that were read;
- list at most 5 findings and 3 review candidates, one line each, and count the rest;
- never show a channel that did not measure as "0", and keep the note of an
  incomplete scan;
- print on a console that cannot encode box-drawing characters.
"""

from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from slop_detector.core import SlopDetector
from slop_detector.renderer_terminal import METER_WIDTH, print_summary
from slop_detector.report_view import build_report_view

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo_project"
RUST = "pub fn parse(input: &str) -> u8 {\n    dbg!(input);\n    todo!()\n}\n"
JSX = "var count = 0;\nexport function Page(props) {\n  console.log(props);\n  return count;\n}\n"
PY = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"


def _view(root: Path, files: dict = None):
    for name, text in (files or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return build_report_view(SlopDetector(read_only=True).analyze_project(str(root)))


def _render(view, width: int = 120, **console) -> str:
    out = io.StringIO()
    print_summary(view, console=Console(file=out, width=width, color_system=None, **console))
    return out.getvalue()


def test_the_verdict_comes_first_with_its_direction_and_basis():
    screen = _render(_view(DEMO))
    top = "\n".join(screen.splitlines()[:8])
    assert "13.5 / 100" in top and "CLEAN" in top, top
    assert "higher = more warning signs" in top, top
    assert "weighted by lines of code" in top, top


def test_the_meter_is_filled_in_proportion_to_the_score(tmp_path):
    for view, score in ((_view(DEMO), 13.5), (_view(tmp_path, {"src/lib.rs": RUST}), None)):
        screen = _render(view)
        score = view.score if score is None else score
        line = next(line for line in screen.splitlines() if f"{score:.1f} / 100" in line)
        filled, rest = line.count("━"), line.count("─")
        assert filled == round(score / 100 * METER_WIDTH), (score, filled)
        assert filled + rest >= METER_WIDTH, line
    assert "30" in screen and "50" in screen and "70" in screen  # the band limits


def test_findings_are_counted_by_severity_and_languages_are_named(tmp_path):
    screen = _render(_view(tmp_path, {"src/lib.rs": RUST, "web/a.jsx": JSX, "pkg/calc.py": PY}))
    assert "0 critical" in screen and "1 high" in screen, screen
    files = next(line for line in screen.splitlines() if "3 files" in line)
    assert "Python 1" in files and "JS/TS 1" in files and "Rust 1" in files, files
    assert "Go" not in files, files  # a language with no file is not named


def test_each_listed_item_takes_one_line_and_the_rest_is_counted():
    view = _view(DEMO)
    screen = _render(view, width=90)
    lines = screen.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(" Fix first"))
    rows = lines[start + 1 : start + 6]
    assert "5 of 9" in lines[start], lines[start]
    for row, item in zip(rows, view.findings[:5]):
        assert item.rule in row and f":{item.line}" in row, row
    assert "+4 more" in lines[start + 6], lines[start + 6]
    review = next(i for i, line in enumerate(lines) if line.startswith(" To review (not scored)"))
    assert "3 of 4" in lines[review], lines[review]
    for row, item in zip(lines[review + 1 : review + 4], view.candidates[:3]):
        assert item.rule in row, row
    assert "+1 more" in lines[review + 4], lines[review + 4]


def test_a_message_is_cut_to_its_first_clause_and_never_wraps():
    screen = _render(_view(DEMO), width=200)
    row = next(line for line in screen.splitlines() if "return_constant_stub" in line)
    assert "Function 'compute_discount' returns constant 0.1" in row, row
    assert "likely stub" not in screen  # the rest is in --details and the reports


def test_a_project_without_python_has_no_line_about_python_channels(tmp_path):
    screen = _render(_view(tmp_path, {"src/lib.rs": RUST}))
    assert "not applicable" not in screen and "to review" not in screen.lower(), screen
    assert "Promises" not in screen and "Hollow" not in screen


def test_a_channel_that_did_not_measure_is_never_zero(tmp_path):
    from dataclasses import replace

    from slop_detector.report_view import ClaimState, SemanticState

    view = _view(DEMO)
    for state, words in (("UNMEASURED", "not measured"), ("SKIPPED", "skipped")):
        failed = replace(
            view, candidates=[], semantic=SemanticState(state), claims=ClaimState(state)
        )
        screen = _render(failed)
        assert f"review candidates: {words}" in screen.lower(), screen
        assert "0 to review" not in screen and "0 candidate" not in screen


def test_nothing_measured_reads_not_evaluated_without_a_meter(tmp_path):
    screen = _render(_view(tmp_path))
    assert "N/A" in screen and "NOT EVALUATED" in screen, screen
    assert "━" not in screen and "/ 100" not in screen


def test_the_screen_prints_on_a_console_that_cannot_encode_its_glyphs():
    view = _view(DEMO)
    for encoding in ("cp1252", "cp949", "ascii"):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding=encoding, errors="strict")
        print_summary(view, console=Console(file=stream, width=120, color_system=None))
        stream.flush()
        text = raw.getvalue().decode(encoding)
        assert "13.5 / 100" in text and "Fix first" in text, encoding
    assert "#" in text and "━" not in text  # ascii: the meter is drawn with # and -


def test_docstring_promises_that_were_not_measured_are_said_so():
    """The promise channel has no line of its own on this screen; when it did
    not measure, the screen must still say so (never silence, never zero)."""
    from dataclasses import replace

    from slop_detector.report_view import ClaimState

    view = _view(DEMO)
    assert "docstring promises" not in _render(view)  # measured: counted among the candidates
    for state, words in (("UNMEASURED", "not measured"), ("SKIPPED", "skipped")):
        screen = _render(replace(view, claims=ClaimState(state)))
        assert f"docstring promises: {words}" in screen, screen
