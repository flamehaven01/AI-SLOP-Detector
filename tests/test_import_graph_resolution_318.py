"""The import graph follows the 3.18 module roots and scan boundary.

3.18.0 changed project module resolution (project_resolution.py): a directory
that is itself a regular package is not a module root, and a link that leads
out of the scan root is not followed. The import graph resolves through the
same ProjectModuleIndex, so it changed with it; these controls pin the graph's
side of that contract. Measured against the 3.17.0 source:

- `import fhir` inside regular package `pkg` (holding `pkg/fhir/`):
  conditional_internal (E4, pkg/fhir) in 3.17.0, external in 3.18.0. It was
  never a hard edge, so the hard graph is unchanged by it.
- `import extmod` where `extmod` is a link to a directory outside the project:
  resolved (hard edge) in 3.17.0, external in 3.18.0.
- relative imports, qualified package names, an explicitly declared root (E1,
  setuptools `where`), the conventional `src` root (E2) and a
  monorepo conditional root (`backend/app`) resolve as before.

"external" means no target was found under the observed module roots; it is not
evidence that an installed distribution provides the name.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

import pytest

from slop_detector.analysis.import_graph import (
    ImportEdge,
    build_import_edges,
    coverage,
    hard_graph,
    unchecked_imports,
)


def _tree(root: Path, files: Dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _edges(root: Path) -> List[ImportEdge]:
    return build_import_edges(root, sorted(root.rglob("*.py")))


def _edge(edges: List[ImportEdge], importer: str, requested: str, level: int = 0) -> ImportEdge:
    found = [
        e
        for e in edges
        if Path(e.importer).name == importer
        and e.requested_module == requested
        and e.relative_level == level
    ]
    assert len(found) == 1, (importer, requested, level, edges)
    return found[0]


def _target(root: Path, edge: ImportEdge) -> str:
    assert edge.imported is not None
    return Path(edge.imported).resolve().relative_to(root.resolve()).as_posix()


def _link_dir(link: Path, target: Path) -> None:
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi  # type: ignore[import-not-found]

        _winapi.CreateJunction(str(target), str(link))  # no privilege needed on Windows
    except (ImportError, OSError, AttributeError):
        pytest.skip("cannot create a directory link here")


PACKAGE = {
    "pkg/__init__.py": "",
    "pkg/fhir/__init__.py": "",
    "pkg/a.py": "import fhir\nfrom . import fhir as f2\nimport pkg.fhir\n",
}


def test_a_subpackage_is_not_a_top_level_name(tmp_path):
    edges = _edges(_tree(tmp_path, PACKAGE))
    edge = _edge(edges, "a.py", "fhir")
    assert edge.resolution_state == "external"
    assert edge.imported is None
    assert edge.root_authority == "none"


def test_a_relative_import_still_reaches_the_subpackage(tmp_path):
    root = _tree(tmp_path, PACKAGE)
    edge = _edge(_edges(root), "a.py", "", level=1)
    assert edge.resolution_state == "resolved"
    assert _target(root, edge) == "pkg/fhir/__init__.py"


def test_the_qualified_name_still_reaches_the_subpackage(tmp_path):
    root = _tree(tmp_path, PACKAGE)
    edge = _edge(_edges(root), "a.py", "pkg.fhir")
    assert edge.resolution_state == "resolved"
    assert _target(root, edge) == "pkg/fhir/__init__.py"


def test_the_hard_graph_of_the_package_is_its_resolved_edges(tmp_path):
    root = _tree(tmp_path, PACKAGE)
    graph = hard_graph(_edges(root))
    importer = next(k for k in graph if Path(k).name == "a.py")
    assert {Path(t).resolve().relative_to(root.resolve()).as_posix() for t in graph[importer]} == {
        "pkg/fhir/__init__.py"
    }


def test_an_explicitly_declared_root_resolves(tmp_path):
    root = _tree(
        tmp_path,
        {
            "pyproject.toml": (
                "[project]\nname = 'm'\n\n[tool.setuptools.packages.find]\nwhere = [\"lib\"]\n"
            ),
            "lib/mylib/__init__.py": "",
            "lib/mylib/util.py": "",
            "lib/mylib/core.py": "import mylib.util\n",
        },
    )
    edge = _edge(_edges(root), "core.py", "mylib.util")
    assert edge.resolution_state == "resolved"
    assert edge.root_authority == "E1"
    assert _target(root, edge) == "lib/mylib/util.py"


def test_a_conventional_src_root_resolves(tmp_path):
    root = _tree(
        tmp_path,
        {
            "pyproject.toml": "[project]\nname = 'm'\n",
            "src/mylib/__init__.py": "",
            "src/mylib/util.py": "",
            "src/mylib/core.py": "import mylib.util\n",
        },
    )
    edge = _edge(_edges(root), "core.py", "mylib.util")
    assert edge.resolution_state == "resolved"
    assert edge.root_authority == "E2"
    assert _target(root, edge) == "src/mylib/util.py"


def test_a_monorepo_root_stays_conditional(tmp_path):
    root = _tree(
        tmp_path,
        {
            "backend/app/__init__.py": "",
            "backend/app/models.py": "",
            "backend/app/x.py": "import app.models\n",
        },
    )
    edge = _edge(_edges(root), "x.py", "app.models")
    assert edge.resolution_state == "conditional_internal"
    assert edge.root_authority == "E4"
    assert _target(root, edge) == "backend/app/models.py"


def test_a_link_out_of_the_scan_root_is_not_an_edge(tmp_path):
    outside = _tree(tmp_path / "outside", {"extmod/__init__.py": ""})
    root = _tree(tmp_path / "project", {"main.py": "import extmod\n"})
    _link_dir(root / "extmod", outside / "extmod")
    edges = _edges(root)
    edge = _edge(edges, "main.py", "extmod")
    assert edge.resolution_state == "external"
    assert edge.imported is None
    assert all(not targets for targets in hard_graph(edges).values())


def test_coverage_counts_the_changed_states(tmp_path):
    edges = _edges(_tree(tmp_path, PACKAGE))
    counts = coverage(edges)
    assert counts["external"] == 1
    assert counts["resolved"] == 2
    assert counts["conditional_internal"] == 0
    assert unchecked_imports(counts) == 0
