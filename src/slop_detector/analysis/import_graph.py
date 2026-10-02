"""Import edges with resolution evidence (docs/IMPORT_GRAPH.md).

Each import alias yields edges to its most specific target. Observation
(statement shape), addressing (absolute/relative), outcome (resolution_state)
and execution semantics (type_only/deferred) are recorded separately. Only
`resolved` edges with a file target may enter the legacy `import_graph`.
"""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from slop_detector.project_resolution import (
    HARD_AUTHORITIES,
    ModuleLocation,
    ModuleRoot,
    ProjectModuleIndex,
    probe_module,
)

RESOLUTION_STATES: Tuple[str, ...] = (
    "resolved",
    "conditional_internal",
    "unresolved_internal",
    "external",
    "ambiguous",
)


@dataclass(frozen=True)
class ImportEdge:
    importer: str
    imported: Optional[str]
    line: int
    statement_kind: str  # "import" | "from"
    requested_module: str
    requested_name: Optional[str]
    relative_level: int
    import_scope: str  # "absolute" | "relative"
    resolution_state: str
    root_authority: str  # "E1".."E4" | "none"
    target_kind: str  # module | package | package_member | namespace_package | unknown
    type_only: bool
    deferred: bool
    candidates: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["candidates"] = list(self.candidates)
        return data


@dataclass(frozen=True)
class _Ctx:
    importer: Path
    line: int
    statement_kind: str
    requested_module: str
    relative_level: int
    type_only: bool
    deferred: bool


@dataclass(frozen=True)
class _InitBindings:
    submodule: frozenset
    member: frozenset
    conditional: frozenset
    dynamic: bool  # module-level __getattr__ or `import *`


# ---------------------------------------------------------------------------
# Statement collection
# ---------------------------------------------------------------------------


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _iter_imports(nodes: Sequence[ast.AST], type_only: bool, deferred: bool) -> Iterator:
    """Yield (import_node, type_only, deferred) in source order."""
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node, type_only, deferred
        elif isinstance(node, ast.If) and _is_type_checking_test(node.test):
            yield from _iter_imports(node.body, True, deferred)
            yield from _iter_imports(node.orelse, type_only, deferred)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            yield from _iter_imports(list(ast.iter_child_nodes(node)), type_only, True)
        else:
            yield from _iter_imports(list(ast.iter_child_nodes(node)), type_only, deferred)


# ---------------------------------------------------------------------------
# Package __init__ analysis (CPython checks the attribute before the submodule)
# ---------------------------------------------------------------------------


def _from_bindings(stmt: ast.ImportFrom) -> Tuple[set, set]:
    """`from .x import y` sets submodule attribute x; `from . import y` sets y."""
    relative_here = stmt.level == 1
    submodule = {stmt.module.split(".")[0]} if relative_here and stmt.module else set()
    member = set()
    for alias in stmt.names:
        if alias.name == "*":
            continue
        if relative_here and not stmt.module and alias.asname is None:
            submodule.add(alias.name)
        else:
            member.add(alias.asname or alias.name)
    return submodule, member


def _import_bindings(stmt: ast.Import, package_name: str) -> Tuple[set, set]:
    """`import pkg.x` inside pkg/__init__.py sets submodule attribute x."""
    submodule, member = set(), set()
    for alias in stmt.names:
        head, _, rest = alias.name.partition(".")
        if head == package_name and rest and alias.asname is None:
            submodule.add(rest.split(".")[0])
        else:
            member.add(alias.asname or head)
    return submodule, member


def _assigned_names(stmt: ast.stmt) -> set:
    targets = stmt.targets if isinstance(stmt, ast.Assign) else [getattr(stmt, "target", None)]
    return {n.id for t in targets if t is not None for n in ast.walk(t) if isinstance(n, ast.Name)}


def _bound_names(stmt: ast.stmt, package_name: str) -> Tuple[set, set]:
    """Return (submodule_names, member_names) bound by one top-level statement."""
    if isinstance(stmt, ast.ImportFrom):
        return _from_bindings(stmt)
    if isinstance(stmt, ast.Import):
        return _import_bindings(stmt, package_name)
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return set(), {stmt.name}
    if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return set(), _assigned_names(stmt)
    return set(), set()


