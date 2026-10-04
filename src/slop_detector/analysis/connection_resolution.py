"""Name resolution for connection evidence: modules, import bindings, gaps.

Reads the files a connection pass covers, binds every import to what it names
(using the import graph's resolution), follows re-exports, and records where
evidence could not be collected (a gap). A gap with a scope concerns only
symbols defined in one of its files or directories, so an unresolved import
that cannot name a symbol leaves that symbol alone.

Also resolves pyproject scripts and entry points to symbols. The evidence
passes are in connection_collectors; states and the report block in
connection_evidence.
"""

from __future__ import annotations

import ast
import builtins
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from slop_detector.analysis.import_graph import ImportEdge, build_import_edges
from slop_detector.path_facts import DEFAULT_EXCLUDE_PARTS, path_facts
from slop_detector.project_resolution import (
    HARD_AUTHORITIES,
    ProjectModuleIndex,
    load_pyproject,
    probe_module,
)

MAX_HOPS = 8  # re-export chain depth

_GAP_STATES = frozenset({"conditional_internal", "ambiguous", "unresolved_internal"})
BUILTINS = frozenset(dir(builtins))

Site = Tuple[str, int]
Def = Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]
Scope = Optional[Tuple[Path, ...]]  # files/directories a gap concerns; None = anywhere
Gaps = Dict[str, List[Tuple[str, Scope]]]  # name -> (reason, scope)
# A binding target: ("symbols", syms) | ("module", path) | ("member", path, name)
#                   | ("dotted", dotted, target) | ("gap", names, reason, scope)
Target = Tuple[Any, ...]


@dataclass
class Symbol:
    """One top-level function or class and the evidence collected for it."""

    file: Path
    name: str
    kind: str
    line: int
    evidence: Dict[str, List[Site]] = field(default_factory=dict)
    dynamic: List[str] = field(default_factory=list)
    unmeasured: List[str] = field(default_factory=list)
    test_referenced: bool = False


