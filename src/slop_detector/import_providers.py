"""Import provider resolution: which distribution provides an import name.

Design and evidence ladder: docs/IMPORT_PROVIDER_RESOLUTION.md. Two boundaries:

- presence of evidence strengthens a link, absence does not prove absence;
- mapping knowledge is not presence: that the analyzer has a distribution
  installed shows which names it provides, not that the analyzed project has it.

Evidence, strongest first (provider_state):
  ARTIFACT_VERIFIED  the target environment's installed files (dist-info RECORD / top_level.txt)
  METADATA_DECLARED  PEP 794 Import-Name / Import-Namespace of a target-environment distribution
  MAPPING_SUPPORTED  the analyzer environment's metadata, or the shipped table
                     (config/import_providers.json)
  NAME_CANDIDATE     the declared name itself, normalized: a candidate, never the basis of a
                     CRITICAL or HIGH verdict
  PROVIDER_UNKNOWN / PROVIDER_CONFLICT  no evidence / evidence that disagrees

The target environment is a virtual environment directly inside a project root (a directory
with pyvenv.cfg). It is read as files only: never activated, imported from or executed.
Import names are compared exactly (case-sensitive); distribution names after PEP 503
normalization.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from slop_detector.environment_resolution import RACY_NS, State, environment_state
from slop_detector.path_boundary import leaves, walk_boundary

ARTIFACT_VERIFIED = "ARTIFACT_VERIFIED"
METADATA_DECLARED = "METADATA_DECLARED"
MAPPING_SUPPORTED = "MAPPING_SUPPORTED"
NAME_CANDIDATE = "NAME_CANDIDATE"
PROVIDER_UNKNOWN = "PROVIDER_UNKNOWN"
PROVIDER_CONFLICT = "PROVIDER_CONFLICT"

_TABLE_PATH = Path(__file__).parent / "config" / "import_providers.json"
_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_PREFIXES = ("flamehaven_", "flame_", "py", "python_")


def normalize(name: str) -> str:
    """PEP 503 normalized distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


# ---------------------------------------------------------------------------
# Requirements
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Requirement:
    """One declared distribution: the name as written, normalized, its marker and its source."""

    written: str
    dist: str
    marker: Optional[str]
    label: str


def parse_requirement(raw: str, label: str) -> Optional[Requirement]:
    """A requirement string as declaration files hold it (PEP 508, conda spec, table key)."""
    text = raw.split("#", 1)[0].strip()
    if not text or text.startswith(("-", "git+", "http://", "https://", "file:", ".")):
        return None
    head, _, marker = text.partition(";")
    head = head.strip()
    if "::" in head:  # conda channel::name
        head = head.split("::", 1)[1]
    match = _NAME_RE.match(head)
    if not match:
        return None
    written = match.group(0).rstrip("._-")
    return Requirement(written, normalize(written), marker.strip() or None, label)


# ---------------------------------------------------------------------------
# Environment markers (PEP 508), evaluated for the environment the analyzed code targets
# ---------------------------------------------------------------------------

# A target known to be POSIX is known not to be Windows, although which POSIX platform it is
# stays unknown: these variables can then be decided against the Windows value only.
_WINDOWS_VALUE = {"sys_platform": "win32", "platform_system": "Windows"}


def marker_environment(target: Optional["TargetEnvironment"]) -> Dict[str, str]:
    """Marker variables known for the target environment; a variable it does not establish is
    absent (unknown). With no target environment nothing is known: the analyzer's own
    platform and Python are not evidence about where the analyzed code runs."""
    if target is None:
        return {}
    env: Dict[str, str] = {}
    if target.platform == "win32":
        env.update(sys_platform="win32", platform_system="Windows", os_name="nt")
    elif target.platform == "posix":
        env.update(os_name="posix")
    if target.python_version:
        env["python_version"] = target.python_version
    if target.python_full_version:
        env["python_full_version"] = target.python_full_version
    return env


_TOKEN_RE = re.compile(
    r"\s*(\(|\)|not\s+in\b|in\b|and\b|or\b|===|==|!=|<=|>=|~=|<|>|\"[^\"]*\"|'[^']*'|[A-Za-z_][A-Za-z0-9_.]*)"
)
_VERSION_VARS = {"python_version", "python_full_version", "implementation_version"}


