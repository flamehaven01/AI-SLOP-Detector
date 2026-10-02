"""pre-commit adapter: run `slop-detector scan` once per changed file.

pre-commit appends every changed file to the hook's arguments, while `scan`
takes one path. This runs the unchanged `scan` for each file, in input order,
with the hook's flags, and returns the worst exit code. It does no analysis or
scoring of its own.

    python -m slop_detector.precommit [scan flags] FILE [FILE ...]
"""

from __future__ import annotations

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


def main(argv: Optional[Sequence[str]] = None) -> int:
    flags, files = split_arguments(list(sys.argv[1:] if argv is None else argv))
    worst = 0
    for path in files:
        worst = max(worst, scan_main(["scan", path, *flags]))
    return worst


if __name__ == "__main__":
    sys.exit(main())