@dataclass
class Module:
    path: Path
    tree: ast.Module
    is_test: bool
    candidate_source: bool
    defs: Dict[str, List[Symbol]] = field(default_factory=dict)
    bindings: Dict[str, List[Target]] = field(default_factory=dict)
    stars: List[Target] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def top_level_defs(tree: ast.Module) -> List[Def]:
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def last_name(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else None


def name_chain(node: ast.expr) -> Optional[List[str]]:
    """`a.b.c` -> ['a', 'b', 'c']; None when the base is not a plain name."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return [node.id] + parts[::-1]


def module_level(tree: ast.Module) -> Iterable[ast.stmt]:
    """Top-level statements, including those inside top-level if/try blocks."""
    stack = list(tree.body)
    while stack:
        stmt = stack.pop(0)
        yield stmt
        if isinstance(stmt, (ast.If, ast.Try)):
            stack[:0] = [*stmt.body, *getattr(stmt, "handlers", ()), *stmt.orelse]
            stack[:0] = list(getattr(stmt, "finalbody", ()))
        elif isinstance(stmt, ast.ExceptHandler):
            stack[:0] = list(stmt.body)


def all_assignments(tree: ast.Module) -> Iterator[ast.stmt]:
    for stmt in module_level(tree):
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else getattr(stmt, "target", None)
        if isinstance(target, ast.Name) and target.id == "__all__":
            yield stmt


def dunder_all(tree: ast.Module) -> List[Tuple[str, int]]:
    names: List[Tuple[str, int]] = []
    for stmt in all_assignments(tree):
        value = getattr(stmt, "value", None)
        if isinstance(value, (ast.List, ast.Tuple)):
            names.extend(
                (elt.value, stmt.lineno)
                for elt in value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            )
    return names


def _dirs_below(path: Path, root: Path) -> List[Path]:
    """Directories holding `path`, nearest first, strictly below `root`."""
    return [d for d in path.parents if d != root and root in d.parents]


# ---------------------------------------------------------------------------
# Collector: modules, import bindings, name resolution
# ---------------------------------------------------------------------------


class Collector:
    def __init__(self, root: Path, edges: Sequence[ImportEdge]) -> None:
        self.root = root
        self.index = ProjectModuleIndex(root)
        self.modules: Dict[Path, Module] = {}
        self.edges: Dict[Tuple[str, int, str, int], List[ImportEdge]] = {}
        self.unresolved: List[Dict[str, Any]] = []
        self.unparsed: Dict[Path, str] = {}
        self.config_files = 0  # configuration files read for external references
        self.escaped: Dict[Path, str] = {}  # module objects used as values
        self.package_parents: Dict[str, List[Path]] = {}
        self._unrooted_cache: Dict[Tuple[Path, str], Tuple[Path, ...]] = {}
        self.add_edges(edges)

    def add_edges(self, edges: Sequence[ImportEdge]) -> None:
        for edge in edges:
            key = (edge.importer, edge.line, edge.requested_module, edge.relative_level)
            self.edges.setdefault(key, []).append(edge)

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def site(self, path: Path, line: int) -> Site:
        return self.rel(path), line

    # -- modules and bindings ------------------------------------------------

    def add_module(self, path: Path, tree: ast.Module, candidate_source: bool) -> None:
        is_test = bool(path_facts(path, self.root).is_test)
        module = Module(path, tree, is_test, candidate_source and not is_test)
        for node in top_level_defs(tree):
            # Names defined in a non-candidate file still resolve (a re-export may
            # pass through); they just are not candidates.
            group = module.defs.setdefault(node.name, [])
            if module.candidate_source:
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                group.append(Symbol(path, node.name, kind, node.lineno))
        self.modules[path] = module

    def bind_all(self) -> None:
        self._index_package_dirs()
        for module in self.modules.values():
            for node in ast.walk(module.tree):
                if isinstance(node, ast.Import):
                    self._bind_import(module, node)
                elif isinstance(node, ast.ImportFrom):
                    self._bind_from(module, node)

    def _index_package_dirs(self) -> None:
        """Package directory name -> its parents, for plugin-style imports."""
        for path in self.modules:
            for directory in _dirs_below(path, self.root):
                if not (directory / "__init__.py").is_file():
                    continue
                parents = self.package_parents.setdefault(directory.name, [])
                if directory.parent not in parents:
                    parents.append(directory.parent)

    def _gap(self, path: Path, line: int, names: Tuple[str, ...]) -> Target:
        return ("gap", names, f"unresolved_import:{self.rel(path)}:{line}", None)

    def _unrooted(self, importer: Path, dotted: str) -> Tuple[Path, ...]:
        """Where an `external` import may land if part of the project is on sys.path.

        Each directory from the importer's own up to the root (scripts run in
        place, app roots), and the parent of every package directory of that
        name elsewhere in the project (an installed plugin). Every file,
        package directory, or namespace directory found, except the importer
        itself; empty when nothing in the project carries the name.
        """
        key = (importer.parent, dotted)
        if key not in self._unrooted_cache:
            parts = [p for p in dotted.split(".") if p]
            bases = [d for d in importer.parents if d == self.root or self.root in d.parents]
            bases += self.package_parents.get(parts[0], []) if parts else []
            scopes: List[Path] = []
            for base in bases:
                hit = probe_module(base, parts) or probe_module(base, parts[:1])
                scope = None if hit is None else hit[0].parent if hit[1] == "package" else hit[0]
                if scope is not None and scope not in scopes:
                    scopes.append(scope)
            self._unrooted_cache[key] = tuple(scopes)
        return tuple(s for s in self._unrooted_cache[key] if s != importer)

    def _edge_target(self, module: Module, edge: ImportEdge, name: str) -> Optional[Target]:
        if edge.resolution_state in _GAP_STATES:
            return self._gap(module.path, edge.line, (name,))
        if edge.resolution_state == "external":
            scopes = self._unrooted(module.path, edge.requested_module)
            if not scopes:
                return None
            return ("gap", (name,), f"unrooted_import:{self.rel(module.path)}:{edge.line}", scopes)
        if edge.resolution_state != "resolved" or edge.imported is None:
            return None
        return ("module", Path(edge.imported))

    def _bind_import(self, module: Module, node: ast.Import) -> None:
        for alias in node.names:
            key = (str(module.path), node.lineno, alias.name, 0)
            edge = next(iter(self.edges.get(key, ())), None)
            last = alias.name.split(".")[-1]
            target = self._edge_target(module, edge, last) if edge else None
            if alias.asname:
                if target is not None:
                    module.bindings.setdefault(alias.asname, []).append(target)
                continue
            head = alias.name.split(".")[0]
            module.bindings.setdefault(head, []).append(("dotted", alias.name, target))

    def _bind_from(self, module: Module, node: ast.ImportFrom) -> None:
        key = (str(module.path), node.lineno, node.module or "", node.level or 0)
        edges = self.edges.get(key, [])
        for alias in node.names:
            if alias.name == "*":
                self._bind_star(module, edges)
                continue
            target = self._from_target(module, node.lineno, edges, alias.name)
            if target is not None:
                module.bindings.setdefault(alias.asname or alias.name, []).append(target)

    def _bind_star(self, module: Module, edges: List[ImportEdge]) -> None:
        whole = next((e for e in edges if e.requested_name is None), None)
        star = self._edge_target(module, whole, "*") if whole else None
        if star is not None:
            module.stars.append(star)

    def _from_target(
        self, module: Module, line: int, edges: List[ImportEdge], name: str
    ) -> Optional[Target]:
        """What `from x import name` binds, from the edges of that statement."""
        named = [e for e in edges if e.requested_name == name]
        if named:
            if any(e.resolution_state in _GAP_STATES for e in named):
                return self._gap(module.path, line, (name,))
            edge = named[0]
            if edge.resolution_state != "resolved" or edge.imported is None:
                return None
            path = Path(edge.imported)
            return (
                ("member", path, name) if edge.target_kind == "package_member" else ("module", path)
            )
        if not edges:
            return None
        whole = edges[0]
        if whole.resolution_state == "resolved" and whole.imported is not None:
            return ("member", Path(whole.imported), name)
        return self._edge_target(module, whole, name)

    # -- resolution ----------------------------------------------------------

    def resolve_name(self, path: Path, name: str, depth: int = 0) -> List[Target]:
        """What `name` means at module level of `path`, following re-exports."""
        module = self.modules.get(path)
        if module is None or depth > MAX_HOPS:
            return []
        if name in module.defs:
            return [("symbols", tuple(module.defs[name]))]
        out: List[Target] = []
        for binding in module.bindings.get(name, ()):
            out.extend(self._follow(path, name, binding, depth))
        return out or self._through_stars(module, name, depth)

    def _follow(self, path: Path, name: str, binding: Target, depth: int) -> List[Target]:
        if binding[0] == "dotted":
            return []
        if binding[0] != "member":
            return [binding]
        # `from pkg import x` inside pkg/__init__.py binds its own submodule.
        own = binding[1] == path and binding[2] == name
        found = [] if own else self.resolve_name(binding[1], binding[2], depth + 1)
        return found or self._submodule(binding[1], binding[2])

    def _through_stars(self, module: Module, name: str, depth: int) -> List[Target]:
        out: List[Target] = []
        for star in module.stars:
            if star[0] == "gap":
                out.append(("gap", (name,), star[2], star[3]))
            elif star[0] == "module":
                out.extend(self.resolve_name(star[1], name, depth + 1))
        return out

    def _submodule(self, path: Path, part: str) -> List[Target]:
        """Submodule `part` of the package whose `__init__.py` is `path`."""
        if path.name != "__init__.py":
            return []
        for candidate in (path.parent / f"{part}.py", path.parent / part / "__init__.py"):
            if candidate in self.modules:
                return [("module", candidate)]
        return []

    def resolve_chain(self, module: Module, parts: List[str]) -> List[Tuple[Target, int]]:
        """Targets reached by a name chain, with how many parts were consumed."""
        return [self._advance(target, used, parts) for target, used in self._starts(module, parts)]

    def _starts(self, module: Module, parts: List[str]) -> List[Tuple[Target, int]]:
        starts: List[Tuple[Target, int]] = []
        dotted = _dotted_start(module, parts)
        if dotted is not None:
            starts.append(dotted)
        starts.extend((t, 1) for t in self.resolve_name(module.path, parts[0]))
        if not starts and parts[0] not in BUILTINS:
            gaps = [s for s in module.stars if s[0] == "gap"]
            starts.extend((("gap", (parts[0],), s[2], s[3]), 1) for s in gaps)
        return starts

    def _advance(self, target: Target, used: int, parts: List[str]) -> Tuple[Target, int]:
        """Walk the remaining parts: a module attribute first, then a submodule."""
        while target[0] == "module" and used < len(parts):
            nxt = self.resolve_name(target[1], parts[used]) or self._submodule(
                target[1], parts[used]
            )
            if not nxt:
                break
            target, used = nxt[0], used + 1
        if target[0] == "gap" and used < len(parts):
            target = ("gap", target[1] + (parts[used],), target[2], target[3])
        return target, used


def _dotted_start(module: Module, parts: List[str]) -> Optional[Tuple[Target, int]]:
    """The longest resolvable `import a.b.c` whose dotted name prefixes the chain."""
    best: Optional[Tuple[Target, int]] = None
    for binding in module.bindings.get(parts[0], ()):
        if binding[0] != "dotted" or binding[2] is None:
            continue
        dotted = binding[1].split(".")
        if parts[: len(dotted)] == dotted and (best is None or len(dotted) > best[1]):
            best = (binding[2], len(dotted))
    return best


# ---------------------------------------------------------------------------
# Gaps and marking
# ---------------------------------------------------------------------------


def record_gap(target: Target, gaps: Gaps) -> None:
    for name in target[1]:
        gaps.setdefault(name, []).append((target[2], target[3]))


def mark(targets: List[Target], kind: str, site: Site, gaps: Gaps) -> List[Target]:
    """Add `kind` evidence to every symbol reached; a gap reached is recorded."""
    for target in targets:
        if target[0] == "symbols":
            for symbol in target[1]:
                symbol.evidence.setdefault(kind, []).append(site)
        elif target[0] == "gap":
            record_gap(target, gaps)
    return targets


def unparsed_mentions(collector: Collector, gaps: Gaps) -> None:
    for path, text in collector.unparsed.items():
        reason = f"unparsed_file:{collector.rel(path)}"
        collector.unresolved.append({"kind": "unparsed_file", "file": collector.rel(path)})
        for word in set(re.findall(r"[A-Za-z_]\w*", text)):
            gaps.setdefault(word, []).append((reason, None))


def apply_gaps(symbols: List[Symbol], gaps: Gaps) -> None:
    for symbol in symbols:
        for reason, scope in gaps.get(symbol.name, ()):
            if scope is None or any(
                symbol.file == place or place in symbol.file.parents for place in scope
            ):
                symbol.unmeasured.append(reason)


# ---------------------------------------------------------------------------
# pyproject scripts and entry points
# ---------------------------------------------------------------------------


def _table(node: Any, key: str) -> Dict[str, Any]:
    """`node[key]` when both are tables, else {} (parsing is not shape)."""
    value = node.get(key) if isinstance(node, dict) else None
    return value if isinstance(value, dict) else {}


def _pyproject_entries(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(evidence kind, 'module:attr') for every script and entry point."""
    entries: List[Tuple[str, str]] = []
    project = _table(data, "project")
    poetry = _table(_table(data, "tool"), "poetry")
    for table in (project.get("scripts"), project.get("gui-scripts"), poetry.get("scripts")):
        if isinstance(table, dict):
            entries.extend(("pyproject_script", v) for v in table.values() if isinstance(v, str))
    for groups in (project.get("entry-points"), poetry.get("plugins")):
        for group in groups.values() if isinstance(groups, dict) else ():
            if isinstance(group, dict):
                entries.extend(
                    ("pyproject_entry_point", v) for v in group.values() if isinstance(v, str)
                )
    return entries


