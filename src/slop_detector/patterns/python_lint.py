"""Lint/type suppression comment detection pattern."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity

_NOQA_BARE = re.compile(r"#\s*noqa\s*$", re.IGNORECASE)
_NOQA_SPECIFIC = re.compile(r"#\s*noqa\s*:\s*[\w,\s]+", re.IGNORECASE)
_TYPE_IGNORE = re.compile(r"#\s*type\s*:\s*ignore", re.IGNORECASE)
_PYLINT_DISABLE = re.compile(r"#\s*pylint\s*:\s*disable\s*=", re.IGNORECASE)


class LintEscapePattern(BasePattern):
    """Detect lint and type suppression comments used to silence tooling.

    Three signals:
      1. Bare ``# noqa``       — HIGH   (silences all warnings, no documentation)
      2. Specific ``# noqa: CODE`` — LOW (targeted; occasionally legitimate)
      3. ``# type: ignore`` / ``# pylint: disable=`` — MEDIUM
    """

    id = "lint_escape"
    severity = Severity.HIGH
    axis = Axis.QUALITY
    message = "Lint suppression comment hides potential issue"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        lines = content.splitlines()

        for lineno, raw in enumerate(lines, start=1):
            stripped = raw.lstrip()
            if not stripped or stripped.startswith("#"):
                continue

            if _NOQA_BARE.search(raw):
                issues.append(
                    self.create_issue(
                        file=file,
                        line=lineno,
                        column=raw.find("#"),
                        message="Bare '# noqa' suppresses ALL linter warnings on this line",
                        suggestion=(
                            "Fix the underlying lint error instead of suppressing it. "
                            "If suppression is truly necessary, specify the rule: "
                            "# noqa: E501"
                        ),
                        severity_override=Severity.HIGH,
                    )
                )
            elif _NOQA_SPECIFIC.search(raw):
                code_match = _NOQA_SPECIFIC.search(raw)
                code = code_match.group(0).split(":", 1)[-1].strip() if code_match else "?"
                issues.append(
                    self.create_issue(
                        file=file,
                        line=lineno,
                        column=raw.find("#"),
                        message=f"Lint suppression: # noqa: {code}",
                        suggestion=(
                            "Verify this suppression is intentional and document why "
                            "the underlying issue cannot be fixed."
                        ),
                        severity_override=Severity.LOW,
                    )
                )

            if _TYPE_IGNORE.search(raw):
                issues.append(
                    self.create_issue(
                        file=file,
                        line=lineno,
                        column=raw.find("#"),
                        message="Type error suppressed with '# type: ignore'",
                        suggestion=(
                            "Resolve the type error with a proper annotation or cast. "
                            "# type: ignore hides real bugs from static analysis."
                        ),
                        severity_override=Severity.MEDIUM,
                    )
                )

            if _PYLINT_DISABLE.search(raw):
                issues.append(
                    self.create_issue(
                        file=file,
                        line=lineno,
                        column=raw.find("#"),
                        message="Pylint check disabled inline",
                        suggestion=(
                            "Fix the pylint warning rather than disabling it. "
                            "Inline disables are harder to audit than .pylintrc entries."
                        ),
                        severity_override=Severity.MEDIUM,
                    )
                )

        return issues
