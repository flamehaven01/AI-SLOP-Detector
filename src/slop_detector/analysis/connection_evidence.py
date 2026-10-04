"""Connection evidence for top-level functions and classes (candidate-only).

For every top-level function and class in a production file this records what
connects it, kept apart by kind:

    connection  direct_call, direct_reference, registry_reference (an entry in
                an assigned dict/list/tuple/set), decorator_registration (a
                decorator that registers with a framework: route, command,
                task, register, fixture, hookimpl, ...)
    exposure    public_export (`__all__`), package_reexport (bound by a package
                `__init__`), pyproject_script, pyproject_entry_point

and derives one state, highest first: connected, externally_exposed,
dynamic_unknown, unmeasured, disconnected_candidate. `dynamic_unknown` means
the code reaches names in a way static analysis cannot follow (an unknown
decorator, a computed getattr, importlib, globals(), eval, a package scan, a
module object used as a value, the name or its module path as a string);
`unmeasured` means evidence this symbol needs was not collected (an unresolved
import, one that resolves only with part of the project on sys.path, or an
unparsed file that may name it). Both are candidate-local: a gap elsewhere in
the project changes nothing here.

No finding, `score_effect` "none". Methods are not evaluated. References from
test files set `test_referenced` and never change the state. An import alone is
not a connection; the imported name has to be used. Name scoping is file-wide,
so a local that shadows a top-level name reads as a reference: the error leans
toward connected, never toward disconnected.
"""

from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

from slop_detector.analysis.import_graph import ImportEdge, build_import_edges
from slop_detector.path_facts import path_facts
from slop_detector.project_resolution import (
    HARD_AUTHORITIES,
    ProjectModuleIndex,
    load_pyproject,
    probe_module,
)

SCORE_EFFECT = "none"
SCOPE = "top_level_functions_and_classes"
STATES = (
    "connected",
    "externally_exposed",
    "dynamic_unknown",
    "unmeasured",
    "disconnected_candidate",
)
CONNECTION_KINDS = (
    "direct_call",
    "direct_reference",
    "registry_reference",
    "decorator_registration",
)
EXPOSURE_KINDS = ("public_export", "package_reexport", "pyproject_script", "pyproject_entry_point")
EVIDENCE_KINDS = CONNECTION_KINDS + EXPOSURE_KINDS

# Last name of a decorator that registers the function with a framework
# (leading underscores ignored: a private `_register` is still a registry).
REGISTERING_DECORATORS = frozenset(
    {
        "route",
        "get",
        "post",
        "put",
        "delete",
        "patch",
        "head",
        "options",
        "websocket",
        "api_route",
        "command",
        "group",
        "task",
        "shared_task",
        "register",
        "fixture",
        "hookimpl",
        "hookspec",
        "receiver",
    }
)
# Decorators that wrap or describe without registering: evidence of nothing.
PLAIN_DECORATORS = frozenset(
    {
        "dataclass",
        "property",
        "cached_property",
        "lru_cache",
        "cache",
        "staticmethod",
        "classmethod",
        "total_ordering",
        "wraps",
        "contextmanager",
        "asynccontextmanager",
        "abstractmethod",
        "overload",
        "final",
        "override",
        "runtime_checkable",
        "singledispatch",
        "unique",
    }
)
EVIDENCE_SAMPLE = 5  # sites kept per symbol; evidence_counts has the totals
MAX_HOPS = 8  # re-export chain depth

_GAP_STATES = frozenset({"conditional_internal", "ambiguous", "unresolved_internal"})
_CONTAINERS = (ast.Dict, ast.List, ast.Tuple, ast.Set)
_ASSIGNMENTS = (ast.Assign, ast.AnnAssign, ast.AugAssign)
_BUILTINS = frozenset(dir(builtins))
_DOTTED = re.compile(r"^[A-Za-z_][\w.]*[.:]([A-Za-z_]\w*)$")

