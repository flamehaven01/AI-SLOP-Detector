"""Static verification of names imported from installed (external) packages.

The target is never imported or executed. The top-level package is located with
the import system's finders, which do not run it, over the analyzer's environment
(slop_detector.environment_resolution), and only source files are read.
Each requested module or name is one of:

    present  source evidence shows it exists
    absent   source evidence shows it does not exist (phantom_member)
    unknown  absence cannot be shown statically (unverified_imports, no score)

Anything the static view cannot settle (no Python source, module __getattr__,
star re-export, conditional or dynamic definitions) is unknown, never absent.
"""

from __future__ import annotations

import ast
import importlib.machinery
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Iterator, List, Optional, Sequence, Set, Tuple

from slop_detector.analysis.import_graph import _bound_names, _iter_imports
from slop_detector.environment_resolution import find_installed_spec, search_path

VERIFICATION_BASIS = "source_static_analysis"

PRESENT = "present"
ABSENT = "absent"
UNKNOWN = "unknown"

_EXTENSIONS = tuple(importlib.machinery.EXTENSION_SUFFIXES)
_DYNAMIC_CALLS = frozenset({"globals", "vars", "exec"})
_IMPORT_HOOKS = frozenset({"meta_path", "path_hooks"})


@dataclass(frozen=True)
class Outcome:
    state: str
    reason: str = ""


@dataclass(frozen=True)
class _Module:
    dotted: str
    kind: str  # "package" | "module" | "namespace" | "opaque"
    source: Optional[Path] = None  # file whose top level defines the attributes
    search: Tuple[Path, ...] = ()  # directories holding submodules
    reason: str = ""  # why an opaque module cannot be read


@dataclass(frozen=True)
class _Scope:
    bound: FrozenSet[str]
    conditional: FrozenSet[str]
    all_names: FrozenSet[str]
    sys_modules: FrozenSet[str]  # literal keys assigned into sys.modules
    getattr: bool
    star: bool
    dynamic: bool


@dataclass(frozen=True)
class Finding:
    line: int
    column: int
    module: str
    name: Optional[str]  # None when the module itself is absent


# ---------------------------------------------------------------------------
# Locating modules without importing them
# ---------------------------------------------------------------------------


def _source_of(spec) -> Optional[Path]:
    origin = spec.origin
    if origin == "frozen":
        origin = getattr(spec.loader_state, "filename", None)
    if origin and str(origin).endswith(".py") and Path(origin).is_file():
        return Path(origin)
    return None


_TOP_LEVEL: Dict[Tuple[str, Tuple[str, ...]], Optional[_Module]] = {}


def top_level(name: str, excluded: Sequence[Path] = ()) -> Optional[_Module]:
    """The installed top-level module `name`, or None; cached per search path.

    Looked up in the analyzer's environment, never in its cwd or the `excluded`
    project roots (slop_detector.environment_resolution).
    """
    key = (name, search_path(excluded))
    if key not in _TOP_LEVEL:
        _TOP_LEVEL[key] = _find_top_level(name, excluded)
    return _TOP_LEVEL[key]


def _find_top_level(name: str, excluded: Sequence[Path]) -> Optional[_Module]:
    try:
        spec = find_installed_spec(name, excluded)
    except (ImportError, ValueError, AttributeError):
        return _Module(name, "opaque", reason="no_python_source")
    if spec is None:
        return None
    search = tuple(Path(p) for p in (spec.submodule_search_locations or ()))
    if spec.submodule_search_locations is not None and spec.origin in (None, "namespace"):
        return _Module(name, "namespace", search=search)
    source = _source_of(spec)
    if source is None:
        return _Module(name, "opaque", reason="no_python_source")
    kind = "package" if spec.submodule_search_locations is not None else "module"
    return _Module(name, kind, source=source, search=search)


def _file_child(dotted: str, directory: Path, name: str) -> Optional[_Module]:
    package = directory / name
    if (package / "__init__.py").is_file():
        return _Module(dotted, "package", source=package / "__init__.py", search=(package,))
    if package.is_dir() and any(package.glob("__init__.*")):
        return _Module(dotted, "opaque", reason="no_python_source")
    if any((directory / f"{name}{suffix}").is_file() for suffix in _EXTENSIONS):
        return _Module(dotted, "opaque", reason="no_python_source")
    if (directory / f"{name}.py").is_file():
        return _Module(dotted, "module", source=directory / f"{name}.py")
    if (directory / f"{name}.pyc").is_file():
        return _Module(dotted, "opaque", reason="no_python_source")
    return None


