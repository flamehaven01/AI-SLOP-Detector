"""
Git integration for automatic history recording.
Provides pre-commit hook and git info extraction.
"""

import shlex
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

# Ownership line of the hook install_pre_commit_hook writes; only a hook that
# carries it is replaced.
HOOK_MARKER = "# ai-slop-detector managed pre-commit hook"


class GitIntegration:
    """Git integration utilities"""

    @staticmethod
    def is_git_repo(path: str = ".") -> bool:
        """Check if current directory is a git repository"""
        try:
            subprocess.run(
                ["git", "rev-parse", "--git-dir"], cwd=path, capture_output=True, check=True
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    @staticmethod
    def get_current_info(path: str = ".") -> Optional[Dict[str, str]]:
        """Get current git commit and branch info"""
        if not GitIntegration.is_git_repo(path):
            return None

        try:
            # Get current commit hash
            commit_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=path,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            commit = commit_result.stdout.strip()

            # Get current branch
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=path,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            branch = branch_result.stdout.strip()

            return {"commit": commit, "branch": branch}
        except subprocess.CalledProcessError:
            return None

    @staticmethod
    def get_staged_files(path: str = ".", extensions: tuple = (".py",)) -> list:
        """Get list of staged files with specified extensions"""
        if not GitIntegration.is_git_repo(path):
            return []

        try:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    "core.quotepath=off",
                    "diff",
                    "--cached",
                    "--name-only",
                    "--diff-filter=ACM",
                ],
                cwd=path,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )

            files = result.stdout.strip().split("\n")
            return [f for f in files if f and any(f.endswith(ext) for ext in extensions)]
        except subprocess.CalledProcessError:
            return []

    @staticmethod
    def install_pre_commit_hook(repo_path: str = ".") -> bool:
        """Install a git pre-commit hook that scans the staged .py files.

        The hook runs `python -m slop_detector.precommit --staged --ci-mode hard`
        with the interpreter that installed it (deleting that environment
        breaks the hook with an error). The commit is blocked when a scan fails
        the hard gate or cannot run, and when a staged file has unstaged
        changes (the scan reads the working tree). The hooks directory comes
        from git (worktrees, core.hooksPath). A hook that does not carry
        HOOK_MARKER is someone else's and is never overwritten.
        """
        try:
            hooks = subprocess.run(
                ["git", "rev-parse", "--git-path", "hooks"],
                cwd=repo_path,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            print("[!] Not a git repository")
            return False

        hook_path = (Path(repo_path) / hooks / "pre-commit").resolve()
        if hook_path.exists():
            try:
                existing = hook_path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                print(f"[-] Cannot read existing hook {hook_path}: {e}")
                return False
            if HOOK_MARKER not in existing:
                print(f"[-] {hook_path} exists and was not installed by slop-detector; left as is")
                return False

        interpreter = shlex.quote(Path(sys.executable).as_posix())
        hook_content = (
            "#!/bin/sh\n"
            f"{HOOK_MARKER}\n"
            "# Scans staged .py files with --ci-mode hard; see slop_detector.precommit.\n"
            f"exec {interpreter} -m slop_detector.precommit --staged --ci-mode hard\n"
        )
        try:
            hook_path.parent.mkdir(parents=True, exist_ok=True)
            hook_path.write_text(hook_content, encoding="utf-8", newline="\n")
            hook_path.chmod(0o755)
        except OSError as e:
            print(f"[-] Failed to install hook: {e}")
            return False
        print(f"[+] Pre-commit hook installed at: {hook_path}")
        return True
