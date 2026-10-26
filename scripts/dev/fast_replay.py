"""Fast external replay of selected patterns, with coverage and source binding.

Each repo is analyzed by the product's own discovery and `analyze_file` (so
suppression, masking and role skips are the product's), with every pattern
except the selected ones disabled. Repos run in parallel.

usage:
  python -P scripts/dev/fast_replay.py run    --src SRC --repos ROOT --patterns a,b --out OUT.json REPO...
  python -P scripts/dev/fast_replay.py parity --src SRC --repos ROOT --patterns a,b REPO...
  python -P scripts/dev/fast_replay.py diff   OLD.json NEW.json

`run` writes, per repository, git HEAD and dirty-file count, the config used,
discovered / analyzed / failed files, files with pattern errors and a coverage
state; per finding the file's SHA-256; per report the src digest and Python
version. `parity` compares each repository with the full CLI pipeline
(`--project --json --read-only`) on (file, line, pattern, message) and on the
number of analyzed files; a repository that either side did not measure
completely never matches, and `run` exits non-zero on any incomplete
repository. Unknown pattern ids are refused. `diff`
prints the findings one report adds or drops against another.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _src_digest(src: Path) -> str:
    lines = [
        f"{_sha(p)}  {p.relative_to(src).as_posix()}"
        for p in sorted(src.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _git_state(repo: Path) -> dict:
    def git(*args):
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    status = git("status", "--porcelain")
    return {"head": head, "dirty_files": None if status is None else len(status.splitlines())}


def _scan_repo(job: tuple) -> dict:
    src, repo, patterns = job
    sys.path.insert(0, src)
    os.environ.pop("SLOP_CONFIG", None)
    home = tempfile.mkdtemp(prefix="replay_home_")
    os.environ["HOME"] = os.environ["USERPROFILE"] = home
    try:
        result = _scan(repo, patterns)
    finally:
        shutil.rmtree(home, ignore_errors=True)
    result["temp_home_left"] = os.path.exists(home)
    return result


def _scan(repo: str, patterns: set) -> dict:
    from slop_detector.core import SlopDetector
    from slop_detector.core_project import project_walk_scope
    from slop_detector.project_context import project_context_scope
    from slop_detector.service.policy import resolve_config_path

    # The same config the CLI would use: the project's .slopconfig.yaml, if any.
    config_path = resolve_config_path(Path(repo), True, None)
    detector = SlopDetector(config_path=config_path, read_only=True)
    for pattern in list(detector.pattern_registry.get_all()):
        if pattern.id not in patterns:
            detector.pattern_registry.disable(pattern.id)
    root = Path(repo)
    started = time.perf_counter()
    findings, failed, pattern_failed = [], [], []
    with project_context_scope(), project_walk_scope():
        files = detector._discover_supported_files(
            root, ["**/*.py"], {".py"}, detector.config.get_ignore_patterns()
        )
        for path in files:
            try:
                result = detector.analyze_file(str(path), root=str(root))
            except Exception as exc:  # noqa: BLE001 - recorded, not hidden
                failed.append({"file": str(path.relative_to(root)), "error": type(exc).__name__})
                continue
            if result.pattern_errors:
                pattern_failed.append(str(path.relative_to(root)))
            for issue in result.pattern_issues:
                if issue.pattern_id in patterns:
                    findings.append(
                        {
                            "file": path.relative_to(root).as_posix(),
                            "sha256": _sha(path),
                            "line": issue.line,
                            "pattern": issue.pattern_id,
                            "message": issue.message,
                        }
                    )
    analyzed = len(files) - len(failed)
    state = (
        "NO_MEASUREMENT" if not analyzed else "PARTIAL" if failed or pattern_failed else "COMPLETE"
    )
    return {
        "repo": root.name,
        "git": _git_state(root),
        "config": config_path,
        "discovered_files": len(files),
        "analyzed_files": analyzed,
        "failed_files": failed,
        "pattern_failed_files": pattern_failed,
        "coverage_state": state,
        "seconds": round(time.perf_counter() - started, 1),
        "findings": sorted(findings, key=lambda f: (f["file"], f["line"], f["pattern"])),
    }


def run(src: str, repos_root: str, patterns: set, repos: list, workers: int) -> dict:
    jobs = [(src, str(Path(repos_root) / name), patterns) for name in repos]
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(_scan_repo, jobs))
    return {
        "src": src,
        "src_digest": _src_digest(Path(src)),
        "python": platform.python_version(),
        "patterns": sorted(patterns),
        "wall_seconds": round(time.perf_counter() - started, 1),
        "repos": results,
    }


def _full_pipeline(src: str, repo: Path, patterns: set) -> tuple:
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, HOME=home, USERPROFILE=home, PYTHONPATH=src, PYTHONHASHSEED="1")
        env.pop("SLOP_CONFIG", None)
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "slop_detector.cli",
                "--project",
                str(repo),
                "--json",
                "--read-only",
            ],
            capture_output=True,
            env=env,
            cwd=home,
        )
    data = json.loads(done.stdout.decode("utf-8"))
    found = set()
    results = data.get("file_results", [])
    state = (data.get("scan_coverage") or {}).get("measurement_state")
    for fr in results:
        rel = Path(fr["file_path"]).resolve().relative_to(repo.resolve()).as_posix()
        for issue in fr.get("pattern_issues", []):
            if issue["pattern_id"] in patterns:
                found.add((rel, issue.get("line"), issue["pattern_id"], issue.get("message", "")))
    return found, len(results), state


def parity_state(repo: dict, full: set, full_files: int, full_state) -> str:
    """MATCH only when both sides measured everything and agree."""
    if repo["coverage_state"] != "COMPLETE" or full_state != "COMPLETE":
        return "INCOMPLETE"
    if key_set(repo) != full or repo["analyzed_files"] != full_files:
        return "MISMATCH"
    return "MATCH"


def run_exit(report: dict) -> int:
    """Non-zero when any repository was not completely measured."""
    return 0 if all(r["coverage_state"] == "COMPLETE" for r in report["repos"]) else 1


def key_set(report_repo: dict) -> set:
    return {(f["file"], f["line"], f["pattern"], f["message"]) for f in report_repo["findings"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["run", "parity", "diff"])
    parser.add_argument("rest", nargs="*")
    parser.add_argument("--src")
    parser.add_argument("--repos")
    parser.add_argument("--patterns", default="")
    parser.add_argument("--out")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    patterns = set(filter(None, args.patterns.split(",")))
    if args.mode != "diff":
        sys.path.insert(0, args.src)
        from slop_detector.patterns import get_all_patterns

        unknown = patterns - {p.id for p in get_all_patterns()}
        if not patterns or unknown:
            parser.error(f"--patterns must name registered pattern ids; unknown: {sorted(unknown)}")

    if args.mode == "diff":
        old, new = (json.loads(Path(p).read_text(encoding="utf-8")) for p in args.rest)
        olds = {r["repo"]: key_set(r) for r in old["repos"]}
        for repo in new["repos"]:
            before = olds.get(repo["repo"], set())
            after = key_set(repo)
            added, dropped = sorted(after - before), sorted(before - after)
            print(f"{repo['repo']}: +{len(added)} -{len(dropped)} ({repo['coverage_state']})")
            for item in added:
                print("   +", *item)
            for item in dropped:
                print("   -", *item)
        return 0

    report = run(args.src, args.repos, patterns, args.rest, args.workers)
    if args.mode == "run":
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        for repo in report["repos"]:
            print(
                f"{repo['repo']}: {len(repo['findings'])} findings, {repo['analyzed_files']}/"
                f"{repo['discovered_files']} files, {repo['coverage_state']}, {repo['seconds']} s"
                + (", temp HOME left" if repo["temp_home_left"] else "")
            )
        print(f"wall {report['wall_seconds']} s, src {report['src_digest'][:12]}")
        return run_exit(report)

    mismatches = 0
    for repo in report["repos"]:
        fast = key_set(repo)
        full, full_files, full_state = _full_pipeline(
            args.src, Path(args.repos) / repo["repo"], patterns
        )
        state = parity_state(repo, full, full_files, full_state)
        mismatches += state != "MATCH"
        print(
            f"{repo['repo']}: {state} fast={len(fast)} full={len(full)} "
            f"only_fast={len(fast - full)} only_full={len(full - fast)} "
            f"files={repo['analyzed_files']}/{full_files} full_state={full_state}"
        )
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