def child(parent: _Module, name: str) -> Optional[_Module]:
    """A file-backed submodule of `parent`, in CPython finder order."""
    dotted = f"{parent.dotted}.{name}"
    portions: List[Path] = []
    for directory in parent.search:
        found = _file_child(dotted, directory, name)
        if found is not None:
            return found
        if (directory / name).is_dir() and name.isidentifier():
            portions.append(directory / name)
    return _Module(dotted, "namespace", search=tuple(portions)) if portions else None


# ---------------------------------------------------------------------------
# Static view of a module's top-level namespace
# ---------------------------------------------------------------------------


def _all_names(stmt: ast.stmt) -> Set[str]:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [getattr(stmt, "target", None)]
    if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
        return set()
    value = getattr(stmt, "value", None)
    if isinstance(value, (ast.List, ast.Tuple)):
        return {
            e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
        }
    return set()


def _is_sys_modules(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "modules"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    )


def _sys_modules_key(node: ast.AST) -> Tuple[Optional[str], bool]:
    """(literal key, dynamic) for `sys.modules[...] = ...` targets."""
    if isinstance(node, ast.Subscript) and _is_sys_modules(node.value):
        key = node.slice
        index = getattr(ast, "Index", None)  # Python 3.8 wraps the key
        if index is not None and isinstance(key, index):
            key = getattr(key, "value", key)
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value, False
        return None, True
    return None, False


def _is_dynamic(node: ast.AST) -> bool:
    """Namespace changes a static read cannot follow."""
    if isinstance(node, ast.Call):
        return _is_dynamic_call(node) or _is_sys_modules_mutation(node)
    return _is_import_hook(node)


def _is_dynamic_call(node: ast.Call) -> bool:
    """globals(), vars(), exec(), or setattr(sys.modules[...], ...)."""
    if not isinstance(node.func, ast.Name):
        return False
    if node.func.id in _DYNAMIC_CALLS:
        return True
    return node.func.id == "setattr" and bool(node.args) and _is_sys_modules_lookup(node.args[0])


def _is_import_hook(node: ast.AST) -> bool:
    """sys.meta_path or sys.path_hooks: a custom finder can supply any module."""
    if not (isinstance(node, ast.Attribute) and node.attr in _IMPORT_HOOKS):
        return False
    return isinstance(node.value, ast.Name) and node.value.id == "sys"


def _is_sys_modules_lookup(node: ast.AST) -> bool:
    return isinstance(node, ast.Subscript) and _is_sys_modules(node.value)


def _is_sys_modules_mutation(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in {"update", "setdefault"}
        and (_is_sys_modules(func.value))
    )


def _sys_modules_assignments(tree: ast.Module) -> Tuple[Set[str], bool]:
    literal: Set[str] = set()
    dynamic = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                key, is_dynamic = _sys_modules_key(target)
                dynamic = dynamic or is_dynamic
                if key:
                    literal.add(key)
    return literal, dynamic


def _top_level_bindings(tree: ast.Module, package_name: str):
    bound: Set[str] = set()
    conditional: Set[str] = set()
    all_names: Set[str] = set()
    getattr_hook = star = False
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "__getattr__":
            getattr_hook = True
        if isinstance(stmt, ast.ImportFrom) and any(a.name == "*" for a in stmt.names):
            star = True
            continue
        all_names |= _all_names(stmt)
        if isinstance(stmt, (ast.If, ast.Try, ast.For, ast.While, ast.With, ast.AsyncWith)):
            conditional |= _names_inside(stmt, package_name)
            star = star or _has_star(stmt)
            continue
        sub, mem = _bound_names(stmt, package_name)
        bound |= sub | mem
    return bound, conditional, all_names, getattr_hook, star


def _names_inside(block: ast.stmt, package_name: str) -> Set[str]:
    names: Set[str] = set()
    for stmt in ast.walk(block):
        if isinstance(stmt, ast.stmt) and stmt is not block:
            sub, mem = _bound_names(stmt, package_name)
            names |= sub | mem
    return names


