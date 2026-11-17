"""A scan never fails on the terminal's encoding (R1, 2026-11-14).

With stdout redirected on Windows, Python writes in the locale encoding
(cp949 on a Korean system, cp1252 on a US one). A finding message the
encoding cannot hold (an em dash in a Go/JS message, Korean text in a user's
TODO comment) ended the scan with UnicodeEncodeError before --report-dir
wrote any file. The terminal now shows such a character escaped; the report
files are UTF-8 and keep it.

The PDF needs a local browser, which CI may not have; it is checked apart
(tests/test_ai_report.py). Here the browser is pinned to a missing one, so
every environment gets the same run: the PDF is the only file not written
and the CLI exits 2 for the incomplete bundle, never on the encoding.
"""

import os
import subprocess
import sys

import pytest

from slop_detector.report_pdf import BROWSER_ENV

HANGUL = chr(0xD55C) + chr(0xAE00)  # two Korean syllables, as in a user's comment
BUNDLE = ("report.md", "report.html", "ai-report.jsonl", "ai-report.md", "scan.json")


def _project(tmp_path):
    tmp_path.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "enc"\n', encoding="utf-8")
    (tmp_path / "main.go").write_text(
        "package main\n\n"
        f"// TODO: {HANGUL} handling\n"
        "func pending() {}\n\n"
        'func main() {\n\tpanic("x")\n}\n',
        encoding="utf-8",
    )
    (tmp_path / "app.js").write_text("var a = 1;\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("encoding", ["cp949", "cp1252", "utf-8"])
@pytest.mark.parametrize("extra", [[], ["--details", "--no-color"]])
def test_a_redirected_terminal_in_any_encoding_gets_the_full_run(tmp_path, encoding, extra):
    root = _project(tmp_path / "p")
    out = tmp_path / "out"
    env = dict(os.environ, PYTHONIOENCODING=encoding)
    env.pop("PYTHONUTF8", None)
    env[BROWSER_ENV] = str(tmp_path / "no-browser")
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "slop_detector.cli",
            "--project",
            str(root),
            "--report-dir",
            str(out),
            *extra,
        ],
        capture_output=True,
        env=env,
        cwd=str(root),
    )
    stderr = done.stderr.decode(encoding, errors="replace")
    assert "UnicodeEncodeError" not in stderr and "Traceback" not in stderr, stderr[-2000:]
    assert done.returncode == 2, stderr[-2000:]  # the incomplete bundle, not a crash
    not_written = [line for line in stderr.splitlines() if "not written:" in line]
    assert len(not_written) == 1 and "report.pdf" in not_written[0], stderr[-2000:]
    for name in BUNDLE:
        assert (out / name).is_file(), name
    # The files keep the user's text as written.
    assert HANGUL in (out / "report.md").read_text(encoding="utf-8")
    assert HANGUL in (out / "ai-report.md").read_text(encoding="utf-8")
