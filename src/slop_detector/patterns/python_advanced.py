"""
Python Advanced Structural Patterns (v2.8.0 / v2.9.0)

God function, dead code, deep nesting, lint escape, and phantom import detection.
Uses AST for structural analysis; line scanning for comment-based patterns.

Thresholds:
  GOD_FUNCTION_LINES       = 50  (lines in a single function)
  GOD_FUNCTION_COMPLEXITY  = 10  (cyclomatic complexity)
  DEEP_NESTING_THRESHOLD   = 4   (control flow nesting depth)
  LINT_ESCAPE_BARE_LIMIT   = 1   (bare # noqa before HIGH; 0 = first occurrence)
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import FrozenSet, Optional

from slop_detector.patterns.base import Axis, BasePattern, Issue, Severity

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

GOD_FUNCTION_LINES = 50
GOD_FUNCTION_COMPLEXITY = 10
DEEP_NESTING_THRESHOLD = 4

# Regex patterns for lint-escape detection (comment-based, not AST)
_NOQA_BARE = re.compile(r"#\s*noqa\s*$", re.IGNORECASE)
_NOQA_SPECIFIC = re.compile(r"#\s*noqa\s*:\s*[\w,\s]+", re.IGNORECASE)
_TYPE_IGNORE = re.compile(r"#\s*type\s*:\s*ignore", re.IGNORECASE)
_PYLINT_DISABLE = re.compile(r"#\s*pylint\s*:\s*disable\s*=", re.IGNORECASE)

# AST node types that contribute to cyclomatic complexity (+1 each)
_BRANCH_NODES = (
    ast.If,
    ast.For,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
)

# Nodes whose body sequence we scan for dead code
_BLOCK_CONTAINER_FIELDS = ("body", "orelse", "finalbody", "handlers")

# Statement types that terminate control flow in their block
_TERMINAL_STMTS = (ast.Return, ast.Raise, ast.Break, ast.Continue)

# Compound statement types (have a nested body)
_COMPOUND_STMTS = (
    ast.If,
    ast.For,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.AsyncFor,
    ast.Try,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _cyclomatic_complexity(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Compute McCabe cyclomatic complexity of a function.

    Base complexity = 1.
    +1 for each: if, for, while, except, with, async-with, async-for.
    +1 for each additional boolean operator (and/or) in a BoolOp.
    """
    complexity = 1
    for node in ast.walk(func_node):
        if isinstance(node, _BRANCH_NODES):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            # AND / OR: each additional operand adds one branch
            complexity += len(node.values) - 1
    return complexity


def _max_nesting_depth(node: ast.AST, depth: int = 0) -> int:
    """Return maximum control-flow nesting depth within a node.

    Depth increases for: if, for, while, with, try, except.
    """
    max_d = depth
    if isinstance(
        node, (ast.If, ast.For, ast.While, ast.With, ast.AsyncWith, ast.AsyncFor, ast.Try)
    ):
        depth += 1
        max_d = depth

    for child in ast.iter_child_nodes(node):
        max_d = max(max_d, _max_nesting_depth(child, depth))

    return max_d


def _collect_dead_statements(
    stmts: list[ast.stmt],
) -> list[ast.stmt]:
    """Return statements in the block that follow a terminal statement."""
    dead: list[ast.stmt] = []
    found_terminal = False
    for stmt in stmts:
        if found_terminal:
            dead.append(stmt)
        elif isinstance(stmt, _TERMINAL_STMTS):
            found_terminal = True
    return dead


def _find_dead_code_in_tree(root: ast.AST) -> list[ast.stmt]:
    """Recursively find all unreachable statements in every block."""
    dead: list[ast.stmt] = []

    for node in ast.walk(root):
        # Check every named block field that contains a statement list
        for field_name in ("body", "orelse", "finalbody"):
            stmts = getattr(node, field_name, None)
            if isinstance(stmts, list) and stmts:
                dead.extend(_collect_dead_statements(stmts))
        # try.handlers is a list of ExceptHandler, each with its own body
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                dead.extend(_collect_dead_statements(handler.body))

    return dead


# ------------------------------------------------------------------
# Patterns
# ------------------------------------------------------------------