def _tokens(marker: str) -> Optional[List[str]]:
    out, pos = [], 0
    while pos < len(marker):
        if marker[pos:].strip() == "":
            break
        m = _TOKEN_RE.match(marker, pos)
        if not m:
            return None
        out.append(m.group(1))
        pos = m.end()
    return out


def _version_tuple(value: str) -> Optional[Tuple[int, ...]]:
    parts = re.findall(r"\d+", value)
    return tuple(int(p) for p in parts) if parts else None


def _compare(left: str, op: str, right: str, version: bool) -> Optional[bool]:
    if op in ("in", "not in"):
        found = left in right
        return found if op == "in" else not found
    if not version:
        if op in ("==", "==="):
            return left == right
        return left != right if op == "!=" else None
    a, b = _version_tuple(left), _version_tuple(right)
    if a is None or b is None:
        return None
    width = max(len(a), len(b))
    va, vb = a + (0,) * (width - len(a)), b + (0,) * (width - len(b))
    results = {
        "==": va == vb,
        "===": va == vb,
        "!=": va != vb,
        "<": va < vb,
        "<=": va <= vb,
        ">": va > vb,
        ">=": va >= vb,
        "~=": va >= vb,
    }
    return results.get(op)


def _not_windows(
    var: Optional[str], op: str, values: Sequence[str], env: Dict[str, str]
) -> Optional[bool]:
    """Decide a test of an unknown platform variable on a target known to be POSIX, when the
    test only asks whether it is the Windows value."""
    if var not in _WINDOWS_VALUE or env.get("os_name") != "posix":
        return None
    if not values or any(v != _WINDOWS_VALUE[var] for v in values):
        return None
    return op in ("!=", "not in")


def _and(values: Sequence[Optional[bool]]) -> Optional[bool]:
    if any(v is False for v in values):
        return False
    return None if any(v is None for v in values) else True


def _or(values: Sequence[Optional[bool]]) -> Optional[bool]:
    if any(v is True for v in values):
        return True
    return None if any(v is None for v in values) else False


def marker_active(marker: Optional[str], env: Dict[str, str]) -> Optional[bool]:
    """True/False for a marker in the target environment `env`; None when it cannot be
    decided (a variable the target does not establish, `extra`, a syntax this evaluator does
    not read)."""
    if not marker:
        return True
    toks = _tokens(marker)
    if toks is None:
        return None
    parser = _MarkerParser(toks, env)
    try:
        result = parser.expr()
    except (IndexError, ValueError):
        return None
    return result if parser.pos == len(toks) else None


class _MarkerParser:
    """Recursive descent over marker tokens: expr := conj ('or' conj)*, conj := atom ('and' atom)*,
    atom := '(' expr ')' | value op value. Three-valued: None when a value is unknown."""

    def __init__(self, toks: List[str], env: Dict[str, str]) -> None:
        self.toks, self.env, self.pos = toks, env, 0

    def _take(self) -> str:
        tok = self.toks[self.pos]
        self.pos += 1
        return tok

    def _peek(self, tok: str) -> bool:
        return self.pos < len(self.toks) and self.toks[self.pos] == tok

    def value(self) -> Tuple[Optional[str], bool, Optional[str]]:
        """(value or None when unknown, is a version variable, variable name or None)."""
        tok = self._take()
        if tok[0] in "\"'":
            return tok[1:-1], False, None
        return (self.env.get(tok) if tok != "extra" else None), tok in _VERSION_VARS, tok

    def atom(self) -> Optional[bool]:
        if self._peek("("):
            self._take()
            result = self.expr()
            if not self._peek(")"):
                raise ValueError("unbalanced")
            self._take()
            return result
        left, lv, lvar = self.value()
        op = re.sub(r"\s+", " ", self._take())
        right, rv, _ = self.value()
        if right is None:
            return None
        if left is None:
            return _not_windows(lvar, op, [right], self.env)
        return _compare(left, op, right, lv or rv)

    def conj(self) -> Optional[bool]:
        values = [self.atom()]
        while self._peek("and"):
            self._take()
            values.append(self.atom())
        return _and(values)

    def expr(self) -> Optional[bool]:
        values = [self.conj()]
        while self._peek("or"):
            self._take()
            values.append(self.conj())
        return _or(values)


