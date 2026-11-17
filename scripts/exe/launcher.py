"""Entry point of the single-file executable (scripts/exe/build_exe.py).

With arguments it is the slop-detector CLI, unchanged. Started with none (a
double-click), it asks for a folder, scans it with the report chooser
(`--project . --interactive` from inside that folder, so saved reports go to
<folder>/slop-report/), and waits for Enter before the window closes, so the
result or an error message stays readable.

ASCII-only (cp949 safety).
"""

import os
import sys
from pathlib import Path

CLOSE = "Press Enter to close."


def ask_folder(ask=input, say=print):
    """An existing folder, asked until one is given; Enter = the current folder.
    Quotes around a pasted or dragged path are dropped."""
    here = Path.cwd()
    while True:
        answer = ask(f"Folder to scan [{here}]: ").strip().strip('"').strip()
        folder = Path(answer) if answer else here
        if folder.is_dir():
            return folder.resolve()
        say(f"Not a folder: {answer}")


def run(argv, ask=input, say=print, cli=None):
    if cli is None:
        from slop_detector.cli import main as cli
    if argv:
        return cli(list(argv))
    try:
        folder = ask_folder(ask, say)
    except (KeyboardInterrupt, EOFError):
        return 130
    os.chdir(folder)
    try:
        code = cli(["--project", ".", "--interactive"])
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else 1
    except KeyboardInterrupt:
        code = 130
    try:
        ask(CLOSE)
    except (KeyboardInterrupt, EOFError):
        pass
    return code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
