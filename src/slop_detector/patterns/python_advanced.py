"""
Python Advanced Structural Patterns (v2.8.0 / v2.9.0 / v3.0.1)

God function, dead code, deep nesting, lint escape, and phantom import detection.
Uses AST for structural analysis; line scanning for comment-based patterns.

Thresholds:
  GOD_FUNCTION_LINES       = 50  (lines in a single function)
  GOD_FUNCTION_COMPLEXITY  = 10  (cyclomatic complexity)
  DEEP_NESTING_THRESHOLD   = 4   (control flow nesting depth)
  LINT_ESCAPE_BARE_LIMIT   = 1   (bare # noqa before HIGH; 0 = first occurrence)

D2 (v3.0.1): god_function thresholds are configurable via .slopconfig.yaml.
  domain_overrides allow per-function-name threshold exemptions for domain-complex
  safety systems where high complexity is inherent to the problem (e.g., clinical
  decision engines, rule interpreters). See docs/CONFIGURATION.md for examples.
"""

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, List, Optional, Union

if TYPE_CHECKING:
    from pathlib import Path

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
      - It has more than lines_threshold non-blank lines, OR
      - Its cyclomatic complexity exceeds complexity_threshold.

    Thresholds default to GOD_FUNCTION_LINES / GOD_FUNCTION_COMPLEXITY but
    can be overridden via .slopconfig.yaml:

      patterns:
        god_function:
          complexity_threshold: 10    # global default
          lines_threshold: 50         # global default
          domain_overrides:
            - function_pattern: "evaluate"    # fnmatch; exact name or wildcard
              complexity_threshold: 80
              lines_threshold: 300

    domain_overrides allow safety-critical engines with inherent domain
    complexity (clinical decision trees, rule interpreters) to declare their
    own thresholds rather than generate false-positive god_function hits.

    God functions are the primary carrier of slop in AI-generated code:
    they combine unrelated responsibilities and resist meaningful testing.
    """

    id = "god_function"
    severity = Severity.HIGH
    axis = Axis.STYLE
    message = "God function detected"

    def __init__(
        self,
        complexity_threshold: int = GOD_FUNCTION_COMPLEXITY,
        lines_threshold: int = GOD_FUNCTION_LINES,
        domain_overrides: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__()
        self.complexity_threshold = complexity_threshold
        self.lines_threshold = lines_threshold
        self.domain_overrides: List[Dict[str, Any]] = domain_overrides or []

    def _thresholds_for(self, func_name: str) -> tuple[int, int]:
        """Return (complexity_threshold, lines_threshold) for a given function name.

        Checks domain_overrides in order; first match wins.
        Falls back to instance defaults if no override matches.
        """
        for override in self.domain_overrides:
            pattern = override.get("function_pattern", "")
            if pattern and fnmatch.fnmatch(func_name, pattern):
                cc = int(override.get("complexity_threshold", self.complexity_threshold))
                ln = int(override.get("lines_threshold", self.lines_threshold))
                return cc, ln
        return self.complexity_threshold, self.lines_threshold

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
            cc_limit, ln_limit = self._thresholds_for(node.name)

            is_too_long = logic_lines > ln_limit
            is_too_complex = complexity > cc_limit

            if is_too_long or is_too_complex:
                reasons = []
                if is_too_long:
                    reasons.append(f"{logic_lines} logic lines (limit {ln_limit})")
                if is_too_complex:
                    reasons.append(f"complexity={complexity} (limit {cc_limit})")

                # P2: Split severity — long-but-simple is a different problem than complex.
                # Physics pipelines / orchestrators are legitimately long with low branching.
                # Only flag HIGH when complexity is genuinely elevated.
                if is_too_complex:
                    # High complexity is always a structural problem
                    sev = Severity.HIGH
                elif is_too_long and complexity <= 5:
                    # Long but sequential — pipeline/orchestrator pattern; informational only
                    sev = Severity.LOW
                else:
                    sev = Severity.MEDIUM

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
                        severity_override=sev,
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


# Composite thresholds for nested_complexity pattern
_NESTED_CC_THRESHOLD = 5  # min cyclomatic complexity (moderate)
_NESTED_DEPTH_THRESHOLD = 4  # same as DEEP_NESTING_THRESHOLD


class NestedComplexityPattern(BasePattern):
    """Detect functions that combine deep nesting with moderate cyclomatic complexity.

    Either metric alone can have legitimate explanations. Both together
    signal structural slop: a function that is simultaneously hard to read
    (deep nesting) and hard to test (high branch count) without domain justification.

    Severity: CRITICAL — composite structural issue, harder to refactor away
    than a single nesting violation.

    D2 (v3.0.2): thresholds configurable via .slopconfig.yaml nested_complexity section.
    domain_overrides allow per-function-name exemptions for inherently complex domains.
    """

    id = "nested_complexity"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY

    def __init__(
        self,
        depth_threshold: int = _NESTED_DEPTH_THRESHOLD,
        cc_threshold: int = _NESTED_CC_THRESHOLD,
        domain_overrides: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__()
        self.depth_threshold = depth_threshold
        self.cc_threshold = cc_threshold
        self.domain_overrides: List[Dict[str, Any]] = domain_overrides or []

    def _thresholds_for(self, func_name: str) -> tuple[int, int]:
        """Return (depth_threshold, cc_threshold) for a given function name.

        Checks domain_overrides in order; first match wins.
        Falls back to instance defaults if no override matches.
        """
        for override in self.domain_overrides:
            pattern = override.get("function_pattern", "")
            if pattern and fnmatch.fnmatch(func_name, pattern):
                depth = int(override.get("depth_threshold", self.depth_threshold))
                cc = int(override.get("cc_threshold", self.cc_threshold))
                return depth, cc
        return self.depth_threshold, self.cc_threshold

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            depth = _max_nesting_depth(node)
            cc = _cyclomatic_complexity(node)
            depth_limit, cc_limit = self._thresholds_for(node.name)
            if depth >= depth_limit and cc >= cc_limit:
                issues.append(
                    self.create_issue(
                        file=file,
                        line=node.lineno,
                        column=node.col_offset,
                        message=(
                            f"Function '{node.name}' has both deep nesting (depth={depth}) "
                            f"and high cyclomatic complexity (cc={cc}) — structural complexity composite"
                        ),
                        suggestion=(
                            "Extract nested blocks into named helper functions. "
                            "Use early-return / guard clauses and reduce branch count."
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

# Single-entry cache: {"v": frozenset(...)} when populated.
# Dict mutation avoids a global statement.
_RESOLVABLE_MODULES_STORE: Dict[str, FrozenSet[str]] = {}

# ------------------------------------------------------------------
# Project-local package discovery (P0 fix)
# ------------------------------------------------------------------

_PROJECT_PACKAGES_CACHE: Dict[str, FrozenSet[str]] = {}

_SKIP_LAYOUT_DIRS: FrozenSet[str] = frozenset(
    {
        "tests",
        "test",
        "docs",
        "doc",
        "examples",
        "scripts",
        "tools",
        ".venv",
        "venv",
        "env",
        "build",
        "dist",
        ".git",
        "__pycache__",
        "node_modules",
        "site-packages",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".tox",
        "htmlcov",
    }
)


def _find_project_root(file_path: Path) -> Optional[Path]:
    """Walk up directory tree to find project root by standard markers."""
    markers = {"pyproject.toml", "setup.py", "setup.cfg", ".git"}
    current = file_path.parent
    for _ in range(12):
        if any((current / m).exists() for m in markers):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _add_dep_names(dep_list: List[str], packages: set) -> None:
    """Parse a list of PEP-508 dependency strings and add canonical names."""
    for dep in dep_list:
        name = re.split(r"[>=<!~;\[\s]", dep.strip())[0].strip()
        if not name:
            continue
        canon = name.replace("-", "_").lower()
        packages.add(canon)
        for prefix in ("flamehaven_", "flame_", "py", "python_"):
            if canon.startswith(prefix) and len(canon) > len(prefix) + 1:
                packages.add(canon[len(prefix) :])


def _augment_from_pyproject(project_root: Any, packages: set, scan_dir_fn: Any) -> None:
    """Read pyproject.toml and augment packages with layout dirs + dep names."""
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return
    try:
        toml_mod: Any = None
        try:
            import tomllib  # type: ignore[import-not-found]

            toml_mod = tomllib  # Python 3.11+
        except ImportError:
            try:
                import tomli  # type: ignore[import-not-found,import]

                toml_mod = tomli
            except ImportError:
                pass
        if toml_mod is None:
            return
        with open(pyproject, "rb") as fh:
            data = toml_mod.load(fh)
        # 3a. Filesystem scan via [tool.setuptools.packages.find] where = [...]
        find_cfg = data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
        for where in find_cfg.get("where", []):
            scan_dir_fn(project_root / where)
        # 3b. Declared dependencies → top-level import name whitelist
        dep_lists: List[List[str]] = [data.get("project", {}).get("dependencies", [])]
        for extras in data.get("project", {}).get("optional-dependencies", {}).values():
            dep_lists.append(extras)
        for dep_list in dep_lists:
            _add_dep_names(dep_list, packages)
    except Exception:  # noqa: BLE001
        pass


def _discover_project_packages(project_root: Path) -> FrozenSet[str]:
    """Discover internal Python package names via filesystem scan.

    Checks three layouts:
    1. src/ layout  : src/<name>/__init__.py
    2. Flat layout  : <name>/__init__.py at project root
    3. pyproject.toml: [tool.setuptools.packages.find] where = [...]

    Result is cached per project_root for the lifetime of the process.
    """
    root_key = str(project_root)
    if root_key in _PROJECT_PACKAGES_CACHE:
        return _PROJECT_PACKAGES_CACHE[root_key]

    packages: set[str] = set()

    def _scan_dir(search: Path) -> None:
        try:
            for item in search.iterdir():
                if (
                    item.is_dir()
                    and item.name not in _SKIP_LAYOUT_DIRS
                    and not item.name.startswith(".")
                    and (item / "__init__.py").exists()
                ):
                    packages.add(item.name)
        except OSError:
            pass

    # 1. src/ layout
    src_dir = project_root / "src"
    if src_dir.is_dir():
        _scan_dir(src_dir)

    # 2. Flat layout
    _scan_dir(project_root)

    # 3. pyproject.toml — package discovery + declared dependencies
    _augment_from_pyproject(project_root, packages, _scan_dir)

    result = frozenset(packages)
    _PROJECT_PACKAGES_CACHE[root_key] = result
    if result:
        logger.debug("Internal packages at %s: %s", project_root, result)
    return result


def _get_resolvable_modules() -> FrozenSet[str]:
    """Build the set of all top-level module names resolvable in this environment.

    Three sources, combined:
      1. Built-in C extension modules  (sys.builtin_module_names)
      2. Standard library              (sys.stdlib_module_names, Python 3.10+)
      3. Installed distributions       (importlib.metadata.packages_distributions)

    The result is cached for the lifetime of the process.
    """
    if "v" in _RESOLVABLE_MODULES_STORE:
        return _RESOLVABLE_MODULES_STORE["v"]

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

    _RESOLVABLE_MODULES_STORE["v"] = frozenset(known)
    return _RESOLVABLE_MODULES_STORE["v"]


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


# Exception names that indicate an optional-dependency guard pattern.
# Exception / BaseException are superclasses of ImportError and therefore
# also guard against import failures (e.g. `except Exception as e: raise HTTPException`).
_IMPORT_GUARD_EXC_NAMES: FrozenSet[str] = frozenset(
    {
        "ImportError",
        "ModuleNotFoundError",
        "Exception",
        "BaseException",
    }
)


def _handler_is_import_guard(handler: ast.ExceptHandler) -> bool:
    """Return True if this except handler would catch an ImportError."""
    if handler.type is None:
        return True  # bare except — guards ImportError among everything else
    exc_names: set[str] = set()
    if isinstance(handler.type, ast.Name):
        exc_names.add(handler.type.id)
    elif isinstance(handler.type, ast.Tuple):
        for elt in handler.type.elts:
            if isinstance(elt, ast.Name):
                exc_names.add(elt.id)
    return bool(exc_names & _IMPORT_GUARD_EXC_NAMES)


def _collect_import_guard_lines(tree: ast.AST) -> FrozenSet[int]:
    """Return line numbers of import statements inside try/except ImportError blocks.

    Detects intentional optional-dependency guard patterns:

        try:
            import heavy_library          # <- this line's lineno is returned
        except (ImportError, ModuleNotFoundError):
            heavy_library = None

    These imports are NOT phantom (the package exists) but are undeclared
    optional dependencies.  They deserve MEDIUM severity and a different
    suggestion ("add to optional-dependencies") rather than CRITICAL
    ("potential AI hallucination").

    Bare except handlers are also treated as import guards — they suppress
    ImportError along with everything else.
    """
    guarded: set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if any(_handler_is_import_guard(h) for h in node.handlers):
            for stmt in node.body:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    guarded.add(stmt.lineno)

    return frozenset(guarded)


class PhantomImportPattern(BasePattern):
    """Detect imports that reference non-existent packages (phantom/hallucinated imports).

    AI code generators occasionally produce import statements for packages that
    do not exist in the Python ecosystem — either because the model invented a
    plausible-sounding name, conflated two real package names, or referenced a
    package from a different language.

    Detection strategy:
      Cross-reference the top-level module name from every import statement
      against the union of:
        - Python built-in C modules      (sys.builtin_module_names)
        - Standard library modules       (sys.stdlib_module_names, 3.10+)
        - Installed distributions        (importlib.metadata.packages_distributions)
        - Project-local packages         (src-layout filesystem scan + pyproject.toml)
        - importlib.util.find_spec       (fallback for namespace / editable installs)

      Relative imports (from . import X) are excluded — they reference local
      project structure which is environment-dependent and not resolvable globally.

    Three-tier classification:
      CRITICAL  Unguarded unresolvable import — hard runtime crash, likely AI hallucination.
      MEDIUM    Guarded with try/except ImportError — real package, but not declared in
                [project.optional-dependencies].  Correct fix: add to optional extras.
      (skip)    Internal project package or resolvable in current environment.
    """

    id = "phantom_import"
    severity = Severity.CRITICAL
    axis = Axis.QUALITY
    message = "Import references a package that cannot be resolved in this environment"

    def check(self, tree: ast.AST, file: Path, content: str) -> list[Issue]:
        issues: list[Issue] = []

        # Build project-local whitelist (cached per project root).
        project_root = _find_project_root(file)
        internal_packages = (
            _discover_project_packages(project_root) if project_root else frozenset()
        )

        # Build ImportError-guard line index for this file.
        guarded_lines = _collect_import_guard_lines(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in internal_packages or _module_exists(top):
                        continue
                    lineno = getattr(node, "lineno", 0)
                    issues.append(
                        self._make_issue(
                            file,
                            lineno,
                            getattr(node, "col_offset", 0),
                            alias.name,
                            lineno in guarded_lines,
                        )
                    )

            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if not node.module:
                    continue
                top = node.module.split(".")[0]
                if top in internal_packages or _module_exists(top):
                    continue
                lineno = getattr(node, "lineno", 0)
                issues.append(
                    self._make_issue(
                        file,
                        lineno,
                        getattr(node, "col_offset", 0),
                        node.module,
                        lineno in guarded_lines,
                    )
                )

        return issues

    def _make_issue(
        self, file: Path, line: int, column: int, module_name: str, is_guarded: bool
    ) -> "Issue":
        """Build a phantom-import Issue with severity tuned to guard context.

        is_guarded=True  → MEDIUM: undeclared optional dependency
        is_guarded=False → CRITICAL: potential AI hallucination / hard crash
        """
        if is_guarded:
            return self.create_issue(
                file=file,
                line=line,
                column=column,
                message=(
                    f"Undeclared optional dependency: '{module_name}' is guarded with "
                    f"ImportError but not listed in [project.optional-dependencies]"
                ),
                suggestion=(
                    f"Add '{module_name}' to the appropriate "
                    f"[project.optional-dependencies.<group>] in pyproject.toml so "
                    f"users know this feature requires an extra install."
                ),
                severity_override=Severity.MEDIUM,
            )
        return self.create_issue(
            file=file,
            line=line,
            column=column,
            message=(
                f"Phantom import: '{module_name}' cannot be resolved "
                f"(not in stdlib, built-ins, or installed packages)"
            ),
            suggestion=(
                f"Verify '{module_name}' exists on PyPI and add it to "
                f"[project.dependencies] in pyproject.toml. "
                f"AI models sometimes generate plausible-looking but non-existent "
                f"package names."
            ),
            severity_override=Severity.CRITICAL,
        )


# ------------------------------------------------------------------
# v3.1.0: Function Clone Detection
# ------------------------------------------------------------------


class FunctionClonePattern(BasePattern):
    """Detect files where many functions have near-identical AST structure.

    Addresses the complexity_hidden_in_helpers evasion (SPAR A4):
    A god function split into N structurally identical helpers evades all
    per-function pattern gates, but produces a measurable signal at the
    file level: a large cluster of near-identical function AST distributions.

    Algorithm: pairwise Jensen-Shannon Divergence on 30-dim AST node-type
    histograms. Functions with JSD < 0.05 form clone groups (BFS components).
    Ported and adapted from Protocol-ReGenesis-Engine src/core/math_models.py
    (which itself ports Flamehaven-TOE v4.5.0 toe/math/di2.py).

    Thresholds (calibrated against SPAR A4 ground truth):
      >= 6 clones: HIGH   (complexity_hidden_in_helpers fires at 12 helpers)
      >= 4 clones: MEDIUM (borderline — document but don't over-penalize)
    """

    id = "function_clone_cluster"
    severity = Severity.HIGH
    axis = Axis.STRUCTURE

    def check(self, tree: ast.AST, file: Any, content: str) -> List[Issue]:
        from slop_detector.metrics.stub_density import (
            _CLONE_HIGH_THRESHOLD,
            _CLONE_MED_THRESHOLD,
            _MIN_FUNCTIONS_FOR_CLONE,
            calculate_stub_density,
        )

        result = calculate_stub_density(content)
        if result is None or result.total_functions < _MIN_FUNCTIONS_FOR_CLONE:
            return []

        if result.max_clone_group < _CLONE_MED_THRESHOLD:
            return []

        clone_size = result.max_clone_group
        names_preview = ", ".join(result.clone_group_names[:6])
        if len(result.clone_group_names) > 6:
            names_preview += f", ... (+{len(result.clone_group_names) - 6} more)"

        if clone_size >= _CLONE_HIGH_THRESHOLD:
            sev = Severity.CRITICAL
            msg = (
                f"{clone_size} structurally near-identical functions detected "
                f"(AST JSD < 0.05): {names_preview}. "
                f"Possible god function fragmented into helpers to evade per-function gates."
            )
        else:
            sev = Severity.HIGH
            msg = (
                f"{clone_size} structurally similar functions detected "
                f"(AST JSD < 0.05): {names_preview}. "
                f"Review for unnecessary decomposition."
            )

        return [
            Issue(
                pattern_id=self.id,
                severity=sev,
                axis=self.axis,
                file=Path(str(file)) if file else Path(),
                line=1,
                column=0,
                message=msg,
                suggestion=(
                    "If these functions represent a fragmented complex operation, "
                    "consider consolidating or using a data-driven dispatch table."
                ),
            )
        ]


# ------------------------------------------------------------------
# v3.1.0: Placeholder Variable Naming Detection
# ------------------------------------------------------------------

# Thresholds (v1.0 — first version, built to improve over time)
_PLACEHOLDER_PARAM_THRESHOLD = 5  # >= N single-letter params -> HIGH
_NUMBERED_SEQ_HIGH = 8  # >= N sequential numbered vars -> HIGH
_NUMBERED_SEQ_MED = 4  # >= N sequential numbered vars -> MEDIUM


def _max_consecutive_run(nums: list) -> int:
    """Length of the longest consecutive integer run in a sorted list."""
    if not nums:
        return 0
    best = cur = 1
    for i in range(1, len(nums)):
        if nums[i] == nums[i - 1] + 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
    return best


class PlaceholderVariableNamingPattern(BasePattern):
    """Detect systematic placeholder variable naming in function bodies.

    Two sub-checks:

    1. High single-letter parameter count.
       Real functions name parameters after what they represent.
       Having >= 5 single-letter params (a,b,c,d,e,f,g...) is a strong
       indicator of AI-generated placeholder code.

       Exclusions: self, cls, _ (underscore).
       Known false positive zones: matrix/tensor ops (configure with
       domain_overrides or --config ignore to suppress).

    2. Sequential numbered variable pattern.
       Variables named r1,r2,r3... / x1,x2,x3... / temp1,temp2... indicate
       code generated without semantic naming. >= 4 in sequence -> MEDIUM,
       >= 8 in sequence -> HIGH.

    v1.0 design note: This is a first version intentionally.
    The tool detects naming STYLE, not semantic quality.
    The signal is strong enough to flag obvious cases.
    Future versions can refine with context-aware heuristics.
    """

    id = "placeholder_variable_naming"
    severity = Severity.HIGH
    axis = Axis.QUALITY

    def check(self, tree: ast.AST, file: Any, content: str) -> List[Issue]:
        issues: List[Issue] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                issues.extend(self._check_function(node, file))
        return issues

    def _check_function(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef], file: Any
    ) -> List[Issue]:
        found: List[Issue] = []

        # --- Check 1: single-letter parameter count ---
        all_args = (
            [a.arg for a in node.args.args]
            + [a.arg for a in node.args.posonlyargs]
            + [a.arg for a in node.args.kwonlyargs]
        )
        semantic_args = [a for a in all_args if a not in ("self", "cls", "_")]
        single_letter = [a for a in semantic_args if len(a) == 1]

        if len(single_letter) >= _PLACEHOLDER_PARAM_THRESHOLD:
            preview = ", ".join(single_letter[:8])
            found.append(
                self.create_issue_from_node(
                    node,
                    file,
                    message=(
                        f"Function '{node.name}' has {len(single_letter)} single-letter "
                        f"parameters ({preview}) -- placeholder naming pattern"
                    ),
                    suggestion=(
                        "Use semantic parameter names that describe the data they represent. "
                        "For math/science code, suppress with domain_overrides in .slopconfig.yaml."
                    ),
                )
            )

        # --- Check 2: sequential numbered variable pattern ---
        numbered: dict = {}
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        m = re.match(r"^([a-zA-Z_][a-zA-Z_]*)(\d+)$", target.id)
                        if m:
                            prefix, num = m.group(1), int(m.group(2))
                            numbered.setdefault(prefix, []).append(num)

        for prefix, nums in numbered.items():
            run = _max_consecutive_run(sorted(set(nums)))
            if run < _NUMBERED_SEQ_MED:
                continue
            sev = Severity.HIGH if run >= _NUMBERED_SEQ_HIGH else Severity.MEDIUM
            found.append(
                self.create_issue(
                    file=file,
                    line=getattr(node, "lineno", 0),
                    column=getattr(node, "col_offset", 0),
                    message=(
                        f"Function '{node.name}' uses {run} sequential numbered variables "
                        f"({prefix}1..{prefix}{run}) -- placeholder naming pattern"
                    ),
                    suggestion=(
                        "Use semantic variable names that describe the computation. "
                        "Sequential numbered variables (r1, r2, r3...) indicate "
                        "generated or draft code."
                    ),
                    severity_override=sev,
                )
            )
            break  # one numbered-var issue per function is enough

        return found
