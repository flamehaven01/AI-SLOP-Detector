"""The terminal summary prints repository text as text.

The default screen is drawn with rich, which reads `[name]` as a style tag.
Paths, messages and docstring text of the scanned repository went through
that reader: `app/[id]/page.jsx` was shown as `app//page.jsx`, a hollow
candidate lost the input it names (`save_record [record]:` read
`save_record :`), and a docstring holding `[/x]` ended the summary with a
MarkupError traceback. `--details` already escaped these.
"""

from __future__ import annotations

import dataclasses
import io
from pathlib import Path

from rich.console import Console

from slop_detector.core import SlopDetector
from slop_detector.renderer_terminal import print_summary
from slop_detector.report_view import build_report_view

JSX = "var count = 0;\nexport function Page(props) {\n  console.log(props);\n  return count;\n}\n"
HOLLOW = (
    "def persist(record):\n    pass\n\n\n"
    'def save_record(record):\n    """Save the record."""\n    persist(record)\n    return True\n'
)


def _promise(text: str) -> str:
    return (
        f'def total_parallel(values):\n    """{text}"""\n    total = 0\n'
        "    for value in values:\n        total += value\n    return total\n"
    )


def _screen(root: Path, files: dict) -> str:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_project(str(root))
    out = io.StringIO()
    print_summary(build_report_view(result), console=Console(file=out, width=240))
    return out.getvalue()


def test_plain_text_is_still_shown(tmp_path):
    """Positive control: the screen has its parts and the item it reports."""
    screen = _screen(tmp_path, {"web/page.jsx": JSX})
    assert "AI SLOP Detector" in screen and "Fix first" in screen and "Next" in screen
    assert "MEDIUM" in screen and "web/page.jsx:1" in screen and "js_var_usage" in screen


def test_a_path_with_brackets_is_shown_as_it_is(tmp_path):
    screen = _screen(tmp_path, {"app/[id]/page.jsx": JSX})
    assert "app/[id]/page.jsx:1" in screen, screen
    assert "app//page.jsx" not in screen


def test_a_hollow_candidate_names_its_input(tmp_path):
    screen = _screen(tmp_path, {"pkg/store.py": HOLLOW})
    assert "save_record [record]:" in screen, screen


def test_docstring_text_in_brackets_is_kept(tmp_path):
    screen = _screen(tmp_path, {"pkg/a.py": _promise("Sum the values [fast] in parallel.")})
    assert "Sum the values [fast] in parallel." in screen, screen


def test_a_closing_tag_in_repository_text_does_not_end_the_summary(tmp_path):
    screen = _screen(tmp_path, {"pkg/a.py": _promise("Sum the values [/x] in parallel.")})
    assert "Sum the values [/x] in parallel." in screen, screen
    assert "Next" in screen


def test_a_target_with_brackets_is_named(tmp_path):
    """The headline names the target as given (a POSIX path: on Windows a
    backslash before the bracket would hide the defect)."""
    for name, text in {"web/page.jsx": JSX}.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    view = build_report_view(SlopDetector(read_only=True).analyze_project(str(tmp_path)))
    view = dataclasses.replace(view, target="work/[proj]/app")
    out = io.StringIO()
    print_summary(view, console=Console(file=out, width=240))
    assert "work/[proj]/app" in out.getvalue(), out.getvalue()


def test_a_long_next_step_wraps_under_its_own_text(tmp_path):
    """A step that does not fit continues under its text, not at column 0."""
    for name, text in {"web/page.jsx": JSX}.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    view = build_report_view(SlopDetector(read_only=True).analyze_project(str(tmp_path)))
    view = dataclasses.replace(view, next_steps=["word " * 40])
    out = io.StringIO()
    print_summary(view, console=Console(file=out, width=60))
    lines = out.getvalue().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("  1. word"))
    wrapped = [line for line in lines[start + 1 :] if "word" in line]
    assert wrapped, lines
    assert all(line.startswith("     word") for line in wrapped), wrapped


def test_a_next_step_names_a_path_with_brackets(tmp_path):
    for name, text in {"web/page.jsx": JSX}.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    view = build_report_view(SlopDetector(read_only=True).analyze_project(str(tmp_path)))
    step = "Start with `app/[id]/page.jsx` (1 high finding(s))"
    out = io.StringIO()
    print_summary(
        dataclasses.replace(view, next_steps=[step]), console=Console(file=out, width=240)
    )
    assert step in out.getvalue(), out.getvalue()


def _cli_stderr(root: Path, *flags: str) -> str:
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "slop_detector.cli", "--project", str(root), "--no-history", *flags],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stderr


def test_the_file_count_per_language_is_not_logged_onto_the_screen(tmp_path):
    """`[INFO] Analyzed 1 Rust files` sat above the summary, which already
    says how many files were analyzed. It is a detail for --verbose."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text("pub fn add(a: u8, b: u8) -> u8 {\n    a + b\n}\n")
    assert "Analyzed" not in _cli_stderr(tmp_path)
    assert "Analyzed 1 Rust file\n" in _cli_stderr(tmp_path, "--verbose").replace("\r\n", "\n")


def test_a_scan_of_the_current_folder_names_the_folder(tmp_path, monkeypatch):
    """`slop-detector --project .` headed its screen "AI SLOP Detector ... - ."."""
    root = tmp_path / "shop-api"
    (root / "web").mkdir(parents=True)
    (root / "web" / "page.jsx").write_text(JSX, encoding="utf-8")
    monkeypatch.chdir(root)
    view = build_report_view(SlopDetector(read_only=True).analyze_project("."))
    assert view.target == "."
    out = io.StringIO()
    print_summary(view, console=Console(file=out, width=240))
    named = [line for line in out.getvalue().splitlines() if "shop-api" in line]
    assert named and "1 file" in out.getvalue(), out.getvalue()
