"""The one report view and the screens built on it (docs/REPORTS.md, O2)."""

import io
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from slop_detector.core import SlopDetector
from slop_detector.renderer_glossary import next_steps
from slop_detector.renderer_markdown import generate_markdown_report
from slop_detector.renderer_terminal import Progress, hollow_line, print_summary, quiet_line
from slop_detector.report_view import REVIEW_CANDIDATE, build_report_view, short_path

HOLLOW = '''
def persist(record):
    return None


def save_record(record):
    persist(record)
    return True
'''


def _project(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _screen(view):
    out = io.StringIO()
    print_summary(view, console=Console(file=out, width=200, color_system=None))
    return out.getvalue()


def test_the_view_separates_findings_from_review_candidates(tmp_path):
    result = _project(tmp_path, {"pkg/store.py": HOLLOW})
    view = build_report_view(result)
    assert view.findings and all(i.kind == "FINDING" for i in view.findings)
    assert {i.rule for i in view.candidates} >= {"success_without_effect"}
    assert all(i.kind == REVIEW_CANDIDATE for i in view.candidates)
    assert view.semantic.state == "MEASURED" and view.semantic.functions == 2
    assert view.next_steps == next_steps(result)  # the project's own next steps, not recomputed
    # the view reads the result; it does not change the score or the status
    assert view.score == result.weighted_deficit_score
    assert view.status == str(getattr(result.overall_status, "value", result.overall_status)).upper()


def test_a_clean_band_with_a_high_finding_keeps_the_band_and_asks_for_review():
    issue = SimpleNamespace(pattern_id="god_function", severity="high", line=3, message="m", suggestion="")
    result = SimpleNamespace(
        avg_deficit_score=0.0, weighted_deficit_score=0.0, avg_ldr=1.0, avg_inflation=0.0, avg_ddc=1.0,
        deficit_files=0, priority_hotspots=[], file_results=[SimpleNamespace(pattern_issues=[issue])],
    )
    steps = next_steps(result)
    assert "no action needed" not in " ".join(steps)
    assert "critical or high" in steps[0]


def test_a_project_with_nothing_measured_is_not_evaluated(tmp_path):
    result = _project(tmp_path, {})
    view = build_report_view(result)
    assert view.score is None and view.status == "NOT EVALUATED"
    assert view.semantic.state == "NOT_APPLICABLE"
    assert "score N/A NOT EVALUATED" in quiet_line(view)
    assert "N/A" in _screen(view)


def test_an_unmeasured_or_skipped_hollow_channel_is_never_zero(tmp_path):
    result = _project(tmp_path, {"pkg/store.py": HOLLOW})
    for state, words in (("UNMEASURED", "not measured"), ("SKIPPED", "skipped")):
        for f in result.file_results:
            f.semantic_coverage = {"state": state}
            f.semantic_findings = []
        view = build_report_view(result)
        assert hollow_line(view).startswith(words)
        screen = _screen(view)
        assert "0 review candidate" not in screen and "Hollow review candidates" not in screen
        assert words in generate_markdown_report(result)
        assert "0 review candidate" not in generate_markdown_report(result)


def test_a_partly_measured_hollow_channel_says_partial(tmp_path):
    result = _project(tmp_path, {"a.py": HOLLOW, "b.py": HOLLOW})
    result.file_results[0].semantic_coverage = {"state": "UNMEASURED"}
    view = build_report_view(result)
    assert view.semantic.state == "PARTIAL"
    assert "partial: 1 MEASURED, 1 UNMEASURED files" in hollow_line(view)


def test_the_terminal_lists_five_findings_and_three_candidates_then_the_rest(tmp_path):
    many = "".join(f"\ndef stub_{i}(value):\n    return None\n" for i in range(7))
    result = _project(tmp_path, {"many.py": many, "pkg/store.py": HOLLOW * 1})
    view = build_report_view(result)
    screen = _screen(view)
    assert f"top 5 of {len(view.findings)}" in screen
    assert f"+{len(view.findings) - 5} more" in screen
    shown = min(3, len(view.candidates))
    assert f"top {shown} of {len(view.candidates)}" in screen


def test_a_long_path_is_shown_relative_to_the_scanned_root(tmp_path):
    deep = tmp_path / "a" / "very" / "deep" / "package" / "module.py"
    assert short_path(str(deep), str(tmp_path)) == "a/very/deep/package/module.py"
    outside = Path(tmp_path).parent / "elsewhere.py"
    assert short_path(str(outside), str(tmp_path)).endswith("elsewhere.py")


def test_progress_writes_only_to_a_terminal_and_never_ends_a_scan():
    event = SimpleNamespace(kind="file_done", index=1, total=2, path="x/a.py")
    quiet = io.StringIO()
    Progress(quiet)(event)
    assert quiet.getvalue() == ""  # not a terminal

    class Tty(io.StringIO):
        def isatty(self):
            return True

    tty = Tty()
    Progress(tty)(event)
    assert "[1/2] a.py" in tty.getvalue()

    class Broken(Tty):
        def write(self, text):
            raise OSError("closed")

    Progress(Broken())(event)  # does not raise


def test_a_single_file_view_has_its_own_next_step(tmp_path):
    path = tmp_path / "store.py"
    path.write_text(HOLLOW, encoding="utf-8")
    view = build_report_view(SlopDetector(read_only=True).analyze_file(str(path)))
    assert not view.is_project and view.files == 1
    assert "lower-severity finding(s) are open" in _screen(view)
    urgent = replace(view, severity=dict(view.severity, high=1))
    assert "Review the 1 critical or high finding(s)" in _screen(urgent)
