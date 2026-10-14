"""`--inspector-read-only` is `--read-only` under the name the Flamehaven Inspector uses.

The Inspector runs `scan <target> --project --json --no-history
--inspector-read-only`. No release ever had that flag (3.9.3 and 3.10.0 exit
2 with "unrecognized arguments"). It is now an alias of --read-only: one
argparse option, so the two cannot drift apart.
"""

from __future__ import annotations

import json

import pytest

from slop_detector.cli_parsers import _build_arg_parser
from tests.test_read_only import WRITE_OPTIONS, _cli, _diff, _main, _project, _state

INSPECTOR_FLAGS = ["--project", "--json", "--no-history", "--inspector-read-only"]


def test_exact_inspector_argv_runs_and_changes_nothing(tmp_path):
    home, project = tmp_path / "home", _project(tmp_path / "proj")
    home.mkdir()
    before = _state(home, project)
    result = _cli(home, "scan", str(project), *INSPECTOR_FLAGS)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["project_path"] == str(project)
    assert _diff(before, _state(home, project)) == []


def test_alias_parses_to_the_same_options_as_read_only():
    parser = _build_arg_parser()
    alias = vars(parser.parse_args(["p", "--inspector-read-only"]))
    canonical = vars(parser.parse_args(["p", "--read-only"]))
    assert alias == canonical and alias["read_only"] is True


def test_alias_output_matches_read_only_output(tmp_path):
    project = _project(tmp_path / "proj")
    runs = {}
    for flag in ("--inspector-read-only", "--read-only"):
        home = tmp_path / f"home{flag}"
        home.mkdir()
        runs[flag] = _cli(home, "scan", str(project), "--project", "--json", "--no-history", flag)
    assert runs["--inspector-read-only"].returncode == runs["--read-only"].returncode == 0
    assert runs["--inspector-read-only"].stdout == runs["--read-only"].stdout


@pytest.mark.parametrize("option", WRITE_OPTIONS, ids=lambda o: o[0])
def test_alias_refuses_write_capable_options(tmp_path, capsys, option):
    project = str(_project(tmp_path / "p"))
    code, err = _main(["scan", project, "--inspector-read-only", *option], capsys)
    assert code == 2 and "incompatible with" in err and option[0] in err


def test_help_lists_the_alias():
    assert "--inspector-read-only" in _build_arg_parser().format_help()
