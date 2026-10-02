"""Import-graph evidence and structure measures in one report block.

Every row carries a classification (see docs/IMPORT_GRAPH.md):

    finding  a circular group or inner cycle whose loop runs, at import time or
             when a function is called. It is the structural view of an
             `import_cycle` the report already carries: never a second finding.
    context  type-checking-only loops, dependency hubs, dependency load, change
             reach. Descriptive; a widely imported module is not a defect.
    unknown  internal imports that could not be checked.

Nothing here feeds a score (`score_effect` is always "none").
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from slop_detector.analysis.graph_metrics import (
    DEFAULT_TOP_N,
    DEFERRED_RUNTIME,
    IMPORT_TIME,
    build_graph_metrics,
)
from slop_detector.analysis.import_graph import UNCHECKED_STATES, ImportEdge, coverage

FINDING = "finding"
CONTEXT = "context"
UNKNOWN = "unknown"
SCORE_EFFECT = "none"

# The phases kept by the graph that `import_cycles` is built from (type_only excluded).
_CYCLE_FINDING_PHASES = frozenset({IMPORT_TIME, DEFERRED_RUNTIME})


def _classified_cycle(row: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    if row["execution_phase"] in _CYCLE_FINDING_PHASES:
        out.update(classification=FINDING, finding_kind="import_cycle")
    else:
        out["classification"] = CONTEXT
    out["score_effect"] = SCORE_EFFECT
    return out


def _circular_groups(components: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    groups = []
    for component in components:
        group = _classified_cycle(component)
        group["inner_cycles"] = [_classified_cycle(c) for c in component["inner_cycles"]]
        groups.append(group)
    return groups


def _context(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(row, classification=CONTEXT) for row in rows]


def _unknowns(edges: Sequence[ImportEdge]) -> List[Dict[str, Any]]:
    rows = [
        {
            "importer": edge.importer,
            "line": edge.line,
            "requested_module": edge.requested_module,
            "requested_name": edge.requested_name,
            "relative_level": edge.relative_level,
            "resolution_state": edge.resolution_state,
            "classification": UNKNOWN,
        }
        for edge in edges
        if edge.resolution_state in UNCHECKED_STATES
    ]
    rows.sort(key=lambda row: (row["importer"], row["line"]))
    return rows


def build_structure_evidence(
    edges: Sequence[ImportEdge], top_n: int = DEFAULT_TOP_N
) -> Dict[str, Any]:
    """The `structure_evidence` block for one set of import edges."""
    measures = build_graph_metrics(edges, top_n)
    unknowns = _unknowns(edges)
    return {
        "evidence_complete": not unknowns,
        "coverage": coverage(edges),
        "unknowns": unknowns[:top_n],
        "circular_groups": _circular_groups(measures["strongly_connected_components"]),
        "dependency_hubs": _context(measures["fan_in"]),
        "dependency_load": _context(measures["fan_out"]),
        "change_reach": _context(measures["blast_radius"]),
        "totals": dict(measures["totals"], unknown_imports=len(unknowns)),
        "guide": measures["guide"],
        "score_effect": SCORE_EFFECT,
    }
