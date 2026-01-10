"""Base classes for pattern detection."""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class Severity(Enum):
    """Issue severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Axis(Enum):
    """Slop detection axes (from Sloppylint)."""

    NOISE = "noise"  # Information Utility - debug prints, redundant comments
    QUALITY = "quality"  # Information Quality - hallucinations, wrong APIs
    STYLE = "style"  # Style/Taste - overconfident comments, god functions
    STRUCTURE = "structure"  # Structural issues - bare except, anti-patterns


@dataclass
class Issue:
    """A detected code issue."""

    pattern_id: str
    severity: Severity
    axis: Axis
    file: Path
    line: int
    column: int
    message: str
    code: Optional[str] = None
    suggestion: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "pattern_id": self.pattern_id,
            "severity": self.severity.value,
            "axis": self.axis.value,
            "file": str(self.file),
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "code": self.code,
            "suggestion": self.suggestion,
        }


class BasePattern(ABC):
    """Base class for all detection patterns."""

    # Pattern metadata (override in subclasses)
    id: str = ""
    severity: Severity = Severity.MEDIUM
    axis: Axis = Axis.NOISE
    message: str = ""

    def create_issue(
        self,
        file: Path,
        line: int,
        column: int = 0,
        code: Optional[str] = None,
        message: Optional[str] = None,
        suggestion: Optional[str] = None,
    ) -> Issue:
        """Create an issue from this pattern."""
        return Issue(
            pattern_id=self.id,
            severity=self.severity,
            axis=self.axis,
            file=file,
            line=line,
            column=column,
            message=message or self.message,
            code=code,
            suggestion=suggestion,
        )

    def create_issue_from_node(
        self,
        node: ast.AST,
        file: Path,
        code: Optional[str] = None,
        message: Optional[str] = None,
        suggestion: Optional[str] = None,
    ) -> Issue:
        """Create an issue from an AST node."""
        return self.create_issue(
            file=file,
            line=getattr(node, "lineno", 0),
            column=getattr(node, "col_offset", 0),
            code=code,
            message=message,
            suggestion=suggestion,
        )

    @abstractmethod
    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        """
        Check for pattern violations.

        Args:
            tree: Parsed AST
            file: File path
            content: File content (for line-based checks)

        Returns:
            List of detected issues
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r})"


class ASTPattern(BasePattern):
    """Base class for AST-based patterns."""

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        """Walk AST and check each node."""
        issues = []
        for node in ast.walk(tree):
            if issue := self.check_node(node, file, content):
                if isinstance(issue, list):
                    issues.extend(issue)
                else:
                    issues.append(issue)
        return issues

    @abstractmethod
    def check_node(self, node: ast.AST, file: Path, content: str) -> Optional[Issue | list[Issue]]:
        """Check a single AST node."""
        pass


class RegexPattern(BasePattern):
    """Base class for regex-based patterns."""

    import re
    from typing import Pattern

    # Override in subclasses
    pattern: Pattern[str] | str = ""

    def __init__(self):
        if isinstance(self.pattern, str):
            self.pattern = self.re.compile(self.pattern)
        # Type narrowing for mypy
        assert not isinstance(self.pattern, str)

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        """Search content for regex matches."""
        issues = []
        lines = content.split("\n")

        # Type guard for mypy
        pattern = self.pattern
        if isinstance(pattern, str):
            pattern = self.re.compile(pattern)

        for line_num, line in enumerate(lines, start=1):
            for match in pattern.finditer(line):
                issue = self.create_issue(
                    file=file,
                    line=line_num,
                    column=match.start(),
                    code=line.strip(),
                )
                issues.append(issue)

        return issues
