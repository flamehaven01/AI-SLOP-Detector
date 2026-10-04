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

This module holds the states and the report block. Name resolution is in
connection_resolution, the evidence passes in connection_collectors.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Sequence

from slop_detector.analysis import connection_collectors as collectors
from slop_detector.analysis import connection_resolution as resolution
from slop_detector.analysis.connection_resolution import Collector, Gaps, Symbol
from slop_detector.analysis.import_graph import ImportEdge

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
EVIDENCE_SAMPLE = 5  # sites kept per symbol; evidence_counts has the totals


def state_of(symbol: Symbol) -> str:
    """The first state that applies, in precedence order (see the module docstring)."""
    if any(kind in symbol.evidence for kind in CONNECTION_KINDS):
        return "connected"
    if any(kind in symbol.evidence for kind in EXPOSURE_KINDS):
        return "externally_exposed"
    if symbol.dynamic:
        return "dynamic_unknown"
    return "unmeasured" if symbol.unmeasured else "disconnected_candidate"


def symbol_row(symbol: Symbol) -> Dict[str, Any]:
    sites = [
        {"kind": kind, "file": file, "line": line}
        for kind in EVIDENCE_KINDS
        for file, line in sorted(set(symbol.evidence.get(kind, ())))
    ]
    return {
        "file": str(symbol.file),
        "name": symbol.name,
        "kind": symbol.kind,
        "line": symbol.line,
        "state": state_of(symbol),
        "evidence_kinds": [kind for kind in EVIDENCE_KINDS if kind in symbol.evidence],
        "evidence_counts": {k: len(set(v)) for k, v in symbol.evidence.items()},
        "evidence": sites[:EVIDENCE_SAMPLE],
        "test_referenced": symbol.test_referenced,
        "reasons": list(dict.fromkeys(symbol.dynamic + symbol.unmeasured)),
    }


def _block(collector: Collector, symbols: List[Symbol]) -> Dict[str, Any]:
    rows = [symbol_row(symbol) for symbol in symbols]
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
    collector = Collector(Path(root).resolve(), edges)
    resolution.load(collector, files, trees)
    collector.bind_all()

    gaps: Gaps = {}
    collectors.references(collector, gaps)
    collectors.decorators(collector)
    collectors.exports(collector, gaps)
    resolution.pyproject_evidence(collector, gaps)
    collectors.dynamic(collector)
    resolution.unparsed_mentions(collector, gaps)

    symbols = sorted(
        (s for m in collector.modules.values() for group in m.defs.values() for s in group),
        key=lambda s: (str(s.file), s.line),
    )
    resolution.apply_gaps(symbols, gaps)
    return _block(collector, symbols)
