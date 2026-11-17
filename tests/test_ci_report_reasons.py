"""The CI report says why the gate decided (R2, 2026-11-14).

A hard gate failed (exit 1) on a project of one clean file and one file the
analyzer could not read, and the --ci-report body said only "Analyzed: 1
files (1 clean, 0 with issues)". The report now carries the verdict and its
message, and lists the files that could not be analyzed (relative path,
language, error type) apart from the files over the quality thresholds.
"""

from slop_detector.core import SlopDetector
from slop_detector.service.policy import evaluate_gate

UNREADABLE = 'fn f() {\n    let s = "never closed;\n}\n'


def _project(tmp_path, files):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "r"\n', encoding="utf-8")
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def test_a_gate_failed_by_an_unreadable_file_says_so(tmp_path):
    result = _project(
        tmp_path, {"src/lib.rs": "pub fn f() -> u8 { 1 }\n", "src/broken.rs": UNREADABLE}
    )
    gate = evaluate_gate(result, mode="hard", claims_strict=False, read_only=True)
    assert gate.should_fail_build is True
    report = gate.pr_comment
    assert "FAIL" in report and "could not be analyzed" in report, report
    assert "`src/broken.rs` (rust): RustReadError" in report, report
    assert "Failed Quality Checks" not in report, report  # no file is over a threshold
    # A failed gate never says the build passed (the thresholds part reads as such).
    assert "PASSED" not in gate.message and "PASSED" not in report, gate.message
    assert "no analyzed file exceeds the quality thresholds" in gate.message, gate.message


def test_a_complete_clean_scan_has_no_failure_section(tmp_path):
    result = _project(tmp_path, {"src/lib.rs": "pub fn f() -> u8 { 1 }\n"})
    gate = evaluate_gate(result, mode="hard", claims_strict=False, read_only=True)
    assert gate.should_fail_build is False
    assert "could not be analyzed" not in gate.pr_comment
    assert "PASS" in gate.pr_comment, gate.pr_comment


def test_the_terminal_summary_says_a_file_could_not_be_analyzed(tmp_path):
    """R9: the one-screen summary said 'measurement: PARTIAL' and nothing else."""
    import io

    from rich.console import Console

    from slop_detector.renderer_terminal import print_summary
    from slop_detector.report_view import build_report_view

    result = _project(
        tmp_path, {"src/lib.rs": "pub fn f() -> u8 { 1 }\n", "src/broken.rs": UNREADABLE}
    )
    out = io.StringIO()
    print_summary(
        build_report_view(result), console=Console(file=out, width=200, color_system=None)
    )
    text = out.getvalue()
    assert "PARTIAL" in text and "1 file could not be analyzed (RustReadError: 1)" in text, text


GO_PANICS = "package main\n\nfunc a() { panic(1) }\nfunc b() { panic(2) }\nfunc c() { panic(3) }\n"


def _start_step(result):
    from slop_detector.renderer_glossary import next_steps

    steps = [s for s in next_steps(result) if s.startswith("Start with")]
    return steps[0] if steps else ""


def test_start_with_names_the_file_with_the_most_severe_findings_in_any_language(tmp_path):
    """R3: 'Start with' and the hotspots read Python files only."""
    result = _project(
        tmp_path,
        {
            "app.py": "# TODO: later\ndef f(x):\n    return x + 1\n",
            "svc/main.go": GO_PANICS,
        },
    )
    step = _start_step(result)
    assert step.startswith("Start with `svc/main.go`"), step
    assert "critical" in step and "deficit" not in step, step  # counts, not a cross-language score


def test_a_project_without_python_gets_a_starting_file(tmp_path):
    result = _project(tmp_path, {"svc/main.go": GO_PANICS})
    assert _start_step(result).startswith("Start with `svc/main.go`"), _start_step(result)