def _has_dynamic_attributes(stmt: ast.stmt) -> bool:
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "__getattr__":
        return True
    return isinstance(stmt, ast.ImportFrom) and any(a.name == "*" for a in stmt.names)


def _conditional_bindings(block: ast.stmt, package_name: str) -> Tuple[set, bool]:
    """Names bound anywhere inside an if/try block, and whether any is dynamic."""
    inner = [n for n in ast.walk(block) if isinstance(n, ast.stmt) and n is not block]
    names: set = set()
    for stmt in inner:
        sub, mem = _bound_names(stmt, package_name)
        names |= sub | mem
    return names, any(_has_dynamic_attributes(stmt) for stmt in inner)


def _scan_init(tree: ast.Module, package_name: str) -> _InitBindings:
    submodule, member, conditional = set(), set(), set()
    dynamic = False
    for stmt in tree.body:
        dynamic = dynamic or _has_dynamic_attributes(stmt)
        if isinstance(stmt, (ast.If, ast.Try)):
            names, inner_dynamic = _conditional_bindings(stmt, package_name)
            conditional |= names
            dynamic = dynamic or inner_dynamic
            continue
        sub, mem = _bound_names(stmt, package_name)
        submodule |= sub
        member |= mem
    return _InitBindings(frozenset(submodule), frozenset(member), frozenset(conditional), dynamic)


def _read_init_bindings(init_path: Path, cache: Dict[Path, _InitBindings]) -> _InitBindings:
    if init_path not in cache:
        try:
            tree = ast.parse(init_path.read_text(encoding="utf-8", errors="ignore"))
            cache[init_path] = _scan_init(tree, init_path.parent.name)
        except (OSError, SyntaxError, ValueError):
            empty: frozenset = frozenset()
            cache[init_path] = _InitBindings(empty, empty, empty, True)
    return cache[init_path]


# ---------------------------------------------------------------------------
# Edge construction
# ---------------------------------------------------------------------------


def _edge(
    ctx: _Ctx,
    state: str,
    *,
    imported: Optional[Path] = None,
    name: Optional[str] = None,
    scope: str = "absolute",
    authority: str = "none",
    kind: str = "unknown",
    candidates: Sequence[Path] = (),
) -> ImportEdge:
    return ImportEdge(
        importer=str(ctx.importer),
        imported=str(imported) if imported is not None else None,
        line=ctx.line,
        statement_kind=ctx.statement_kind,
        requested_module=ctx.requested_module,
        requested_name=name,
        relative_level=ctx.relative_level,
        import_scope=scope,
        resolution_state=state,
        root_authority=authority,
        target_kind=kind,
        type_only=ctx.type_only,
        deferred=ctx.deferred,
        candidates=tuple(str(c) for c in candidates),
    )


