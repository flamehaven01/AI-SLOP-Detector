"""Optional Rust hot-path file discovery for project scans."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)


def _candidate_binary_paths() -> List[Path]:
    root = Path(__file__).resolve().parents[2]
    binary_name = "slop_scan.exe" if os.name == "nt" else "slop_scan"
    candidates = [
        Path(os.environ["SLOP_RUST_SCAN_BIN"]) if os.environ.get("SLOP_RUST_SCAN_BIN") else None,
        root / "rust" / "slop_scan" / "target" / "release" / binary_name,
        root / "rust" / "slop_scan" / "target" / "debug" / binary_name,
    ]
    return [candidate for candidate in candidates if candidate is not None]


# Measured 2026-10-14 (release build, best of 3): the slowest of 16 replay-corpus
# repositories took 0.243 s (7,539 entries); 30 s is over 100x that. A timeout
# costs only time: discovery falls back to the Python walk, same file set.
RUST_SCAN_TIMEOUT_SECONDS = 30.0


def _scan_command(
    binary: Path, root: Path, include_patterns: Sequence[str], ignore_patterns: Sequence[str]
) -> List[str]:
    cmd = [str(binary), "--root", str(root)]
    for pattern in include_patterns:
        cmd.extend(["--include", pattern])
    for pattern in ignore_patterns:
        cmd.extend(["--ignore", pattern])
    return cmd


def _run_rust_scan(
    root: Path, include_patterns: Sequence[str], ignore_patterns: Sequence[str]
) -> Optional[List[str]]:
    for binary in _candidate_binary_paths():
        if not binary.exists():
            continue
        cmd = _scan_command(binary, root, include_patterns, ignore_patterns)
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=RUST_SCAN_TIMEOUT_SECONDS,
            )
            payload = json.loads(completed.stdout or "{}")
        except subprocess.TimeoutExpired:
            logger.debug("Rust file discovery timed out; using the Python walk")
            return None
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
            return None
        files = payload.get("files", [])
        if not isinstance(files, list):
            return None
        return [str(item) for item in files if isinstance(item, str)]
    return None


def discover_project_files(
    root: Path, include_patterns: Sequence[str], ignore_patterns: Sequence[str]
) -> Optional[List[Path]]:
    """Discover files via Rust hot path when the compiled helper is available."""
    discovered = _run_rust_scan(root, include_patterns, ignore_patterns)
    if discovered is None:
        return None
    result: List[Path] = []
    for item in discovered:
        path = Path(item)
        result.append(path if path.is_absolute() else root / path)
    return result
