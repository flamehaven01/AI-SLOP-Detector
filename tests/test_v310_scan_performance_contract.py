"""v3.10 scan performance: the same answers from less repeated work.

Measured on NSRW (66 files) and Flamehaven-TOE (179 files): the project was
walked four times (coverage plus discovery for Python, JS and Go) with an
ignore-pattern check per file, each module was walked by every pattern
(about forty `ast.walk` per file), every jargon regex was escaped per line,
and four cross-language patterns analysed every scope of every module.
Cold/warm before -> after: TOE 33.09 s / 10.24 s -> 10.92 s / 3.24 s,
NSRW 11.05 s / 1.55 s -> 4.31 s / 0.78 s; full JSON output identical except
which 200 of TOE's 13,997 excluded files the bounded detail list shows (now
the walk's sorted depth-first order instead of the filesystem's).

Contract: the shared walk, the per-module node list and the pattern cache
give exactly the answers of the code they replace.
"""

from __future__ import annotations

import ast
from pathlib import Path

from slop_detector.ast_index import walk_nodes
from slop_detector.config import Config
from slop_detector.core import SlopDetector
from slop_detector.core_project import (
    ignore_reason,
    project_files,
    project_walk_scope,
    walk_project,
)

SOURCE = "import os\n\n\nclass A:\n    def f(self, x):\n        return [y for y in x if y]\n"


def _tree(root: Path) -> None:
    for rel in (
        "main.py",
        "pkg/mod.py",
        "pkg/sub/deep.py",
        ".venv/lib/site-packages/dep/x.py",
        "build/gen.py",
        "tests/test_a.py",
        "docs/readme.md",
        "node_modules/a/index.js",
        "venv",  # a file named like an excluded directory
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(SOURCE, encoding="utf-8")


def test_walk_nodes_is_ast_walk_once_per_module():
    tree = ast.parse(SOURCE)
    nodes = walk_nodes(tree)
    assert [type(n) for n in nodes] == [type(n) for n in ast.walk(tree)]
    assert walk_nodes(tree) is nodes
    function = tree.body[1].body[0]
    assert walk_nodes(function) is not walk_nodes(function)  # subtrees are not cached


def test_walk_lists_the_files_rglob_lists(tmp_path):
    _tree(tmp_path)
    walked = {item.path for item in walk_project(tmp_path)}
    assert walked == {path for path in tmp_path.rglob("*") if path.is_file()}


def test_walked_reasons_equal_ignore_reason(tmp_path):
    _tree(tmp_path)
    patterns = Config().get_ignore_patterns()
    for item in walk_project(tmp_path):
        assert item.ignore_reason(patterns) == ignore_reason(item.path, patterns, root=tmp_path)
        assert item.relative == item.path.relative_to(tmp_path).as_posix()


def test_a_scan_walks_the_project_once(tmp_path, monkeypatch):
    _tree(tmp_path)
    from slop_detector import core_project

    calls = []
    original = core_project.walk_project

    def counting(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(core_project, "walk_project", counting)
    SlopDetector(read_only=True).analyze_project(str(tmp_path))
    assert len(calls) == 1
    # Outside a scan scope every call walks again (no stale listing).
    project_files(tmp_path)
    project_files(tmp_path)
    assert len(calls) == 3
    with project_walk_scope():
        project_files(tmp_path)
        project_files(tmp_path)
    assert len(calls) == 4


def test_symlinked_directories_are_not_followed(tmp_path):
    """Python 3.13+ `**` does not follow them either; 3.8-3.12 rglob did, which
    could list files outside the project or loop. The walk never follows them."""
    import pytest

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "elsewhere.py").write_text(SOURCE, encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text(SOURCE, encoding="utf-8")
    try:
        (project / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create a directory symlink here")

    assert [item.relative for item in walk_project(project)] == ["main.py"]