Site = Tuple[str, int]
_Def = Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]
Scope = Optional[Tuple[Path, ...]]  # files/directories a gap concerns; None = anywhere
Gaps = Dict[str, List[Tuple[str, Scope]]]  # name -> (reason, scope)
# A binding target: ("symbols", syms) | ("module", path) | ("member", path, name)
#                   | ("dotted", dotted, target) | ("gap", names, reason, scope)
# A gap with a scope concerns only symbols defined in one of its files/directories.
Target = Tuple[Any, ...]


@dataclass
class _Symbol:
    file: Path
    name: str
    kind: str
    line: int
    evidence: Dict[str, List[Site]] = field(default_factory=dict)
    dynamic: List[str] = field(default_factory=list)
    unmeasured: List[str] = field(default_factory=list)
    test_referenced: bool = False

    def state(self) -> str:
        if any(kind in self.evidence for kind in CONNECTION_KINDS):
            return "connected"
        if any(kind in self.evidence for kind in EXPOSURE_KINDS):
            return "externally_exposed"
        if self.dynamic:
            return "dynamic_unknown"
        return "unmeasured" if self.unmeasured else "disconnected_candidate"

    def to_dict(self) -> Dict[str, Any]:
        sites = [
            {"kind": kind, "file": file, "line": line}
            for kind in EVIDENCE_KINDS
            for file, line in sorted(set(self.evidence.get(kind, ())))
        ]
        return {
            "file": str(self.file),
            "name": self.name,
            "kind": self.kind,
            "line": self.line,
            "state": self.state(),
            "evidence_kinds": [kind for kind in EVIDENCE_KINDS if kind in self.evidence],
            "evidence_counts": {k: len(set(v)) for k, v in self.evidence.items()},
            "evidence": sites[:EVIDENCE_SAMPLE],
            "test_referenced": self.test_referenced,
            "reasons": list(dict.fromkeys(self.dynamic + self.unmeasured)),
        }


@dataclass
class _Module:
    path: Path
    tree: ast.Module
    is_test: bool
    candidate_source: bool
    defs: Dict[str, List[_Symbol]] = field(default_factory=dict)
    bindings: Dict[str, List[Target]] = field(default_factory=dict)
    stars: List[Target] = field(default_factory=list)


class _Use(NamedTuple):
    kind: str
    full: bool  # the whole name chain resolved, no attribute left over
    owner: Optional[str]  # the top-level def/class the use sits in
    line: int


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _top_level_defs(tree: ast.Module) -> List[_Def]:
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]


