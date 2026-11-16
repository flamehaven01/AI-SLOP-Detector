"""`--interactive`: choose which report files to save after the summary.

The contract (Inspector TUI_OPT_IN_REQUIRED):

- the chooser appears only when `--interactive` is given AND stdin and stdout
  are both terminals; without the flag nothing ever waits for input;
- nothing is written before a choice; Enter, end of input and Ctrl+C write
  nothing;
- a choice writes the same file `--report-dir` writes, under `slop-report/`;
- it cannot be combined with an option that already decides the output, or
  with `--read-only`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slop_detector.core import SlopDetector
from slop_detector.report_chooser import choose, conflicts, should_prompt

PY = "def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result\n"


class Stream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture
def result(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "calc.py").write_text(PY, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _answers(*lines):
    """An `ask` that returns the given lines, then signals end of input."""
    pending = list(lines)

    def ask(_prompt: str) -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    return ask


def _run(result, folder, *lines):
    said = []
    written = choose(result, str(folder), ask=_answers(*lines), say=said.append)
    return written, said


def test_without_the_flag_nothing_ever_prompts():
    both = (Stream(True), Stream(True))
    assert should_prompt(SimpleNamespace(interactive=False), *both) is False
    assert should_prompt(SimpleNamespace(), *both) is False
    # Positive control: the flag on a terminal does.
    assert should_prompt(SimpleNamespace(interactive=True), *both) is True


def test_the_flag_without_a_terminal_does_not_prompt():
    flag = SimpleNamespace(interactive=True)
    assert should_prompt(flag, Stream(False), Stream(True)) is False
    assert should_prompt(flag, Stream(True), Stream(False)) is False


def test_a_choice_writes_that_file_and_only_that_file(result, tmp_path):
    from slop_detector.renderer_html import generate_html_report

    folder = tmp_path / "slop-report"
    written, said = _run(result, folder, "1\n", "\n")
    assert written == ["report.html"]
    assert sorted(p.name for p in folder.iterdir()) == ["report.html"]
    assert (folder / "report.html").read_text(encoding="utf-8") == generate_html_report(result)
    assert any("report.html" in line for line in said)


def test_several_choices_in_one_answer(result, tmp_path):
    from slop_detector.cli_output import render_json

    folder = tmp_path / "slop-report"
    written, _ = _run(result, folder, "2, 4\n", "\n")
    assert written == ["report.md", "scan.json"]
    assert (folder / "scan.json").read_text(encoding="utf-8") == render_json(result)


def test_enter_end_of_input_and_ctrl_c_write_nothing(result, tmp_path):
    for name, lines in (("enter", ("\n",)), ("eof", ())):
        folder = tmp_path / name
        written, _ = _run(result, folder, *lines)
        assert written == [] and not folder.exists(), name

    def interrupted(_prompt: str) -> str:
        raise KeyboardInterrupt

    folder = tmp_path / "ctrl-c"
    try:
        written = choose(result, str(folder), ask=interrupted, say=lambda _line: None)
    except KeyboardInterrupt:
        pytest.fail("Ctrl+C in the chooser must end it, not the program")
    assert written == [] and not folder.exists()


def test_an_answer_that_is_no_choice_is_asked_again(result, tmp_path):
    folder = tmp_path / "slop-report"
    written, said = _run(result, folder, "x\n", "9\n", "3\n", "\n")
    assert written == ["ai-report.md"]
    assert sum("1-4" in line for line in said) == 2  # told twice what a choice is
    # An answer that mixes a choice with anything else is no choice either.
    mixed = tmp_path / "mixed"
    written, said = _run(result, mixed, "1x\n", "\n")
    assert written == [] and not mixed.exists(), written
    assert sum("1-4" in line for line in said) == 1


def test_options_that_already_decide_the_output_conflict():
    def names(**options):
        return conflicts(SimpleNamespace(interactive=True, **options))

    assert names() == []
    assert names(json=True) == ["--json"]
    assert names(output="r.md", quiet=True) == ["--output", "--quiet"]
    assert names(read_only=True, ci_report=True, ci_mode="hard", report_dir="d", ai=True) == [
        "--ci-mode",
        "--ci-report",
        "--format ai",
        "--read-only",
        "--report-dir",
    ]
    assert conflicts(SimpleNamespace(interactive=False, json=True)) == []


def _cli(root: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "slop_detector.cli", "--project", ".", "--no-history", *flags],
        cwd=str(root),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


def test_the_cli_refuses_a_conflicting_option(tmp_path):
    (tmp_path / "calc.py").write_text(PY, encoding="utf-8")
    proc = _cli(tmp_path, "--interactive", "--json")
    assert proc.returncode == 2, proc.stderr
    assert "--interactive is incompatible with: --json" in proc.stderr
    assert not (tmp_path / "slop-report").exists()


def test_the_cli_without_a_terminal_scans_and_does_not_wait(tmp_path):
    (tmp_path / "calc.py").write_text(PY, encoding="utf-8")
    proc = _cli(tmp_path, "--interactive")  # stdin is not a terminal: must return
    assert proc.returncode == 0, proc.stderr
    assert "--interactive needs a terminal" in proc.stderr
    assert "Save a report" not in proc.stdout
    assert not (tmp_path / "slop-report").exists()
    plain = _cli(tmp_path)
    assert plain.returncode == 0 and "--interactive needs a terminal" not in plain.stderr


def test_ci_and_write_capable_options_conflict_too():
    """Inspector INS-317-01/02: a CI option must never reach a prompt, and an
    option that writes or runs something of its own would act although no
    report was chosen: every option --read-only refuses is refused here too."""
    from slop_detector.cli import write_capable_options

    def names(**options):
        return conflicts(SimpleNamespace(interactive=True, **options))

    assert names(ci_claims_strict=True) == ["--ci-claims-strict"]
    assert names(fix=True) == ["--fix"]

    class Everything:
        interactive = True

        def __getattr__(self, name):
            return True

    table = set(write_capable_options(Everything()))
    assert len(table) >= 15 and table <= set(conflicts(Everything())), table


def test_the_cli_refuses_the_strict_ci_option(tmp_path):
    (tmp_path / "calc.py").write_text(PY, encoding="utf-8")
    proc = _cli(tmp_path, "--interactive", "--ci-claims-strict")
    assert proc.returncode == 2, proc.stderr
    assert "--interactive is incompatible with: --ci-claims-strict" in proc.stderr