class GodFunctionPattern(BasePattern):
    """Detect functions that are too large or too complex.

    A function is a 'god function' if:
      - It has more than GOD_FUNCTION_LINES non-blank lines, OR
      - Its cyclomatic complexity exceeds GOD_FUNCTION_COMPLEXITY.

    God functions are the primary carrier of slop in AI-generated code:
    they combine unrelated responsibilities and resist meaningful testing.
    """

    id = "god_function"
    severity = Severity.HIGH
    axis = Axis.STYLE
    message = "God function detected"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        lines = content.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            start = node.lineno
            end = getattr(node, "end_lineno", node.lineno)

            # Count non-blank logic lines within the function
            logic_lines = sum(
                1 for ln in lines[start - 1 : end] if ln.strip() and not ln.strip().startswith("#")
            )

            complexity = _cyclomatic_complexity(node)

            is_too_long = logic_lines > GOD_FUNCTION_LINES
            is_too_complex = complexity > GOD_FUNCTION_COMPLEXITY

            if is_too_long or is_too_complex:
                reasons = []
                if is_too_long:
                    reasons.append(f"{logic_lines} logic lines (limit {GOD_FUNCTION_LINES})")
                if is_too_complex:
                    reasons.append(f"complexity={complexity} (limit {GOD_FUNCTION_COMPLEXITY})")

                issues.append(
                    self.create_issue(
                        file=file,
                        line=start,
                        column=node.col_offset,
                        message=(f"God function '{node.name}': {', '.join(reasons)}"),
                        suggestion=(
                            "Break into smaller single-responsibility functions. "
                            "Each function should do one thing and fit on one screen."
                        ),
                    )
                )

        return issues


class DeadCodePattern(BasePattern):
    """Detect unreachable statements after return/raise/break/continue.

    AI-generated code frequently produces dead code when it inserts
    defensive logic after already-returned or raises, e.g.:
        return result
        print(\"done\")  # never reached
    """

    id = "dead_code"
    severity = Severity.MEDIUM
    axis = Axis.QUALITY
    message = "Unreachable code after return/raise/break/continue"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        dead_stmts = _find_dead_code_in_tree(tree)

        for stmt in dead_stmts:
            line = getattr(stmt, "lineno", 0)
            col = getattr(stmt, "col_offset", 0)
            issues.append(
                self.create_issue(
                    file=file,
                    line=line,
                    column=col,
                    message=self.message,
                    suggestion="Remove dead code. It is never executed and confuses readers.",
                )
            )

        return issues


class DeepNestingPattern(BasePattern):
    """Detect excessive control-flow nesting depth.

    Nesting depth > DEEP_NESTING_THRESHOLD in a single function is a
    strong signal of AI-generated 'defensive' code or absent abstractions.
    Each additional nesting level doubles cognitive load.
    """

    id = "deep_nesting"
    severity = Severity.HIGH
    axis = Axis.STYLE
    message = "Excessive nesting depth"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            depth = _max_nesting_depth(node)
            if depth > DEEP_NESTING_THRESHOLD:
                issues.append(
                    self.create_issue(
                        file=file,
                        line=node.lineno,
                        column=node.col_offset,
                        message=(
                            f"Function '{node.name}' has nesting depth {depth} "
                            f"(limit {DEEP_NESTING_THRESHOLD})"
                        ),
                        suggestion=(
                            "Extract nested blocks into helper functions. "
                            "Use early-return / guard clauses to reduce nesting."
                        ),
                    )
                )

        return issues


class LintEscapePattern(BasePattern):
    """Detect lint and type suppression comments used to silence tooling.

    AI-generated code frequently uses suppression comments to pass CI
    without actually fixing the underlying issue.  Three distinct signals:

    1. Bare ``# noqa`` (no rule code)  — HIGH
       The most egregious form: silences ALL warnings on the line with no
       indication of what was suppressed or why.

    2. Specific ``# noqa: CODE`` — LOW
       Targeted suppression.  Legitimate in some cases (long URLs, re-exports),
       but suspicious in large quantities or on logic-heavy lines.

    3. ``# type: ignore`` / ``# pylint: disable=`` — MEDIUM
       Type and style tool suppression.  Occasionally valid, often used to
       hide real type errors that the model could not resolve.

    Scoring rationale: bare noqa is significantly worse than specific noqa
    because it provides no documentation of *what* was wrong or *why* the
    suppression is intentional.
    """

    id = "lint_escape"
    severity = Severity.HIGH  # overridden per occurrence below
    axis = Axis.QUALITY
    message = "Lint suppression comment hides potential issue"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        lines = content.splitlines()

        for lineno, raw in enumerate(lines, start=1):
            # Skip comment-only lines and blank lines — focus on code lines
            stripped = raw.lstrip()
            if not stripped or stripped.startswith("#"):
                continue

            if _NOQA_BARE.search(raw):
                # Bare # noqa — highest severity
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
                # Specific targeted noqa with rule code — lower severity
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


