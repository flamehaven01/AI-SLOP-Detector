"""Structural measures over the resolved import graph (stdlib only).

These describe how files depend on each other. They are context for a reader
and never feed a slop score: a widely imported module is not a defective one
(docs/GRAPH_STRUCTURE_UPDATE_PLAN.md, Phase 1).

Edge phases, strongest first:
    import_time       runs when the importer module is imported
    deferred_runtime  runs when a function containing the import is called
    type_only         inside `if TYPE_CHECKING:`; never runs
Only `resolved` edges with a file target form the graph.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from slop_detector.analysis.import_graph import ImportEdge

IMPORT_TIME = "import_time"
DEFERRED_RUNTIME = "deferred_runtime"
TYPE_ONLY = "type_only"

_STRENGTH = {IMPORT_TIME: 3, DEFERRED_RUNTIME: 2, TYPE_ONLY: 1}

DEFAULT_TOP_N = 10

Pair = Tuple[str, str]


def edge_phase(edge: ImportEdge) -> str:
    """Phase of one import statement.

    Inside `if TYPE_CHECKING:` an import never runs, even within a function, so
    type_only wins over deferred. A plain function-level import runs when the
    function is called (deferred_runtime).
    """
    if edge.type_only:
        return TYPE_ONLY
    return DEFERRED_RUNTIME if edge.deferred else IMPORT_TIME


def pair_phases(edges: Sequence[ImportEdge]) -> Dict[Pair, str]:
    """Strongest phase per (importer, imported) file pair. Self imports are dropped."""
    phases: Dict[Pair, str] = {}
    for edge in edges:
        if edge.resolution_state != "resolved" or edge.imported is None:
            continue
        if edge.importer == edge.imported:
            continue
        pair = (edge.importer, edge.imported)
        phase = edge_phase(edge)
        if _STRENGTH[phase] > _STRENGTH.get(phases.get(pair, ""), 0):
            phases[pair] = phase
    return phases


def _adjacency(phases: Mapping[Pair, str], minimum: str) -> Dict[str, Set[str]]:
    graph: Dict[str, Set[str]] = {}
    for (src, dst), phase in phases.items():
        graph.setdefault(dst, set())
        if _STRENGTH[phase] >= _STRENGTH[minimum]:
            graph.setdefault(src, set()).add(dst)
        else:
            graph.setdefault(src, set())
    return graph


class _Tarjan:
    """Iterative Tarjan over a sorted successor map (no recursion limit)."""

    def __init__(self, successors: Mapping[str, Sequence[str]]) -> None:
        self.successors = successors
        self.index: Dict[str, int] = {}
        self.low: Dict[str, int] = {}
        self.on_stack: Set[str] = set()
        self.stack: List[str] = []
        self.components: List[List[str]] = []

    def run(self, nodes: Sequence[str]) -> List[List[str]]:
        for root in nodes:
            if root not in self.index:
                self._explore(root)
        return self.components

    def _explore(self, root: str) -> None:
        work: List[Tuple[str, int]] = [(root, 0)]
        while work:
            node, child = work.pop()
            if child == 0:
                self._enter(node)
            descend = self._advance(node, child)
            if descend is not None:
                work.append((node, descend[0]))
                work.append((descend[1], 0))
                continue
            self._leave(node)
            if work:
                parent = work[-1][0]
                self.low[parent] = min(self.low[parent], self.low[node])

    def _enter(self, node: str) -> None:
        self.index[node] = self.low[node] = len(self.index)
        self.stack.append(node)
        self.on_stack.add(node)

    def _advance(self, node: str, start: int) -> Optional[Tuple[int, str]]:
        """Scan successors from `start`; return (resume position, child) to descend."""
        successors = self.successors[node]
        for position in range(start, len(successors)):
            nxt = successors[position]
            if nxt not in self.index:
                return position + 1, nxt
            if nxt in self.on_stack:
                self.low[node] = min(self.low[node], self.index[nxt])
        return None

    def _leave(self, node: str) -> None:
        if self.low[node] != self.index[node]:
            return
        members: List[str] = []
        while True:
            member = self.stack.pop()
            self.on_stack.discard(member)
            members.append(member)
            if member == node:
                break
        if len(members) > 1:
            self.components.append(sorted(members))


def strongly_connected_components(graph: Mapping[str, Iterable[str]]) -> List[List[str]]:
    """Components with at least two nodes (a cycle), deterministic and sorted.

    Nodes inside a component are sorted; components are ordered by (-size, nodes).
    """
    nodes = sorted(set(graph) | {n for targets in graph.values() for n in targets})
    successors = {n: sorted(set(graph.get(n, ()))) for n in nodes}
    components = _Tarjan(successors).run(nodes)
    return sorted(components, key=lambda c: (-len(c), c))


class _PhaseViews:
    """SCCs of the three nested views: import-time links, plus function-level, plus type-only."""

    def __init__(self, phases: Mapping[Pair, str]) -> None:
        self.structural = strongly_connected_components(_adjacency(phases, TYPE_ONLY))
        self.runtime = strongly_connected_components(_adjacency(phases, DEFERRED_RUNTIME))
        self.import_time = strongly_connected_components(_adjacency(phases, IMPORT_TIME))
        self._import_time_sets = {frozenset(c) for c in self.import_time}
        self._runtime_sets = {frozenset(c) for c in self.runtime}

    def phase_of(self, members: Sequence[str]) -> str:
        """Strongest phase in which ALL of `members` are still one cycle group.

        A smaller cycle inside the set does not promote it: its other files are
        not part of that cycle (see inner_cycles).
        """
        key = frozenset(members)
        if key in self._import_time_sets:
            return IMPORT_TIME
        return DEFERRED_RUNTIME if key in self._runtime_sets else TYPE_ONLY

    def inner_cycles(self, members: Sequence[str]) -> List[Dict[str, Any]]:
        """Stronger cycle groups strictly inside `members`, each labelled by phase_of."""
        whole = frozenset(members)
        inner = {
            frozenset(c): c for c in (*self.runtime, *self.import_time) if frozenset(c) < whole
        }
        ordered = sorted(inner.values(), key=lambda c: (-len(c), c))
        return [{"files": c, "execution_phase": self.phase_of(c)} for c in ordered]


def _components(views: _PhaseViews) -> List[Dict[str, Any]]:
    return [
        {
            "files": members,
            "size": len(members),
            "execution_phase": views.phase_of(members),
            "inner_cycles": views.inner_cycles(members),
        }
        for members in views.structural
    ]


def _fan_rows(counts: Mapping[str, int], top_n: int) -> List[Dict[str, Any]]:
    ranked = sorted(((f, c) for f, c in counts.items() if c > 0), key=lambda r: (-r[1], r[0]))
    return [{"file": f, "count": c} for f, c in ranked[:top_n]]


def _fan_counts(phases: Mapping[Pair, str]) -> Tuple[Dict[str, int], Dict[str, int]]:
    fan_in: Dict[str, int] = {}
    fan_out: Dict[str, int] = {}
    for src, dst in phases:
        fan_in[dst] = fan_in.get(dst, 0) + 1
        fan_out[src] = fan_out.get(src, 0) + 1
    return fan_in, fan_out


def _reverse_adjacency(phases: Mapping[Pair, str]) -> Dict[str, List[Tuple[str, str]]]:
    reverse: Dict[str, List[Tuple[str, str]]] = {}
    for (src, dst), phase in phases.items():
        reverse.setdefault(dst, []).append((src, phase))
    for dependents in reverse.values():
        dependents.sort()
    return reverse


def _walk_dependents(
    reverse: Mapping[str, List[Tuple[str, str]]], target: str, max_depth: int
) -> List[Dict[str, Any]]:
    seen = {target}
    hits: List[Dict[str, Any]] = []
    queue = deque([(target, 0)])
    while queue:
        node, depth = queue.popleft()
        if max_depth and depth >= max_depth:
            continue
        for dependent, phase in reverse.get(node, ()):
            if dependent in seen:
                continue
            seen.add(dependent)
            hits.append({"file": dependent, "depth": depth + 1, "via": node, "phase": phase})
            queue.append((dependent, depth + 1))
    return hits


def blast_radius(
    edges: Sequence[ImportEdge], target: str, max_depth: int = 0
) -> List[Dict[str, Any]]:
    """Files that depend on `target`, directly or through others (breadth first).

    Each hit carries its `depth`, the file it was reached `via`, and the `phase`
    of the connecting edge. `max_depth` 0 means unbounded.
    """
    return _walk_dependents(_reverse_adjacency(pair_phases(edges)), target, max_depth)


def _radius_rows(
    fan_in: Mapping[str, int], reverse: Mapping[str, List[Tuple[str, str]]], top_n: int
) -> List[Dict[str, Any]]:
    rows = []
    for row in _fan_rows(fan_in, top_n):
        hits = _walk_dependents(reverse, row["file"], 0)
        rows.append(
            {
                "file": row["file"],
                "dependents": len(hits),
                "max_depth": max((h["depth"] for h in hits), default=0),
            }
        )
    return rows


def _guide(
    components: Sequence[Mapping[str, Any]],
    import_time_groups: int,
    graph_files: int,
    graph_edges: int,
    top_in: Sequence[Mapping[str, Any]],
) -> List[Dict[str, str]]:
    busiest = f"{top_in[0]['count']} files" if top_in else "none"
    return [
        {
            "label": "Circular Groups",
            "value": f"{len(components)} ({import_time_groups} at import time)",
            "direction": "Lower",
            "means": "Sets of files that import each other in a loop, directly or through others.",
        },
        {
            "label": "Most Imported File",
            "value": busiest,
            "direction": "context",
            "means": "How many files import the busiest file. High is normal for a core module.",
        },
        {
            "label": "Import Graph Size",
            "value": f"{graph_files} files, {graph_edges} links",
            "direction": "context",
            "means": "Files and file-to-file import links that were resolved to project files.",
        },
    ]


def build_graph_metrics(edges: Sequence[ImportEdge], top_n: int = DEFAULT_TOP_N) -> Dict[str, Any]:
    """All Phase 1 measures for one set of import edges (additive report block)."""
    phases = pair_phases(edges)
    views = _PhaseViews(phases)
    components = _components(views)
    fan_in, fan_out = _fan_counts(phases)
    reverse = _reverse_adjacency(phases)
    top_in = _fan_rows(fan_in, top_n)
    files = {f for pair in phases for f in pair}
    return {
        "strongly_connected_components": components,
        "fan_in": top_in,
        "fan_out": _fan_rows(fan_out, top_n),
        "blast_radius": _radius_rows(fan_in, reverse, top_n),
        "totals": {
            "files": len(files),
            "links": len(phases),
            "components": len(components),
            "import_time_components": len(views.import_time),
        },
        "guide": _guide(components, len(views.import_time), len(files), len(phases), top_in),
    }