def _has_star(block: ast.stmt) -> bool:
    return any(
        isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names)
        for node in ast.walk(block)
    )


_SCOPES: Dict[Tuple[Path, int], Optional[_Scope]] = {}


def scope(path: Path) -> Optional[_Scope]:
    """Static top-level namespace of one source file; None when it cannot be parsed.

    Cached per (path, mtime), so an upgraded package is read again.
    """
    try:
        key = (path, path.stat().st_mtime_ns)
    except OSError:
        return None
    if key not in _SCOPES:
        _SCOPES[key] = _read_scope(path)
    return _SCOPES[key]


def _read_scope(path: Path) -> Optional[_Scope]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None
    package_name = path.parent.name if path.name == "__init__.py" else path.stem
    bound, conditional, all_names, getattr_hook, star = _top_level_bindings(tree, package_name)
    literal, sys_dynamic = _sys_modules_assignments(tree)
    dynamic = sys_dynamic or any(_is_dynamic(node) for node in ast.walk(tree))
    return _Scope(
        bound=frozenset(bound),
        conditional=frozenset(conditional - bound),
        all_names=frozenset(all_names),
        sys_modules=frozenset(literal),
        getattr=getattr_hook,
        star=star,
        dynamic=dynamic,
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _virtual_or_absent(parent: _Module, name: str) -> Tuple[Optional[_Module], Outcome]:
    """A requested submodule with no file: registered in sys.modules, unknown, or absent."""
    if parent.kind == "namespace":
        # Open set: any installed or not-installed distribution can add a portion.
        return None, Outcome(UNKNOWN, "namespace_portion_not_installed")
    view = scope(parent.source) if parent.source else None
    dotted = f"{parent.dotted}.{name}"
    if view is None:
        return None, Outcome(UNKNOWN, parent.reason or "no_python_source")
    if dotted in view.sys_modules:
        alias = _Module(dotted, "opaque", reason="runtime_dependent_alias")
        return alias, Outcome(PRESENT)
    if view.dynamic:
        return None, Outcome(UNKNOWN, "dynamic_namespace")
    return None, Outcome(ABSENT)


def resolve_module(dotted: str, excluded: Sequence[Path] = ()) -> Tuple[Optional[_Module], Outcome]:
    """Walk `a.b.c` from the installed top level; never imports anything."""
    parts = dotted.split(".")
    module = top_level(parts[0], excluded)
    if module is None:
        return None, Outcome(UNKNOWN, "not_installed")
    for name in parts[1:]:
        if module.kind == "opaque":
            return None, Outcome(UNKNOWN, module.reason)
        found = child(module, name)
        if found is None:
            found, outcome = _virtual_or_absent(module, name)
            if found is None:
                return None, outcome
        module = found
    return module, Outcome(PRESENT)


def member(module: _Module, name: str) -> Outcome:
    """Whether `from <module> import <name>` can succeed, from source evidence."""
    if module.kind == "opaque":
        return Outcome(UNKNOWN, module.reason)
    if module.kind in ("package", "namespace") and child(module, name) is not None:
        return Outcome(PRESENT)
    if module.kind == "namespace":
        return Outcome(UNKNOWN, "namespace_portion_not_installed")
    view = scope(module.source) if module.source else None
    if view is None:
        return Outcome(UNKNOWN, "no_python_source")
    return _member_in_scope(view, f"{module.dotted}.{name}", name)


def _member_in_scope(view: _Scope, dotted: str, name: str) -> Outcome:
    if name in view.bound or dotted in view.sys_modules:
        return Outcome(PRESENT)
    for flag, reason in (
        (name in view.conditional, "conditional_definition"),
        (view.getattr, "module_getattr"),
        (view.star, "star_reexport"),
        (view.dynamic, "dynamic_namespace"),
        (name in view.all_names, "declared_in_all_only"),
    ):
        if flag:
            return Outcome(UNKNOWN, reason)
    return Outcome(ABSENT)


# ---------------------------------------------------------------------------
# Whole-file verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileVerification:
    findings: Tuple[Finding, ...]
    unknowns: Tuple[Dict[str, object], ...]


def _requests(node: ast.AST) -> Iterator[Tuple[str, Optional[str]]]:
    """(module, name) pairs one import statement asks for; name None for `import a.b`."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name, None
    elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
        for alias in node.names:
            if alias.name != "*":
                yield node.module, alias.name


def _check(
    module_name: str, name: Optional[str], excluded: Sequence[Path]
) -> Tuple[Outcome, Optional[str]]:
    """Outcome, and the missing name (None when the module itself is the subject)."""
    module, outcome = resolve_module(module_name, excluded)
    if module is None or name is None:
        return outcome, None
    return member(module, name), name


def verify_imports(
    tree: ast.Module,
    skip_top: FrozenSet[str],
    guarded_lines: FrozenSet[int],
    skip_module: Callable[[str, List[str]], bool] = lambda dotted, names: False,
    excluded: Sequence[Path] = (),
) -> FileVerification:
    """Verify every absolute import of an installed, non-project top-level package."""
    findings: List[Finding] = []
    unknowns: List[Dict[str, object]] = []
    for node, type_only, _deferred in _iter_imports(tree.body, False, False):
        line = getattr(node, "lineno", 0)
        if line in guarded_lines:
            continue
        for module_name, name in _requests(node):
            top = module_name.split(".")[0]
            if top in skip_top or skip_module(module_name, [name] if name else []):
                continue
            if top_level(top, excluded) is None:
                continue  # not installed: phantom_import's case
            outcome, subject = _check(module_name, name, excluded)
            if outcome.state == ABSENT and type_only:
                outcome = Outcome(UNKNOWN, "type_checking_only")
            _record(outcome, node, module_name, name, subject, findings, unknowns)
    return FileVerification(tuple(findings), tuple(unknowns))


def _record(
    outcome: Outcome,
    node: ast.AST,
    module_name: str,
    name: Optional[str],
    subject: Optional[str],
    findings: List[Finding],
    unknowns: List[Dict[str, object]],
) -> None:
    line = getattr(node, "lineno", 0)
    if outcome.state == ABSENT:
        findings.append(Finding(line, getattr(node, "col_offset", 0), module_name, subject))
    elif outcome.state == UNKNOWN:
        unknowns.append(_unknown_row(line, module_name, name, outcome.reason))


def guarded_import_lines(tree: ast.AST, is_import_guard: Callable[[ast.ExceptHandler], bool]):
    """Imports that are probes or fallbacks, not claims, in one walk of the tree.

    Imports in the body of a try whose handler catches ImportError, and imports
    inside any except branch (version or platform fallbacks).
    """
    lines: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        if any(is_import_guard(h) for h in node.handlers):
            lines.update(s.lineno for s in node.body if isinstance(s, (ast.Import, ast.ImportFrom)))
        for handler in node.handlers:
            lines.update(
                n.lineno for n in ast.walk(handler) if isinstance(n, (ast.Import, ast.ImportFrom))
            )
    return frozenset(lines)


def _unknown_row(line: int, module: str, name: Optional[str], reason: str) -> Dict[str, object]:
    return {
        "line": line,
        "requested_module": module,
        "requested_name": name,
        "evidence_state": UNKNOWN,
        "reason": reason,
        "score_effect": "none",
        "verification_basis": VERIFICATION_BASIS,
    }


def clear_caches() -> None:
    _SCOPES.clear()
    _TOP_LEVEL.clear()


@lru_cache(maxsize=1)
def _distributions() -> Dict[str, Sequence[str]]:
    """Top-level name -> distributions (Python 3.10+; empty mapping before that)."""
    import importlib.metadata as metadata

    mapping = getattr(metadata, "packages_distributions", None)
    return dict(mapping()) if mapping is not None else {}


def _version(distribution: str) -> str:
    """Installed version, or "" when the metadata cannot be read."""
    import importlib.metadata as metadata

    try:
        return metadata.version(distribution)
    except Exception:  # broken metadata only removes detail from the message
        return ""


def describe_installed(top: str) -> str:
    """Which installed code the verdict was checked against; never imports `top`."""
    import sys

    if top in getattr(sys, "stdlib_module_names", ()):
        return f"the standard library of Python {sys.version.split()[0]}"
    dists = _distributions().get(top, [])
    if dists:
        return f"installed {dists[0]} {_version(dists[0])}".rstrip()
    return f"installed '{top}'"