def _last_name(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else None


def _chain(node: ast.expr) -> Optional[List[str]]:
    """`a.b.c` -> ['a', 'b', 'c']; None when the base is not a plain name."""
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return [node.id] + parts[::-1]


def _module_level(tree: ast.Module) -> Iterable[ast.stmt]:
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


def _all_assignments(tree: ast.Module) -> Iterator[ast.stmt]:
    for stmt in _module_level(tree):
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else getattr(stmt, "target", None)
        if isinstance(target, ast.Name) and target.id == "__all__":
            yield stmt


def _dunder_all(tree: ast.Module) -> List[Tuple[str, int]]:
    names: List[Tuple[str, int]] = []
    for stmt in _all_assignments(tree):
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


class _Collector:
    def __init__(self, root: Path, edges: Sequence[ImportEdge]) -> None:
        self.root = root
        self.index = ProjectModuleIndex(root)
        self.modules: Dict[Path, _Module] = {}
        self.edges: Dict[Tuple[str, int, str, int], List[ImportEdge]] = {}
        self.unresolved: List[Dict[str, Any]] = []
        self.unparsed: Dict[Path, str] = {}
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
        module = _Module(path, tree, is_test, candidate_source and not is_test)
        for node in _top_level_defs(tree):
            # Names defined in a non-candidate file still resolve (a re-export may
            # pass through); they just are not candidates.
            group = module.defs.setdefault(node.name, [])
            if module.candidate_source:
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                group.append(_Symbol(path, node.name, kind, node.lineno))
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

    def _edge_target(self, module: _Module, edge: ImportEdge, name: str) -> Optional[Target]:
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

    def _bind_import(self, module: _Module, node: ast.Import) -> None:
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

    def _bind_from(self, module: _Module, node: ast.ImportFrom) -> None:
        key = (str(module.path), node.lineno, node.module or "", node.level or 0)
        edges = self.edges.get(key, [])
        for alias in node.names:
            if alias.name == "*":
                self._bind_star(module, edges)
                continue
            target = self._from_target(module, node.lineno, edges, alias.name)
            if target is not None:
                module.bindings.setdefault(alias.asname or alias.name, []).append(target)

    def _bind_star(self, module: _Module, edges: List[ImportEdge]) -> None:
        whole = next((e for e in edges if e.requested_name is None), None)
        star = self._edge_target(module, whole, "*") if whole else None
        if star is not None:
            module.stars.append(star)

    def _from_target(
        self, module: _Module, line: int, edges: List[ImportEdge], name: str
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

    def _through_stars(self, module: _Module, name: str, depth: int) -> List[Target]:
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

    def resolve_chain(self, module: _Module, parts: List[str]) -> List[Tuple[Target, int]]:
        """Targets reached by a name chain, with how many parts were consumed."""
        return [self._advance(target, used, parts) for target, used in self._starts(module, parts)]

    def _starts(self, module: _Module, parts: List[str]) -> List[Tuple[Target, int]]:
        starts: List[Tuple[Target, int]] = []
        dotted = _dotted_start(module, parts)
        if dotted is not None:
            starts.append(dotted)
        starts.extend((t, 1) for t in self.resolve_name(module.path, parts[0]))
        if not starts and parts[0] not in _BUILTINS:
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


def _dotted_start(module: _Module, parts: List[str]) -> Optional[Tuple[Target, int]]:
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
# Evidence: uses, decorators, exports, pyproject
# ---------------------------------------------------------------------------


def _context(
    tree: ast.Module,
) -> Tuple[List[Tuple[ast.AST, Optional[str]]], Dict[ast.AST, ast.AST]]:
    """One pass: every node with the top-level def/class it sits in, and parent links."""
    nodes: List[Tuple[ast.AST, Optional[str]]] = []
    parents: Dict[ast.AST, ast.AST] = {}
    stack: List[Tuple[ast.AST, Optional[str]]] = [(tree, None)]
    while stack:
        node, owner = stack.pop()
        nodes.append((node, owner))
        for child in ast.iter_child_nodes(node):
            parents[child] = node
            is_def = node is tree and isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            stack.append((child, getattr(child, "name", None) if is_def else owner))
    return nodes, parents


def _chain_at(
    node: ast.AST, parents: Dict[ast.AST, ast.AST]
) -> Optional[Tuple[List[str], ast.expr]]:
    """The name chain a load starts, taken only at the top of its chain."""
    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
        if isinstance(parents.get(node), ast.Attribute):
            return None  # the enclosing chain is handled at its top
        return [node.id], node
    if not (isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)):
        return None
    parent = parents.get(node)
    if isinstance(parent, ast.Attribute) and parent.value is node:
        return None
    chain = _chain(node)
    return None if chain is None else (chain, node)


def _use_kind(top: ast.expr, parents: Dict[ast.AST, ast.AST]) -> str:
    parent = parents.get(top)
    if isinstance(parent, ast.Call) and parent.func is top:
        return "direct_call"
    node: ast.AST = top
    while isinstance(parent, _CONTAINERS):
        node, parent = parent, parents.get(parent)
    if node is not top and isinstance(parent, _ASSIGNMENTS):
        return "registry_reference"
    return "direct_reference"


def _record_gap(target: Target, gaps: Gaps) -> None:
    for name in target[1]:
        gaps.setdefault(name, []).append((target[2], target[3]))


def _connect(collector: _Collector, module: _Module, symbol: _Symbol, use: _Use) -> None:
    if symbol.file == module.path and use.owner == symbol.name:
        return  # a symbol's own body does not connect it
    if module.is_test:
        symbol.test_referenced = True
    else:
        symbol.evidence.setdefault(use.kind, []).append(collector.site(module.path, use.line))


def _record_use(
    collector: _Collector, module: _Module, target: Target, use: _Use, gaps: Gaps
) -> None:
    if target[0] == "gap":
        _record_gap(target, gaps)
    elif target[0] == "module" and use.full and not module.is_test:
        # The module object itself is a value: its names may be reached through
        # whatever holds it.
        site = collector.site(module.path, use.line)
        collector.escaped.setdefault(target[1], "module_escape:%s:%d" % site)
    elif target[0] == "symbols":
        for symbol in target[1]:
            _connect(collector, module, symbol, use)


def _references(collector: _Collector, gaps: Gaps) -> None:
    for module in collector.modules.values():
        nodes, parents = _context(module.tree)
        for node, owner in nodes:
            found = _chain_at(node, parents)
            if found is None:
                continue
            parts, top = found
            for target, used in collector.resolve_chain(module, parts):
                full = used == len(parts)
                kind = _use_kind(top, parents) if full else "direct_reference"
                _record_use(collector, module, target, _Use(kind, full, owner, top.lineno), gaps)


def _defined(module: _Module) -> Iterator[Tuple[_Def, _Symbol]]:
    for node in _top_level_defs(module.tree):
        for symbol in module.defs.get(node.name, ()):
            if symbol.line == node.lineno:
                yield node, symbol


def _judge_decorators(collector: _Collector, module: _Module, node: _Def, symbol: _Symbol) -> None:
    for deco in node.decorator_list:
        name = _last_name(deco)
        if name and name.lstrip("_") in REGISTERING_DECORATORS:
            site = collector.site(module.path, deco.lineno)
            symbol.evidence.setdefault("decorator_registration", []).append(site)
        elif name not in PLAIN_DECORATORS:
            symbol.dynamic.append(f"unknown_decorator:{name or '?'}")


def _decorators(collector: _Collector) -> None:
    for module in collector.modules.values():
        for node, symbol in _defined(module):
            _judge_decorators(collector, module, node, symbol)


def _mark(targets: List[Target], kind: str, site: Site, gaps: Gaps) -> List[Target]:
    """Add `kind` evidence to every symbol reached; a gap reached is recorded."""
    for target in targets:
        if target[0] == "symbols":
            for symbol in target[1]:
                symbol.evidence.setdefault(kind, []).append(site)
        elif target[0] == "gap":
            _record_gap(target, gaps)
    return targets


def _star_reexports(collector: _Collector, module: _Module, site: Site, gaps: Gaps) -> None:
    for star in module.stars:
        source = collector.modules.get(star[1]) if star[0] == "module" else None
        if source is None:
            continue
        for name in [n for n in source.defs if not n.startswith("_")]:
            _mark(collector.resolve_name(source.path, name), "package_reexport", site, gaps)


def _reexports(collector: _Collector, module: _Module, gaps: Gaps) -> None:
    for stmt in _module_level(module.tree):
        if not isinstance(stmt, ast.ImportFrom):
            continue
        site = collector.site(module.path, stmt.lineno)
        for alias in stmt.names:
            if alias.name == "*":
                _star_reexports(collector, module, site, gaps)
            else:
                local = alias.asname or alias.name
                _mark(collector.resolve_name(module.path, local), "package_reexport", site, gaps)


def _exports(collector: _Collector, gaps: Gaps) -> None:
    for module in list(collector.modules.values()):
        if module.is_test:
            continue
        for name, line in _dunder_all(module.tree):
            site = collector.site(module.path, line)
            _mark(collector.resolve_name(module.path, name), "public_export", site, gaps)
        if module.path.name == "__init__.py":
            _reexports(collector, module, gaps)


def _pyproject_entries(data: Dict[str, Any]) -> List[Tuple[str, str]]:
    """(evidence kind, 'module:attr') for every script and entry point."""
    entries: List[Tuple[str, str]] = []

    def sub(node: Any, key: str) -> Dict[str, Any]:
        value = node.get(key) if isinstance(node, dict) else None
        return value if isinstance(value, dict) else {}

    project = sub(data, "project")
    poetry = sub(sub(data, "tool"), "poetry")
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


def _entry_point(collector: _Collector, kind: str, value: str, site: Site, gaps: Gaps) -> None:
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
    if any(t[0] == "symbols" for t in _mark(targets, kind, site, gaps)):
        return
    if collector.index.is_internal_top_level(module_name.strip().split(".")[0]):
        collector.unresolved.append({"kind": "unresolved_entry_point", "value": value})
        gaps.setdefault(name, []).append((f"unresolved_entry_point:{value}", None))


def _pyproject(collector: _Collector, gaps: Gaps) -> None:
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


def _unparsed_mentions(collector: _Collector, gaps: Gaps) -> None:
    for path, text in collector.unparsed.items():
        reason = f"unparsed_file:{collector.rel(path)}"
        collector.unresolved.append({"kind": "unparsed_file", "file": collector.rel(path)})
        for word in set(re.findall(r"[A-Za-z_]\w*", text)):
            gaps.setdefault(word, []).append((reason, None))


# ---------------------------------------------------------------------------
# Dynamic access
# ---------------------------------------------------------------------------


def _module_names(collector: _Collector) -> Dict[Path, str]:
    names: Dict[Path, str] = {}
    hard = [r for r in collector.index.roots if r.authority in HARD_AUTHORITIES]
    for path in collector.modules:
        root = next((r for r in hard if r.path in path.parents), None)
        if root is None:
            continue
        parts = list(path.relative_to(root.path).with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        names[path] = ".".join(parts)
    return names


def _module_target(collector: _Collector, module: _Module, node: ast.expr) -> Optional[Path]:
    """The module file a name chain such as `pkg.sub` denotes, else None."""
    parts = _chain(node)
    if not parts:
        return None
    for target, used in collector.resolve_chain(module, parts):
        if target[0] == "module" and used == len(parts):
            return target[1]
    return None


def _mentioned_name(node: ast.Constant) -> Optional[str]:
    text = str(node.value).strip()
    if text.isidentifier():
        return text
    match = _DOTTED.match(text)
    return match.group(1) if match else None


def _string_constants_to_skip(tree: ast.Module) -> Set[int]:
    """Ids of `__all__` entries: an export list names symbols, it does not reach them."""
    return {
        id(node)
        for stmt in _all_assignments(tree)
        for node in ast.walk(getattr(stmt, "value", None) or ast.Constant(value=None))
    }


class _DynamicScan:
    """What makes names reachable in ways static reading cannot follow."""

    def __init__(self, collector: _Collector) -> None:
        self.collector = collector
        self.names = _module_names(collector)
        self.dotteds = set(self.names.values())
        self.mentioned: Dict[str, str] = {}
        self.attributes: Set[str] = set()
        self.files: Dict[Path, str] = {}

    def mark(self, path: Path, reason: str) -> None:
        self.files.setdefault(path, reason)

    def scan(self, module: _Module) -> None:
        rel = self.collector.rel(module.path)
        if any(n.name == "__getattr__" for n in _top_level_defs(module.tree)):
            self.mark(module.path, f"module_getattr:{rel}")
        skip = _string_constants_to_skip(module.tree)
        for node in ast.walk(module.tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                skip.add(id(node.value))  # docstrings and bare strings
            else:
                self._visit(module, node, skip, f"{rel}:{getattr(node, 'lineno', 0)}")
            self._package_scan(module, node, rel)

    def _visit(self, module: _Module, node: ast.AST, skip: Set[int], site: str) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skip:
                self._string(node, site)
        elif isinstance(node, (ast.JoinedStr, ast.BinOp)):
            prefix, whole = self.text_prefix(module, node)
            if prefix and not whole:
                self._module_path(prefix, False, site)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            self.attributes.add(node.attr)
        elif isinstance(node, ast.Call):
            self._call(module, node, site)

    def _string(self, node: ast.Constant, site: str) -> None:
        name = _mentioned_name(node)
        if name:
            self.mentioned.setdefault(name, f"string_mention:{site}")
        self._module_path(str(node.value), True, site)

    def _module_path(self, text: str, whole: bool, site: str) -> None:
        """A dotted string naming a project module, or a prefix ending in '.'.

        A single name ("config") is not taken as a module path: it is a dict
        key or a word far more often than an import target.
        """
        text = text.strip()
        if whole and "." in text and text in self.dotteds:
            hits = [path for path, dotted in self.names.items() if dotted == text]
        elif not whole and text.endswith("."):
            hits = [path for path, dotted in self.names.items() if dotted.startswith(text)]
        else:
            return
        for path in hits:
            self.mark(path, f"module_path_string:{site}")

    def text_prefix(self, module: _Module, node: ast.expr) -> Tuple[Optional[str], bool]:
        """(known leading text of a string expression, whether that is all of it).

        Constants and `{pkg.__name__}` / `{__name__}` parts are known; the first
        other part ends the prefix.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value, True
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.text_prefix(module, node.left)[0], False
        if not isinstance(node, ast.JoinedStr):
            return None, False
        text = ""
        for part in node.values:
            piece = self._known_text(module, part)
            if piece is None:
                return text or None, False
            text += piece
        return text, True

    def _known_text(self, module: _Module, part: ast.expr) -> Optional[str]:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            return part.value
        if not isinstance(part, ast.FormattedValue):
            return None
        value = part.value
        if isinstance(value, ast.Name) and value.id == "__name__":
            return self.names.get(module.path)
        if isinstance(value, ast.Attribute) and value.attr == "__name__":
            path = _module_target(self.collector, module, value.value)
            return self.names.get(path) if path is not None else None
        return None

    def _call(self, module: _Module, node: ast.Call, site: str) -> None:
        func = _last_name(node.func)
        if func == "globals" or (func == "vars" and not node.args):
            self.mark(module.path, f"namespace_access:{site}")
        elif func in ("eval", "exec") and isinstance(node.func, ast.Name):
            self.mark(module.path, f"eval:{site}")
        elif func == "getattr" and len(node.args) >= 2:
            self._getattr(module, node, site)
        elif func in ("import_module", "__import__") and node.args:
            self._import(module, node, site)

    def _getattr(self, module: _Module, node: ast.Call, site: str) -> None:
        if self.text_prefix(module, node.args[1])[1]:
            return  # a constant attribute name is a string mention, not a scan
        path = _module_target(self.collector, module, node.args[0])
        if path is not None:
            self.mark(path, f"dynamic_getattr:{site}")

    def _import(self, module: _Module, node: ast.Call, site: str) -> None:
        prefix, whole = self.text_prefix(module, node.args[0])
        if not prefix or prefix.startswith("."):
            file = site.rsplit(":", 1)[0]
            self.collector.unresolved.append(
                {"kind": "unscoped_dynamic_import", "file": file, "line": node.lineno}
            )
            return
        for path, dotted in self.names.items():
            if (dotted == prefix) if whole else dotted.startswith(prefix):
                self.mark(path, f"dynamic_import:{site}")

    def _package_scan(self, module: _Module, node: ast.AST, rel: str) -> None:
        """`<pkg>.__path__` (or `__path__` in a package) enumerates its modules."""
        package: Optional[Path] = None
        if isinstance(node, ast.Name) and node.id == "__path__":
            package = module.path.parent if module.path.name == "__init__.py" else None
        elif isinstance(node, ast.Attribute) and node.attr == "__path__":
            init = _module_target(self.collector, module, node.value)
            package = init.parent if init is not None and init.name == "__init__.py" else None
        if package is None:
            return
        reason = f"package_scan:{rel}:{getattr(node, 'lineno', 0)}"
        for path in self.collector.modules:
            if package in path.parents:
                self.mark(path, reason)

    def apply(self) -> None:
        escaped = self.collector.escaped
        for module in self.collector.modules.values():
            for name, symbols in module.defs.items():
                reasons = [self.files.get(module.path), self.mentioned.get(name)]
                if name in self.attributes:
                    reasons.append(escaped.get(module.path))
                for symbol in symbols:
                    symbol.dynamic.extend(r for r in reasons if r)


def _dynamic(collector: _Collector) -> None:
    scan = _DynamicScan(collector)
    for module in collector.modules.values():
        if not module.is_test:
            scan.scan(module)
    scan.apply()


# ---------------------------------------------------------------------------
# Entry point
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


def _load(collector: _Collector, files: Sequence[Path], trees: Dict[str, ast.AST]) -> None:
    """Scanned files are candidate sources; their package `__init__.py` files are context."""
    for path in files:
        tree = trees.get(str(path))
        if isinstance(tree, ast.Module):
            collector.add_module(path, tree, candidate_source=True)
        else:
            collector.unparsed[path] = _parse(path)[1]
    extra: Dict[str, ast.AST] = {}
    for init in _package_inits(files, collector.root, set(files)):
        tree, text = _parse(init)
        if tree is None:
            collector.unparsed[init] = text
            continue
        collector.add_module(init, tree, candidate_source=False)
        extra[str(init)] = tree
    if extra:
        collector.add_edges(build_import_edges(collector.root, [Path(p) for p in extra], extra))


def _apply_gaps(symbols: List[_Symbol], gaps: Gaps) -> None:
    for symbol in symbols:
        for reason, scope in gaps.get(symbol.name, ()):
            if scope is None or any(
                symbol.file == place or place in symbol.file.parents for place in scope
            ):
                symbol.unmeasured.append(reason)


def _block(collector: _Collector, symbols: List[_Symbol]) -> Dict[str, Any]:
    rows = [symbol.to_dict() for symbol in symbols]
    summary: Dict[str, int] = {"candidates": len(rows)}
    summary.update({state: sum(r["state"] == state for r in rows) for state in STATES})
    summary["test_referenced"] = sum(r["test_referenced"] for r in rows)
    summary["test_files_seen"] = sum(m.is_test for m in collector.modules.values())
    return {
        "scope": SCOPE,
        "score_effect": SCORE_EFFECT,
        "summary": summary,
        "symbols": rows,
        "unresolved_reasons": collector.unresolved,
    }


def build_connections(
    root: Path,
    files: Sequence[Path],
    trees: Dict[str, ast.AST],
    edges: Sequence[ImportEdge],
) -> Dict[str, Any]:
    """The `structure_evidence.connections` block (candidate-only, no score effect)."""
    collector = _Collector(Path(root).resolve(), edges)
    _load(collector, files, trees)
    collector.bind_all()

    gaps: Gaps = {}
    _references(collector, gaps)
    _decorators(collector)
    _exports(collector, gaps)
    _pyproject(collector, gaps)
    _dynamic(collector)
    _unparsed_mentions(collector, gaps)

    symbols = sorted(
        (s for m in collector.modules.values() for group in m.defs.values() for s in group),
        key=lambda s: (str(s.file), s.line),
    )
    _apply_gaps(symbols, gaps)
    return _block(collector, symbols)