def _find_pyproject(root: Path) -> Optional[Path]:
    for directory in (root, *list(root.parents)[:2]):  # Path.parents slices from 3.10
        if (directory / "pyproject.toml").is_file():
            return directory / "pyproject.toml"
    return None


def _entry_point(collector: Collector, kind: str, value: str, site: Site, gaps: Gaps) -> None:
    module_name, _, attr = value.split("[")[0].strip().partition(":")
    if not attr:
        return
    name = attr.strip().split(".")[0]
    locations = [
        loc
        for loc in collector.index.locate(module_name.strip())
        if loc.root.authority in HARD_AUTHORITIES and loc.kind != "namespace_package"
    ]
    targets = collector.resolve_name(locations[0].path, name) if locations else []
    if any(t[0] == "symbols" for t in mark(targets, kind, site, gaps)):
        return
    if collector.index.is_internal_top_level(module_name.strip().split(".")[0]):
        collector.unresolved.append({"kind": "unresolved_entry_point", "value": value})
        gaps.setdefault(name, []).append((f"unresolved_entry_point:{value}", None))


def pyproject_evidence(collector: Collector, gaps: Gaps) -> None:
    pyproject = _find_pyproject(collector.root)
    if pyproject is None:
        return
    data = load_pyproject(pyproject.parent)
    if not data:
        raw = pyproject.read_text(encoding="utf-8", errors="ignore")
        collector.unresolved.append({"kind": "pyproject_unreadable", "file": str(pyproject)})
        for name in set(re.findall(r":\s*([A-Za-z_]\w*)", raw)):
            gaps.setdefault(name, []).append(("pyproject_unreadable", None))
        return
    for kind, value in _pyproject_entries(data):
        _entry_point(collector, kind, value, (pyproject.name, 0), gaps)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _package_inits(files: Sequence[Path], root: Path, known: Set[Path]) -> List[Path]:
    """`__init__.py` of every package holding a scanned file, up to the root."""
    inits: Set[Path] = set()
    for path in files:
        for directory in _dirs_below(path, root):
            init = directory / "__init__.py"
            if init.is_file() and init not in known:
                inits.add(init)
    return sorted(inits)


