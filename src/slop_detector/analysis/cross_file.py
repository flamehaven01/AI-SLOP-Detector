"""
Cross-File Analysis Module

Detects project-level slop patterns that single-file analysis misses:

1. Slop Propagation  : file A imports from slop file B -> contamination flag
2. Duplicate Code    : identical function bodies across files (SHA-256 of the body)
3. Import Cycles     : circular import detection via DFS
4. Slop Hotspots     : files that are both heavily imported AND have high slop score
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Set, Tuple

from slop_detector.analysis import connection_evidence
from slop_detector.analysis.import_graph import ImportEdge, build_import_edges, hard_graph
from slop_detector.analysis.structure_evidence import build_structure_evidence
from slop_detector.clone_identity import MIN_SEMANTIC_NODES, body_fingerprint

# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------


@dataclass
class DuplicateBlock:
    """Two code blocks that are exact cross-file duplicates."""

    file_a: str
    file_b: str
    func_a: str
    func_b: str
    similarity: float  # 0.0-1.0
    line_a: int
    line_b: int


@dataclass
class ImportCycle:
    """A detected circular import chain."""

    cycle: Tuple[str, ...]  # ordered file paths forming the cycle

    def __str__(self) -> str:
        return " -> ".join(Path(p).name for p in self.cycle) + f" -> {Path(self.cycle[0]).name}"


@dataclass
class SlopHotspot:
    """A file with high slop score that is heavily imported."""

    file_path: str
    slop_score: float
    import_count: int  # how many files import this
    contaminated_files: List[str]


@dataclass
class CrossFileReport:
    """Full cross-file analysis report."""

    project_path: str
    total_files: int
    import_cycles: List[ImportCycle] = field(default_factory=list)
    duplicates: List[DuplicateBlock] = field(default_factory=list)
    hotspots: List[SlopHotspot] = field(default_factory=list)
    slop_propagation: Dict[str, List[str]] = field(default_factory=dict)
    import_graph: Dict[str, List[str]] = field(default_factory=dict)
    import_edges: List[ImportEdge] = field(default_factory=list)
    structure_evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "project_path": self.project_path,
            "total_files": self.total_files,
            "import_cycles": [
                {"cycle": list(c.cycle), "display": str(c)} for c in self.import_cycles
            ],
            "duplicates": [
                {
                    "file_a": d.file_a,
                    "func_a": d.func_a,
                    "line_a": d.line_a,
                    "file_b": d.file_b,
                    "func_b": d.func_b,
                    "line_b": d.line_b,
                    "similarity": d.similarity,
                }
                for d in self.duplicates
            ],
            "hotspots": [
                {
                    "file": h.file_path,
                    "slop_score": h.slop_score,
                    "imported_by": h.import_count,
                    "contaminates": h.contaminated_files,
                }
                for h in self.hotspots
            ],
            "slop_propagation": self.slop_propagation,
            "import_graph": self.import_graph,
            "import_edges": [edge.to_dict() for edge in self.import_edges],
            "structure_evidence": dict(self.structure_evidence),
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _hash_function_body(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """The shared body identity (clone_identity); "" for a body below the floor."""
    identity, size = body_fingerprint(func_node)
    return identity if size >= MIN_SEMANTIC_NODES else ""


def _extract_functions(tree: ast.AST) -> List[Tuple[str, int, str]]:
    """
    Extract (func_name, line_no, body_hash) from AST.
    Body hash: the shared body identity, "" when the body is below the floor.
    """
    return [
        (node.name, node.lineno, _hash_function_body(node))
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _levenshtein_ratio(a: str, b: str) -> float:
    """Approximate similarity ratio using edit distance."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    # Quick length filter
    if max(la, lb) / max(min(la, lb), 1) > 3:
        return 0.0
    # Full DP for short strings only
    if la > 200 or lb > 200:
        return 1.0 if a[:100] == b[:100] else 0.0
    dp = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        new_dp = [i]
        for j, cb in enumerate(b, 1):
            new_dp.append(min(dp[j] + 1, new_dp[-1] + 1, dp[j - 1] + (0 if ca == cb else 1)))
        dp = new_dp
    dist = dp[lb]
    return round(1.0 - dist / max(la, lb), 4)