# ------------------------------------------------------------------
# Module resolution index (built once per process, shared across files)
# ------------------------------------------------------------------

_RESOLVABLE_MODULES: Optional[FrozenSet[str]] = None


def _get_resolvable_modules() -> FrozenSet[str]:
    """Build the set of all top-level module names resolvable in this environment.

    Three sources, combined:
      1. Built-in C extension modules  (sys.builtin_module_names)
      2. Standard library              (sys.stdlib_module_names, Python 3.10+)
      3. Installed distributions       (importlib.metadata.packages_distributions)

    The result is cached for the lifetime of the process.
    """
    global _RESOLVABLE_MODULES
    if _RESOLVABLE_MODULES is not None:
        return _RESOLVABLE_MODULES

    known: set[str] = set()

    # 1. Built-in C modules (always available)
    known.update(sys.builtin_module_names)

    # 2. Standard library (Python 3.10+)
    if hasattr(sys, "stdlib_module_names"):
        known.update(sys.stdlib_module_names)  # type: ignore[attr-defined]

    # 3. Installed distributions — maps top-level import names to dist names
    try:
        from importlib.metadata import packages_distributions  # type: ignore[attr-defined]

        for top_level_names in packages_distributions().values():
            for name in top_level_names:
                known.add(name)
                known.add(name.replace("-", "_"))
    except (AttributeError, ImportError) as exc:
        # packages_distributions() unavailable on Python < 3.11; resolution index will be
        # incomplete but functional — falls through to find_spec on unknown names
        logger.debug("packages_distributions unavailable, skipping layer 3: %s", exc)

    _RESOLVABLE_MODULES = frozenset(known)
    return _RESOLVABLE_MODULES


def _module_exists(name: str) -> bool:
    """Return True if *name* is a resolvable top-level module.

    Falls back to importlib.util.find_spec for edge cases
    (namespace packages, local editable installs) not captured by the index.
    Errs on the side of False Negative (returns True on error) to avoid
    false positives on unusual but legitimate setups.
    """
    if name in _get_resolvable_modules():
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return True  # unknown environment — assume resolvable


class PhantomImportPattern(BasePattern):
    """Detect imports that reference non-existent packages (phantom/hallucinated imports).

    AI code generators occasionally produce import statements for packages that
    do not exist in the Python ecosystem — either because the model invented a
    plausible-sounding name, conflated two real package names, or referenced a
    package from a different language.

    Examples of phantom imports produced by AI:
        import tensorflow_utils          # does not exist
        from requests_async_v2 import get # does not exist
        import numpy_extended            # does not exist

    Detection strategy:
      Cross-reference the top-level module name from every import statement
      against the union of:
        - Python built-in C modules      (sys.builtin_module_names)
        - Standard library modules       (sys.stdlib_module_names, 3.10+)
        - Installed distributions        (importlib.metadata.packages_distributions)
        - importlib.util.find_spec       (fallback for namespace / editable installs)

      Relative imports (from . import X) are excluded — they reference local
      project structure which is environment-dependent and not resolvable globally.

    Severity: CRITICAL — a phantom import is a hard runtime error waiting to happen
    and is a direct signal of hallucinated code.
    """

    id = "phantom_import"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Import references a package that cannot be resolved in this environment"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if not _module_exists(top):
                        issues.append(
                            self.create_issue(
                                file=file,
                                line=getattr(node, "lineno", 0),
                                column=getattr(node, "col_offset", 0),
                                message=(
                                    f"Phantom import: '{alias.name}' cannot be resolved "
                                    f"(not in stdlib, built-ins, or installed packages)"
                                ),
                                suggestion=(
                                    f"Verify '{alias.name}' exists on PyPI and is listed "
                                    f"in your project dependencies. AI models sometimes "
                                    f"generate plausible-looking but non-existent package names."
                                ),
                            )
                        )

            elif isinstance(node, ast.ImportFrom):
                # Skip relative imports (level > 0) — local project structure
                if node.level and node.level > 0:
                    continue
                if not node.module:
                    continue
                top = node.module.split(".")[0]
                if not _module_exists(top):
                    issues.append(
                        self.create_issue(
                            file=file,
                            line=getattr(node, "lineno", 0),
                            column=getattr(node, "col_offset", 0),
                            message=(
                                f"Phantom import: '{node.module}' cannot be resolved "
                                f"(not in stdlib, built-ins, or installed packages)"
                            ),
                            suggestion=(
                                f"Verify '{node.module}' exists on PyPI and is listed "
                                f"in your project dependencies."
                            ),
                        )
                    )

        return issues
