"""Controls for the structure measures over the import graph.

Written before the implementation (see docs/IMPORT_GRAPH.md).
Graph measures are structure descriptors; none of them may enter a slop score.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import List, Optional
from unittest.mock import patch

from slop_detector.analysis.cross_file import CrossFileAnalyzer
from slop_detector.analysis.graph_metrics import (
    blast_radius,
    build_graph_metrics,
    strongly_connected_components,
)
from slop_detector.analysis.import_graph import ImportEdge
from slop_detector.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _edge(
    importer: str,
    imported: Optional[str],
    *,
    type_only: bool = False,
    deferred: bool = False,
    state: str = "resolved",
) -> ImportEdge:
    return ImportEdge(
        importer=importer,
        imported=imported,
        line=1,
        statement_kind="from",
        requested_module="m",
        requested_name=None,
        relative_level=0,
        import_scope="absolute",
        resolution_state=state,
        root_authority="E3",
        target_kind="module",
        type_only=type_only,
        deferred=deferred,
    )


def _section(metrics, key):
    assert isinstance(metrics, dict) and key in metrics, f"block lacks {key!r}"
    return metrics[key]


def _metrics_of(report):
    metrics = getattr(report, "structure_evidence", None)
    assert metrics, "CrossFileReport.structure_evidence is not implemented"
    return metrics


def _graph_of(pairs: List[tuple]) -> dict:
    graph: dict = {}
    for src, dst in pairs:
        graph.setdefault(src, set()).add(dst)
        graph.setdefault(dst, set())
    return graph


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class _FA:
    def __init__(self, path: Path) -> None:
        self.file_path = str(path)
        self.deficit_score = 0.0


def _analyze(root: Path):
    return CrossFileAnalyzer().analyze(str(root), [_FA(p) for p in sorted(root.rglob("*.py"))])


# ---------------------------------------------------------------------------
# SCC (additive next to the ordered import_cycles)
# ---------------------------------------------------------------------------


def test_scc_groups_a_three_node_cycle():
    graph = _graph_of([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")])
    assert strongly_connected_components(graph) == [["a", "b", "c"]]


def test_scc_ignores_acyclic_nodes_and_single_nodes():
    assert strongly_connected_components(_graph_of([("a", "b"), ("b", "c")])) == []


def test_scc_merges_cycles_that_share_a_node_unlike_import_cycles(tmp_path):
    """Two 2-cycles sharing `b`: one SCC {a,b,c}; the legacy DFS lists two paths.

    Both are asserted so neither output silently replaces the other.
    """
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b\n")
    _write(tmp_path, "pkg/b.py", "from pkg import a\nfrom pkg import c\n")
    _write(tmp_path, "pkg/c.py", "from pkg import b\n")
    report = _analyze(tmp_path)
    legacy = sorted(sorted(Path(p).name for p in c.cycle) for c in report.import_cycles)
    assert legacy == [["a.py", "b.py"], ["b.py", "c.py"]]
    components = _section(_metrics_of(report), "circular_groups")
    assert [sorted(Path(p).name for p in c["files"]) for c in components] == [
        ["a.py", "b.py", "c.py"]
    ]


def test_scc_is_deterministic_and_sorted():
    graph = _graph_of([("z", "y"), ("y", "z"), ("b", "a"), ("a", "b"), ("c", "d"), ("d", "e")])
    reordered = {k: graph[k] for k in sorted(graph, reverse=True)}
    expected = [["a", "b"], ["y", "z"]]
    assert strongly_connected_components(graph) == expected
    assert strongly_connected_components(reordered) == expected


def test_scc_handles_a_very_long_cycle_without_recursion():
    n = 5000
    graph = _graph_of([(f"n{i}", f"n{(i + 1) % n}") for i in range(n)])
    components = strongly_connected_components(graph)
    assert len(components) == 1 and len(components[0]) == n


# ---------------------------------------------------------------------------
# Execution phase of a component
# ---------------------------------------------------------------------------


def _phase_of(edges: List[ImportEdge]) -> str:
    components = _section(build_graph_metrics(edges), "strongly_connected_components")
    assert len(components) == 1, components
    return components[0]["execution_phase"]


def test_cycle_of_plain_imports_is_import_time():
    assert _phase_of([_edge("a", "b"), _edge("b", "a")]) == "import_time"


def test_cycle_closed_through_a_function_level_import_is_deferred_runtime():
    assert _phase_of([_edge("a", "b"), _edge("b", "a", deferred=True)]) == "deferred_runtime"


def test_cycle_closed_only_by_type_checking_import_is_type_only():
    assert _phase_of([_edge("a", "b"), _edge("b", "a", type_only=True)]) == "type_only"


def test_type_checking_inside_a_function_counts_as_type_only():
    edges = [_edge("a", "b"), _edge("b", "a", type_only=True, deferred=True)]
    assert _phase_of(edges) == "type_only"


def test_mixed_component_takes_the_phase_of_the_whole_not_of_a_part():
    """`c` is in no import-time cycle, so {a,b,c} is not an import-time group.

    Structural SCC {a,b,c}; import-time SCC {a,b}. The parent is type_only: linking
    all three needs the TYPE_CHECKING edge. The inner cycle is reported separately.
    """
    edges = [
        _edge("a", "b"),
        _edge("b", "a"),
        _edge("a", "c"),
        _edge("c", "a", type_only=True),
    ]
    assert _phase_of(edges) == "type_only"


def test_deferred_edge_needed_to_link_the_whole_component_gives_deferred_runtime():
    edges = [_edge("a", "b"), _edge("b", "a"), _edge("a", "c"), _edge("c", "a", deferred=True)]
    assert _phase_of(edges) == "deferred_runtime"


def test_inner_cycles_expose_the_stronger_cycle_without_promoting_the_parent():
    edges = [
        _edge("a", "b"),
        _edge("b", "a"),
        _edge("a", "c"),
        _edge("c", "a", type_only=True),
    ]
    (component,) = _section(build_graph_metrics(edges), "strongly_connected_components")
    assert component["execution_phase"] == "type_only"
    assert component.get("inner_cycles") == [
        {"files": ["a", "b"], "execution_phase": "import_time"}
    ]


def test_inner_cycles_label_a_deferred_inner_cycle_and_keep_import_time_inner_cycles():
    edges = [
        _edge("a", "b"),
        _edge("b", "a", deferred=True),
        _edge("c", "d"),
        _edge("d", "c"),
        _edge("b", "c"),
        _edge("d", "a", type_only=True),
    ]
    (component,) = _section(build_graph_metrics(edges), "strongly_connected_components")
    assert component["execution_phase"] == "type_only"
    inner = {tuple(c["files"]): c["execution_phase"] for c in component.get("inner_cycles", [])}
    assert inner == {("a", "b"): "deferred_runtime", ("c", "d"): "import_time"}


def test_a_whole_component_that_is_already_one_cycle_has_no_inner_cycles():
    (component,) = _section(
        build_graph_metrics([_edge("a", "b"), _edge("b", "c"), _edge("c", "a")]),
        "strongly_connected_components",
    )
    assert component["execution_phase"] == "import_time"
    assert component.get("inner_cycles") == []


def test_import_time_count_counts_cycle_groups_not_parent_groups():
    """The guide must not undercount: the mixed parent is type_only but holds an import-time cycle."""
    edges = [_edge("a", "b"), _edge("b", "a"), _edge("a", "c"), _edge("c", "a", type_only=True)]
    metrics = build_graph_metrics(edges)
    assert _section(metrics, "totals").get("import_time_components") == 1
    value = next(r["value"] for r in _section(metrics, "guide") if r["label"] == "Circular Groups")
    assert "1 at import time" in value


def test_only_resolved_edges_form_the_graph():
    edges = [
        _edge("a", "b"),
        _edge("b", "a", state="conditional_internal"),
        _edge("b", None, state="ambiguous"),
    ]
    metrics = build_graph_metrics(edges)
    assert _section(metrics, "strongly_connected_components") == []


# ---------------------------------------------------------------------------
# Fan-in / fan-out
# ---------------------------------------------------------------------------


def test_fan_in_and_fan_out_count_distinct_files_and_ignore_self_and_repeats():
    edges = [
        _edge("a", "core"),
        _edge("a", "core"),  # same pair twice: one dependency
        _edge("b", "core"),
        _edge("c", "core", type_only=True),
        _edge("core", "core"),  # self import: ignored
        _edge("core", "util"),
    ]
    metrics = build_graph_metrics(edges)
    fan_in = {row["file"]: row["count"] for row in _section(metrics, "fan_in")}
    fan_out = {row["file"]: row["count"] for row in _section(metrics, "fan_out")}
    assert fan_in == {"core": 3, "util": 1}
    assert fan_out == {"a": 1, "b": 1, "c": 1, "core": 1}


def test_fan_lists_are_top_n_sorted_with_path_tiebreak():
    edges = [_edge(f"m{i}", t) for i in range(3) for t in ("y", "x", "z")]
    rows = _section(build_graph_metrics(edges, top_n=2), "fan_in")
    assert [(r["file"], r["count"]) for r in rows] == [("x", 3), ("y", 3)]


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------


def test_blast_radius_reports_depth_and_via():
    edges = [_edge("a", "core"), _edge("b", "a"), _edge("c", "b")]
    hits = blast_radius(edges, "core")
    assert [(h["file"], h["depth"], h["via"]) for h in hits] == [
        ("a", 1, "core"),
        ("b", 2, "a"),
        ("c", 3, "b"),
    ]


def test_blast_radius_is_bounded_by_max_depth():
    edges = [_edge("a", "core"), _edge("b", "a"), _edge("c", "b")]
    assert [h["file"] for h in blast_radius(edges, "core", max_depth=2)] == ["a", "b"]


def test_blast_radius_terminates_on_cycles_and_excludes_the_target():
    edges = [_edge("a", "core"), _edge("core", "a"), _edge("b", "a")]
    assert [h["file"] for h in blast_radius(edges, "core")] == ["a", "b"]


def test_blast_radius_marks_the_phase_of_the_connecting_edge():
    edges = [_edge("a", "core", type_only=True), _edge("b", "core", deferred=True)]
    phases = {h["file"]: h["phase"] for h in blast_radius(edges, "core")}
    assert phases == {"a": "type_only", "b": "deferred_runtime"}


def test_blast_radius_of_unknown_or_unused_target_is_empty():
    assert blast_radius([_edge("a", "b")], "nope") == []
    assert blast_radius([_edge("a", "b")], "a") == []


def test_report_includes_transitive_dependents_for_top_fan_in_files():
    edges = [_edge("a", "core"), _edge("b", "a"), _edge("c", "b"), _edge("d", "core")]
    rows = _section(build_graph_metrics(edges), "blast_radius")
    assert rows, "no blast radius rows"
    top = rows[0]
    assert (top["file"], top["dependents"], top["max_depth"]) == ("core", 4, 3)


# ---------------------------------------------------------------------------
# Contract: additive, no scoring, no dependency
# ---------------------------------------------------------------------------


def test_graph_metrics_is_additive_and_leaves_existing_outputs_unchanged(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b\n")
    _write(tmp_path, "pkg/b.py", "from pkg import a\n")
    report = _analyze(tmp_path)
    assert len(report.import_cycles) == 1
    payload = report.to_dict()
    assert "structure_evidence" in payload
    assert {"import_cycles", "import_graph"} <= set(payload)
    assert "risk_score" not in payload  # cross-file analysis is evidence, not a score
    assert [p for p in payload["import_cycles"]] == [
        {"cycle": list(c.cycle), "display": str(c)} for c in report.import_cycles
    ]


def test_graph_metrics_module_uses_only_the_standard_library_and_project():
    import slop_detector.analysis.graph_metrics as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            roots.add(node.module.split(".")[0])
    assert roots <= set(
        sys.stdlib_module_names if hasattr(sys, "stdlib_module_names") else roots
    ) | {
        "slop_detector",
        "__future__",
    }
    assert "networkx" not in roots


def test_guide_rows_describe_each_measure_without_a_health_verdict(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b\n")
    _write(tmp_path, "pkg/b.py", "B = 1\n")
    guide = _section(_metrics_of(_analyze(tmp_path)), "guide")
    assert guide, "no guide rows"
    for row in guide:
        assert set(row) == {"label", "value", "direction", "means"}
        assert "health" not in row


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------


def _cycle_project(root: Path) -> None:
    _write(root, "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1"\n')
    _write(root, "pkg/__init__.py")
    _write(root, "pkg/a.py", "from pkg import b\n")
    _write(root, "pkg/b.py", "from pkg import a\n")


def test_sweep_boundary_summary_carries_the_circular_group(tmp_path, monkeypatch):
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    _cycle_project(tmp_path)

    def summary(kind: str) -> dict:
        out = tmp_path / f"{kind}.json"
        argv = ["slop-detector", kind, str(tmp_path), "--json", "-o", str(out)]
        with patch.object(sys, "argv", argv):
            assert main() == 0
        return json.loads(out.read_text(encoding="utf-8"))["summary"]

    boundary = summary("boundary-violations")
    components = _section(boundary.get("structure_evidence"), "circular_groups")
    assert components and components[0]["size"] == 2


def test_cross_file_text_prints_a_component_summary(tmp_path, capsys):
    _cycle_project(tmp_path)
    argv = ["slop-detector", "--project", str(tmp_path), "--cross-file", "--no-history"]
    with patch.object(sys, "argv", argv):
        main()
    out = capsys.readouterr().out
    assert "Circular Groups (1)" in out
    assert "import-time" in out


def test_cross_file_text_shows_the_inner_cycle_of_a_mixed_group(tmp_path, capsys):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "demo"\nversion = "0.1"\n')
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b\nfrom pkg import c\n")
    _write(tmp_path, "pkg/b.py", "from pkg import a\n")
    _write(
        tmp_path,
        "pkg/c.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pkg import a\n",
    )
    argv = ["slop-detector", "--project", str(tmp_path), "--cross-file", "--no-history"]
    with patch.object(sys, "argv", argv):
        main()
    out = capsys.readouterr().out
    assert "3 files, type-checking only" in out
    assert "inner import-time cycle: a.py, b.py" in out


# ---------------------------------------------------------------------------
# Controls added after the first mutation run (each closes a measured gap)
# ---------------------------------------------------------------------------


def test_scc_components_are_ordered_by_size_not_discovery():
    """Discovery order (a, b first) differs from the contract order (largest first)."""
    graph = _graph_of([("a", "b"), ("b", "a"), ("x", "y"), ("y", "z"), ("z", "x")])
    assert strongly_connected_components(graph) == [["x", "y", "z"], ["a", "b"]]


def test_strongest_phase_wins_regardless_of_edge_order():
    weak_first = [_edge("a", "b", type_only=True), _edge("a", "b", deferred=True), _edge("a", "b")]
    reverse = [_edge("b", "a")]
    assert _phase_of(weak_first + reverse) == "import_time"
    assert _phase_of(list(reversed(weak_first)) + reverse) == "import_time"


def test_blast_radius_lists_each_dependent_once_when_a_cycle_is_off_target():
    """b and c import each other; neither is the target. Each appears exactly once."""
    edges = [_edge("a", "core"), _edge("b", "a"), _edge("c", "b"), _edge("b", "c")]
    assert [(h["file"], h["depth"]) for h in blast_radius(edges, "core")] == [
        ("a", 1),
        ("b", 2),
        ("c", 3),
    ]


def test_to_dict_carries_the_computed_block_not_an_empty_one(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b\n")
    _write(tmp_path, "pkg/b.py", "from pkg import a\n")
    block = _analyze(tmp_path).to_dict().get("structure_evidence", {})
    assert block.get("totals", {}).get("components") == 1


def test_inner_cycles_are_ordered_by_size_then_name():
    """Two import-time inner cycles of different sizes; the larger one is listed first."""
    edges = [
        _edge("a", "b"),
        _edge("b", "a"),
        _edge("c", "d"),
        _edge("d", "e"),
        _edge("e", "c"),
        _edge("b", "c"),
        _edge("e", "a", type_only=True),
    ]
    (component,) = _section(build_graph_metrics(edges), "strongly_connected_components")
    assert component["execution_phase"] == "type_only"
    assert [c["files"] for c in component.get("inner_cycles", [])] == [["c", "d", "e"], ["a", "b"]]