class _Resolver:
    def __init__(self, index: ProjectModuleIndex) -> None:
        self.index = index
        self._init_cache: Dict[Path, _InitBindings] = {}

    # -- module level -------------------------------------------------------

    def absolute(self, dotted: str) -> Tuple[str, Optional[ModuleLocation], List[ModuleLocation]]:
        """Return (state, chosen_location, candidates) for an absolute module name."""
        locations = self.index.locate(dotted)
        hard = [loc for loc in locations if loc.root.authority in HARD_AUTHORITIES]
        if hard:
            return "resolved", hard[0], hard
        conditional = [loc for loc in locations if loc.root.authority == "E4"]
        if len({loc.root.path for loc in conditional}) == 1:
            return "conditional_internal", conditional[0], conditional
        if conditional:
            return "ambiguous", None, conditional
        top = dotted.split(".")[0]
        if self.index.is_internal_top_level(top):
            return "unresolved_internal", None, []
        return "external", None, []

    def module_edges(self, ctx: _Ctx, dotted: str) -> List[ImportEdge]:
        state, loc, candidates = self.absolute(dotted)
        return [self.module_edge(ctx, state, loc, candidates, "absolute")]

    def module_edge(
        self,
        ctx: _Ctx,
        state: str,
        loc: Optional[ModuleLocation],
        candidates: Sequence[ModuleLocation],
        scope: str,
        name: Optional[str] = None,
    ) -> ImportEdge:
        if loc is None:
            return _edge(
                ctx, state, name=name, scope=scope, candidates=[c.path for c in candidates]
            )
        imported = None if loc.kind == "namespace_package" else loc.path
        authority = "none" if scope == "relative" else loc.root.authority
        return _edge(
            ctx,
            state,
            imported=imported,
            name=name,
            scope=scope,
            authority=authority,
            kind=loc.kind,
            candidates=[c.path for c in candidates] if state == "ambiguous" else (),
        )

    # -- from-import names --------------------------------------------------

    def _submodule(self, loc: ModuleLocation, dotted: str, name: str, scope: str):
        """Locate `name` as a submodule of the package at `loc`."""
        if scope == "relative" or loc.kind != "namespace_package":
            base = loc.path.parent if loc.kind == "package" else loc.path
            hit = probe_module(base, [name])
            return [ModuleLocation(hit[0], hit[1], loc.root)] if hit else []
        return [
            sub
            for sub in self.index.locate(f"{dotted}.{name}")
            if sub.root.authority == loc.root.authority
        ]

    def name_edges(
        self, ctx: _Ctx, loc: ModuleLocation, dotted: str, name: str, scope: str
    ) -> List[ImportEdge]:
        subs = self._submodule(loc, dotted, name, scope)
        if loc.kind == "namespace_package":
            if subs:
                return [self.module_edge(ctx, "resolved", subs[0], subs, scope, name)]
            return [_edge(ctx, "unresolved_internal", name=name, scope=scope)]
        bindings = _read_init_bindings(loc.path, self._init_cache)
        package_edge = self.module_edge(ctx, "resolved", loc, [loc], scope, name)
        verdict = _classify_name(bindings, name, bool(subs))
        if verdict == "submodule":
            return [self.module_edge(ctx, "resolved", subs[0], subs, scope, name)]
        if verdict == "ambiguous":
            candidates = [sub.path for sub in subs]
            return [
                package_edge,
                _edge(ctx, "ambiguous", name=name, scope=scope, candidates=candidates),
            ]
        if verdict == "member":
            return [_replace_kind(package_edge, "package_member")]
        return [_edge(ctx, "unresolved_internal", name=name, scope=scope)]


def _classify_name(bindings: _InitBindings, name: str, has_submodule: bool) -> str:
    """CPython order: attribute first, then submodule; undecidable -> ambiguous."""
    if name in bindings.member and name not in bindings.submodule:
        return "member"
    if name in bindings.submodule and has_submodule:
        return "submodule"
    if bindings.dynamic or name in bindings.conditional:
        return "ambiguous"
    return "submodule" if has_submodule else "unresolved"


def _replace_kind(edge: ImportEdge, kind: str) -> ImportEdge:
    data = asdict(edge)
    data["target_kind"] = kind
    return ImportEdge(**data)


def _relative_location(
    index: ProjectModuleIndex, importer: Path, level: int, module: Optional[str]
):
    """Climb the package hierarchy, not the filesystem.

    Every directory climbed through, from the importer's own directory up to the
    base, must be a package; otherwise CPython raises "attempted relative import
    beyond top-level package" and there is no edge.
    """
    base = importer.parent
    for step in range(level):
        if not index.is_package_dir(base):
            return None
        if step < level - 1:
            base = base.parent
    return probe_module(base, module.split(".") if module else [])


def _import_statement_edges(
    resolver: _Resolver, path: Path, node: ast.Import, type_only: bool, deferred: bool
) -> List[ImportEdge]:
    edges: List[ImportEdge] = []
    for alias in node.names:
        ctx = _Ctx(path, node.lineno, "import", alias.name, 0, type_only, deferred)
        edges.extend(resolver.module_edges(ctx, alias.name))
    return edges


