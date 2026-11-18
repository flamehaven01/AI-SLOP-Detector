"""The executable's entry point (scripts/exe/launcher.py).

With arguments it hands them to the CLI untouched; started with none it asks
for a folder, scans it from inside with the report chooser, and waits for
Enter so the window stays open on the result or on an error.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "exe_launcher", REPO / "scripts" / "exe" / "launcher.py"
)
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


class Script:
    """Answers the prompts in order and records them."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def recording_cli(calls, code=0):
    def cli(argv):
        calls.append((list(argv), Path.cwd()))
        if isinstance(code, BaseException):
            raise code
        return code

    return cli


def test_arguments_go_to_the_cli_unchanged_without_a_prompt():
    calls, ask = [], Script()
    assert launcher.run(["--project", "x", "--json"], ask=ask, cli=recording_cli(calls, 3)) == 3
    assert [argv for argv, _ in calls] == [["--project", "x", "--json"]]
    assert ask.prompts == []


def test_no_arguments_scans_the_chosen_folder_from_inside_and_waits(tmp_path, monkeypatch):
    project = tmp_path / "my project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    calls, ask = [], Script(f'"{project}"', "")
    assert launcher.run([], ask=ask, cli=recording_cli(calls, 2)) == 2
    assert calls == [(["--project", ".", "--interactive"], project.resolve())]
    assert ask.prompts[-1] == launcher.CLOSE


def test_enter_scans_the_current_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls, ask = [], Script("", "")
    launcher.run([], ask=ask, cli=recording_cli(calls))
    assert calls[0][1] == tmp_path.resolve()
    assert str(tmp_path) in ask.prompts[0]


def test_a_name_that_is_no_folder_is_asked_again(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file.txt").write_text("x")
    calls, ask, said = [], Script("missing", "file.txt", str(tmp_path), ""), []
    launcher.run([], ask=ask, say=said.append, cli=recording_cli(calls))
    assert said == ["Not a folder: missing", "Not a folder: file.txt"]
    assert len(calls) == 1


def test_an_error_exit_still_waits_for_enter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls, ask = [], Script("", "")
    assert launcher.run([], ask=ask, cli=recording_cli(calls, SystemExit(2))) == 2
    assert ask.prompts[-1] == launcher.CLOSE


def test_ctrl_c_at_the_folder_prompt_ends_without_a_scan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    assert launcher.run([], ask=Script(KeyboardInterrupt()), cli=recording_cli(calls)) == 130
    assert calls == []


def test_end_of_input_at_the_close_prompt_returns_the_scan_code(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert launcher.run([], ask=Script("", EOFError()), cli=recording_cli([], 1)) == 1