# ---------------------------------------------------------------------------
# Platform guards in code: `if sys.platform == "win32": import win32api`
# ---------------------------------------------------------------------------


def _attr(node: ast.AST, base: str, name: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == name
        and isinstance(node.value, ast.Name)
        and node.value.id == base
    )


def _guard_variable(node: ast.AST) -> Optional[str]:
    """The marker variable a guard expression reads, or None if it reads none."""
    if _attr(node, "sys", "platform"):
        return "sys_platform"
    if _attr(node, "os", "name"):
        return "os_name"
    if isinstance(node, ast.Call) and not node.args and _attr(node.func, "platform", "system"):
        return "platform_system"
    return None


def _constants(node: ast.AST) -> Optional[Tuple[str, ...]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        values = [
            e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if len(values) == len(node.elts):
            return tuple(str(v) for v in values)
    return None


_GUARD_OPS = {ast.Eq: "==", ast.NotEq: "!=", ast.In: "in", ast.NotIn: "not in"}


def _compare_test(node: ast.Compare, env: Dict[str, str]) -> Optional[bool]:
    """`sys.platform == "win32"`, `os.name != "nt"`, `platform.system() in (...)`."""
    var, consts = _guard_variable(node.left), _constants(node.comparators[0])
    op = _GUARD_OPS.get(type(node.ops[0]))
    if var is None or consts is None or op is None:
        return None
    actual = env.get(var)
    if actual is None:
        return _not_windows(var, op, consts, env)
    if op in ("==", "!="):
        return (actual == consts[0]) == (op == "==")
    return (actual in consts) == (op == "in")


def _startswith_test(node: ast.Call, env: Dict[str, str]) -> Optional[bool]:
    """`sys.platform.startswith("linux")` (a string or a tuple of strings)."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "startswith" and len(node.args) == 1):
        return None
    if not _attr(func.value, "sys", "platform"):
        return None
    consts = _constants(node.args[0])
    if consts is None:
        return None
    actual = env.get("sys_platform")
    if actual is None:
        # a POSIX target is known not to start with "win"
        if env.get("os_name") == "posix" and all(c and "win32".startswith(c) for c in consts):
            return False
        return None
    return actual.startswith(consts)


def platform_test(node: ast.AST, env: Dict[str, str]) -> Optional[bool]:
    """Value of a platform test in the target environment; None if it is not one or the
    target does not establish it."""
    if isinstance(node, ast.BoolOp):
        values = [platform_test(v, env) for v in node.values]
        return _and(values) if isinstance(node.op, ast.And) else _or(values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = platform_test(node.operand, env)
        return None if inner is None else not inner
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        return _compare_test(node, env)
    if isinstance(node, ast.Call):
        return _startswith_test(node, env)
    return None


def _is_platform_test(node: ast.AST) -> bool:
    """Whether a test reads a platform variable at all (decided or not)."""
    return any(_guard_variable(n) for n in ast.walk(node)) or any(
        isinstance(n, ast.Attribute)
        and n.attr == "startswith"
        and _attr(n.value, "sys", "platform")
        for n in ast.walk(node)
    )


def platform_guard_lines(
    tree: ast.AST, env: Dict[str, str]
) -> Tuple[FrozenSet[int], FrozenSet[int]]:
    """(inactive, undecided) lines of import statements under platform tests: inactive when a
    test is false in the target environment, undecided when a platform test cannot be decided
    there (the target is unknown, or it does not establish the variable)."""
    inactive: set = set()
    undecided: set = set()

    def visit(node: ast.AST, off: bool, unknown: bool) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if off:
                inactive.add(node.lineno)
            elif unknown:
                undecided.add(node.lineno)
        if isinstance(node, ast.If):
            value = platform_test(node.test, env)
            undecided_here = unknown or (value is None and _is_platform_test(node.test))
            for stmt in node.body:
                visit(stmt, off or value is False, undecided_here)
            for stmt in node.orelse:
                visit(stmt, off or value is True, undecided_here)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                visit(child, off, unknown)

    visit(tree, False, False)
    return frozenset(inactive), frozenset(undecided)


# ---------------------------------------------------------------------------
# Imports a static verdict cannot settle: they do not run (TYPE_CHECKING), or the file has
# changed the search path before they run (sys.path)
# ---------------------------------------------------------------------------

TYPE_CHECKING_ONLY = "type_checking_only"
SYS_PATH_MODIFIED = "sys_path_modified"
OUT_OF_BOUNDARY = "out_of_boundary"  # only a link out of the scan area could supply it
# A directory a sys.path change adds: its absolute path when the expression is tied to the
# file's own location, None when it is not known statically (a relative string such as "../"
# or os.getcwd() names a directory of the working directory, which the source does not fix).
AddedPath = Optional[str]

# Calls that return their one argument's path unchanged (as str or Path).
_SAME_PATH_CALLS = {"str", "fspath", "Path", "PurePath", "abspath", "realpath", "normpath"}


def _is_type_checking(test: ast.AST) -> bool:
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _is_sys_path(node: ast.AST) -> bool:
    return _attr(node, "sys", "path")


def _path_part(node: ast.AST) -> Optional[str]:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _joined(base: Optional[str], parts: Sequence[ast.AST]) -> Optional[str]:
    names = [_path_part(p) for p in parts]
    if base is None or any(n is None for n in names):
        return None
    return str(Path(base).joinpath(*[n for n in names if n is not None]))


def _anchored_path(node: ast.AST, file: Path) -> Optional[str]:
    """The path an expression names when it is built from `__file__` (Path(__file__).parent,
    os.path.dirname(__file__), joined with string constants); None for anything else."""
    if isinstance(node, ast.Name):
        return str(file) if node.id == "__file__" else None
    if isinstance(node, ast.Attribute) and node.attr == "parent":
        base = _anchored_path(node.value, file)
        return str(Path(base).parent) if base is not None else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _joined(_anchored_path(node.left, file), [node.right])
    if not isinstance(node, ast.Call) or node.keywords:
        return None
    func, args = node.func, node.args
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    if isinstance(func, ast.Attribute) and name in ("resolve", "absolute") and not args:
        return _anchored_path(func.value, file)
    if isinstance(func, ast.Attribute) and name == "joinpath":
        return _joined(_anchored_path(func.value, file), args)
    if name == "join" and args:
        return _joined(_anchored_path(args[0], file), args[1:])
    if name in _SAME_PATH_CALLS | {"dirname"} and len(args) == 1:
        base = _anchored_path(args[0], file)
        return str(Path(base).parent) if name == "dirname" and base is not None else base
    return None


def _listed(node: ast.AST, file: Path) -> Tuple[AddedPath, ...]:
    if isinstance(node, (ast.List, ast.Tuple)):
        return tuple(_anchored_path(e, file) for e in node.elts)
    return (None,)


def _added_paths(stmt: ast.stmt, file: Path) -> Optional[Tuple[AddedPath, ...]]:
    """The directories a statement adds to sys.path; None when it does not change sys.path.
    `sys.path.insert/append/extend(...)`, `sys.path += [...]`; replacing sys.path or an entry
    and `site.addsitedir(...)` (its .pth files can add more) add what is not known."""
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
        func = call.func
        if isinstance(func, ast.Attribute) and _is_sys_path(func.value):
            if func.attr == "insert" and len(call.args) == 2:
                return (_anchored_path(call.args[1], file),)
            if func.attr == "append" and len(call.args) == 1:
                return (_anchored_path(call.args[0], file),)
            if func.attr == "extend" and len(call.args) == 1:
                return _listed(call.args[0], file)
            if func.attr in ("insert", "append", "extend", "__setitem__"):
                return (None,)
        if isinstance(func, ast.Attribute) and _attr(func, "site", "addsitedir"):
            return (None,)
    if isinstance(stmt, ast.AugAssign) and _is_sys_path(stmt.target):
        return _listed(stmt.value, file)
    if isinstance(stmt, ast.Assign) and any(
        _is_sys_path(t) or (isinstance(t, ast.Subscript) and _is_sys_path(t.value))
        for t in stmt.targets
    ):
        return (None,)
    return None


def _contained_paths(stmt: ast.stmt, file: Path) -> Tuple[AddedPath, ...]:
    """What every sys.path change anywhere in the statement adds, not inside a nested function
    or class (which run later, if ever)."""
    own = _added_paths(stmt, file)
    if own is not None:
        return own
    found: Tuple[AddedPath, ...] = ()
    for child in ast.iter_child_nodes(stmt):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(child, ast.stmt):
            found += _contained_paths(child, file)
        elif isinstance(child, ast.ExceptHandler):
            for s in child.body:
                found += _contained_paths(s, file)
    return found


@dataclass(frozen=True)
class DeferredImports:
    """Import lines a static verdict cannot settle as they are.

    type_checking: under `if TYPE_CHECKING:` (or `typing.TYPE_CHECKING`); the `else` branch
      runs and is not listed.
    added_paths: imports that run after a sys.path change earlier in their own scope or an
      enclosing one (a function defined after a module-level change is called after it), with
      the directories added before them. Whether that withholds the import depends on what the
      directories could supply (patterns/python_imports.py).
    """

    type_checking: FrozenSet[int]
    added_paths: Dict[int, Tuple[AddedPath, ...]]


def deferred_imports(tree: ast.AST, file: Path) -> DeferredImports:
    typing_only: set = set()
    added: Dict[int, Tuple[AddedPath, ...]] = {}

    def block(stmts: Sequence[ast.stmt], paths: Tuple[AddedPath, ...]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If) and _is_type_checking(stmt.test):
                typing_only.update(
                    n.lineno
                    for s in stmt.body
                    for n in ast.walk(s)
                    if isinstance(n, (ast.Import, ast.ImportFrom))
                )
                block(stmt.orelse, paths)
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if paths:
                    added.setdefault(stmt.lineno, paths)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                block(stmt.body, paths)
            else:
                for field in ("body", "orelse", "finalbody"):
                    block(getattr(stmt, field, None) or [], paths)
                for handler in getattr(stmt, "handlers", None) or []:
                    block(handler.body, paths)
                paths = paths + _contained_paths(stmt, file)

    block(getattr(tree, "body", []), ())
    return DeferredImports(frozenset(typing_only), added)


# ---------------------------------------------------------------------------
# Provider knowledge
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def shipped_table() -> Dict[str, FrozenSet[str]]:
    """config/import_providers.json: normalized distribution -> import names."""
    data = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    return {normalize(k): frozenset(v) for k, v in data["providers"].items()}


@lru_cache(maxsize=1)
def shipped_audit() -> Dict[str, str]:
    """Audit state of each shipped mapping entry (ARTIFACT_VERIFIED / AUDIT_PENDING)."""
    data = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    return {
        normalize(k): str(v.get("status", "AUDIT_PENDING"))
        for k, v in data.get("audit", {}).items()
    }


_ANALYZER: Dict[State, Tuple[Dict[str, FrozenSet[str]], Dict[str, str]]] = {}


def _distribution_tops() -> Dict[str, List[str]]:
    """Top-level name -> distributions, for Python < 3.10 (no packages_distributions):
    read from each distribution's top_level.txt, else its RECORD file list."""
    import importlib.metadata as metadata

    found: Dict[str, List[str]] = {}
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        if not name:
            continue
        text = dist.read_text("top_level.txt")
        if text:
            tops = frozenset(t.strip() for t in text.splitlines() if t.strip())
        else:
            tops = _record_tops("\n".join(str(f) for f in (dist.files or [])))
        for top in tops:
            found.setdefault(top, []).append(name)
    return found


def analyzer_providers() -> Tuple[Dict[str, FrozenSet[str]], Dict[str, str]]:
    """Installed distributions of the analyzer environment -> import names, and display names.
    Mapping knowledge only (packages_distributions on Python 3.10+, the same data read from
    dist-info files before that)."""
    state = environment_state()
    if state not in _ANALYZER:
        import importlib.metadata as metadata

        names: Dict[str, set] = {}
        display: Dict[str, str] = {}
        mapping = getattr(metadata, "packages_distributions", None)
        for top, dists in (mapping() if mapping is not None else _distribution_tops()).items():
            for dist in dists:
                key = normalize(dist)
                names.setdefault(key, set()).add(top)
                display.setdefault(key, dist)
        _ANALYZER.clear()
        _ANALYZER[state] = ({k: frozenset(v) for k, v in names.items()}, display)
    return _ANALYZER[state]


@dataclass(frozen=True)
class TargetEnvironment:
    """A project's own virtual environment, read from its files."""

    path: Path
    sites: Tuple[Path, ...]
    provides: Dict[str, FrozenSet[str]]  # normalized dist -> import names
    states: Dict[str, str]  # normalized dist -> ARTIFACT_VERIFIED / METADATA_DECLARED
    display: Dict[str, str]  # normalized dist -> name as in METADATA
    versions: Dict[str, str]
    fingerprint: str
    # What the environment establishes about where the code runs, read from its files:
    # "win32" (Lib/site-packages layout) or "posix" (lib/pythonX.Y/site-packages), and the
    # Python version recorded in pyvenv.cfg. None: not established.
    platform: Optional[str] = None
    python_version: Optional[str] = None
    python_full_version: Optional[str] = None

    def has_module(self, top: str) -> bool:
        if any(top in names for names in self.provides.values()):
            return True
        for site in self.sites:
            if (site / top).is_dir() or (site / f"{top}.py").is_file():
                return True
            if any(site.glob(f"{top}.*.pyd")) or any(site.glob(f"{top}.*.so")):
                return True
        return False

    def providers_of(self, top: str) -> List[str]:
        return sorted(
            d for d, names in self.provides.items() if any(n.split(".")[0] == top for n in names)
        )


def _sites(venv: Path) -> Tuple[Path, ...]:
    found = [venv / "Lib" / "site-packages"] + sorted((venv / "lib").glob("python*/site-packages"))
    return tuple(p for p in found if p.is_dir())


def _layout_platform(venv: Path) -> Optional[str]:
    windows = (venv / "Lib" / "site-packages").is_dir()
    posix = any((venv / "lib").glob("python*/site-packages"))
    if windows != posix:
        return "win32" if windows else "posix"
    return None


def _pyvenv_versions(text: str) -> Tuple[Optional[str], Optional[str]]:
    """(major.minor, full) from pyvenv.cfg (`version_info` or `version`)."""
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() in ("version_info", "version"):
            parts = re.findall(r"\d+", value)
            if len(parts) >= 2:
                full = ".".join(parts[:3]) if len(parts) >= 3 else None
                return f"{parts[0]}.{parts[1]}", full
    return None, None


def _metadata_fields(text: str) -> Dict[str, List[str]]:
    fields: Dict[str, List[str]] = {}
    for line in text.splitlines():
        if not line.strip():
            break  # headers end at the first blank line; the body follows
        key, sep, value = line.partition(":")
        if sep:
            fields.setdefault(key.strip().lower(), []).append(value.strip())
    return fields


def _record_tops(text: str) -> FrozenSet[str]:
    tops = set()
    for line in text.splitlines():
        path = line.split(",", 1)[0].strip().replace("\\", "/")
        if not path or path.startswith("..") or "/" not in path and not path.endswith(".py"):
            continue
        first = path.split("/", 1)[0]
        if first.endswith((".dist-info", ".data")) or first == "__pycache__":
            continue
        tops.add(first[:-3] if first.endswith(".py") else first)
    return frozenset(t for t in tops if t.isidentifier())


_EVIDENCE_FILES = ("METADATA", "top_level.txt", "RECORD")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _load_environment(venv: Path, sites: Tuple[Path, ...]) -> TargetEnvironment:
    """Read every dist-info of the sites. The fingerprint is the sha256 of the bytes of every
    file the verdicts read (METADATA, top_level.txt, RECORD) with their paths, so an in-place
    edit is a different environment even when no directory name changes."""
    provides: Dict[str, FrozenSet[str]] = {}
    states: Dict[str, str] = {}
    display: Dict[str, str] = {}
    versions: Dict[str, str] = {}
    digest = hashlib.sha256(str(venv).encode("utf-8"))
    cfg = _read(venv / "pyvenv.cfg")
    digest.update(b"pyvenv.cfg" + bytes(1) + cfg.encode("utf-8") + bytes(1))
    for site in sites:
        for info in sorted(site.glob("*.dist-info")):
            texts = {name: _read(info / name) for name in _EVIDENCE_FILES}
            for name in _EVIDENCE_FILES:
                digest.update(f"{info.name}/{name}".encode("utf-8") + b"\0")
                digest.update(texts[name].encode("utf-8") + b"\0")
            if not texts["METADATA"]:
                continue
            fields = _metadata_fields(texts["METADATA"])
            name = (fields.get("name") or [info.name.split("-")[0]])[0]
            key = normalize(name)
            declared = [
                v.split(";", 1)[0].strip()
                for v in fields.get("import-name", []) + fields.get("import-namespace", [])
            ]
            declared = [v for v in declared if v]
            if declared:
                provides[key], states[key] = frozenset(declared), METADATA_DECLARED
            else:
                tops = frozenset(
                    t.strip() for t in texts["top_level.txt"].splitlines() if t.strip()
                ) or _record_tops(texts["RECORD"])
                provides[key], states[key] = tops, ARTIFACT_VERIFIED
            display[key] = name
            versions[key] = (fields.get("version") or [""])[0]
    python_version, python_full_version = _pyvenv_versions(cfg)
    return TargetEnvironment(
        venv,
        sites,
        provides,
        states,
        display,
        versions,
        digest.hexdigest(),
        _layout_platform(venv),
        python_version,
        python_full_version,
    )


def _stat_signature(
    sites: Tuple[Path, ...], cfg: Path
) -> Optional[Tuple[Tuple[str, int, int], ...]]:
    """Cheap identity of every file _load_environment reads: (path, mtime_ns, size). None
    when any of them changed within RACY_NS: its mtime may not move on the next edit, so
    the environment is read again instead of served from the cache."""
    now = time.time_ns()
    entries = []
    try:
        st = cfg.stat()
    except OSError:
        return None
    if now - st.st_mtime_ns < RACY_NS:
        return None
    entries.append((str(cfg), st.st_mtime_ns, st.st_size))
    for site in sites:
        try:
            entries.append((str(site), site.stat().st_mtime_ns, 0))
            for info in sorted(site.glob("*.dist-info")):
                for name in _EVIDENCE_FILES:
                    path = info / name
                    if path.is_file():
                        st = path.stat()
                        if now - st.st_mtime_ns < RACY_NS:
                            return None
                        entries.append((str(path), st.st_mtime_ns, st.st_size))
        except OSError:
            return None
    return tuple(entries)


_TARGET_CACHE: Dict[Tuple[str, Tuple[Tuple[str, int, int], ...]], TargetEnvironment] = {}


# Directory names a project environment conventionally has. A link out of the scan area is not
# read, so whether it holds pyvenv.cfg is not known; under one of these names it is taken to be the
# project's environment, left unread (patterns/python_imports.py: no verdict rests on presence).
_ENVIRONMENT_NAMES = frozenset({".venv", "venv", "env", ".env", "virtualenv"})


def unread_environment_links(roots: Iterable[Path]) -> Tuple[Path, ...]:
    """Links out of the scan area, named like a virtual environment, directly in the roots."""
    found: List[Path] = []
    for root in roots:
        boundary = walk_boundary(root)
        found.extend(
            root / name for name in sorted(_ENVIRONMENT_NAMES) if leaves(root / name, boundary)
        )
    return tuple(found)


def find_target_environment(roots: Iterable[Path]) -> Optional[TargetEnvironment]:
    """The first virtual environment directly inside one of the roots, or None."""
    for root in roots:
        try:
            boundary = walk_boundary(root)
            children = sorted(
                p
                for p in root.iterdir()
                if not leaves(p, boundary) and p.is_dir() and (p / "pyvenv.cfg").is_file()
            )
        except OSError:
            continue
        for venv in children:
            sites = _sites(venv)
            if not sites:
                continue
            signature = _stat_signature(sites, venv / "pyvenv.cfg")
            if signature is None:
                return _load_environment(venv, sites)
            key = (str(venv), signature)
            if key not in _TARGET_CACHE:
                _TARGET_CACHE[key] = _load_environment(venv, sites)
            return _TARGET_CACHE[key]
    return None


def candidate_names(written: str) -> FrozenSet[str]:
    """Rank 5: names a distribution might provide, derived from its name alone."""
    exact = written.replace("-", "_").replace(".", "_")
    canon = exact.lower()
    names = {exact, canon, normalize(written).replace("-", ".")}
    for prefix in _PREFIXES:
        if canon.startswith(prefix) and len(canon) > len(prefix) + 1:
            names.add(canon[len(prefix) :])
    return frozenset(names)


def provides(names: Iterable[str], module: str, members: Sequence[str] = ()) -> bool:
    """Whether provided import names cover `module` (or `module.member`): exact, case-sensitive;
    a dotted name covers itself and its submodules."""
    targets = {module} | {f"{module}.{m}" for m in members}
    top = module.split(".")[0]
    for name in names:
        if "." in name:
            if any(t == name or t.startswith(name + ".") for t in targets):
                return True
        elif name == top:
            return True
    return False


@dataclass(frozen=True)
class ProviderView:
    names: FrozenSet[str]
    state: str
    display: str
    mapping_audit: Optional[str] = None  # set when the names come from the shipped mapping


class ProviderKnowledge:
    """What is known about which distribution provides what, for one file's analysis."""

    def __init__(self, target: Optional[TargetEnvironment]) -> None:
        self.target = target
        self.environment = "target" if target is not None else "analyzer"
        self._analyzer, self._analyzer_display = analyzer_providers()

    def view(self, req: Requirement) -> ProviderView:
        """The import names a declared distribution provides, with the strongest evidence."""
        key = req.dist
        if self.target is not None and key in self.target.provides:
            return ProviderView(self.target.provides[key], self.target.states[key], req.written)
        if key in self._analyzer:
            return ProviderView(self._analyzer[key], MAPPING_SUPPORTED, req.written)
        table = shipped_table()
        if key in table:
            audit = shipped_audit().get(key, "AUDIT_PENDING")
            return ProviderView(table[key], MAPPING_SUPPORTED, req.written, audit)
        return ProviderView(candidate_names(req.written), NAME_CANDIDATE, req.written)

    def known_providers(self, module: str, members: Sequence[str] = ()) -> List[Tuple[str, str]]:
        """(display name, state) of distributions known (ranks 1-4) to provide `module`."""
        found: Dict[str, Tuple[str, str]] = {}
        if self.target is not None:
            for key, names in self.target.provides.items():
                if provides(names, module, members):
                    found[key] = (self.target.display[key], self.target.states[key])
        for key, names in self._analyzer.items():
            if key not in found and provides(names, module, members):
                found[key] = (self._analyzer_display.get(key, key), MAPPING_SUPPORTED)
        for key, names in shipped_table().items():
            if key not in found and provides(names, module, members):
                found[key] = (key, MAPPING_SUPPORTED)
        return [found[k] for k in sorted(found)]

    def mapping_audit_of(self, provider: Optional[str]) -> Optional[str]:
        """Audit state when `provider` is known from the shipped mapping only (not the target
        environment, not the analyzer's installed metadata); None otherwise."""
        if provider is None:
            return None
        key = normalize(provider)
        if self.target is not None and key in self.target.provides:
            return None
        if key in self._analyzer or key not in shipped_table():
            return None
        return shipped_audit().get(key, "AUDIT_PENDING")

    def installed_provider(self, top: str) -> List[str]:
        """Normalized distributions that supply the importable `top` where the code is checked:
        the target environment's when there is one (the analyzer's installs are not evidence
        about the target), else the analyzer's."""
        if self.target is not None:
            return self.target.providers_of(top) if self.target.has_module(top) else []
        return sorted(k for k, names in self._analyzer.items() if top in names)

    def display_of(self, key: str) -> str:
        if self.target is not None and key in self.target.display:
            return self.target.display[key]
        return self._analyzer_display.get(key, key)

    def version_of(self, key: str) -> str:
        if self.target is not None and key in self.target.versions:
            return self.target.versions[key]
        try:
            import importlib.metadata as metadata

            return metadata.version(self._analyzer_display.get(key, key))
        except Exception:  # broken metadata only removes detail from a message
            return ""


def evidence(
    import_name: str, provider: Optional[str], state: str, environment: str
) -> Dict[str, object]:
    return {
        "import_name": import_name,
        "provider": provider,
        "provider_state": state,
        "environment": environment,
    }