def _from_target(resolver: _Resolver, path: Path, node: ast.ImportFrom, ctx: _Ctx):
    """Resolve the module part of a from-import: (location, scope, terminal_edge)."""
    if node.level:
        hit = _relative_location(resolver.index, path, node.level, node.module)
        if hit is None:
            return None, "relative", _edge(ctx, "unresolved_internal", scope="relative")
        # Relative resolution does not depend on sys.path, so no root authority applies.
        return ModuleLocation(hit[0], hit[1], ModuleRoot(path.parent, "none")), "relative", None
    state, loc, candidates = resolver.absolute(node.module or "")
    if state != "resolved" or loc is None:
        return None, "absolute", resolver.module_edge(ctx, state, loc, candidates, "absolute")
    return loc, "absolute", None


def _from_statement_edges(
    resolver: _Resolver, path: Path, node: ast.ImportFrom, type_only: bool, deferred: bool
) -> List[ImportEdge]:
    module = node.module or ""
    ctx = _Ctx(path, node.lineno, "from", module, node.level or 0, type_only, deferred)
    loc, scope, terminal = _from_target(resolver, path, node, ctx)
    if terminal is not None:
        return [terminal]
    if loc.kind == "module":
        return [resolver.module_edge(ctx, "resolved", loc, [loc], scope)]
    edges: List[ImportEdge] = []
    for alias in node.names:
        if alias.name == "*":
            edges.append(resolver.module_edge(ctx, "resolved", loc, [loc], scope))
        else:
            edges.extend(resolver.name_edges(ctx, loc, module, alias.name, scope))
    return edges


def _file_edges(resolver: _Resolver, path: Path, tree: ast.AST) -> List[ImportEdge]:
    edges: List[ImportEdge] = []
    for node, type_only, deferred in _iter_imports([tree], False, False):
        if isinstance(node, ast.Import):
            edges.extend(_import_statement_edges(resolver, path, node, type_only, deferred))
        else:
            edges.extend(_from_statement_edges(resolver, path, node, type_only, deferred))
    return edges


def build_import_edges(
    project_root: Path,
    files: Sequence[Path],
    trees: Optional[Dict[str, ast.AST]] = None,
) -> List[ImportEdge]:
    """Resolve every import statement in `files` against the project's module roots.

    `trees` maps str(path) to an already parsed module, to avoid parsing twice.
    """
    resolver = _Resolver(ProjectModuleIndex(project_root))
    edges: List[ImportEdge] = []
    for path in files:
        tree = (trees or {}).get(str(path))
        if tree is None:
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source, filename=str(path))
            except (OSError, SyntaxError, ValueError):
                continue
        edges.extend(_file_edges(resolver, path, tree))
    return edges


def hard_graph(edges: Sequence[ImportEdge], exclude_type_only: bool = False) -> Dict[str, set]:
    """Map importer -> resolved file targets (no self-loops).

    `exclude_type_only` drops `if TYPE_CHECKING:` edges, which never execute.
    Deferred (function-level) edges are kept: they execute when the function is
    called. Per-phase views live in graph_metrics.
    """
    graph: Dict[str, set] = {}
    for edge in edges:
        graph.setdefault(edge.importer, set())
        if edge.resolution_state != "resolved" or edge.imported is None:
            continue
        if exclude_type_only and edge.type_only:
            continue
        if Path(edge.imported) == Path(edge.importer):
            continue
        graph[edge.importer].add(edge.imported)
    return graph


def coverage(edges: Sequence[ImportEdge]) -> Dict[str, int]:
    counts = {state: 0 for state in RESOLUTION_STATES}
    for edge in edges:
        counts[edge.resolution_state] = counts.get(edge.resolution_state, 0) + 1
    return counts


# Internal imports that were seen but are not hard graph edges.
UNCHECKED_STATES: Tuple[str, ...] = ("conditional_internal", "ambiguous", "unresolved_internal")


def unchecked_imports(graph_coverage: Dict[str, int]) -> int:
    """Count of internal imports the graph could not check; 0 means complete evidence."""
    return sum(graph_coverage.get(state, 0) for state in UNCHECKED_STATES)