def canonical_cycle(cycle: Tuple[str, ...]) -> Tuple[str, ...]:
    """Rotate a directed cycle to start at its smallest path; direction is kept."""
    start = cycle.index(min(cycle))
    return tuple(cycle[start:]) + tuple(cycle[:start])


def _parse_files(
    py_files: List[Path],
) -> Tuple[Dict[str, ast.AST], Dict[str, List[Tuple[str, int, str]]]]:
    """Parse each file once; unparsable files are skipped."""
    tree_cache: Dict[str, ast.AST] = {}
    func_cache: Dict[str, List[Tuple[str, int, str]]] = {}
    for fpath in py_files:
        try:
            tree = ast.parse(
                fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(fpath)
            )
        except Exception:
            continue
        tree_cache[str(fpath)] = tree
        func_cache[str(fpath)] = _extract_functions(tree)
    return tree_cache, func_cache


# ------------------------------------------------------------------
# Analyzer
# ------------------------------------------------------------------


class CrossFileAnalyzer:
    """
    Project-level slop analysis across all Python files.

    Usage:
        analyzer = CrossFileAnalyzer()
        report = analyzer.analyze(project_path, file_analyses)
    """

    DUPLICATE_THRESHOLD = 0.85  # similarity >= this -> duplicate
    HOTSPOT_SLOP_THRESHOLD = 40.0  # slop_score >= this -> hotspot candidate
    HOTSPOT_IMPORT_MIN = 2  # imported by >= this many files
    GRAPH_TOP_N = 10  # rows kept per structure_evidence list

    def analyze(
        self,
        project_path: str,
        file_analyses: List,  # List[FileAnalysis] from core.py
        slop_threshold: float = HOTSPOT_SLOP_THRESHOLD,
        connections: bool = False,
    ) -> CrossFileReport:
        """
        Run cross-file analysis.

        Args:
            project_path:   Root directory of the project.
            file_analyses:  List of FileAnalysis from SlopDetector.
            slop_threshold: Score above which a file is considered sloppy.
            connections:    Add `structure_evidence.connections` (candidate-only
                            connection evidence per top-level symbol; no score effect).
        """
        root = Path(project_path).resolve()
        py_files = [
            Path(fa.file_path).resolve()
            for fa in file_analyses
            if Path(fa.file_path).suffix == ".py"
        ]

        score_map: Dict[str, float] = {
            str(Path(fa.file_path).resolve()): getattr(fa, "deficit_score", 0.0)
            for fa in file_analyses
        }

        tree_cache, func_cache = _parse_files(py_files)

        # Import graph: only resolved, file-backed edges.
        import_edges = build_import_edges(root, py_files, tree_cache)
        import_graph: Dict[str, Set[str]] = {str(fpath): set() for fpath in py_files}
        for importer, targets in hard_graph(import_edges).items():
            import_graph.setdefault(importer, set()).update(targets)
        # Cycles exclude only `if TYPE_CHECKING:` edges, which never execute;
        # function-level imports run when called and still close a cycle.
        runtime_graph = hard_graph(import_edges, exclude_type_only=True)

        report = CrossFileReport(
            project_path=project_path,
            total_files=len(py_files),
        )

        report.import_cycles = self._detect_cycles(runtime_graph)
        report.duplicates = self._detect_duplicates(func_cache, py_files)
        report.hotspots, report.slop_propagation = self._detect_hotspots(
            import_graph, score_map, slop_threshold
        )
        report.import_graph = {key: sorted(value) for key, value in import_graph.items()}
        report.import_edges = import_edges
        report.structure_evidence = build_structure_evidence(import_edges, self.GRAPH_TOP_N)
        if connections:
            report.structure_evidence["connections"] = connection_evidence.build_connections(
                root, py_files, tree_cache, import_edges
            )

        return report

    def _dfs(
        self,
        node: str,
        graph: Dict[str, Set[str]],
        visited: Set[str],
        rec_stack: Set[str],
        path: List[str],
        cycles: List[ImportCycle],
    ) -> None:
        """Single DFS step for import cycle detection."""
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in visited:
                self._dfs(neighbor, graph, visited, rec_stack, path, cycles)
            elif neighbor in rec_stack:
                cycle_nodes = tuple(path[path.index(neighbor) :])
                if len(cycle_nodes) >= 2:
                    cycles.append(ImportCycle(cycle=cycle_nodes))
        path.pop()
        rec_stack.discard(node)

    def _detect_cycles(self, graph: Dict[str, Set[str]]) -> List[ImportCycle]:
        """DFS-based cycle detection in import graph.

        Nodes and neighbors are visited in sorted order, so the same graph gives
        the same cycles under any hash seed. One cycle per set of files, written
        from its smallest path; the list is sorted before the cap.
        """
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        cycles: List[ImportCycle] = []
        path: List[str] = []
        for node in sorted(graph):
            if node not in visited:
                self._dfs(node, graph, visited, rec_stack, path, cycles)
        seen: Set[FrozenSet[str]] = set()
        unique: List[ImportCycle] = []
        for c in cycles:
            key = frozenset(c.cycle)
            if key not in seen:
                seen.add(key)
                unique.append(ImportCycle(cycle=canonical_cycle(c.cycle)))
        unique.sort(key=lambda c: c.cycle)
        return unique[:20]

    def _build_exact_duplicate_pairs(
        self,
        hash_index: Dict[str, List[Tuple[str, str, int]]],
    ) -> List[DuplicateBlock]:
        """Build DuplicateBlock list from exact-match hash groups (cap 50)."""
        duplicates: List[DuplicateBlock] = []
        seen_pairs: Set[FrozenSet] = set()
        for entries in hash_index.values():
            if len(entries) < 2:
                continue
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    fa, na, la = entries[i]
                    fb, nb, lb = entries[j]
                    if fa == fb:
                        continue
                    pair = frozenset({(fa, na), (fb, nb)})
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    duplicates.append(
                        DuplicateBlock(
                            file_a=fa,
                            func_a=na,
                            line_a=la,
                            file_b=fb,
                            func_b=nb,
                            line_b=lb,
                            similarity=1.0,
                        )
                    )
                    if len(duplicates) >= 50:
                        return duplicates
        return duplicates

    def _detect_duplicates(
        self,
        func_cache: Dict[str, List[Tuple[str, int, str]]],
        py_files: List[Path],
    ) -> List[DuplicateBlock]:
        """Detect exact duplicate functions across files."""
        hash_index: Dict[str, List[Tuple[str, str, int]]] = defaultdict(list)
        for fpath, funcs in func_cache.items():
            for fname, lineno, bhash in funcs:
                if bhash:
                    hash_index[bhash].append((fpath, fname, lineno))
        return self._build_exact_duplicate_pairs(hash_index)

    def _detect_hotspots(
        self,
        graph: Dict[str, Set[str]],
        score_map: Dict[str, float],
        slop_threshold: float,
    ) -> Tuple[List[SlopHotspot], Dict[str, List[str]]]:
        """
        Find files that are heavily imported AND sloppy.
        Also map slop propagation: slop_file -> [files that import it].
        """
        # Reverse graph: file -> list of files that import it
        reverse: Dict[str, List[str]] = defaultdict(list)
        for importer, imported_set in graph.items():
            for imported in imported_set:
                reverse[imported].append(importer)

        hotspots: List[SlopHotspot] = []
        propagation: Dict[str, List[str]] = {}

        for fpath, score in score_map.items():
            importers = reverse.get(fpath, [])
            if score >= slop_threshold and len(importers) >= self.HOTSPOT_IMPORT_MIN:
                hotspots.append(
                    SlopHotspot(
                        file_path=fpath,
                        slop_score=score,
                        import_count=len(importers),
                        contaminated_files=importers,
                    )
                )
            if score >= slop_threshold and importers:
                propagation[fpath] = importers

        hotspots.sort(key=lambda h: h.slop_score * h.import_count, reverse=True)
        return hotspots[:10], propagation
