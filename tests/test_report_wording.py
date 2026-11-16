"""Report wording (R11, R12, R13, 2026-11-14 review of the actual outputs).

- R11: go_empty_func suggested "Implement or mark as // TODO", which adds the
  marker go_todo_comment reports.
- R12: the headline score is the project's weighted score (by lines of code),
  but said only "(score band)" next to an average score elsewhere.
- R13: the CI report named files by their base name ("main.go"), so two files
  of one name in different folders could not be told apart.
"""

import io

from slop_detector.core import SlopDetector
from slop_detector.service.policy import evaluate_gate

PANICS = "package main\n\nfunc a() { panic(1) }\nfunc b() { panic(2) }\nfunc c() { panic(3) }\n"


def _project(root, files):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "w"\n', encoding="utf-8")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(root))


def test_the_empty_go_function_fix_does_not_ask_for_a_todo(tmp_path):
    result = _project(tmp_path / "p", {"main.go": "package main\n\nfunc pending() {}\n"})
    (issue,) = [i for i in result.go_file_results[0].issues if i.pattern_id == "go_empty_func"]
    assert "TODO" not in issue.suggestion.upper(), issue.suggestion


def test_the_headline_score_says_it_is_weighted_by_lines(tmp_path):
    from rich.console import Console

    from slop_detector.renderer_html import generate_html_report
    from slop_detector.renderer_terminal import print_summary
    from slop_detector.report_view import build_report_view

    result = _project(tmp_path / "p", {"svc/main.go": PANICS})
    out = io.StringIO()
    print_summary(
        build_report_view(result), console=Console(file=out, width=200, color_system=None)
    )
    assert "weighted by lines of code" in out.getvalue(), out.getvalue()
    assert "weighted by lines" in generate_html_report(result)


def test_the_ci_report_names_files_by_their_project_path(tmp_path):
    result = _project(tmp_path / "p", {"svc/a/main.go": PANICS, "svc/b/main.go": PANICS})
    gate = evaluate_gate(result, mode="hard", claims_strict=False, read_only=True)
    assert len(gate.failed_files) == 2
    assert (
        "`svc/a/main.go`" in gate.pr_comment and "`svc/b/main.go`" in gate.pr_comment
    ), gate.pr_comment
