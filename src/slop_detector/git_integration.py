"""
Git integration for automatic history recording.
Provides pre-commit hook and git info extraction.
"""

import subprocess
from pathlib import Path
from typing import Dict, Optional


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
                ["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True
            )
            commit = commit_result.stdout.strip()

            # Get current branch
            branch_result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=path,
                capture_output=True,
                text=True,
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
                ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                cwd=path,
                capture_output=True,
                text=True,
                check=True,
            )

            files = result.stdout.strip().split("\n")
            return [f for f in files if f and any(f.endswith(ext) for ext in extensions)]
        except subprocess.CalledProcessError:
            return []

    @staticmethod
    def install_pre_commit_hook(repo_path: str = ".") -> bool:
        """Install git pre-commit hook for automatic slop detection"""
        if not GitIntegration.is_git_repo(repo_path):
            print("[!] Not a git repository")
            return False

        git_dir = Path(repo_path) / ".git"
        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(exist_ok=True)

        hook_path = hooks_dir / "pre-commit"

        hook_content = """#!/bin/sh
# AI SLOP Detector Pre-Commit Hook

echo "[*] Running AI SLOP Detector on staged files..."

# Get staged Python files
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E '\\.py$')

if [ -z "$STAGED_FILES" ]; then
    echo "[+] No Python files to check"
    exit 0
fi

# Run slop detector with history recording
slop-detector --files $STAGED_FILES --record-history --fail-on regression

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "[-] Slop detection failed! Fix issues before committing."
    echo "    Run: slop-detector <file> --verbose for details"
    exit 1
fi

echo "[+] Slop detection passed!"
exit 0
"""

        try:
            hook_path.write_text(hook_content)
            hook_path.chmod(0o755)  # Make executable
            print(f"[+] Pre-commit hook installed at: {hook_path}")
            return True
        except Exception as e:
            print(f"[-] Failed to install hook: {e}")
            return False
