"""Connection evidence for top-level functions and classes (Graph Rebind Phase 1).

Candidate-only: `structure_evidence.connections` says, per top-level symbol,
what connects it. It is computed only with `--cross-file`, never produces a
finding, and never moves a score or a status. Methods are not evaluated.

States, highest first:

    connected               an internal call, reference, registry entry, or a
                            known registration decorator reaches the symbol
    externally_exposed      no internal connection, but `__all__`, a package
                            re-export, or a pyproject script/entry point
    dynamic_unknown         the code reaches names dynamically (getattr with a
                            computed name, importlib, globals(), an unknown
                            decorator, the name as a string), so static
                            evidence cannot decide
    unmeasured              evidence this symbol needs could not be collected
                            (an unresolved import or unparsed file that may
                            name it). An unrelated gap changes nothing.
    disconnected_candidate  the collectors ran and found none of the above

`test_referenced` is recorded beside the state; tests never change it.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List
from unittest.mock import patch

import pytest

from slop_detector.analysis.cross_file import CrossFileAnalyzer

STATES = {
    "connected",
    "externally_exposed",
    "dynamic_unknown",
    "unmeasured",
    "disconnected_candidate",
}


def _write(root: Path, rel: str, text: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _files(root: Path):
    return [
        SimpleNamespace(file_path=str(p), deficit_score=0.0) for p in sorted(root.rglob("*.py"))
    ]


def _connections(root: Path) -> dict:
    report = CrossFileAnalyzer().analyze(str(root), _files(root), connections=True)
    block = report.to_dict()["structure_evidence"].get("connections")
    assert isinstance(block, dict), "no structure_evidence.connections block"
    return block


def _row(root: Path, rel: str, name: str) -> dict:
    block = _connections(root)
    wanted = (root / rel).resolve()
    rows = [
        r for r in block["symbols"] if Path(r["file"]).resolve() == wanted and r["name"] == name
    ]
    assert len(rows) == 1, (rel, name, [(r["file"], r["name"]) for r in block["symbols"]])
    return rows[0]


@pytest.fixture
def root(tmp_path_factory):
    proj = tmp_path_factory.mktemp("proj")
    _write(proj, "pkg/__init__.py")
    return proj


# ---------------------------------------------------------------------------
# Block shape
# ---------------------------------------------------------------------------


def test_block_shape_and_score_effect(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n\n\nclass C:\n    pass\n")
    block = _connections(root)
    assert block["score_effect"] == "none"
    assert block["scope"] == "top_level_functions_and_classes"
    assert {r["state"] for r in block["symbols"]} <= STATES
    summary = block["summary"]
    assert summary["candidates"] == len(block["symbols"])
    assert sum(summary[s] for s in STATES) == summary["candidates"]
    for row in block["symbols"]:
        assert {
            "file",
            "name",
            "kind",
            "line",
            "state",
            "evidence_kinds",
            "test_referenced",
            "reasons",
        } <= set(row)
        assert row["kind"] in {"function", "class"}
    assert "unresolved_reasons" in block


# ---------------------------------------------------------------------------
# connected
# ---------------------------------------------------------------------------


def test_same_module_call_connects(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n\n\ndef g():\n    return f()\n")
    assert _row(root, "pkg/a.py", "f")["state"] == "connected"
    assert _row(root, "pkg/a.py", "f")["evidence_kinds"] == ["direct_call"]
    assert _row(root, "pkg/a.py", "g")["state"] == "disconnected_candidate"


def test_main_guard_call_connects(root):
    _write(
        root, "pkg/a.py", "def main():\n    return 1\n\n\nif __name__ == '__main__':\n    main()\n"
    )
    assert _row(root, "pkg/a.py", "main")["state"] == "connected"


def test_recursion_alone_is_not_a_connection(root):
    _write(root, "pkg/a.py", "def f(n):\n    return f(n - 1) if n else 0\n")
    assert _row(root, "pkg/a.py", "f")["state"] == "disconnected_candidate"


def test_aliased_from_import_call_connects(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", "from pkg.a import f as g\n\ng()\n")
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "connected"
    assert row["evidence_kinds"] == ["direct_call"]


def test_relative_from_import_call_connects(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", "from .a import f\n\n\ndef run():\n    return f()\n")
    assert _row(root, "pkg/a.py", "f")["state"] == "connected"


@pytest.mark.parametrize(
    "consumer",
    ["import pkg.a as x\n\nx.f()\n", "from pkg import a\n\na.f()\n", "import pkg.a\n\npkg.a.f()\n"],
    ids=["import-as", "from-package-import-module", "dotted-import"],
)
def test_module_attribute_call_connects(root, consumer):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", consumer)
    assert _row(root, "pkg/a.py", "f")["state"] == "connected"


def test_reference_without_call_connects(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", "from pkg.a import f\n\n\ndef run(apply):\n    return apply(f)\n")
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "connected"
    assert row["evidence_kinds"] == ["direct_reference"]


def test_import_without_use_is_not_a_connection(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", "from pkg.a import f\n")
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "disconnected_candidate"
    assert row["evidence_kinds"] == []


@pytest.mark.parametrize(
    "registry",
    ['HANDLERS = {"x": f}\n', "HANDLERS = [f]\n", "HANDLERS = (f,)\n"],
    ids=["dict-value", "list", "tuple"],
)
def test_registry_entry_connects(root, registry):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", "from pkg.a import f\n\n" + registry)
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "connected"
    assert row["evidence_kinds"] == ["registry_reference"]


@pytest.mark.parametrize(
    "decorator",
    [
        "@app.route('/')",
        "@app.get('/items')",
        "@router.post('/items')",
        "@click.command()",
        "@cli.group()",
        "@celery.task",
        "@registry.register",
        "@pytest.fixture",
        "@pytest.fixture(scope='session')",
        "@hookimpl",
        "@pytest.hookimpl(tryfirst=True)",
        "@_register('bare_except')",
    ],
)
def test_known_registration_decorator_connects(root, decorator):
    _write(root, "pkg/a.py", f"{decorator}\ndef handler():\n    return 1\n")
    row = _row(root, "pkg/a.py", "handler")
    assert row["state"] == "connected"
    assert row["evidence_kinds"] == ["decorator_registration"]


@pytest.mark.parametrize(
    "header",
    [
        "from dataclasses import dataclass\n\n\n@dataclass\nclass P:\n    x: int = 0\n",
        "import functools\n\n\n@functools.lru_cache(maxsize=None)\ndef P():\n    return 1\n",
        "from functools import cache\n\n\n@cache\ndef P():\n    return 1\n",
    ],
    ids=["dataclass", "lru_cache", "cache"],
)
def test_non_registering_decorator_is_not_evidence(root, header):
    _write(root, "pkg/a.py", header)
    row = _row(root, "pkg/a.py", "P")
    assert row["state"] == "disconnected_candidate"
    assert row["evidence_kinds"] == []


def test_used_class_is_connected_and_its_methods_are_not_evaluated(root):
    _write(root, "pkg/a.py", "class Service:\n    def unused_method(self):\n        return 1\n")
    _write(root, "pkg/b.py", "from pkg.a import Service\n\nService()\n")
    block = _connections(root)
    names = {r["name"] for r in block["symbols"]}
    assert "unused_method" not in names
    assert _row(root, "pkg/a.py", "Service")["state"] == "connected"


def test_nested_function_is_not_a_candidate(root):
    _write(root, "pkg/a.py", "def outer():\n    def inner():\n        return 1\n    return inner\n")
    names = {r["name"] for r in _connections(root)["symbols"]}
    assert names == {"outer"}


# ---------------------------------------------------------------------------
# externally_exposed
# ---------------------------------------------------------------------------


def test_dunder_all_exposes(root):
    _write(root, "pkg/a.py", '__all__ = ["f"]\n\n\ndef f():\n    return 1\n')
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "externally_exposed"
    assert row["evidence_kinds"] == ["public_export"]


@pytest.mark.parametrize(
    "init", ["from pkg.a import f\n", "from .a import f\n", "from .a import f as g\n"]
)
def test_package_init_reexport_exposes(root, init):
    _write(root, "pkg/__init__.py", init)
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "externally_exposed"
    assert row["evidence_kinds"] == ["package_reexport"]


def test_use_through_a_package_reexport_connects_the_definition(root):
    _write(root, "pkg/__init__.py", "from .a import f\n")
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", "from pkg import f\n\nf()\n")
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "connected"
    assert row["evidence_kinds"] == ["direct_call", "package_reexport"]


def test_pyproject_script_exposes(root):
    _write(
        root,
        "pyproject.toml",
        '[project]\nname = "x"\n\n[project.scripts]\ntool = "pkg.cli:main"\n',
    )
    _write(root, "pkg/cli.py", "def main():\n    return 0\n")
    row = _row(root, "pkg/cli.py", "main")
    assert row["state"] == "externally_exposed"
    assert row["evidence_kinds"] == ["pyproject_script"]


def test_pyproject_entry_point_exposes(root):
    _write(
        root,
        "pyproject.toml",
        '[project]\nname = "x"\n\n[project.entry-points."pytest11"]\nplug = "pkg.plugin:Plugin"\n',
    )
    _write(root, "pkg/plugin.py", "class Plugin:\n    pass\n")
    row = _row(root, "pkg/plugin.py", "Plugin")
    assert row["state"] == "externally_exposed"
    assert row["evidence_kinds"] == ["pyproject_entry_point"]


def test_script_target_also_called_internally_is_connected_with_both_evidence(root):
    _write(
        root,
        "pyproject.toml",
        '[project]\nname = "x"\n\n[project.scripts]\ntool = "pkg.cli:main"\n',
    )
    _write(root, "pkg/cli.py", "def main():\n    return 0\n")
    _write(root, "pkg/__main__.py", "from pkg.cli import main\n\nmain()\n")
    row = _row(root, "pkg/cli.py", "main")
    assert row["state"] == "connected"
    assert row["evidence_kinds"] == ["direct_call", "pyproject_script"]


# ---------------------------------------------------------------------------
# dynamic_unknown
# ---------------------------------------------------------------------------


def test_unknown_decorator_is_dynamic(root):
    _write(
        root,
        "pkg/a.py",
        "def mystery(fn):\n    return fn\n\n\n@mystery\ndef f():\n    return 1\n",
    )
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "dynamic_unknown"
    assert any("decorator" in reason for reason in row["reasons"]), row["reasons"]
    assert _row(root, "pkg/a.py", "mystery")["state"] == "connected"


@pytest.mark.parametrize(
    "consumer",
    [
        "import pkg.a as m\n\n\ndef run(name):\n    return getattr(m, name)()\n",
        "import importlib\n\nmod = importlib.import_module('pkg.a')\n",
        "HANDLER = 'f'\n",
    ],
    ids=["getattr-computed-name", "importlib", "string-mention"],
)
def test_dynamic_access_from_another_module_is_dynamic(root, consumer):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", consumer)
    assert _row(root, "pkg/a.py", "f")["state"] == "dynamic_unknown"


@pytest.mark.parametrize(
    "tail",
    [
        "def call(name):\n    return globals()[name]()\n",
        "def __getattr__(name):\n    raise AttributeError(name)\n",
    ],
    ids=["globals", "module-getattr"],
)
def test_dynamic_namespace_in_the_defining_module_is_dynamic(root, tail):
    _write(root, "pkg/a.py", "def f():\n    return 1\n\n\n" + tail)
    assert _row(root, "pkg/a.py", "f")["state"] == "dynamic_unknown"


def test_dynamic_access_to_another_module_does_not_touch_this_one(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/c.py", "def h():\n    return 2\n")
    _write(
        root, "pkg/b.py", "import pkg.c as m\n\n\ndef run(name):\n    return getattr(m, name)()\n"
    )
    assert _row(root, "pkg/a.py", "f")["state"] == "disconnected_candidate"


# ---------------------------------------------------------------------------
# unmeasured is candidate-local
# ---------------------------------------------------------------------------


def test_unresolved_import_that_may_name_the_symbol_is_unmeasured(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", "from pkg.gone import f\n\nf()\n")
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "unmeasured"
    assert any("b.py" in reason for reason in row["reasons"]), row["reasons"]


def test_unrelated_unresolved_import_changes_nothing(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    before = _row(root, "pkg/a.py", "f")
    _write(root, "pkg/c.py", "from pkg.gone import other\n\nother()\n")
    after = _row(root, "pkg/a.py", "f")
    assert before["state"] == after["state"] == "disconnected_candidate"
    assert after["reasons"] == before["reasons"]


def test_unparsed_file_naming_the_symbol_is_unmeasured(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/broken.py", "def (:\n    f()\n")
    assert _row(root, "pkg/a.py", "f")["state"] == "unmeasured"


def test_unparsed_file_not_naming_the_symbol_changes_nothing(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/broken.py", "def (:\n    other()\n")
    assert _row(root, "pkg/a.py", "f")["state"] == "disconnected_candidate"


# ---------------------------------------------------------------------------
# precedence
# ---------------------------------------------------------------------------


def test_exposure_outranks_dynamic(root):
    _write(root, "pkg/a.py", '__all__ = ["f"]\n\n\ndef f():\n    return 1\n')
    _write(root, "pkg/b.py", "HANDLER = 'f'\n")
    assert _row(root, "pkg/a.py", "f")["state"] == "externally_exposed"


def test_dynamic_outranks_unmeasured(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "pkg/b.py", "from pkg.gone import f\n\nf()\nHANDLER = 'f'\n")
    assert _row(root, "pkg/a.py", "f")["state"] == "dynamic_unknown"


def test_connection_outranks_everything_and_keeps_all_evidence(root):
    _write(root, "pkg/a.py", '__all__ = ["f"]\n\n\ndef f():\n    return 1\n\n\nf()\n')
    _write(root, "pkg/b.py", "from pkg.gone import f as g\n\ng()\nHANDLER = 'f'\n")
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "connected"
    assert row["evidence_kinds"] == ["direct_call", "public_export"]


# ---------------------------------------------------------------------------
# tests are recorded, never counted
# ---------------------------------------------------------------------------


def test_test_only_reference_keeps_the_production_state(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "tests/test_a.py", "from pkg.a import f\n\n\ndef test_f():\n    assert f() == 1\n")
    row = _row(root, "pkg/a.py", "f")
    assert row["state"] == "disconnected_candidate"
    assert row["test_referenced"] is True
    assert row["evidence_kinds"] == []


def test_test_files_hold_no_candidates(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "tests/test_a.py", "def test_x():\n    assert True\n")
    _write(root, "tests/conftest.py", "def helper():\n    return 1\n")
    files = {Path(r["file"]).name for r in _connections(root)["symbols"]}
    assert files == {"a.py"}


# ---------------------------------------------------------------------------
# no score or status effect, no default cost
# ---------------------------------------------------------------------------


def test_scores_and_statuses_are_bit_for_bit_unchanged(root):
    from slop_detector.core import SlopDetector

    _write(root, "pkg/a.py", "def f():\n    return 1\n\n\ndef g(x):\n    return x * 2\n")
    _write(root, "pkg/b.py", "from pkg.a import f\n\nf()\n")
    project = SlopDetector(read_only=True).analyze_project(str(root))
    before = copy.deepcopy(project.to_dict())
    CrossFileAnalyzer().analyze(str(root), project.file_results, connections=True)
    assert project.to_dict() == before


def _boom(*_args, **_kwargs):
    raise AssertionError("connection collector ran without --cross-file")


def test_default_analysis_has_no_connections_and_runs_no_collector(root):
    from slop_detector.analysis import connection_evidence

    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    with patch.object(connection_evidence, "build_connections", _boom):
        report = CrossFileAnalyzer().analyze(str(root), _files(root))
    assert "connections" not in report.to_dict()["structure_evidence"]


def test_default_scan_and_sweep_run_no_collector(root, tmp_path, capsys):
    from slop_detector.analysis import connection_evidence
    from slop_detector.cli import main

    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    out = tmp_path / "sweep.json"
    with patch.object(connection_evidence, "build_connections", _boom):
        main([str(root), "--no-history"])
        argv = ["slop-detector", "dead-code", str(root), "--json", "-o", str(out)]
        with patch.object(sys, "argv", argv):
            main()
    assert '"connections"' not in out.read_text(encoding="utf-8")


def test_cross_file_cli_shows_candidates(root, capsys):
    from slop_detector.analysis import connection_evidence
    from slop_detector.cli import main

    _write(
        root,
        "pkg/a.py",
        "def lonely_helper():\n    return 1\n\n\ndef used():\n    return 2\n\n\nused()\n",
    )
    calls: List[int] = []
    real = connection_evidence.build_connections

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    with patch.object(connection_evidence, "build_connections", spy):
        main([str(root), "--no-history", "--cross-file"])
    text = capsys.readouterr().out
    assert calls == [1]
    assert "Connections" in text
    assert "lonely_helper" in text
    assert "candidate" in text.lower()


# ---------------------------------------------------------------------------
# evidence sources outside the scanned set
# ---------------------------------------------------------------------------


def test_unscanned_package_init_still_counts_as_a_reexport(root):
    """The default config skips `**/__init__.py`; its re-exports are still evidence."""
    _write(root, "pkg/__init__.py", "from .a import f\n\n\ndef init_helper():\n    return 1\n")
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    scanned = [SimpleNamespace(file_path=str(root / "pkg" / "a.py"), deficit_score=0.0)]
    report = CrossFileAnalyzer().analyze(str(root), scanned, connections=True)
    block = report.to_dict()["structure_evidence"]["connections"]
    rows = {r["name"]: r for r in block["symbols"]}
    assert set(rows) == {"f"}
    assert rows["f"]["state"] == "externally_exposed"
    assert rows["f"]["evidence_kinds"] == ["package_reexport"]


def test_summary_says_how_many_test_files_were_seen(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    assert _connections(root)["summary"]["test_files_seen"] == 0
    _write(root, "tests/test_a.py", "def test_x():\n    assert True\n")
    assert _connections(root)["summary"]["test_files_seen"] == 1


# ---------------------------------------------------------------------------
# found by the 9-repo measurement: resolution the import graph cannot make
# ---------------------------------------------------------------------------


def test_script_directory_import_is_unmeasured_only_for_its_target(root):
    """`from helper import run` beside helper.py resolves only with the script dir on sys.path."""
    _write(root, "scripts/helper.py", "def run():\n    return 1\n")
    _write(root, "scripts/tool.py", "from helper import run\n\nrun()\n")
    _write(root, "pkg/a.py", "def run():\n    return 2\n")
    row = _row(root, "scripts/helper.py", "run")
    assert row["state"] == "unmeasured"
    assert any(r.startswith("unrooted_import:") for r in row["reasons"]), row["reasons"]
    assert _row(root, "pkg/a.py", "run")["state"] == "disconnected_candidate"


def test_app_root_import_is_unmeasured(root):
    _write(root, "app/backend/storage/db.py", "def list_runs():\n    return []\n")
    _write(root, "app/backend/routes/r.py", "from storage.db import list_runs\n\nlist_runs()\n")
    assert _row(root, "app/backend/storage/db.py", "list_runs")["state"] == "unmeasured"


def test_module_attribute_through_an_unrooted_import_is_unmeasured(root):
    _write(root, "scripts/utils.py", "def scale(x):\n    return x\n")
    _write(root, "scripts/run.py", "import utils\n\nutils.scale(2)\n")
    assert _row(root, "scripts/utils.py", "scale")["state"] == "unmeasured"


def test_installed_plugin_package_import_is_unmeasured(root):
    _write(root, "plugins/p/src/plug/__init__.py")
    _write(root, "plugins/p/src/plug/chunk.py", "def build():\n    return 1\n")
    _write(root, "app/x.py", "from plug.chunk import build\n\nbuild()\n")
    assert _row(root, "plugins/p/src/plug/chunk.py", "build")["state"] == "unmeasured"


def test_package_scan_through_dunder_path_is_dynamic(root):
    _write(root, "pkg/checks/__init__.py")
    _write(root, "pkg/checks/disk.py", "class DiskCheck:\n    pass\n")
    _write(root, "pkg/other.py", "def lonely():\n    return 1\n")
    _write(
        root,
        "pkg/runner.py",
        "import pkgutil\nimport pkg.checks as checks\n\n"
        "NAMES = [n for _, n, _ in pkgutil.iter_modules(checks.__path__)]\n",
    )
    assert _row(root, "pkg/checks/disk.py", "DiskCheck")["state"] == "dynamic_unknown"
    assert _row(root, "pkg/other.py", "lonely")["state"] == "disconnected_candidate"


def test_import_module_with_a_package_name_prefix_is_dynamic(root):
    _write(root, "pkg/checks/__init__.py")
    _write(root, "pkg/checks/disk.py", "class DiskCheck:\n    pass\n")
    _write(root, "pkg/other.py", "def lonely():\n    return 1\n")
    _write(
        root,
        "pkg/runner.py",
        "import importlib\nimport pkg.checks as checks\n\n\n"
        "def load(name):\n    return importlib.import_module(f'{checks.__name__}.{name}')\n",
    )
    assert _row(root, "pkg/checks/disk.py", "DiskCheck")["state"] == "dynamic_unknown"
    assert _row(root, "pkg/other.py", "lonely")["state"] == "disconnected_candidate"


def test_escaped_module_attribute_is_dynamic_only_for_the_accessed_name(root):
    _write(
        root, "pkg/engine.py", "def get_defs():\n    return {}\n\n\ndef other():\n    return 1\n"
    )
    _write(
        root,
        "pkg/runner.py",
        "from pkg import engine\n\nMODULES = [engine]\n\n\n"
        "def collect():\n    return [m.get_defs() for m in MODULES]\n",
    )
    assert _row(root, "pkg/engine.py", "get_defs")["state"] == "dynamic_unknown"
    assert _row(root, "pkg/engine.py", "other")["state"] == "disconnected_candidate"


def test_package_importing_its_own_submodule_by_absolute_name(root):
    _write(root, "pkg/proto/__init__.py", "from pkg.proto import engine\n\nengine.start()\n")
    _write(root, "pkg/proto/engine.py", "def start():\n    return 1\n")
    assert _row(root, "pkg/proto/engine.py", "start")["state"] == "connected"


def test_unrooted_import_never_lands_on_the_importer_itself(root):
    """`from auth import helper` inside routes/auth.py does not mean routes/auth.py."""
    _write(root, "app/auth/helper.py", "def run():\n    return 1\n")
    _write(
        root,
        "app/routes/auth.py",
        "from auth import helper\n\nhelper.run()\n\n\ndef run():\n    return 2\n",
    )
    assert _row(root, "app/auth/helper.py", "run")["state"] == "unmeasured"
    assert _row(root, "app/routes/auth.py", "run")["state"] == "disconnected_candidate"


def test_export_through_an_unrooted_import_is_unmeasured(root):
    _write(
        root,
        "ext/src/plug/__init__.py",
        'from plug.adapter import Adapter\n\n__all__ = ["Adapter"]\n',
    )
    _write(root, "ext/src/plug/adapter.py", "class Adapter:\n    pass\n")
    assert _row(root, "ext/src/plug/adapter.py", "Adapter")["state"] == "unmeasured"


def test_module_path_built_from_a_string_prefix_is_dynamic(root):
    _write(root, "pkg/parts/__init__.py")
    _write(root, "pkg/parts/md.py", "def partition_md():\n    return []\n")
    _write(root, "pkg/other.py", "def lonely():\n    return 1\n")
    _write(root, "pkg/kinds.py", "def qname(short):\n    return f'pkg.parts.{short}'\n")
    _write(
        root,
        "pkg/loader.py",
        "import importlib\n\n\ndef load(kind):\n    return importlib.import_module(kind.qname)\n",
    )
    assert _row(root, "pkg/parts/md.py", "partition_md")["state"] == "dynamic_unknown"
    assert _row(root, "pkg/other.py", "lonely")["state"] == "disconnected_candidate"


def test_eval_makes_its_own_module_dynamic(root):
    _write(
        root,
        "pkg/a.py",
        "class TensorCP:\n    pass\n\n\ndef build(name):\n    return eval(name)()\n",
    )
    _write(root, "pkg/other.py", "def lonely():\n    return 1\n")
    assert _row(root, "pkg/a.py", "TensorCP")["state"] == "dynamic_unknown"
    assert _row(root, "pkg/other.py", "lonely")["state"] == "disconnected_candidate"


def test_a_dotted_module_name_string_is_dynamic_but_a_single_word_is_not(root):
    _write(root, "pkg/parts/__init__.py")
    _write(root, "pkg/parts/md.py", "def partition_md():\n    return []\n")
    _write(root, "config.py", "def load():\n    return {}\n")
    _write(root, "pkg/table.py", 'TARGET = "pkg.parts.md"\nKEYS = {"config": 1}\n')
    assert _row(root, "pkg/parts/md.py", "partition_md")["state"] == "dynamic_unknown"
    assert _row(root, "config.py", "load")["state"] == "disconnected_candidate"


# ---------------------------------------------------------------------------
# Phase 1 semantic closure
# ---------------------------------------------------------------------------


def _scanned_without_tests(root: Path):
    """The default configuration skips tests/**: the scan never lists them."""
    return [
        SimpleNamespace(file_path=str(p), deficit_score=0.0)
        for p in sorted(root.rglob("*.py"))
        if "tests" not in p.relative_to(root).parts
    ]


def test_tests_outside_the_scan_are_read_as_evidence_only(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n\n\ndef g():\n    return 2\n")
    _write(root, "tests/test_a.py", "from pkg.a import f\n\n\ndef test_f():\n    assert f() == 1\n")
    report = CrossFileAnalyzer().analyze(str(root), _scanned_without_tests(root), connections=True)
    block = report.to_dict()["structure_evidence"]["connections"]
    rows = {r["name"]: r for r in block["symbols"]}
    assert set(rows) == {"f", "g"}  # no candidate from a test file
    assert rows["f"]["state"] == "disconnected_candidate"
    assert rows["f"]["test_referenced"] is True
    assert rows["g"]["test_referenced"] is False
    assert block["summary"]["test_files_seen"] == 1


def test_cross_file_cli_marks_test_only_candidates(root, capsys):
    from slop_detector.cli import main

    _write(root, "pkg/a.py", "def lonely_helper():\n    return 1\n")
    _write(
        root,
        "tests/test_a.py",
        "from pkg.a import lonely_helper\n\n\ndef test_it():\n    lonely_helper()\n",
    )
    main([str(root), "--no-history", "--cross-file"])
    text = capsys.readouterr().out
    assert "lonely_helper (referenced by tests)" in text
    assert "Test files were not in the scan" not in text


@pytest.mark.parametrize(
    "rel,text",
    [
        ("deploy/serve.yaml", "connector: MyConnector\nreplicas: 2\n"),
        ("deploy/serve.toml", 'plugin = "pkg.conn:MyConnector"\n'),
        (
            ".buildkite/configs/serve.yaml",
            'args:\n    - \'{"kv_connector":"MyConnector","kv_role":"both"}\'\n',
        ),
    ],
    ids=["yaml-value", "toml-dotted-path", "ci-dir-json-in-yaml"],
)
def test_a_config_value_naming_the_symbol_is_external_dynamic(root, rel, text):
    _write(root, "pkg/conn.py", "class MyConnector:\n    pass\n\n\nclass Other:\n    pass\n")
    _write(root, rel, text)
    row = _row(root, "pkg/conn.py", "MyConnector")
    assert row["state"] == "dynamic_unknown"
    assert any(r.startswith("external_config_reference:") for r in row["reasons"]), row["reasons"]
    assert _row(root, "pkg/conn.py", "Other")["state"] == "disconnected_candidate"


@pytest.mark.parametrize(
    "rel",
    ["results/graph.json", ".mypy_cache/3.12/pkg/conn.data.yaml", ".venv/lib/conf.yaml"],
    ids=["json-is-data", "cache-dir", "environment-dir"],
)
def test_data_and_tool_directories_are_not_configuration(root, rel):
    _write(root, "pkg/conn.py", "class MyConnector:\n    pass\n")
    _write(root, rel, '{"label": "MyConnector"}\nname: MyConnector\n')
    assert _row(root, "pkg/conn.py", "MyConnector")["state"] == "disconnected_candidate"


def test_an_unresolved_import_in_a_test_file_changes_nothing(root):
    _write(root, "pkg/a.py", "def f():\n    return 1\n")
    _write(root, "tests/test_a.py", "from pkg.gone import f\n\n\ndef test_f():\n    f()\n")
    report = CrossFileAnalyzer().analyze(str(root), _scanned_without_tests(root), connections=True)
    rows = report.to_dict()["structure_evidence"]["connections"]["symbols"]
    assert [r["state"] for r in rows if r["name"] == "f"] == ["disconnected_candidate"]


def test_a_name_inside_config_prose_is_not_a_reference(root):
    _write(root, "pkg/a.py", "def run():\n    return 1\n")
    _write(root, "ci/job.yaml", "steps:\n  - name: please run the job and check\n")
    assert _row(root, "pkg/a.py", "run")["state"] == "disconnected_candidate"


def test_an_import_inside_a_code_template_string_is_dynamic(root):
    _write(
        root,
        "pkg/watch.py",
        "def apply_limits():\n    return 1\n\n\ndef unrelated():\n    return 2\n",
    )
    _write(
        root,
        "pkg/hooks.py",
        'HOOK = """\\n#!/bin/sh\npython -c "\nfrom pkg.watch import apply_limits\napply_limits()\n"\n"""\n',
    )
    row = _row(root, "pkg/watch.py", "apply_limits")
    assert row["state"] == "dynamic_unknown"
    assert any(r.startswith("code_in_string:") for r in row["reasons"]), row["reasons"]
    assert _row(root, "pkg/watch.py", "unrelated")["state"] == "disconnected_candidate"


def test_an_import_in_a_docstring_is_not_code(root):
    _write(root, "pkg/watch.py", "def apply_limits():\n    return 1\n")
    _write(
        root,
        "pkg/doc.py",
        'def f():\n    """Example:\n\n    from pkg.watch import apply_limits\n    """\n    return 1\n\n\nf()\n',
    )
    assert _row(root, "pkg/watch.py", "apply_limits")["state"] == "disconnected_candidate"


HOLD = "public_api_of_distributable_package"


def test_public_api_of_a_distributable_package_is_held(root):
    _write(root, "pyproject.toml", '[project]\nname = "pkg"\nversion = "0"\n')
    _write(root, "pkg/api.py", "def clean():\n    return 1\n\n\ndef _private():\n    return 2\n")
    _write(root, "scripts/tool.py", "def helper():\n    return 3\n")
    clean = _row(root, "pkg/api.py", "clean")
    assert clean["state"] == "disconnected_candidate"  # the raw state is unchanged
    assert clean["promotion_hold"] == [HOLD]
    assert _row(root, "pkg/api.py", "_private")["promotion_hold"] == []
    assert _row(root, "scripts/tool.py", "helper")["promotion_hold"] == []


def test_without_a_distribution_nothing_is_held(root):
    _write(root, "pkg/api.py", "def clean():\n    return 1\n")
    assert _row(root, "pkg/api.py", "clean")["promotion_hold"] == []


def test_a_private_module_is_not_public_api(root):
    _write(root, "pyproject.toml", '[project]\nname = "pkg"\nversion = "0"\n')
    _write(root, "pkg/_internal/__init__.py")
    _write(root, "pkg/_internal/impl.py", "def clean():\n    return 1\n")
    assert _row(root, "pkg/_internal/impl.py", "clean")["promotion_hold"] == []


def test_a_package_named_like_a_cache_is_still_walked(root):
    """Only tool caches (.mypy_cache, __pycache__) are skipped, not a package called lmcache."""
    _write(root, "lmcache/__init__.py")
    _write(root, "lmcache/a.py", "def f():\n    return 1\n")
    _write(root, "lmcache/tests/test_a.py", "from lmcache.a import f\n\n\ndef test_f():\n    f()\n")
    _write(root, "lmcache/deploy/serve.yaml", "fn: f\n")
    scanned = [SimpleNamespace(file_path=str(root / "lmcache" / "a.py"), deficit_score=0.0)]
    rows = CrossFileAnalyzer().analyze(str(root), scanned, connections=True).to_dict()
    row = rows["structure_evidence"]["connections"]["symbols"][0]
    assert row["test_referenced"] is True
    assert any(r.startswith("external_config_reference:") for r in row["reasons"]), row["reasons"]
