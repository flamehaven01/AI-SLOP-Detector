"""`--interactive`: after the summary, choose which report files to save.

Opt-in only. The chooser appears when `--interactive` is given and stdin and
stdout are both terminals; a scan without the flag never waits for input, and
the flag without a terminal prints a note and returns. Nothing is written
before a choice; a choice writes the file `--report-dir` writes
(report_bundle), under `slop-report/` in the current directory.

ASCII-only (cp949 safety).
"""

from __future__ import annotations

import sys
from typing import Any, Callable, List

# The folder the chosen files go to, relative to the current directory.
FOLDER = "slop-report"
# key, label, file of the bundle (report_bundle.write_bundle).
CHOICES = (
    ("1", "HTML", "report.html"),
    ("2", "Markdown", "report.md"),
    ("3", "AI work order", "ai-report.md"),
    ("4", "JSON", "scan.json"),
)
PROMPT = (
    " Save a report  "
    + "  ".join(f"[{key}] {label}" for key, label, _ in CHOICES)
    + "  [Enter] done > "
)
NEEDS_TERMINAL = "--interactive needs a terminal (stdin and stdout); no report was chosen"
# Options that already decide the output, or forbid writing: not with --interactive.
_CONFLICTS = (
    ("--ci-mode", "ci_mode"),
    ("--ci-report", "ci_report"),
    ("--format ai", "ai"),
    ("--json", "json"),
    ("--output", "output"),
    ("--quiet", "quiet"),
    ("--read-only", "read_only"),
    ("--report-dir", "report_dir"),
)


def conflicts(args: Any) -> List[str]:
    """The given options `--interactive` cannot be combined with (sorted)."""
    if not getattr(args, "interactive", False):
        return []
    return sorted(name for name, attr in _CONFLICTS if getattr(args, attr, None))


def should_prompt(args: Any, stdin: Any = None, stdout: Any = None) -> bool:
    """True only with the flag and a terminal on both stdin and stdout."""
    if not getattr(args, "interactive", False):
        return False
    streams = (sys.stdin if stdin is None else stdin, sys.stdout if stdout is None else stdout)
    return all(bool(getattr(s, "isatty", lambda: False)()) for s in streams)


def _ask(prompt: str) -> str:
    sys.stdout.write(prompt)
    sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        raise EOFError
    return line


def _chosen(answer: str) -> List[str]:
    """The files an answer names, in the order of the menu; [] when the answer
    holds anything that is not a choice."""
    keys = [c for c in answer.replace(",", " ") if not c.isspace()]
    known = {key: name for key, _, name in CHOICES}
    if not keys or any(key not in known for key in keys):
        return []
    return [name for key, _, name in CHOICES if key in keys]


def choose(
    result: Any,
    folder: str = FOLDER,
    ask: Callable[[str], str] = _ask,
    say: Callable[[str], None] = print,
    ai_limit: Any = None,
) -> List[str]:
    """Ask until Enter; write each chosen file; return the files written.
    Enter, end of input and Ctrl+C end the chooser and write nothing more."""
    from slop_detector.report_bundle import write_bundle

    written: List[str] = []
    while True:
        try:
            answer = ask(PROMPT)
        except (EOFError, KeyboardInterrupt):
            say("")
            return written
        if not answer.strip():
            return written
        names = _chosen(answer)
        if not names:
            say(" choose 1-4 (several at once: 1 3), or Enter to finish")
            continue
        done, failed = write_bundle(result, folder, ai_limit, only=names)
        for name in done:
            say(f" saved {folder}/{name}")
            if name not in written:
                written.append(name)
        for name, why in failed:
            say(f" [!] not written: {name} - {why}")
