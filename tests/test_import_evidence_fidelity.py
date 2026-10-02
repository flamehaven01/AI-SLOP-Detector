"""Phase 0 controls: import evidence fidelity (docs/GRAPH_STRUCTURE_UPDATE_PLAN.md).

Written before the implementation. Each test is one row of the Phase 0 fixture
matrix. Tests marked PRESERVATION pass on the old code and must keep passing;
every other test failed on the old code by assertion.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Dict, List
from unittest.mock import patch

from slop_detector.analysis.cross_file import CrossFileAnalyzer
from slop_detector.cli import main
from slop_detector.patterns.python_imports import PhantomImportPattern

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class _FA:
    """Minimal stand-in for FileAnalysis: CrossFileAnalyzer reads only these."""

    def __init__(self, path: Path) -> None:
        self.file_path = str(path)
        self.deficit_score = 0.0


def _analyze(root: Path):
    files = sorted(p for p in root.rglob("*.py"))
    return CrossFileAnalyzer().analyze(str(root), [_FA(p) for p in files])


def _rel(root: Path, value: str) -> str:
    return Path(value).resolve().relative_to(root.resolve()).as_posix()


def _graph(root: Path, report) -> Dict[str, List[str]]:
    return {
        _rel(root, importer): sorted(_rel(root, t) for t in targets)
        for importer, targets in report.import_graph.items()
        if targets
    }


def _edges_from(root: Path, report, importer_rel: str):
    edges = getattr(report, "import_edges", None)
    assert edges is not None, "CrossFileReport.import_edges is not implemented"
    return [e for e in edges if _rel(root, e.importer) == importer_rel]


def _phantoms(path: Path) -> List[str]:
    src = path.read_text(encoding="utf-8")
    issues = PhantomImportPattern().check(ast.parse(src), path, src)
    return [i.message for i in issues if i.pattern_id == "phantom_import"]


_PYPROJECT = '[project]\nname = "demo"\nversion = "0.1"\n'


def _pyproject_where(*roots: str) -> str:
    where = ", ".join(f'"{r}"' for r in roots)
    return _PYPROJECT + f"\n[tool.setuptools.packages.find]\nwhere = [{where}]\n"


# ---------------------------------------------------------------------------
# 0A: phantom_import resolution (RED gate 2, 3; preservation 4, 5)
# ---------------------------------------------------------------------------


def test_single_root_namespace_is_not_phantom(tmp_path):
    _write(tmp_path, "pyproject.toml", _pyproject_where("src"))
    _write(tmp_path, "src/ns_pkg/feature/__init__.py")
    _write(tmp_path, "src/ns_pkg/feature/api.py", "def run():\n    return 1\n")
    use = _write(
        tmp_path,
        "src/ns_pkg/feature/use.py",
        "from ns_pkg.feature import api\n\nVALUE = api.run()\n",
    )
    assert _phantoms(use) == []


def test_declared_multi_portion_namespace_is_not_phantom(tmp_path):
    _write(tmp_path, "pyproject.toml", _pyproject_where("root_a", "root_b"))
    _write(tmp_path, "root_a/ns_pkg/alpha/__init__.py")
    _write(tmp_path, "root_a/ns_pkg/alpha/x.py", "X = 1\n")
    _write(tmp_path, "root_b/ns_pkg/beta/__init__.py")
    _write(tmp_path, "root_b/ns_pkg/beta/y.py", "Y = 2\n")
    use = _write(
        tmp_path,
        "root_a/ns_pkg/alpha/use.py",
        "from ns_pkg.alpha import x\nfrom ns_pkg.beta import y\n\nTOTAL = x.X + y.Y\n",
    )
    assert _phantoms(use) == []


def test_nonexistent_import_is_still_phantom(tmp_path):
    """PRESERVATION (negative control): namespace support must not mute real phantoms."""
    _write(tmp_path, "pyproject.toml", _pyproject_where("src"))
    _write(tmp_path, "src/ns_pkg/feature/__init__.py")
    use = _write(
        tmp_path,
        "src/ns_pkg/feature/use.py",
        "from ai_quantum_reasoning import HyperCausalTransformer\n\nM = HyperCausalTransformer\n",
    )
    assert len(_phantoms(use)) == 1


def test_directory_without_python_sources_is_still_phantom(tmp_path):
    """PRESERVATION (negative control): a data directory is not a namespace package."""
    _write(tmp_path, "pyproject.toml", _pyproject_where("src"))
    _write(tmp_path, "src/datafiles/table.csv", "a,b\n1,2\n")
    _write(tmp_path, "src/app/__init__.py")
    use = _write(tmp_path, "src/app/use.py", "from datafiles import loader\n\nL = loader\n")
    assert len(_phantoms(use)) == 1


def test_monorepo_collision_withholds_phantom(tmp_path):
    """PRESERVATION: two E4 roots providing `app` still withhold the accusation."""
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    for child in ("backend", "worker"):
        _write(tmp_path, f"{child}/app/__init__.py")
        _write(tmp_path, f"{child}/app/x.py", "def f():\n    return 1\n")
    use = _write(tmp_path, "backend/app/use.py", "from app.x import f\n\nV = f()\n")
    assert _phantoms(use) == []


# ---------------------------------------------------------------------------
# 0B: statement shapes (fixture matrix)
# ---------------------------------------------------------------------------


def test_real_src_layout_resolves_from_project_root(tmp_path):
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    _write(tmp_path, "src/pkg/__init__.py")
    _write(tmp_path, "src/pkg/b.py", "B = 1\n")
    _write(tmp_path, "src/pkg/a.py", "from pkg import b\n\nA = b.B\n")
    graph = _graph(tmp_path, _analyze(tmp_path))
    assert "src/pkg/b.py" in graph.get("src/pkg/a.py", [])


def test_relative_import_with_module_never_binds_to_decoy(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/foo.py", "Bar = 1\n")
    _write(tmp_path, "foo.py", "DECOY = 1\n")
    _write(tmp_path, "pkg/a.py", "from .foo import Bar\n")
    targets = _graph(tmp_path, _analyze(tmp_path)).get("pkg/a.py", [])
    assert "pkg/foo.py" in targets
    assert "foo.py" not in targets


def test_relative_import_without_module_resolves_submodule(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/sib.py", "X = 1\n")
    _write(tmp_path, "pkg/b.py", "from . import sib\n")
    report = _analyze(tmp_path)
    assert "pkg/sib.py" in _graph(tmp_path, report).get("pkg/b.py", [])
    scopes = {e.import_scope for e in _edges_from(tmp_path, report, "pkg/b.py")}
    assert scopes == {"relative"}


def test_plain_import_statement_is_resolved(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/sib.py", "X = 1\n")
    _write(tmp_path, "pkg/c.py", "import pkg.sib\n")
    assert "pkg/sib.py" in _graph(tmp_path, _analyze(tmp_path)).get("pkg/c.py", [])


def test_from_package_import_submodule_when_init_is_empty(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/name.py", "X = 1\n")
    _write(tmp_path, "user.py", "from pkg import name\n")
    targets = _graph(tmp_path, _analyze(tmp_path)).get("user.py", [])
    # Ancestor __init__ is implicit (plan, Phase 0 implementation notes).
    assert targets == ["pkg/name.py"]


def test_from_package_import_member_bound_in_init_is_not_submodule(tmp_path):
    """CPython checks the attribute first: `name = ...` in __init__ wins."""
    _write(tmp_path, "pkg/__init__.py", "name = 'member'\n")
    _write(tmp_path, "pkg/name.py", "X = 1\n")
    _write(tmp_path, "user.py", "from pkg import name\n")
    report = _analyze(tmp_path)
    assert _graph(tmp_path, report).get("user.py", []) == ["pkg/__init__.py"]
    kinds = {e.target_kind for e in _edges_from(tmp_path, report, "user.py")}
    assert "package_member" in kinds


def test_from_package_import_reexported_submodule(tmp_path):
    """`from . import name` in __init__ binds the name and imports the submodule."""
    _write(tmp_path, "pkg/__init__.py", "from . import name\n")
    _write(tmp_path, "pkg/name.py", "X = 1\n")
    _write(tmp_path, "user.py", "from pkg import name\n")
    targets = _graph(tmp_path, _analyze(tmp_path)).get("user.py", [])
    assert "pkg/name.py" in targets


def test_from_package_with_module_getattr_is_ambiguous(tmp_path):
    _write(tmp_path, "pkg/__init__.py", "def __getattr__(n):\n    return n\n")
    _write(tmp_path, "pkg/name.py", "X = 1\n")
    _write(tmp_path, "user.py", "from pkg import name\n")
    report = _analyze(tmp_path)
    assert "pkg/name.py" not in _graph(tmp_path, report).get("user.py", [])
    states = {e.resolution_state for e in _edges_from(tmp_path, report, "user.py")}
    assert "ambiguous" in states


def test_namespace_package_resolves_in_graph(tmp_path):
    """Traversal through a namespace *intermediate* directory (CPython never checks it).

    Mutation note: disabling namespace detection does not kill this test, because
    the import target is a regular package; the next test owns detection.
    """
    _write(tmp_path, "pyproject.toml", _pyproject_where("src"))
    _write(tmp_path, "src/ns_pkg/feature/__init__.py")
    _write(tmp_path, "src/ns_pkg/feature/api.py", "X = 1\n")
    _write(tmp_path, "src/ns_pkg/feature/use.py", "from ns_pkg.feature import api\n")
    targets = _graph(tmp_path, _analyze(tmp_path)).get("src/ns_pkg/feature/use.py", [])
    assert "src/ns_pkg/feature/api.py" in targets


def test_namespace_package_as_import_target_is_detected(tmp_path):
    """The namespace directory itself is the resolved module (owns PEP 420 detection)."""
    _write(tmp_path, "pyproject.toml", _pyproject_where("src"))
    _write(tmp_path, "src/ns_pkg/feature/__init__.py")
    _write(tmp_path, "src/ns_pkg/feature/api.py", "X = 1\n")
    _write(tmp_path, "src/app/__init__.py")
    _write(tmp_path, "src/app/use.py", "from ns_pkg import feature\n")
    report = _analyze(tmp_path)
    assert "src/ns_pkg/feature/__init__.py" in _graph(tmp_path, report).get("src/app/use.py", [])
    states = {e.resolution_state for e in _edges_from(tmp_path, report, "src/app/use.py")}
    assert states == {"resolved"}


def test_multi_portion_namespace_resolves_both_portions(tmp_path):
    _write(tmp_path, "pyproject.toml", _pyproject_where("root_a", "root_b"))
    _write(tmp_path, "root_a/ns_pkg/alpha/__init__.py")
    _write(tmp_path, "root_a/ns_pkg/alpha/x.py", "X = 1\n")
    _write(tmp_path, "root_b/ns_pkg/beta/__init__.py")
    _write(tmp_path, "root_b/ns_pkg/beta/y.py", "Y = 2\n")
    _write(
        tmp_path,
        "root_a/ns_pkg/alpha/use.py",
        "from ns_pkg.alpha import x\nfrom ns_pkg.beta import y\n",
    )
    targets = _graph(tmp_path, _analyze(tmp_path)).get("root_a/ns_pkg/alpha/use.py", [])
    assert "root_a/ns_pkg/alpha/x.py" in targets
    assert "root_b/ns_pkg/beta/y.py" in targets


def test_type_checking_and_function_level_imports_are_marked(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/sib.py", "X = 1\n")
    _write(
        tmp_path,
        "pkg/e.py",
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from pkg.sib import X\n"
        "\n"
        "\n"
        "def f():\n"
        "    import pkg.sib\n"
        "    return pkg.sib.X\n",
    )
    report = _analyze(tmp_path)
    internal = [
        e for e in _edges_from(tmp_path, report, "pkg/e.py") if e.resolution_state == "resolved"
    ]
    by_line = {e.line: e for e in internal}
    assert by_line[3].type_only is True and by_line[3].deferred is False
    assert by_line[7].deferred is True and by_line[7].type_only is False
    assert "pkg/sib.py" in _graph(tmp_path, report).get("pkg/e.py", [])


# ---------------------------------------------------------------------------
# 0B: cycles
# ---------------------------------------------------------------------------


def test_seeded_cycle_through_from_package_import_is_found(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/loop_a.py", "from pkg import loop_b\n")
    _write(tmp_path, "pkg/loop_b.py", "from pkg import loop_a\n")
    cycles = [sorted(Path(p).name for p in c.cycle) for c in _analyze(tmp_path).import_cycles]
    assert cycles == [["loop_a.py", "loop_b.py"]]


def test_cycle_closed_only_by_type_only_import_is_not_runtime(tmp_path):
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg.b import B\nA = 1\n")
    _write(
        tmp_path,
        "pkg/b.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from pkg.a import A\nB = 2\n",
    )
    assert _analyze(tmp_path).import_cycles == []


# ---------------------------------------------------------------------------
# 0B: module-root authority (RED gate 4, 5, 6)
# ---------------------------------------------------------------------------


def _monorepo(root: Path, pyproject: str) -> None:
    _write(root, "pyproject.toml", pyproject)
    _write(root, "backend/app/__init__.py")
    _write(root, "backend/app/services/__init__.py")
    _write(root, "backend/app/services/jobs.py", "def run():\n    return 1\n")
    _write(root, "backend/app/main.py", "from app.services.jobs import run\n\nV = run()\n")


def test_undeclared_e4_root_is_conditional_not_hard_edge(tmp_path):
    _monorepo(tmp_path, _PYPROJECT)
    report = _analyze(tmp_path)
    assert "backend/app/services/jobs.py" not in _graph(tmp_path, report).get(
        "backend/app/main.py", []
    )
    edges = _edges_from(tmp_path, report, "backend/app/main.py")
    assert [(e.resolution_state, e.root_authority) for e in edges] == [
        ("conditional_internal", "E4")
    ]
    assert _rel(tmp_path, edges[0].imported) == "backend/app/services/jobs.py"
    assert _phantoms(tmp_path / "backend/app/main.py") == []


def test_declared_e4_root_is_promoted_to_hard_edge(tmp_path):
    _monorepo(tmp_path, _pyproject_where("backend"))
    report = _analyze(tmp_path)
    assert "backend/app/services/jobs.py" in _graph(tmp_path, report).get("backend/app/main.py", [])
    edges = _edges_from(tmp_path, report, "backend/app/main.py")
    assert [(e.resolution_state, e.root_authority) for e in edges] == [("resolved", "E1")]


def test_e4_collision_is_ambiguous(tmp_path):
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    for child in ("backend", "worker"):
        _write(tmp_path, f"{child}/app/__init__.py")
        _write(tmp_path, f"{child}/app/x.py", "def f():\n    return 1\n")
    _write(tmp_path, "backend/app/use.py", "from app.x import f\n")
    report = _analyze(tmp_path)
    assert _graph(tmp_path, report).get("backend/app/use.py", []) == []
    states = [e.resolution_state for e in _edges_from(tmp_path, report, "backend/app/use.py")]
    assert states == ["ambiguous"]


# ---------------------------------------------------------------------------
# Contract and coverage
# ---------------------------------------------------------------------------


def test_import_graph_shape_is_unchanged_and_coverage_is_additive(tmp_path):
    _monorepo(tmp_path, _PYPROJECT)
    report = _analyze(tmp_path)
    assert isinstance(report.import_graph, dict)
    assert all(isinstance(v, list) for v in report.import_graph.values())
    payload = report.to_dict()
    assert "graph_coverage" in payload and "import_edges" in payload, "additive keys missing"
    assert payload["graph_coverage"]["conditional_internal"] == 1
    assert isinstance(payload["import_edges"], list)


def _paired_layout(root: Path, as_package: bool) -> None:
    prefix, pkg = ("src", "src") if as_package else ("src/mypkg", "mypkg")
    for d in ("", "api/", "domain/", "data/"):
        _write(root, f"{prefix}/{d}__init__.py")
    if as_package:
        _write(root, "src/__init__.py")
    _write(root, f"{prefix}/api/controller.py", f"from {pkg}.domain import model\n")
    _write(root, f"{prefix}/domain/model.py", f"from {pkg}.data import repo\n")
    _write(root, f"{prefix}/data/repo.py", "VALUE = 1\n")
    _write(root, f"{prefix}/data/loop_a.py", f"from {pkg}.data import loop_b\n")
    _write(root, f"{prefix}/data/loop_b.py", f"from {pkg}.data import loop_a\n")


def _boundary_issue_types(project: Path, tmp_path: Path) -> List[str]:
    config = tmp_path / f"{project.name}.slopconfig.yaml"
    config.write_text("architecture:\n  enabled: true\n  preset: layered\n", encoding="utf-8")
    out = tmp_path / f"{project.name}.json"
    argv = ["slop-detector", "boundary-violations", str(project), "--config", str(config)]
    with patch.object(sys, "argv", argv + ["--json", "-o", str(out)]):
        assert main() == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    return sorted(item.get("issue_type") for item in payload["issues"])


def test_paired_layouts_report_the_same_findings(tmp_path, monkeypatch):
    """Acceptance: the same architecture in two layouts must give the same findings."""
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    as_package, src_layout = tmp_path / "A", tmp_path / "B"
    _paired_layout(as_package, as_package=True)
    _paired_layout(src_layout, as_package=False)
    expected = ["import_cycle", "layer_boundary_violation"]
    assert _boundary_issue_types(as_package, tmp_path) == expected
    assert _boundary_issue_types(src_layout, tmp_path) == expected


def test_cross_file_text_reports_conditional_imports_instead_of_bare_clean(tmp_path, capsys):
    _monorepo(tmp_path, _PYPROJECT)
    argv = ["slop-detector", "--project", str(tmp_path), "--cross-file", "--no-history"]
    with patch.object(sys, "argv", argv):
        main()
    out = capsys.readouterr().out
    assert "1 conditional" in out
    assert "declare" in out.lower()


def test_sweep_payload_reports_graph_coverage(tmp_path, monkeypatch):
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    _monorepo(tmp_path, _PYPROJECT)
    out = tmp_path / "sweep.json"
    argv = ["slop-detector", "boundary-violations", str(tmp_path), "--json", "-o", str(out)]
    with patch.object(sys, "argv", argv):
        assert main() == 0
    summary = json.loads(out.read_text(encoding="utf-8"))["summary"]
    assert "graph_coverage" in summary, "sweep summary does not disclose import resolution"
    assert summary["graph_coverage"]["conditional_internal"] == 1


# ---------------------------------------------------------------------------
# Revision 6 controls (one owner per finding, written before the fix)
# ---------------------------------------------------------------------------


def test_relative_import_beyond_top_level_package_is_not_an_edge(tmp_path):
    """R6-02: CPython raises here; a project-root decoy must not become an edge."""
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from .. import x\n")
    _write(tmp_path, "x.py", "X = 1\n")
    report = _analyze(tmp_path)
    assert _graph(tmp_path, report).get("pkg/a.py", []) == []
    states = {e.resolution_state for e in _edges_from(tmp_path, report, "pkg/a.py")}
    assert states == {"unresolved_internal"}


def test_relative_import_two_levels_inside_package_resolves(tmp_path):
    """R6-02 PRESERVATION (positive control): climbing inside the package is valid."""
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/sub/__init__.py")
    _write(tmp_path, "pkg/sub/b.py", "from .. import y\n")
    _write(tmp_path, "pkg/y.py", "Y = 1\n")
    assert _graph(tmp_path, _analyze(tmp_path)).get("pkg/sub/b.py", []) == ["pkg/y.py"]


def test_cross_file_text_counts_unresolved_internal_as_unchecked(tmp_path, capsys):
    """R6-03: an unresolved internal import must not read as a clean result."""
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import missing_mod\n")
    argv = ["slop-detector", "--project", str(tmp_path), "--cross-file", "--no-history"]
    with patch.object(sys, "argv", argv):
        main()
    out = capsys.readouterr().out
    assert "1 unresolved internal" in out
    assert "[+] No cross-file issues detected." not in out


def test_sweep_summary_flags_graph_evidence_completeness(tmp_path, monkeypatch):
    """R6-03: verdict semantics unchanged; completeness is disclosed separately."""
    monkeypatch.delenv("SLOP_CONFIG", raising=False)

    def summary_for(project: Path) -> dict:
        out = tmp_path / f"{project.name}.json"
        argv = ["slop-detector", "boundary-violations", str(project), "--json", "-o", str(out)]
        with patch.object(sys, "argv", argv):
            assert main() == 0
        return json.loads(out.read_text(encoding="utf-8"))["summary"]

    incomplete, complete = tmp_path / "mono", tmp_path / "flat"
    _monorepo(incomplete, _PYPROJECT)
    _write(complete, "pkg/__init__.py")
    _write(complete, "pkg/b.py", "B = 1\n")
    _write(complete, "pkg/a.py", "from pkg import b\n")
    assert summary_for(incomplete).get("graph_evidence_complete") is False
    assert summary_for(complete).get("graph_evidence_complete") is True


def test_cycle_closed_by_function_level_import_is_reported(tmp_path):
    """R6-04: a deferred import runs when the function is called; the cycle is real."""
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/a.py", "from pkg import b\n")
    _write(tmp_path, "pkg/b.py", "def f():\n    from pkg import a\n    return a\n")
    cycles = [sorted(Path(p).name for p in c.cycle) for c in _analyze(tmp_path).import_cycles]
    assert cycles == [["a.py", "b.py"]]


def test_deep_namespace_package_is_resolved_without_depth_limit(tmp_path):
    """R6-05: CPython has no depth limit for namespace portions; neither may we."""
    _write(tmp_path, "pyproject.toml", _pyproject_where("src"))
    _write(tmp_path, "src/ns/a/b/c/d/e/mod.py", "X = 1\n")
    _write(tmp_path, "src/app/__init__.py")
    use = _write(tmp_path, "src/app/use.py", "from ns.a.b.c.d.e import mod\n\nV = mod.X\n")
    _write(tmp_path, "src/app/use2.py", "from ns import a\n")
    assert _phantoms(use) == []
    report = _analyze(tmp_path)
    states = {e.resolution_state for e in _edges_from(tmp_path, report, "src/app/use2.py")}
    assert states == {"resolved"}


def test_dynamic_getattr_without_submodule_is_ambiguous(tmp_path):
    """R6-06: the package __init__ runs (resolved); the requested name is undecidable."""
    _write(tmp_path, "pkg/__init__.py", "def __getattr__(n):\n    return n\n")
    _write(tmp_path, "user.py", "from pkg import thing\n")
    report = _analyze(tmp_path)
    assert _graph(tmp_path, report).get("user.py", []) == ["pkg/__init__.py"]
    states = sorted(e.resolution_state for e in _edges_from(tmp_path, report, "user.py"))
    assert states == ["ambiguous", "resolved"]


def test_tomli_is_declared_for_python_below_311():
    """R6-01: declared module roots need a TOML reader on Python 3.8-3.10."""
    from slop_detector.project_resolution import load_pyproject

    repo_root = Path(__file__).resolve().parents[1]
    dependencies = load_pyproject(repo_root).get("project", {}).get("dependencies", [])
    normalized = [d.replace(" ", "").replace("'", '"') for d in dependencies]
    assert any(
        d.startswith("tomli") and 'python_version<"3.11"' in d for d in normalized
    ), "tomli is not declared for Python < 3.11"


def test_namespace_package_is_listed_as_internal_name(tmp_path):
    """Owner of top-level name listing (manifest hygiene, internal vs external)."""
    from slop_detector.project_resolution import discover_project_packages

    _write(tmp_path, "pyproject.toml", _pyproject_where("src"))
    _write(tmp_path, "src/ns_pkg/feature/__init__.py")
    _write(tmp_path, "src/datafiles/table.csv", "a\n")
    names = discover_project_packages(tmp_path)
    assert "ns_pkg" in names
    assert "datafiles" not in names


# ---------------------------------------------------------------------------
# Revision 7 controls (written before the fix)
# ---------------------------------------------------------------------------


def test_intermediate_module_shadows_directory(tmp_path):
    """R7-01: `foo.py` beats `foo/` (no __init__); `import foo.bar` fails in CPython."""
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    _write(tmp_path, "foo.py", "F = 1\n")
    _write(tmp_path, "foo/bar.py", "B = 1\n")
    _write(tmp_path, "user.py", "import foo.bar\n")
    report = _analyze(tmp_path)
    assert "foo/bar.py" not in _graph(tmp_path, report).get("user.py", [])
    states = {e.resolution_state for e in _edges_from(tmp_path, report, "user.py")}
    assert states == {"unresolved_internal"}


def test_module_on_later_root_beats_namespace_portion(tmp_path):
    """R7-01: namespace portions count only when no root provides a module or package."""
    _write(tmp_path, "pyproject.toml", _pyproject_where("root_a", "root_b"))
    _write(tmp_path, "root_a/ns/x.py", "X = 1\n")
    _write(tmp_path, "root_b/ns.py", "N = 1\n")
    _write(tmp_path, "root_b/app/__init__.py")
    _write(tmp_path, "root_b/app/u1.py", "import ns\n")
    _write(tmp_path, "root_b/app/u2.py", "import ns.x\n")
    report = _analyze(tmp_path)
    graph = _graph(tmp_path, report)
    assert graph.get("root_b/app/u1.py", []) == ["root_b/ns.py"]
    assert graph.get("root_b/app/u2.py", []) == []


def test_src_holding_only_a_deep_namespace_is_a_module_root(tmp_path):
    """R7-02: the source scan that decides E2 has no depth limit."""
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    _write(tmp_path, "src/ns/a/b/c/d/e/mod.py", "def run():\n    return 1\n")
    use = _write(
        tmp_path,
        "src/ns/a/b/c/d/e/use.py",
        "from ns.a.b.c.d.e import mod\n\n\ndef go():\n    return mod.run()\n",
    )
    graph = _graph(tmp_path, _analyze(tmp_path))
    assert graph.get("src/ns/a/b/c/d/e/use.py", []) == ["src/ns/a/b/c/d/e/mod.py"]
    assert _phantoms(use) == []


def test_deep_namespace_is_not_an_undeclared_dependency(tmp_path, monkeypatch):
    """R7-02: manifest hygiene must see a deep namespace as internal."""
    monkeypatch.delenv("SLOP_CONFIG", raising=False)
    _write(tmp_path, "pyproject.toml", _PYPROJECT + 'dependencies = ["pyyaml>=6"]\n')
    _write(tmp_path, "src/ns/a/b/c/d/e/mod.py", "def run():\n    return 1\n")
    _write(
        tmp_path,
        "src/ns/a/b/c/d/e/use.py",
        "import yaml\nfrom ns.a.b.c.d.e import mod\n\n\n"
        "def go():\n    return mod.run(), yaml.safe_load('a: 1')\n",
    )
    out = tmp_path / "deps.json"
    argv = ["slop-detector", "unused-deps", str(tmp_path), "--json", "-o", str(out)]
    with patch.object(sys, "argv", argv):
        main()
    issues = json.loads(out.read_text(encoding="utf-8"))["issues"]
    undeclared = [i.get("dependency") for i in issues if i.get("issue_type") == "undeclared_import"]
    assert "ns" not in undeclared


def test_explicit_setuptools_packages_list_does_not_break_resolution(tmp_path):
    """Shape, not just parse: `[tool.setuptools] packages = [...]` is a list, not a table.

    Regression found while measuring R7 on a real repository (graphify): the shared
    resolver raised AttributeError, which reached both phantom_import and the graph.
    """
    _write(
        tmp_path,
        "pyproject.toml",
        _PYPROJECT + '\n[tool.setuptools]\npackages = ["pkg", "pkg.sub"]\n',
    )
    _write(tmp_path, "pkg/__init__.py")
    _write(tmp_path, "pkg/b.py", "B = 1\n")
    a = _write(tmp_path, "pkg/a.py", "from pkg import b\nfrom ai_quantum_reasoning import X\n")
    assert len(_phantoms(a)) == 1
    assert _graph(tmp_path, _analyze(tmp_path)).get("pkg/a.py", []) == ["pkg/b.py"]


def test_top_level_module_file_under_a_root_is_not_phantom(tmp_path):
    """Owner of phantom_import's exact-path check: a module FILE (not a package
    directory) at the top of a module root, imported from another directory."""
    _write(tmp_path, "pyproject.toml", _PYPROJECT)
    _write(tmp_path, "src/helpers.py", "def h():\n    return 1\n")
    _write(tmp_path, "src/pkg/__init__.py")
    a = _write(tmp_path, "src/pkg/a.py", "import helpers\n\nV = helpers.h()\n")
    assert _phantoms(a) == []
