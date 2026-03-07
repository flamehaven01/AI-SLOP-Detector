"""
Auto-Fix Engine for detected slop patterns.

Strategy: Each pattern has a registered Patcher.
The engine applies patches to source lines and returns
FixResult with the modified content and a change log.

Supported patterns (auto-fixable):
  bare_except          -> except Exception as e:
  mutable_default_arg  -> None default + guard
  pass_placeholder     -> raise NotImplementedError
  ellipsis_placeholder -> raise NotImplementedError
  js_push              -> .append(
  js_length            -> len(...)
  js_to_lower          -> .lower()
  js_to_upper          -> .upper()
  csharp_length        -> len(...)
  return_none_placeholder -> (annotate only, no structural change)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class FixChange:
    """A single line-level fix applied to source."""

    pattern_id: str
    line: int  # 1-based
    original: str
    replacement: str
    confidence: float  # 0.0-1.0


@dataclass
class FixResult:
    """Result of applying auto-fixes to a file."""

    file_path: str
    original_content: str
    fixed_content: str
    changes: List[FixChange] = field(default_factory=list)
    unfixable: List[str] = field(default_factory=list)  # pattern_ids not auto-fixed

    @property
    def changed(self) -> bool:
        return self.original_content != self.fixed_content

    @property
    def change_count(self) -> int:
        return len(self.changes)

    def summary(self) -> str:
        lines = [f"File: {self.file_path}"]
        lines.append(f"  Fixed: {self.change_count} issues")
        for ch in self.changes:
            lines.append(
                f"  [L{ch.line}] {ch.pattern_id}: {ch.original.strip()!r} -> {ch.replacement.strip()!r}"
            )
        if self.unfixable:
            lines.append(f"  Unfixable (manual): {', '.join(self.unfixable)}")
        return "\n".join(lines)


# ------------------------------------------------------------------
# Patcher functions
# Each patcher: (lines: List[str], line_idx: int, issue) -> Optional[FixChange]
# ------------------------------------------------------------------

Patcher = Callable[[List[str], int, object], Optional[FixChange]]

_PATCHERS: Dict[str, Patcher] = {}


def _register(pattern_id: str):
    def decorator(fn: Patcher) -> Patcher:
        _PATCHERS[pattern_id] = fn
        return fn

    return decorator


@_register("bare_except")
def _fix_bare_except(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    line = lines[idx]
    stripped = line.rstrip()
    indent = len(line) - len(line.lstrip())
    if "except:" in stripped:
        replacement = " " * indent + "except Exception as e:\n"
        return FixChange(
            pattern_id="bare_except",
            line=idx + 1,
            original=line,
            replacement=replacement,
            confidence=0.95,
        )
    return None


@_register("mutable_default_arg")
def _fix_mutable_default_arg(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    line = lines[idx]
    # Replace =[] with =None, =dict() with =None, ={} with =None
    new_line = re.sub(r"=\s*(\[\]|\{\}|dict\(\)|list\(\)|set\(\))", "=None", line)
    if new_line != line:
        return FixChange(
            pattern_id="mutable_default_arg",
            line=idx + 1,
            original=line,
            replacement=new_line,
            confidence=0.85,
        )
    return None


@_register("pass_placeholder")
def _fix_pass_placeholder(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    # Find the 'pass' line inside the function and replace with NotImplementedError
    line = lines[idx]
    stripped = line.strip()
    if stripped == "pass":
        indent = len(line) - len(line.lstrip())
        replacement = " " * indent + "raise NotImplementedError\n"
        return FixChange(
            pattern_id="pass_placeholder",
            line=idx + 1,
            original=line,
            replacement=replacement,
            confidence=0.80,
        )
    return None


@_register("ellipsis_placeholder")
def _fix_ellipsis_placeholder(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    line = lines[idx]
    stripped = line.strip()
    if stripped == "...":
        indent = len(line) - len(line.lstrip())
        replacement = " " * indent + "raise NotImplementedError\n"
        return FixChange(
            pattern_id="ellipsis_placeholder",
            line=idx + 1,
            original=line,
            replacement=replacement,
            confidence=0.80,
        )
    return None


@_register("js_push")
def _fix_js_push(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    line = lines[idx]
    new_line = line.replace(".push(", ".append(")
    if new_line != line:
        return FixChange(
            pattern_id="js_push",
            line=idx + 1,
            original=line,
            replacement=new_line,
            confidence=0.92,
        )
    return None


@_register("js_length")
def _fix_js_length(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    line = lines[idx]
    # obj.length -> len(obj)
    new_line = re.sub(r"(\w+)\.length\b", r"len(\1)", line)
    if new_line != line:
        return FixChange(
            pattern_id="js_length",
            line=idx + 1,
            original=line,
            replacement=new_line,
            confidence=0.88,
        )
    return None


@_register("csharp_length")
def _fix_csharp_length(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    line = lines[idx]
    new_line = re.sub(r"(\w+)\.Length\b", r"len(\1)", line)
    if new_line != line:
        return FixChange(
            pattern_id="csharp_length",
            line=idx + 1,
            original=line,
            replacement=new_line,
            confidence=0.85,
        )
    return None


@_register("csharp_to_lower")
def _fix_csharp_to_lower(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    line = lines[idx]
    new_line = re.sub(r"\.ToLower\(\)", ".lower()", line)
    if new_line != line:
        return FixChange(
            pattern_id="csharp_to_lower",
            line=idx + 1,
            original=line,
            replacement=new_line,
            confidence=0.95,
        )
    return None


@_register("csharp_to_upper")
def _fix_csharp_to_upper(lines: List[str], idx: int, issue) -> Optional[FixChange]:
    line = lines[idx]
    new_line = re.sub(r"\.ToUpper\(\)", ".upper()", line)
    if new_line != line:
        return FixChange(
            pattern_id="csharp_to_upper",
            line=idx + 1,
            original=line,
            replacement=new_line,
            confidence=0.95,
        )
    return None


# ------------------------------------------------------------------
# Engine
# ------------------------------------------------------------------


class FixEngine:
    """
    Applies auto-fixes to a file based on detected pattern Issues.

    Usage:
        engine = FixEngine()
        result = engine.fix_file(file_path, issues, dry_run=True)
        if result.changed:
            engine.apply(result)
    """

    UNFIXABLE_PATTERNS = {
        "star_import",
        "global_statement",
        "exec_eval_usage",
        "todo_comment",
        "fixme_comment",
        "hack_comment",
        "assert_in_production",
    }

    def fix_file(
        self,
        file_path: str,
        issues: list,
        dry_run: bool = True,
    ) -> FixResult:
        """
        Compute fixes for all issues in a file.

        Args:
            file_path: Path to the Python file.
            issues:    List of Issue objects from pattern detection.
            dry_run:   If True, do not write changes to disk.

        Returns:
            FixResult with original + fixed content and change log.
        """
        path = Path(file_path)
        original = path.read_text(encoding="utf-8", errors="ignore")
        lines = original.splitlines(keepends=True)

        changes: List[FixChange] = []
        unfixable: List[str] = []

        # Sort issues by line descending to apply bottom-up (preserves line numbers)
        sorted_issues = sorted(issues, key=lambda i: getattr(i, "line", 0), reverse=True)

        for issue in sorted_issues:
            pattern_id = getattr(issue, "pattern_id", "")
            if pattern_id in self.UNFIXABLE_PATTERNS:
                if pattern_id not in unfixable:
                    unfixable.append(pattern_id)
                continue

            patcher = _PATCHERS.get(pattern_id)
            if patcher is None:
                if pattern_id not in unfixable:
                    unfixable.append(pattern_id)
                continue

            line_1based = getattr(issue, "line", 0)
            if line_1based < 1 or line_1based > len(lines):
                continue

            idx = line_1based - 1
            change = patcher(lines, idx, issue)
            if change:
                lines[idx] = change.replacement
                changes.append(change)

        fixed_content = "".join(lines)
        result = FixResult(
            file_path=file_path,
            original_content=original,
            fixed_content=fixed_content,
            changes=sorted(changes, key=lambda c: c.line),
            unfixable=unfixable,
        )

        if not dry_run and result.changed:
            path.write_text(fixed_content, encoding="utf-8")

        return result

    def fix_project(
        self,
        file_analyses: List[Tuple[str, list]],
        dry_run: bool = True,
    ) -> List[FixResult]:
        """
        Apply fixes across all files in a project.

        Args:
            file_analyses: List of (file_path, issues) tuples.
            dry_run:       If True, do not write to disk.

        Returns:
            List of FixResult for each file that had fixable issues.
        """
        results = []
        for file_path, issues in file_analyses:
            fixable = [
                i for i in issues if getattr(i, "pattern_id", "") not in self.UNFIXABLE_PATTERNS
            ]
            if not fixable:
                continue
            result = self.fix_file(file_path, fixable, dry_run=dry_run)
            if result.changed or result.unfixable:
                results.append(result)
        return results
