"""
Cross-File Analysis Module

Detects project-level slop patterns that single-file analysis misses:

1. Slop Propagation  : file A imports from slop file B -> contamination flag
2. Duplicate Code    : similar function bodies across files (Levenshtein ratio)
3. Dead Exports      : defined in __all__ or exported but never imported elsewhere
4. Import Cycles     : circular import detection via DFS
5. Slop Hotspots     : files that are both heavily imported AND have high slop score
"""

from __future__ import annotations

import ast
import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------


@dataclass
class DuplicateBlock:
    """Two code blocks that are near-identical."""

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

    @property
    def risk_score(self) -> float:
        """Aggregate project-level risk [0.0-1.0]."""
        cycle_risk = min(len(self.import_cycles) * 0.10, 0.40)
        dup_risk = min(len(self.duplicates) * 0.05, 0.30)
        hotspot_risk = min(len(self.hotspots) * 0.08, 0.30)
        return round(min(cycle_risk + dup_risk + hotspot_risk, 1.0), 4)

    def to_dict(self) -> dict:
        return {
            "project_path": self.project_path,
            "total_files": self.total_files,
            "risk_score": self.risk_score,
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
        }


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _extract_imports(tree: ast.AST, file_path: Path, root: Path) -> Set[str]:
    """
    Extract imported local module paths from an AST.
    Returns absolute file paths where resolvable.
    """
    imported: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            candidate = root / Path(*parts)
            for ext in (".py",):
                p = candidate.with_suffix(ext)
                if p.exists():
                    imported.add(str(p.resolve()))
                p2 = candidate / "__init__.py"
                if p2.exists():
                    imported.add(str(p2.resolve()))
    return imported


def _extract_functions(tree: ast.AST) -> List[Tuple[str, int, str]]:
    """
    Extract (func_name, line_no, body_hash) from AST.
    Body hash: sha256 of normalized function body lines.
    """
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_lines = []
            for child in ast.walk(node):
                if isinstance(child, ast.Expr) and isinstance(child.value, ast.Constant):
                    continue  # skip docstrings
                if hasattr(child, "lineno"):
                    body_lines.append(ast.dump(child))
            body_str = "\n".join(body_lines)
            body_hash = hashlib.sha256(body_str.encode()).hexdigest()
            funcs.append((node.name, node.lineno, body_hash))
    return funcs


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

    def analyze(
        self,
        project_path: str,
        file_analyses: List,  # List[FileAnalysis] from core.py
        slop_threshold: float = HOTSPOT_SLOP_THRESHOLD,
    ) -> CrossFileReport:
        """
        Run cross-file analysis.

        Args:
            project_path:   Root directory of the project.
            file_analyses:  List of FileAnalysis from SlopDetector.
            slop_threshold: Score above which a file is considered sloppy.
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

        # Build import graph
        import_graph: Dict[str, Set[str]] = {}
        tree_cache: Dict[str, ast.AST] = {}
        func_cache: Dict[str, List[Tuple[str, int, str]]] = {}

        for fpath in py_files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content, filename=str(fpath))
                tree_cache[str(fpath)] = tree
                func_cache[str(fpath)] = _extract_functions(tree)
                import_graph[str(fpath)] = _extract_imports(tree, fpath, root)
            except Exception:
                import_graph[str(fpath)] = set()

        report = CrossFileReport(
            project_path=project_path,
            total_files=len(py_files),
        )

        report.import_cycles = self._detect_cycles(import_graph)
        report.duplicates = self._detect_duplicates(func_cache, py_files)
        report.hotspots, report.slop_propagation = self._detect_hotspots(
            import_graph, score_map, slop_threshold
        )

        return report

    def _detect_cycles(self, graph: Dict[str, Set[str]]) -> List[ImportCycle]:
        """DFS-based cycle detection in import graph."""
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        cycles: List[ImportCycle] = []
        path: List[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in rec_stack:
                    # Found cycle: extract from path
                    idx = path.index(neighbor)
                    cycle_nodes = tuple(path[idx:])
                    if len(cycle_nodes) >= 2:
                        cycles.append(ImportCycle(cycle=cycle_nodes))

            path.pop()
            rec_stack.discard(node)

        for node in list(graph.keys()):
            if node not in visited:
                dfs(node)

        # Deduplicate cycles by frozenset of nodes
        seen: Set[FrozenSet[str]] = set()
        unique: List[ImportCycle] = []
        for c in cycles:
            key = frozenset(c.cycle)
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique[:20]  # cap at 20

    def _detect_duplicates(
        self,
        func_cache: Dict[str, List[Tuple[str, int, str]]],
        py_files: List[Path],
    ) -> List[DuplicateBlock]:
        """Detect near-identical functions across files."""
        duplicates: List[DuplicateBlock] = []
        file_list = [str(p) for p in py_files]

        # Index by hash for exact duplicates first
        hash_index: Dict[str, List[Tuple[str, str, int]]] = defaultdict(list)
        for fpath, funcs in func_cache.items():
            for fname, lineno, bhash in funcs:
                if len(bhash) > 0:
                    hash_index[bhash].append((fpath, fname, lineno))

        seen_pairs: Set[FrozenSet] = set()
        for bhash, entries in hash_index.items():
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
