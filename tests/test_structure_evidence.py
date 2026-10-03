"""Controls for `structure_evidence`: one block for import-graph evidence and measures.

Evidence representation may change; finding cardinality and scores must not. A
circular group classified `finding` is the structural view of an `import_cycle`
the report already carries, never a second finding.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List
from unittest.mock import patch

import pytest

from slop_detector.analysis import cross_file
from slop_detector.analysis.cross_file import CrossFileAnalyzer
from slop_detector.analysis.graph_metrics import build_graph_metrics
from slop_detector.cli import main

SECTIONS = {
    "evidence_complete",
    "coverage",
    "unknowns",
    "circular_groups",
    "dependency_hubs",
    "dependency_load",
    "change_reach",
    "totals",
    "guide",
    "score_effect",
}
OLD_KEYS = {"graph_coverage", "graph_evidence_complete", "graph_metrics"}


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _analyze(root: Path):
    files = [
        SimpleNamespace(file_path=str(p), deficit_score=0.0) for p in sorted(root.rglob("*.py"))
    ]
    return CrossFileAnalyzer().analyze(str(root), files)


def _evidence(report) -> dict:
    block = report.to_dict().get("structure_evidence")
    assert isinstance(block, dict), "report has no structure_evidence block"
    return block


def _names(files: List[str]) -> List[str]:
    return sorted(Path(f).name for f in files)


def _runtime_cycle(root: Path) -> None:
    _write(root, "pkg/__init__.py")
    _write(root, "pkg/a.py", "from pkg import b\n")
    _write(root, "pkg/b.py", "from pkg import a\n")


def _deferred_cycle(root: Path) -> None:
    _write(root, "pkg/__init__.py")
    _write(root, "pkg/a.py", "def f():\n    from pkg import b\n    return b\n")
    _write(root, "pkg/b.py", "def g():\n    from pkg import a\n    return a\n")


def _mixed(root: Path) -> None:
    """{a, b, c} is one loop only through a TYPE_CHECKING import; {a, b} runs at import."""
    _write(root, "pkg/__init__.py")
    _write(root, "pkg/core.py", "X = 1\n")
    _write(root, "pkg/a.py", "from pkg import b, c, core\n")
    _write(root, "pkg/b.py", "from pkg import a, core\n")
    _write(
        root,
        "pkg/c.py",
        "from typing import TYPE_CHECKING\nfrom pkg import core\n"
        "if TYPE_CHECKING:\n    from pkg import a\n",
    )


def _star(root: Path, spokes: int = 5) -> None:
    _write(root, "pkg/__init__.py")
    _write(root, "pkg/core.py", "X = 1\n")
    for i in range(spokes):
        _write(root, f"pkg/s{i}.py", "from pkg import core\n")


def _monorepo(root: Path) -> None:
    _write(root, "pyproject.toml", '[project]\nname = "m"\nversion = "0"\n')
    _write(root, "backend/app/__init__.py")
    _write(root, "backend/app/models.py", "X = 1\n")
    _write(root, "backend/app/api.py", "from app import models\n")


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_report_has_one_structure_evidence_block_and_no_scattered_keys(tmp_path):
    _runtime_cycle(tmp_path)
    payload = _analyze(tmp_path).to_dict()
    assert "structure_evidence" in payload, "structure_evidence missing"
    assert set(payload["structure_evidence"]) == SECTIONS
    assert not OLD_KEYS & set(payload), f"old keys still present: {OLD_KEYS & set(payload)}"
    assert {"import_graph", "import_edges", "import_cycles"} <= set(payload)


def test_score_effect_is_none(tmp_path):
    _runtime_cycle(tmp_path)
    assert _evidence(_analyze(tmp_path)).get("score_effect") == "none"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_import_time_cycle_is_the_existing_import_cycle_finding(tmp_path):
    _runtime_cycle(tmp_path)
    (group,) = _evidence(_analyze(tmp_path)).get("circular_groups", [None])
    assert group["classification"] == "finding"
    assert group["finding_kind"] == "import_cycle"
    assert group["score_effect"] == "none"


def test_function_level_cycle_is_a_finding_because_it_is_already_reported(tmp_path):
    """A deferred cycle runs when the function is called and is already an import_cycle."""
    _deferred_cycle(tmp_path)
    report = _analyze(tmp_path)
    assert len(report.import_cycles) == 1
    (group,) = _evidence(report).get("circular_groups", [None])
    assert group["execution_phase"] == "deferred_runtime"
    assert group["classification"] == "finding"
    assert group["finding_kind"] == "import_cycle"


def test_type_only_group_is_context_and_its_inner_runtime_cycle_is_the_finding(tmp_path):
    _mixed(tmp_path)
    (group,) = _evidence(_analyze(tmp_path)).get("circular_groups", [None])
    assert group["execution_phase"] == "type_only"
    assert group["classification"] == "context"
    assert "finding_kind" not in group
    (inner,) = group["inner_cycles"]
    assert _names(inner["files"]) == ["a.py", "b.py"]
    assert inner["classification"] == "finding" and inner["finding_kind"] == "import_cycle"


def test_high_fan_in_alone_is_context_and_creates_no_finding(tmp_path):
    _star(tmp_path)
    report = _analyze(tmp_path)
    evidence = _evidence(report)
    hubs = evidence.get("dependency_hubs", [])
    assert hubs and Path(hubs[0]["file"]).name == "core.py" and hubs[0]["count"] == 5
    for section in ("dependency_hubs", "dependency_load", "change_reach"):
        assert evidence[section], f"{section} is empty"
        assert {row["classification"] for row in evidence[section]} == {"context"}
    assert evidence["circular_groups"] == []
    assert report.import_cycles == []


def test_unchecked_imports_are_unknowns_not_findings(tmp_path):
    _monorepo(tmp_path)
    evidence = _evidence(_analyze(tmp_path))
    assert evidence["evidence_complete"] is False
    (row,) = evidence.get("unknowns", [None])
    assert row["classification"] == "unknown"
    assert row["resolution_state"] == "conditional_internal"
    assert Path(row["importer"]).name == "api.py" and row["line"] == 1
    assert evidence["totals"]["unknown_imports"] == 1


def test_unknowns_keep_top_n_rows_and_count_all(tmp_path):
    _write(tmp_path, "pyproject.toml", '[project]\nname = "m"\nversion = "0"\n')
    _write(tmp_path, "backend/app/__init__.py")
    lines = "".join(f"from app import m{i}\n" for i in range(12))
    for i in range(12):
        _write(tmp_path, f"backend/app/m{i}.py", "X = 1\n")
    _write(tmp_path, "backend/app/api.py", lines)
    evidence = _evidence(_analyze(tmp_path))
    assert evidence["totals"]["unknown_imports"] == 12
    assert len(evidence["unknowns"]) == CrossFileAnalyzer.GRAPH_TOP_N
    assert [row["line"] for row in evidence["unknowns"]] == list(range(1, 11))


@pytest.mark.parametrize("fixture", [_runtime_cycle, _deferred_cycle, _mixed])
def test_every_legacy_cycle_lies_inside_a_finding_row(tmp_path, fixture):
    fixture(tmp_path)
    report = _analyze(tmp_path)
    rows = []
    for group in _evidence(report)["circular_groups"]:
        rows.append(group)
        rows.extend(group.get("inner_cycles", []))
    findings = [set(r["files"]) for r in rows if r["classification"] == "finding"]
    assert report.import_cycles, "fixture has no legacy cycle"
    for cycle in report.import_cycles:
        assert any(set(cycle.cycle) <= files for files in findings), cycle
    # and no finding row exists without a legacy cycle inside it
    for files in findings:
        assert any(set(c.cycle) <= files for c in report.import_cycles), files


# ---------------------------------------------------------------------------
# Invariants: values, cardinality, score
# ---------------------------------------------------------------------------


def test_measure_values_are_the_measure_builder_values(tmp_path):
    _mixed(tmp_path)
    report = _analyze(tmp_path)
    evidence = _evidence(report)
    measures = build_graph_metrics(report.import_edges, CrossFileAnalyzer.GRAPH_TOP_N)

    def strip(rows, extra=("classification", "finding_kind", "score_effect")):
        out = []
        for row in rows:
            clean = {k: v for k, v in row.items() if k not in extra}
            if "inner_cycles" in clean:
                clean["inner_cycles"] = strip(clean["inner_cycles"])
            out.append(clean)
        return out

    assert strip(evidence["circular_groups"]) == measures["strongly_connected_components"]
    assert strip(evidence["dependency_hubs"]) == measures["fan_in"]
    assert strip(evidence["dependency_load"]) == measures["fan_out"]
    assert strip(evidence["change_reach"]) == measures["blast_radius"]
    assert evidence["guide"] == measures["guide"]
    assert {k: v for k, v in evidence["totals"].items() if k != "unknown_imports"} == measures[
        "totals"
    ]


def test_cycles_and_score_do_not_depend_on_structure_evidence(tmp_path):
    """Replace the evidence builder with garbage: cycles, risk and the rest are unchanged."""
    _mixed(tmp_path)
    before = _analyze(tmp_path).to_dict()
    with patch.object(
        cross_file, "build_structure_evidence", lambda *a, **k: {"x": 1}, create=True
    ):
        after = _analyze(tmp_path).to_dict()
    assert after.pop("structure_evidence", None) == {"x": 1}, "the builder was not the source"
    before.pop("structure_evidence", None)
    assert after == before


def test_sweep_verdict_and_issues_do_not_depend_on_structure_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    _write(tmp_path, "pyproject.toml", '[project]\nname = "p"\nversion = "0"\n')
    _mixed(tmp_path)

    def run() -> dict:
        out = tmp_path / "out.json"
        argv = ["slop-detector", "boundary-violations", str(tmp_path), "--json", "-o", str(out)]
        with patch.object(sys, "argv", argv):
            assert main() == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        payload["summary"].pop("structure_evidence", None)
        return payload

    before = run()
    with patch.object(cross_file, "build_structure_evidence", lambda *a, **k: {}, create=True):
        after = run()
    assert after == before
    assert before["verdict"] == "fail"
    assert [i.get("issue_type") for i in before["issues"]].count("import_cycle") == 1


def test_type_checking_only_loop_is_context_and_creates_no_issue(tmp_path, monkeypatch):
    """A circular group with no runtime loop: context in the block, no issue, verdict pass."""
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    _write(tmp_path, "pyproject.toml", '[project]\nname = "p"\nversion = "0"\n')
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b\n")
    _write(
        tmp_path,
        "pkg/b.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pkg import a\n",
    )
    out = tmp_path / "out.json"
    argv = ["slop-detector", "boundary-violations", str(tmp_path), "--json", "-o", str(out)]
    with patch.object(sys, "argv", argv):
        assert main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    (group,) = payload["summary"]["structure_evidence"]["circular_groups"]
    assert group["classification"] == "context"
    assert payload["issues"] == [] and payload["verdict"] == "pass"


# ---------------------------------------------------------------------------
# Sweep surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["boundary-violations", "dupes", "dead-code"])
def test_every_sweep_family_carries_the_same_block(tmp_path, monkeypatch, kind):
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    _write(tmp_path, "pyproject.toml", '[project]\nname = "p"\nversion = "0"\n')
    _runtime_cycle(tmp_path)
    out = tmp_path / f"{kind}.json"
    argv = ["slop-detector", kind, str(tmp_path), "--json", "-o", str(out)]
    with patch.object(sys, "argv", argv):
        assert main() == 0
    summary = json.loads(out.read_text(encoding="utf-8"))["summary"]
    assert set(summary.get("structure_evidence", {})) == SECTIONS
    assert not OLD_KEYS & set(summary)
