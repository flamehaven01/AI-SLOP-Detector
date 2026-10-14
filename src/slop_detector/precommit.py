"""pre-commit adapter: run `slop-detector scan` once per changed file.

pre-commit appends every changed file to the hook's arguments, while `scan`
takes one path. This runs the unchanged `scan` for each file, in input order,
with the hook's flags, and returns the worst exit code. It does no analysis or
scoring of its own.

    python -m slop_detector.precommit [scan flags] FILE [FILE ...]
    python -m slop_detector.precommit --staged [scan flags]

--staged scans the staged .py files instead of the listed ones (the git hook
that GitIntegration.install_pre_commit_hook writes uses it).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from slop_detector.cli import main as scan_main
from slop_detector.cli_parsers import _build_arg_parser


def _values_taken(token: str, following: Optional[str]) -> int:
    """How many tokens after `token` are its value, according to scan's own parser."""
    if "=" in token:
        return 0
    action = _build_arg_parser()._option_string_actions.get(token)
    if action is None or action.nargs == 0:
        return 0
    if action.nargs == "?":
        if following is None or following.startswith("-") or Path(following).exists():
            return 0
        return 1
    return 1


def split_arguments(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Split hook arguments into (scan flags, files), keeping their order."""
    flags: List[str] = []
    files: List[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token.startswith("-") and token != "-":
            taken = _values_taken(token, argv[i + 1] if i + 1 < len(argv) else None)
            flags.extend(argv[i : i + 1 + taken])
            i += 1 + taken
        else:
            files.append(token)
            i += 1
    return flags, files


STAGED_FLAG = "--staged"


def _git_paths(args: List[str]) -> List[str]:
    """Paths git lists NUL-separated (-z: no quoting, no whitespace splitting)."""
    out = subprocess.run(["git", *args, "-z"], capture_output=True, check=True).stdout
    return [path.decode("utf-8") for path in out.split(b"\0") if path]


def staged_python_files() -> Tuple[List[str], List[str]]:
    """(staged added/copied/modified/renamed .py files, those also changed since staging).

    Paths are relative to the repository top, where git runs hooks. The scan
    reads the working tree, so a file changed after `git add` would not be the
    content being committed.
    """
    staged = [
        p
        for p in _git_paths(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
        if p.endswith(".py")
    ]
    unstaged = set(_git_paths(["diff", "--name-only"])) if staged else set()
    return staged, [p for p in staged if p in unstaged]


def _staged_files() -> Optional[List[str]]:
    """Files for --staged, or None after printing why the commit must stop."""
    try:
        staged, diverged = staged_python_files()
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        print(f"[-] Cannot list staged files: {type(exc).__name__}", file=sys.stderr)
        return None
    if diverged:
        print("[-] Changes not staged for commit in:", file=sys.stderr)
        for path in diverged:
            print(f"    {path}", file=sys.stderr)
        print("    The scan reads the working tree; stage or stash them first.", file=sys.stderr)
        return None
    return staged


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    staged_mode = STAGED_FLAG in args
    flags, files = split_arguments([a for a in args if a != STAGED_FLAG])
    if staged_mode:
        staged = _staged_files()
        if staged is None:
            return 1
        if not staged:
            print("[+] No staged Python files to check")
            return 0
        files = staged
    worst = 0
    for path in files:
        worst = max(worst, scan_main(["scan", path, *flags]))
    return worst


if __name__ == "__main__":
    sys.exit(main())
