"""P1: a function that only builds values it discards ignores its inputs.

`def prompt_fn(question)` assigns a
template and returns nothing, so `question` shapes nothing. Reported when
every statement is `pass`, a log line, or a pure value assigned to a name the
function never reads.

Not adopted: reporting an unused positional parameter because the module
calls the function with that argument; it mostly finds argparse dispatch
handlers and helper arguments left behind by a refactor. Such a parameter
stays unreported (see the last test).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from slop_detector.core import SlopDetector

PID = "ignored_parameter"


def _found(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    return sorted((i.line, i.message) for i in result.pattern_issues if i.pattern_id == PID)


def test_body_that_only_builds_and_discards(tmp_path):
    source = '''
    def prompt_fn(question):
        TEMPLATE = """
    Answer the question.

    {Question}
        """.strip()
    '''
    assert _found(tmp_path, source) == [
        (
            2,
            "Parameter 'question' of 'prompt_fn' is never used; the body only builds TEMPLATE"
            " and discards it - it does not affect the result",
        ),
    ]


def test_acting_or_reading_bodies_are_not_discarding(tmp_path):
    source = """
    import subprocess

    def started(cmd, label):
        proc = subprocess.Popen(cmd)

    def kept(question):
        text = "x"
        return text

    def private(question):
        _cache = "x"

    def announce(question):
        msg = "ready"
        print(msg)
    """
    assert _found(tmp_path, source) == []


def test_argument_passed_by_the_module_is_not_evidence(tmp_path):
    source = """
    import subprocess

    def output_docs(backend, out, cwd):
        subprocess.check_call(["./tool", "help", backend], stdout=out)

    def main(backend, out, bin_dir):
        output_docs(backend, out, bin_dir)
    """
    assert _found(tmp_path, source) == []