def _parse(path: Path) -> Tuple[Optional[ast.Module], str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    try:
        return ast.parse(text, filename=str(path)), text
    except (SyntaxError, ValueError):
        return None, text


def _walked(directory: str, hidden: bool) -> bool:
    name = directory.lower()
    tool_cache = name.endswith("cache") and name[:1] in "._"  # .mypy_cache, __pycache__
    if name in DEFAULT_EXCLUDE_PARTS or tool_cache:
        return False
    return hidden or not name.startswith(".")


def walk_files(root: Path, suffixes: FrozenSet[str], hidden: bool = False) -> Iterator[Path]:
    """Files under `root` with one of `suffixes`.

    Environments, build output, and caches are skipped; other dot directories
    only when `hidden` is false (CI configuration lives in `.github`, `.buildkite`).
    """
    for current, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if _walked(d, hidden)]
        for name in names:
            if os.path.splitext(name)[1].lower() in suffixes:
                yield Path(current) / name


def _test_files(root: Path, known: Set[Path]) -> List[Path]:
    """Test files the scan did not list (the default configuration skips tests/**)."""
    return sorted(
        path
        for path in walk_files(root, frozenset({".py"}))
        if path not in known and path_facts(path, root).is_test
    )


def load(collector: Collector, files: Sequence[Path], trees: Dict[str, ast.AST]) -> None:
    """Scanned files are candidate sources; package `__init__.py` and test files are context.

    Context files are read for evidence only: they hold no candidate. An
    unparsable `__init__.py` is a gap; an unparsable test file is skipped, as a
    test reference never changes a state.
    """
    for path in files:
        tree = trees.get(str(path))
        if isinstance(tree, ast.Module):
            collector.add_module(path, tree, candidate_source=True)
        else:
            collector.unparsed[path] = _parse(path)[1]
    known = set(files)
    extra: Dict[str, ast.AST] = {}
    for path in _package_inits(files, collector.root, known) + _test_files(collector.root, known):
        tree, text = _parse(path)
        if tree is None:
            if path.name == "__init__.py":
                collector.unparsed[path] = text
            continue
        collector.add_module(path, tree, candidate_source=False)
        extra[str(path)] = tree
    if extra:
        collector.add_edges(build_import_edges(collector.root, [Path(p) for p in extra], extra))


# ---------------------------------------------------------------------------
# Distribution facts (for the promotion hold)
# ---------------------------------------------------------------------------


def distributable(root: Path) -> bool:
    """A package build is declared: pyproject [project]/[tool.poetry] name, setup.py, or setup.cfg."""
    pyproject = _find_pyproject(root)
    if pyproject is not None:
        data = load_pyproject(pyproject.parent)
        if _table(data, "project").get("name") or _table(_table(data, "tool"), "poetry").get(
            "name"
        ):
            return True
    places = (root, *list(root.parents)[:2])
    return any((d / "setup.py").is_file() or (d / "setup.cfg").is_file() for d in places)


def public_module(collector: Collector, path: Path) -> bool:
    """Inside a regular package under a module root, with no `_private` part on the way."""
    hard = [r for r in collector.index.roots if r.authority in HARD_AUTHORITIES]
    root = next((r.path for r in hard if r.path in path.parents), None)
    if root is None or not (path.parent / "__init__.py").is_file():
        return False
    parts = path.relative_to(root).with_suffix("").parts
    return not any(part.startswith("_") and part != "__init__" for part in parts)
